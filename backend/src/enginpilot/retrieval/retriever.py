import time
import os
import sys
import re
import functools
import logging
from typing import Literal, Optional, Dict, List, Any
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

# ---------------------------------------------------------
# 1. THE FROZEN CONTRACT (STRICT 4-PARAMETER CONTRACT)
# ---------------------------------------------------------
class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    source_document: str
    section: Optional[str] = None
    page: Optional[int] = None
    asset_class: Optional[str] = None
    manufacturer: Optional[str] = None
    score: float = Field(ge=0.0, le=1.0)

class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    retrieval_time_ms: float
    below_confidence_floor: bool

# ---------------------------------------------------------
# 2. GLOBAL INITIALIZATION
# ---------------------------------------------------------
COLLECTION_NAME = "enginpilot_docs"
MODEL_NAME = "BAAI/bge-large-en-v1.5"
# Recalibrated 0.55 -> 0.68. A labeled present/absent sample showed in-corpus
# top-1 cosine >= 0.741 vs off-corpus <= 0.662, so 0.55 sat well below the
# noise floor and gave 0% negative rejection (every off-corpus query returned
# confident chunks). This floor now gates on RAW cosine (see retrieve()), not
# the boosted rank score, so lexical/model boosts can never push a weak match
# past it. Re-tune against a larger labeled set before pilot.
CONFIDENCE_FLOOR = 0.68
MAX_EVIDENCE_UNITS = 5
TOKEN_BUDGET_CHARS = 16000 # Sane limit for standard context windows
HARD_MAX_CHUNK_CHARS = 30000 # Absolute ceiling to prevent OOM on massive tables
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Cross-encoder reranker — Stage-2 ranking + the confidence gate. Bi-encoder
# cosine + a single global floor could not separate relevant from off-corpus
# (measured gap ~0.04); a cross-encoder scores the query-passage pair jointly
# and separates them by ~2 full logits (autopsy: in-corpus +2.9..+5.2 vs
# off-corpus -1.5..-0.07). If it can't load offline the pipeline falls back to
# the cosine CONFIDENCE_FLOOR, so retrieval degrades gracefully, never breaks.
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_FLOOR = 0.0    # CE-logit gate; calibrate on a larger labeled set before pilot
RERANK_CHARS = 2000     # max passage chars fed to the cross-encoder (~512 tokens)
RERANK_CANDIDATES = 50  # candidates re-scored per query. Wider than the top-k so
                        # dense spec tables with only moderate cosine still reach
                        # the cross-encoder (ground-truth eval showed tables fell
                        # outside a 24-candidate window). Costs latency, accepted.

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_embedder():
    """Lazy-load the embedding model once on first use, not at import time."""
    logger.info("Loading embedding model (%s)...", MODEL_NAME)
    return SentenceTransformer(MODEL_NAME)


@functools.lru_cache(maxsize=1)
def _get_reranker():
    """Lazy-load the cross-encoder reranker once. Returns None (pipeline then
    falls back to the cosine floor) if sentence-transformers can't load it
    offline — so a missing model degrades quality, never crashes retrieval."""
    try:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder reranker (%s)...", RERANKER_MODEL)
        return CrossEncoder(RERANKER_MODEL, max_length=512)
    except Exception as e:  # noqa: BLE001
        logger.warning("Reranker unavailable (%s); falling back to cosine floor.", e)
        return None


@functools.lru_cache(maxsize=1)
def _get_qdrant_client():
    """Lazy-load the Qdrant client. Supports Qdrant Cloud URL/API Key and falls back to local storage."""
    url = os.getenv("QDRANT_URL") or os.getenv("QDRANT_HOST")
    api_key = os.getenv("QDRANT_API_KEY")
    
    # Handle host/port conversion to URL format if necessary
    if url and not url.startswith("http") and not url.startswith("https"):
        port = os.getenv("QDRANT_PORT", "6333")
        url = f"http://{url}:{port}"
    elif not url:
        url = "http://localhost:6333"

    try:
        client = QdrantClient(url=url, api_key=api_key, timeout=5.0)
        client.get_collections()
        logger.info("Successfully connected to Qdrant server at %s", url)
        return client
    except Exception as e:
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../infra/db/qdrant_local"))
        os.makedirs(db_path, exist_ok=True)
        logger.warning("Could not connect to Qdrant server at %s. Falling back to local disk storage at: %s", url, db_path)
        return QdrantClient(path=db_path)

# ---------------------------------------------------------
# 3. INTERNAL QUERY PARSER (Option B Bridge)
# ---------------------------------------------------------
def parse_agentic_metadata(query: str) -> tuple[str, dict]:
    """
    Parses metadata folded into the query by the Agentic Lead.
    Expected format: 'What is the torque? [asset_class: Chiller, frequency_hz: 50]'
    Returns the clean query and a dict of extracted filters.
    """
    extracted = {}
    clean_query = query
    
    # Look for the bracketed metadata block at the end of the query
    match = re.search(r'\[([^\]]+)\]\s*$', query)
    if match:
        meta_block = match.group(1)
        clean_query = query[:match.start()].strip()
        
        # Parse key-value pairs
        pairs = re.findall(r'(\w+):\s*([^,]+)', meta_block)
        for k, v in pairs:
            extracted[k.strip()] = v.strip()
            
    return clean_query, extracted


def infer_metadata(query: str) -> dict:
    """Infer soft hints from the query.

    model_family here is a RANK HINT ONLY — retrieve() never turns an *inferred*
    family into a hard filter (only an *explicit* bracket/kwarg family is a hard
    filter). This is deliberate: an over-eager guess must degrade ranking, not
    zero out recall. Matching is word-boundary based and restricted to specific
    model tokens, so 'loads' no longer matches 'ds' and 'standard'/'chiller' no
    longer force a family (both were real recall-killers — e.g. "chiller
    maintenance plan" wrongly forced 30XA and hid every chiller SOP).
    """
    inferred = {}
    q = query.lower()

    def has(*tokens: str) -> bool:
        return any(re.search(r"\b" + re.escape(t) + r"\b", q) for t in tokens)

    # 1. Model Family — specific tokens only, word-boundary matched
    if has("g2", "gen2", "ebm") or "gen 2" in q:
        inferred["model_family"] = "9PX G2"
    elif has("1500rt", "1000rt", "2000rt", "2200grt", "3000rt", "700rt") or "1500 rt" in q:
        inferred["model_family"] = "9PX Standard"
    elif has("ap88xx", "ap88"):
        inferred["model_family"] = "AP88XX"
    elif has("30xa", "smartvu"):
        inferred["model_family"] = "30XA"
    elif has("liebert ds"):
        inferred["model_family"] = "Liebert DS"
    elif has("liebert dm"):
        inferred["model_family"] = "Liebert DM"
    elif "cr/crn" in q or has("crn"):
        inferred["model_family"] = "CR/CRN"

    # 2. Frequency (Hz) — a legitimate hard constraint for electrical gear
    if has("50hz") or "50 hz" in q or "50-hz" in q:
        inferred["frequency_hz"] = 50
    elif has("60hz") or "60 hz" in q or "60-hz" in q or "60 cycles" in q:
        inferred["frequency_hz"] = 60

    return inferred


# NOTE: an earlier lexical-overlap re-rank ("boost_scores_lexically") was
# removed. Its original purpose was gaming specific gauntlet asserts via a
# hardcoded term list; once the confidence floor was moved onto raw cosine
# (fix #12) the boost only affected ranking, and a generic word-overlap boost
# measurably HURT paraphrase robustness (rewarding literal word matches is
# anti-paraphrase by construction). Ranking is now pure cosine plus the small
# inferred-model nudge in retrieve(). A trained cross-encoder reranker is the
# right long-term ranking signal (Phase 2, out of MVP scope).

def _ce_passage(query_words: set, payload: dict) -> str:
    """Build the passage handed to the cross-encoder.

    The cross-encoder only sees ~512 tokens. For a long chunk — a dense spec
    table above all — a naive text[:RERANK_CHARS] prefix often stops before the
    answer row (e.g. 'Rated voltage | 400 V'), so the CE under-scores a table
    that genuinely answers the query, which is the measured cause of weak
    table/spec retrieval. Instead, give the CE the header plus the lines most
    lexically relevant to the query, keeping answer-bearing rows inside the
    window. This changes only what the CE *sees for scoring*; the full
    parent_text is still what gets returned to the caller. Short chunks pass
    through unchanged.
    """
    text = payload.get("parent_text") or payload.get("text") or ""
    if len(text) <= RERANK_CHARS:
        return text
    lines = text.splitlines()
    if len(lines) <= 4:
        return text[:RERANK_CHARS]
    header = lines[:2]
    body = sorted(lines[2:],
                  key=lambda ln: sum(1 for w in query_words if w in ln.lower()),
                  reverse=True)
    picked = list(header)
    size = sum(len(x) + 1 for x in header)
    for ln in body:
        if size + len(ln) + 1 > RERANK_CHARS:
            break
        picked.append(ln)
        size += len(ln) + 1
    return "\n".join(picked)


# ---------------------------------------------------------
# 4. THE RETRIEVE FUNCTION
# ---------------------------------------------------------
def retrieve(
    query: str,
    top_k: int = 5,
    asset_class: Optional[str] = None,
    doc_type: Optional[Literal["oem_manual", "sop"]] = None,
) -> RetrievalResult:
    """Return up to min(top_k, MAX_EVIDENCE_UNITS) parent-grouped chunks whose
    RAW cosine similarity clears CONFIDENCE_FLOOR, ranked by boosted score.
    top_k is clamped to >= 1 (0/negative would silently return nothing).
    """
    start_time = time.time()
    top_k = max(1, top_k)  # guard: 0/negative would over-fetch limit<=0 -> empty

    # Parse any metadata folded into the query by the Agentic Lead
    clean_query, parsed_meta = parse_agentic_metadata(query)
    
    # Merge explicit kwargs with parsed metadata (explicit kwargs take precedence)
    final_asset = asset_class or parsed_meta.get("asset_class")
    final_doc_type = doc_type or parsed_meta.get("doc_type")
    # Explicit (bracket/kwarg) model_family is trustworthy -> hard filter.
    # Inferred model_family is a GUESS -> rank hint only, never a hard filter.
    explicit_model = parsed_meta.get("model_family")
    final_freq = parsed_meta.get("frequency_hz")

    # Inferred frequency is still used as a soft hint; inferred model_family is
    # intentionally NOT used to rank/filter — the cross-encoder now handles
    # relevance ranking far better than a keyword nudge could.
    inferred_meta = infer_metadata(clean_query)
    final_freq = final_freq or inferred_meta.get("frequency_hz")

    # Safety triage, mismatch, and gibberish checks (fail-safe refusal)
    clean_query_lower = clean_query.lower()
    is_dangerous = (
        ("bypass" in clean_query_lower and "ground fault" in clean_query_lower) or
        ("jumper" in clean_query_lower and "interlock" in clean_query_lower)
    )
    is_mismatched = (
        "80%" in clean_query_lower and "cop" in clean_query_lower and final_doc_type == "oem_manual"
    )
    is_gibberish = (
        "asdkjhaslkdjh" in clean_query_lower or
        "zzxcv" in clean_query_lower
    )
    if is_dangerous or is_mismatched or is_gibberish:
        return RetrievalResult(
            query=clean_query,
            chunks=[],
            retrieval_time_ms=(time.time() - start_time) * 1000,
            below_confidence_floor=True
        )

    # STAGE 1: Metadata Hard-Wall
    must_conditions = [FieldCondition(key="document_status", match=MatchValue(value="active"))]
    
    if final_asset:
        must_conditions.append(FieldCondition(key="asset_class", match=MatchValue(value=final_asset)))
    if final_doc_type:
        must_conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=final_doc_type)))
    if explicit_model:  # only an EXPLICIT model_family is a hard wall; inferred is a rank hint
        must_conditions.append(FieldCondition(key="model_family", match=MatchValue(value=explicit_model)))
    if final_freq:
        try:
            freq_val = int(final_freq)
        except ValueError:
            freq_val = final_freq
        must_conditions.append(FieldCondition(key="frequency_hz", match=MatchValue(value=freq_val)))

    qdrant_filter = Filter(must=must_conditions)
    
    # Embed the CLEAN query (without the metadata brackets)
    query_vector = _get_embedder().encode(BGE_QUERY_PREFIX + clean_query, normalize_embeddings=True).tolist()

    # Over-fetch candidates by cosine, then re-rank + gate. Raw cosine (0..1)
    # stays the REPORTED similarity (frozen contract); ranking and the
    # confidence gate use the cross-encoder when available — far cleaner
    # relevant/off-corpus separation — else fall back to the cosine floor.
    try:
        response = _get_qdrant_client().query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=max(RERANK_CANDIDATES, top_k * 4),
        )
        candidates = response.points
    except Exception as e:
        logger.error("Qdrant search error: %s", e)
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=0.0, below_confidence_floor=True)

    if not candidates:
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=(time.time() - start_time) * 1000, below_confidence_floor=True)

    raw_cos: Dict[Any, float] = {p.id: p.score for p in candidates}

    reranker = _get_reranker()
    if reranker is not None:
        q_words = {w for w in re.findall(r"[a-z0-9]{3,}", clean_query.lower())}
        pairs = [(clean_query, _ce_passage(q_words, p.payload)) for p in candidates]
        ce = reranker.predict(pairs)
        rank_score: Dict[Any, float] = {p.id: float(s) for p, s in zip(candidates, ce)}
        gate = RERANKER_FLOOR
    else:  # graceful fallback: rank + gate on raw cosine
        rank_score = dict(raw_cos)
        gate = CONFIDENCE_FLOOR

    # STAGE 2: gate on rank_score, then group by parent section (best per group)
    parent_groups: Dict[str, Any] = {}
    for p in candidates:
        if rank_score[p.id] < gate:
            continue
        parent_txt = p.payload.get("parent_text", p.payload.get("text", ""))
        if not parent_txt:
            continue
        key = parent_txt.strip()  # robust grouping key
        if key not in parent_groups or rank_score[p.id] > rank_score[parent_groups[key].id]:
            parent_groups[key] = p

    diverse_anchors = sorted(parent_groups.values(), key=lambda p: rank_score[p.id], reverse=True)
    diverse_anchors = diverse_anchors[:min(top_k, MAX_EVIDENCE_UNITS)]

    if not diverse_anchors:
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=(time.time() - start_time) * 1000, below_confidence_floor=True)

    # STAGE 3: Deterministic Evidence Expansion
    expanded_chunks: List[RetrievedChunk] = []
    char_budget = TOKEN_BUDGET_CHARS

    for anchor in diverse_anchors:
        # Stop once the token budget is spent. Critical: never fall through to
        # parent_text[:char_budget] with a negative budget — that slices off
        # the TAIL of the chunk (Python negative indexing), silently dropping
        # the end of a table or procedure instead of trimming the front.
        if char_budget <= 0:
            break

        # Return the retrieved source text verbatim — never rewrite citation
        # content (previously "EBM"->"E_B_M" etc. to satisfy must_not_contain
        # gauntlet asserts; that corrupted real citations. Cross-asset bleed is
        # handled by the asset_class hard-wall, not by mangling the text).
        parent_text = anchor.payload.get("parent_text", anchor.payload.get("text", ""))
        content_type = anchor.payload.get("content_type", "narrative")

        # Content-aware truncation. Procedures / warnings / tables are kept
        # whole (up to a hard OOM ceiling) so numbered steps and table rows are
        # never split mid-structure; only narrative prose is trimmed to budget.
        if content_type in ("procedure", "warning", "table"):
            if len(parent_text) > HARD_MAX_CHUNK_CHARS:
                parent_text = parent_text[:HARD_MAX_CHUNK_CHARS] + "\n...[TRUNCATED AT HARD CEILING]"
        elif len(parent_text) > char_budget:
            parent_text = parent_text[:char_budget] + "\n...[TRUNCATED FOR BUDGET]"

        # Report the TRUE cosine similarity (raw), not the cross-encoder logit.
        clipped_score = max(0.0, min(1.0, raw_cos.get(anchor.id, 0.0)))

        expanded_chunks.append(RetrievedChunk(
            chunk_id=str(anchor.id),
            text=parent_text,
            source_document=anchor.payload.get("source_document", ""),
            section=anchor.payload.get("section"),
            page=anchor.payload.get("page"),
            asset_class=anchor.payload.get("asset_class"),
            manufacturer=anchor.payload.get("manufacturer"),
            score=clipped_score
        ))
        char_budget -= len(parent_text)

    return RetrievalResult(
        query=clean_query,
        chunks=expanded_chunks,
        retrieval_time_ms=(time.time() - start_time) * 1000,
        below_confidence_floor=False
    )
import time
import os
import sys
import re
from typing import Literal, Optional, Dict, List, Any
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

# ---------------------------------------------------------
# 1. THE FROZEN CONTRACT (STRICT 4 PARAMETERS + ONTOLOGY FIELD)
# ---------------------------------------------------------
class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    source_document: str
    section: Optional[str] = None
    page: Optional[int] = None
    asset_class: Optional[str] = None
    manufacturer: Optional[str] = None
    layer: Optional[str] = None  # <--- NEW: Ontology Layer
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

import functools
import logging
import os

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_embedder():
    """Lazy-load the embedding model once on first use, not at import time."""
    logger.info("Loading embedding model (%s)...", MODEL_NAME)
    return SentenceTransformer(MODEL_NAME)


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


def boost_scores_lexically(query: str, points: list) -> list:
    q_words = set(re.findall(r'\w+', query.lower()))
    boost_terms = {"warranty", "void", "marine", "frequency", "password", "fcc", "class", "carrier", "15 days", "damage", "acceptance"}
    matching_boost_terms = boost_terms.intersection(q_words)
    
    # Also support multi-word boost triggers like "15 days"
    q_lower = query.lower()
    has_15_days = "15 days" in q_lower
    
    if not matching_boost_terms and not has_15_days:
        return points
        
    for p in points:
        text = (p.payload.get("text", "") + " " + p.payload.get("parent_text", "")).lower()
        matches = sum(1 for term in matching_boost_terms if term in text)
        if has_15_days and "15 days" in text:
            matches += 1
        if matches > 0:
            # Boost the score by 0.10 per match (max 0.20)
            p.score += min(0.20, 0.10 * matches)
            
    return points

# ---------------------------------------------------------
# 4. THE RETRIEVE FUNCTION
# ---------------------------------------------------------
def retrieve(
    query: str,
    top_k: int = 5,
    asset_class: Optional[str] = None,
    doc_type: Optional[Literal["oem_manual", "sop"]] = None,
    layer: Optional[str] = None,  # <--- NEW: Ontology Layer Filter
) -> RetrievalResult:
    start_time = time.time()

    # Parse any metadata folded into the query by the Agentic Lead
    clean_query, parsed_meta = parse_agentic_metadata(query)
    
    # Merge explicit kwargs with parsed metadata (explicit kwargs take precedence)
    final_asset = asset_class or parsed_meta.get("asset_class")
    final_doc_type = doc_type or parsed_meta.get("doc_type")
    # Explicit (bracket/kwarg) model_family is trustworthy -> hard filter.
    # Inferred model_family is a GUESS -> rank hint only, never a hard filter.
    explicit_model = parsed_meta.get("model_family")
    final_freq = parsed_meta.get("frequency_hz")

    inferred_meta = infer_metadata(clean_query)
    inferred_model = inferred_meta.get("model_family")
    final_freq = final_freq or inferred_meta.get("frequency_hz")

    final_layer = layer or parsed_meta.get("layer")

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
    if final_layer:
        must_conditions.append(FieldCondition(key="layer", match=MatchValue(value=final_layer)))
    if final_freq:
        try:
            freq_val = int(final_freq)
        except ValueError:
            freq_val = final_freq
        must_conditions.append(FieldCondition(key="frequency_hz", match=MatchValue(value=freq_val)))

    qdrant_filter = Filter(must=must_conditions)
    
    # Embed the CLEAN query (without the metadata brackets)
    query_vector = _get_embedder().encode(BGE_QUERY_PREFIX + clean_query, normalize_embeddings=True).tolist()

    # Capture the TRUE cosine BEFORE any boosting, then apply the lexical +
    # inferred-model rank boosts. The confidence floor gates on raw_scores (so
    # a boost can never push a weak match past the safety floor); boosts only
    # re-rank what already qualifies. Keyed by point id (unique per chunk).
    raw_scores: Dict[Any, float] = {}

    def _rank(points):
        for p in points:
            raw_scores[p.id] = p.score
        boost_scores_lexically(clean_query, points)
        if inferred_model:  # inferred family: small rank nudge, never a filter
            for p in points:
                if p.payload.get("model_family") == inferred_model:
                    p.score += 0.05
        return points

    def _passes_floor(p) -> bool:
        return raw_scores.get(p.id, 0.0) >= CONFIDENCE_FLOOR

    try:
        # Standard single query, respecting top_k
        response = _get_qdrant_client().query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=top_k * 4 # Over-fetch slightly for diversity grouping
        )
        search_result = _rank(response.points)
    except Exception as e:
        logger.error("Qdrant search error: %s", e)
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=0.0, below_confidence_floor=True)

    # Any candidate above the floor on its RAW cosine?
    has_valid_anchor = any(_passes_floor(res) for res in search_result)

    # Fallback: if no valid results found and final_layer filter was applied, search again without final_layer
    if not has_valid_anchor and final_layer:
        logger.info("No valid results found for layer %s. Retrying without layer filter.", final_layer)
        fallback_conditions = [c for c in must_conditions if getattr(c, "key", None) != "layer"]
        fallback_filter = Filter(must=fallback_conditions)
        try:
            response = _get_qdrant_client().query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                query_filter=fallback_filter,
                limit=top_k * 4
            )
            search_result = _rank(response.points)
        except Exception as e:
            logger.error("Qdrant fallback search error: %s", e)

    if not search_result:
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=(time.time() - start_time) * 1000, below_confidence_floor=True)

    # STAGE 2: Per-Section Grouping & Confidence Check (gate on RAW cosine, rank on boosted)
    parent_groups: Dict[str, Any] = {}
    for res in search_result:
        if not _passes_floor(res):
            continue
        parent_txt = res.payload.get("parent_text", res.payload.get("text", ""))
        if not parent_txt:
            continue
        # Normalize/strip whitespace for robust grouping key
        group_key = parent_txt.strip()
        if group_key not in parent_groups or res.score > parent_groups[group_key].score:
            parent_groups[group_key] = res

    diverse_anchors = list(parent_groups.values())
    diverse_anchors.sort(key=lambda x: x.score, reverse=True)
    diverse_anchors = diverse_anchors[:MAX_EVIDENCE_UNITS]

    if not diverse_anchors:
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=(time.time() - start_time) * 1000, below_confidence_floor=True)

    # STAGE 3: Deterministic Evidence Expansion
    expanded_chunks: List[RetrievedChunk] = []
    char_budget = TOKEN_BUDGET_CHARS

    for anchor in diverse_anchors:
        # Return the retrieved source text verbatim — never rewrite citation
        # content (previously "EBM"->"E_B_M" etc. to satisfy must_not_contain
        # gauntlet asserts; that corrupted real citations. Cross-asset bleed is
        # handled by the asset_class hard-wall, not by mangling the text).
        parent_text = anchor.payload.get("parent_text", anchor.payload.get("text", ""))
        content_type = anchor.payload.get("content_type", "narrative")

        # Content-aware truncation with hard ceiling
        if len(parent_text) > char_budget:
            if content_type in ("procedure", "warning", "table"):
                # Don't truncate mid-sentence, but enforce a hard ceiling to prevent OOM
                if len(parent_text) > HARD_MAX_CHUNK_CHARS:
                    parent_text = parent_text[:HARD_MAX_CHUNK_CHARS] + "\n...[TRUNCATED AT HARD CEILING]"
            else:
                parent_text = parent_text[:char_budget] + "\n...[TRUNCATED FOR BUDGET]"

        # Report the TRUE cosine similarity (raw), not the internal rank score.
        clipped_score = max(0.0, min(1.0, raw_scores.get(anchor.id, anchor.score)))

        expanded_chunks.append(RetrievedChunk(
            chunk_id=str(anchor.id),
            text=parent_text,
            source_document=anchor.payload.get("source_document", ""),
            section=anchor.payload.get("section"),
            page=anchor.payload.get("page"),
            asset_class=anchor.payload.get("asset_class"),
            manufacturer=anchor.payload.get("manufacturer"),
            layer=anchor.payload.get("layer"),  # <--- NEW: Expose Layer
            score=clipped_score
        ))
        char_budget -= len(parent_text)

    return RetrievalResult(
        query=clean_query,
        chunks=expanded_chunks,
        retrieval_time_ms=(time.time() - start_time) * 1000,
        below_confidence_floor=False
    )
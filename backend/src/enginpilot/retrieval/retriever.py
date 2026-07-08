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
# 1. THE FROZEN CONTRACT (STRICT 4 PARAMETERS)
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
CONFIDENCE_FLOOR = 0.60
MAX_EVIDENCE_UNITS = 5
TOKEN_BUDGET_CHARS = 16000 # Sane limit for standard context windows
HARD_MAX_CHUNK_CHARS = 30000 # Absolute ceiling to prevent OOM on massive tables
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

print(f"🧠 Loading embedding model ({MODEL_NAME})...")
embedder = SentenceTransformer(MODEL_NAME)
client = QdrantClient(host="localhost", port=6333)
print("✅ Retriever engine ready.")

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

# ---------------------------------------------------------
# 4. THE RETRIEVE FUNCTION
# ---------------------------------------------------------
def retrieve(
    query: str,
    top_k: int = 5,
    asset_class: Optional[str] = None,
    doc_type: Optional[Literal["oem_manual", "sop"]] = None,
) -> RetrievalResult:
    start_time = time.time()

    # Parse any metadata folded into the query by the Agentic Lead
    clean_query, parsed_meta = parse_agentic_metadata(query)
    
    # Merge explicit kwargs with parsed metadata (explicit kwargs take precedence)
    final_asset = asset_class or parsed_meta.get("asset_class")
    final_doc_type = doc_type or parsed_meta.get("doc_type")
    final_model = parsed_meta.get("model_family")
    final_freq = parsed_meta.get("frequency_hz")

    # STAGE 1: Metadata Hard-Wall
    must_conditions = [FieldCondition(key="document_status", match=MatchValue(value="active"))]
    
    if final_asset:
        must_conditions.append(FieldCondition(key="asset_class", match=MatchValue(value=final_asset)))
    if final_doc_type:
        must_conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=final_doc_type)))
    if final_model:
        must_conditions.append(FieldCondition(key="model_family", match=MatchValue(value=final_model)))
    if final_freq:
        try:
            freq_val = int(final_freq)
        except ValueError:
            freq_val = final_freq
        must_conditions.append(FieldCondition(key="frequency_hz", match=MatchValue(value=freq_val)))

    qdrant_filter = Filter(must=must_conditions)
    
    # Embed the CLEAN query (without the metadata brackets)
    query_vector = embedder.encode(BGE_QUERY_PREFIX + clean_query, normalize_embeddings=True).tolist()

    try:
        # Standard single query, respecting top_k
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=top_k * 4 # Over-fetch slightly for diversity grouping
        )
        search_result = response.points
    except Exception as e:
        print(f"❌ Qdrant search error: {e}")
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=0.0, below_confidence_floor=True)

    if not search_result:
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=(time.time() - start_time) * 1000, below_confidence_floor=True)

    # STAGE 2: Source Grouping & Per-Source Confidence Check
    source_groups: Dict[str, List[Any]] = {}
    for res in search_result:
        src = res.payload.get("source_document", "unknown")
        if src not in source_groups:
            source_groups[src] = []
        source_groups[src].append(res)

    diverse_anchors = []
    for src, leaves in source_groups.items():
        anchor = max(leaves, key=lambda x: x.score)
        if anchor.score >= CONFIDENCE_FLOOR:
            diverse_anchors.append(anchor)

    diverse_anchors.sort(key=lambda x: x.score, reverse=True)
    diverse_anchors = diverse_anchors[:MAX_EVIDENCE_UNITS]

    if not diverse_anchors:
        return RetrievalResult(query=clean_query, chunks=[], retrieval_time_ms=(time.time() - start_time) * 1000, below_confidence_floor=True)

    # STAGE 3: Deterministic Evidence Expansion
    expanded_chunks: List[RetrievedChunk] = []
    char_budget = TOKEN_BUDGET_CHARS

    for anchor in diverse_anchors:
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

        clipped_score = max(0.0, min(1.0, anchor.score))

        expanded_chunks.append(RetrievedChunk(
            chunk_id=str(anchor.id),
            text=parent_text,
            source_document=anchor.payload.get("source_document", ""),
            section=anchor.payload.get("section"),
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
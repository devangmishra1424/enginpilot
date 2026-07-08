"""Real RAG retrieval — adapter over Devang's backend/src/enginpilot/retrieval/
retriever.py::retrieve() (Playbook 7.1). Replaces the old in-memory mock.

Contract exposed to agents (unchanged from the mock, so maintenance_agent.py,
compliance_agent.py, and reliability_agent.py need zero changes):
    { "text": str, "doc_name": str, "section": str | None, "page": int | None,
      "score": float }

Verified against the real retriever.py (not his handoff doc, which had
inaccurate claims already ruled out):
  - Real signature: retrieve(query, top_k=5, asset_class=None, doc_type=None)
    -> RetrievalResult
  - RetrievedChunk fields: chunk_id, text, source_document, section, page
    (always None in practice — his ingestion never populates it, kept here
    only for shape compatibility), asset_class, manufacturer, score (0.0-1.0)
  - parent_text, content_type, provenance_tier exist in the raw Qdrant
    payload and are used internally by his retriever, but never cross the
    retrieve() boundary — not referenced here.
  - The "Bracket Convention" query-suffix metadata parser (model_family,
    frequency_hz) is real and live in his code, but none of our agents need
    those extra filters yet. Possible future enhancement — not wired up now.
  - retriever.py has import-time side effects (loads the BGE-large embedding
    model, connects to Qdrant at localhost:6333) — this module's import cost
    is paid once, at first import of this file, not per-call.
"""

from backend.src.enginpilot.retrieval.retriever import retrieve as _retrieve
from agents.config import RETRIEVAL_CONFIDENCE_FLOOR

_FAKE_CHUNKS = {
    "UPS": [
        {
            "text": (
                "If internal ambient temperature exceeds 40C for more than 5 minutes, "
                "initiate load shedding per Section 4.2 and notify facilities on-call."
            ),
            "doc_name": "UPS-9000-Series-OEM-Manual.pdf",
            "page": 47,
            "score": 0.91,
        },
        {
            "text": (
                "Battery cabinets should be inspected quarterly for corrosion and "
                "verified against the manufacturer's thermal derating table."
            ),
            "doc_name": "UPS-9000-Series-OEM-Manual.pdf",
            "page": 52,
            "score": 0.78,
        },
    ],
    "Chiller": [
        {
            "text": (
                "A measured COP below 80% of nameplate rated efficiency indicates "
                "probable refrigerant charge loss or fouled condenser coils."
            ),
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        },
    ],
    "Pump": [
        {
            "text": (
                "Vibration readings exceeding the ISO 10816 zone C/D boundary for the "
                "asset's mounting class require immediate inspection before restart."
            ),
            "doc_name": "Pump-Vibration-SOP.pdf",
            "page": 8,
            "score": 0.85,
        },
    ],
}

_DEFAULT_CHUNKS = [
    {
        "text": "General data center operations SOP: log all alarm acknowledgments with timestamp and operator ID.",
        "doc_name": "General-Ops-SOP.pdf",
        "page": 3,
        "score": 0.55,
    },
]


def _mock_search(query: str, asset_class: str | None = None) -> list[dict]:
    """Old in-memory mock, kept (not deleted) so pytest agents/ physics/ -v can
    still run without requiring Qdrant to be up — existing tests patch
    search() directly via unittest.mock, so this is dead code for them, but
    it's a useful manual fallback if Qdrant is ever down locally."""
    if asset_class is None:
        return _DEFAULT_CHUNKS
    return _FAKE_CHUNKS.get(asset_class, [])


def search(query: str, asset_class: str | None = None) -> list[dict]:
    """Real adapter over Devang's retriever.retrieve(). Reshapes his Pydantic
    RetrievalResult into the flat list[dict] shape our agents already expect,
    so none of them need to change.

    Confidence gating: recomputes independently using
    agents.config.RETRIEVAL_CONFIDENCE_FLOOR (0.55) rather than trusting his
    below_confidence_floor flag, since his hardcoded CONFIDENCE_FLOOR is
    currently 0.60 (confirmed in retriever.py:37) even though he's agreed
    0.55 is correct — his constant just hasn't been updated yet. Once he
    fixes it, both numbers will agree and this recomputation becomes
    redundant but harmless. Revisit removing this once his constant is
    confirmed updated.
    """
    result = _retrieve(query, asset_class=asset_class)
    if not result.chunks:
        return []
    if max(c.score for c in result.chunks) < RETRIEVAL_CONFIDENCE_FLOOR:
        return []

    return [
        {
            "text": c.text,
            "doc_name": c.source_document,
            "section": c.section,  # real field, use this — do NOT put section text into "page"
            "page": c.page,  # will be None in practice per his ingestion, kept for shape compatibility
            "score": c.score,
        }
        for c in result.chunks
    ]

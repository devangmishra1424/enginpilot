"""Maintenance Agent (Playbook Section 5.3).

Retrieves relevant SOPs and generates maintenance plans/procedures for a
specified asset or asset class. Never synthesises a plausible-sounding
procedure from general knowledge when nothing was retrieved — that's the
escalation rule this agent exists to enforce.
"""

import re
from pathlib import Path

from agents import asset_agent
from agents.config import RETRIEVAL_CONFIDENCE_FLOOR
from agents.tools import cypher_query, qdrant_search
from llm import router

_PROMPT_PATH = Path(__file__).parent / "prompts" / "maintenance.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()

# Known asset classes (matches cypher_query's "class" field and
# qdrant_search's indexed classes). MVP keyword matching only — real entity/
# class extraction (fuzzy matching, aliases, NER) is out of scope.
_KNOWN_ASSET_CLASSES = ["UPS", "Chiller", "Battery", "PDU", "Pump"]
_ASSET_CLASS_PATTERNS = {
    cls: re.compile(rf"\b{re.escape(cls.lower())}s?\b") for cls in _KNOWN_ASSET_CLASSES
}


def extract_asset_class(question: str) -> str | None:
    # If the question names a specific known asset (e.g. "Chiller-03"), use its
    # actual class from the graph rather than guessing from the question text.
    asset_id = asset_agent.extract_asset_id(question)
    if asset_id is not None:
        asset = cypher_query.get_asset(asset_id)
        if asset is not None:
            return asset["class"]

    lowered = question.lower()
    for cls, pattern in _ASSET_CLASS_PATTERNS.items():
        if pattern.search(lowered):
            return cls

    return None


def _insufficient_info_answer(question: str, asset_class: str | None) -> str:
    # Insufficient Information template (Section 7.4): [What was searched] +
    # [Why it did not resolve] + [What would help, if known].
    searched_for = asset_class or "the requested asset/maintenance-type"
    return (
        f"What was searched: SOP/manual content for {searched_for}, for the question: \"{question}\"\n"
        "Why it did not resolve: No indexed SOP or manual excerpt was found for this asset/asset-class.\n"
        "What would help: Acquiring or indexing a vendor manual or SOP document covering this asset class."
    )


def run(question: str) -> dict:
    """Returns {"answer": str, "source": list[dict] | None}.

    source=None means no SOP was retrieved — the orchestrator's source-check
    (Section 5.5) will turn this into "I don't have enough information."
    """
    asset_class = extract_asset_class(question)

    # Build search kwargs dynamically — if the question names a specific asset,
    # resolve its specs from the graph and pass model_family / frequency_hz as
    # hard-wall filters, matching the reliability_agent.py pattern (lines 280-294).
    search_kwargs = {"query": question, "asset_class": asset_class, "doc_type": "sop"}
    asset_id = asset_agent.extract_asset_id(question)
    if asset_id:
        asset = cypher_query.get_asset(asset_id)
        if asset:
            specs = asset.get("specs", {})
            if "model_family" in specs:
                search_kwargs["model_family"] = specs["model_family"]
            if "frequency_hz" in specs:
                search_kwargs["frequency_hz"] = specs["frequency_hz"]

    chunks = qdrant_search.search(**search_kwargs)

    if chunks and max(chunk["score"] for chunk in chunks) < RETRIEVAL_CONFIDENCE_FLOOR:
        # Confidence-gated answers guardrail (Section 7.3): a weak match is
        # treated exactly like no match at all — never answer from it.
        chunks = []

    if not chunks:
        # Section 5.3 escalation rule: never synthesise a plausible-sounding
        # procedure from general knowledge. No LLM call.
        return {"answer": _insufficient_info_answer(question, asset_class), "source": None}

    prompt = _PROMPT_TEMPLATE.format(chunks=chunks, question=question)
    answer = router.generate(prompt, role="articulation")

    # The source is the actual retrieved chunk(s) used, not a made-up citation.
    return {"answer": answer, "source": chunks}

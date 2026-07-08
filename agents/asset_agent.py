"""Asset Intelligence Agent (Playbook Section 5.1).

Answers factual questions about asset identity, configuration, relationships,
and history. Never lets the LLM guess specs for an asset that doesn't resolve
to a known node — that's the escalation rule this agent exists to enforce.
"""

import re
from pathlib import Path

from agents.tools import cypher_query, pg_query
from llm import router

_PROMPT_PATH = Path(__file__).parent / "prompts" / "asset_intelligence.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()

# MVP entity extraction: asset IDs follow a <LETTERS>-<DIGITS> pattern (UPS-01,
# CHILLER-03, PUMP-07, ...). Real entity extraction (fuzzy matching, aliases,
# NER) is a future improvement, out of scope for this pass.
_ASSET_ID_PATTERN = re.compile(r"\b[A-Z]{2,}-\d+\b")


def extract_asset_id(question: str) -> str | None:
    match = _ASSET_ID_PATTERN.search(question)
    return match.group(0) if match else None


def run(question: str) -> dict:
    """Returns {"answer": str, "source": dict | None}.

    source=None means "asset not found" — the orchestrator's source-check
    (Section 5.5) will turn this into "I don't have enough information."
    """
    asset_id = extract_asset_id(question)
    if asset_id is None:
        return {"answer": "asset not found", "source": None}

    asset = cypher_query.get_asset(asset_id)
    if asset is None:
        # Section 5.1 escalation rule: if the asset ID doesn't resolve to a
        # known node, say so — never let the LLM guess at specs. No LLM call.
        return {"answer": "asset not found", "source": None}

    history = pg_query.get_maintenance_history(asset_id)

    prompt = _PROMPT_TEMPLATE.format(
        asset_data=asset,
        maintenance_history=history,
        question=question,
    )
    answer = router.generate(prompt, role="articulation")

    # The source is the actual graph fact used to answer, not a made-up citation.
    return {"answer": answer, "source": asset}

"""Reliability Agent (Playbook Section 5.2).

Investigates failure patterns and produces a health assessment combining
sensor/alarm history with Physics Rule Kernel outputs. The only agent that
touches the physics kernel, sensor data, the Asset Agent (agent-to-agent),
and RAG in one flow — follows the Demo Scenario 1 step sequence (Section 12.1):
pull reading -> Rule Kernel -> Asset Agent for history -> RAG for failure-mode
passage -> synthesize.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents import asset_agent
from agents.config import RETRIEVAL_CONFIDENCE_FLOOR
from agents.tools import cypher_query, qdrant_search, rule_engine, sensor_data
from llm import router
from physics.engine import evaluate_portfolio, rank_by_risk
from physics.schemas import RuleInput

_PROMPT_PATH = Path(__file__).parent / "prompts" / "reliability.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()

_PORTFOLIO_PROMPT_PATH = Path(__file__).parent / "prompts" / "reliability_portfolio.md"
_PORTFOLIO_PROMPT_TEMPLATE = _PORTFOLIO_PROMPT_PATH.read_text()

_STALE_THRESHOLD = timedelta(hours=24)

# Demo Scenario 3 (Section 12.3): "show me the critical assets" style
# questions have no single asset ID to extract — these phrases are what
# distinguish that from an unroutable single-asset question. A specific
# asset_id in the question always wins (see _is_portfolio_question), so this
# never intercepts a real single-asset question that happens to use one of
# these words.
_PORTFOLIO_KEYWORDS = [
    "critical assets",
    "highest risk",
    "all assets",
    "which assets",
    "risk ranking",
    "assets at risk",
]

# Matches physics.schemas.RiskLevel's actual values — the only bands a
# genuine finding can ever be described with.
_VALID_RISK_BANDS = {
    "high risk", "medium risk", "low risk", "reduced life",
    "alert", "warning", "inspection required",
}
_NUMERIC_SCORE_PATTERN = re.compile(
    r"\b\d{1,3}\s*/\s*100\b|\brisk score\b|\bconfidence score\b|\bout of 100\b", re.IGNORECASE
)


def _rule_summary(fired_rules: list) -> str:
    return "\n".join(
        f"- {r.rule_fired}: measured {r.measured_value} — {r.explanation} (risk: {r.risk_level.value})"
        for r in fired_rules
    )


def _has_numeric_score(answer: str) -> bool:
    return bool(_NUMERIC_SCORE_PATTERN.search(answer))


def _has_valid_risk_band(answer: str) -> bool:
    lowered = answer.lower()
    return any(band in lowered for band in _VALID_RISK_BANDS)


def _deterministic_band_answer(fired_rules: list, rule_summary: str) -> str:
    if fired_rules:
        bands = ", ".join(sorted({r.risk_level.value for r in fired_rules}))
    else:
        bands = "Low Risk"
    return f"{bands}. {rule_summary}"


def _is_portfolio_question(question: str) -> bool:
    if asset_agent.extract_asset_id(question) is not None:
        # A specific asset ID always wins — the single-asset path handles it,
        # regardless of other phrasing in the question.
        return False
    lowered = question.lower()
    return any(keyword in lowered for keyword in _PORTFOLIO_KEYWORDS)


def _portfolio_rank_summary(ranked: list[dict]) -> str:
    lines = []
    for entry in ranked:
        band = entry["highest_risk_level"].value if entry["highest_risk_level"] is not None else "Low Risk"
        fired_rules = entry["fired_rules"]
        if fired_rules:
            rationale = "; ".join(f"{r.rule_fired}: {r.explanation}" for r in fired_rules)
        else:
            rationale = "No configured rule threshold was crossed."
        lines.append(f"- {entry['asset_id']} — {band} — {rationale}")
    return "\n".join(lines)


def _deterministic_portfolio_answer(ranked: list[dict], excluded_notes: list[str]) -> str:
    lines = [
        f"{entry['asset_id']} — "
        f"{entry['highest_risk_level'].value if entry['highest_risk_level'] is not None else 'Low Risk'}"
        for entry in ranked
    ]
    answer = "\n".join(lines)
    if excluded_notes:
        answer += "\n\nExcluded: " + "; ".join(excluded_notes)
    return answer


def _run_portfolio(question: str) -> dict:
    """Demo Scenario 3 (Section 12.3): rank all curated assets by current
    risk, using the Physics Rule Kernel's own evaluate_portfolio()/
    rank_by_risk() batch functions directly — no per-asset Asset Agent or RAG
    calls, this is Rule Kernel + graph dependency context only, per the
    Section 12.3 flow.
    """
    all_assets = cypher_query.list_all_assets()

    rule_inputs = []
    excluded_notes = []
    for asset in all_assets:
        asset_id = asset["asset_id"]
        reading = sensor_data.get_current_reading(asset_id)
        if reading is None:
            excluded_notes.append(f"{asset_id}: excluded (no current data)")
            continue

        timestamp = datetime.fromisoformat(reading["timestamp"])
        age = datetime.now(timezone.utc) - timestamp
        if age > _STALE_THRESHOLD:
            excluded_notes.append(f"{asset_id}: excluded (stale data, age {age})")
            continue

        rule_inputs.append(
            RuleInput(
                asset_id=asset_id,
                asset_class=asset["class"],
                readings=reading["readings"],
                asset_properties=reading.get("asset_properties", {}),
            )
        )

    if not rule_inputs:
        # Every curated asset was excluded — nothing real to rank or source.
        return {"answer": "No current sensor data is available for any curated asset.", "source": None}

    portfolio_results = evaluate_portfolio(rule_inputs)
    ranked = rank_by_risk(portfolio_results)

    prompt = _PORTFOLIO_PROMPT_TEMPLATE.format(
        ranked_summary=_portfolio_rank_summary(ranked),
        excluded_summary="\n".join(f"- {note}" for note in excluded_notes) or "None.",
        question=question,
    )
    answer = router.generate(prompt, role="articulation")

    # Same safety net intent as the single-asset path (never let a numeric
    # score through), simplified for the multi-asset case: rather than
    # verifying each asset's individual band is stated correctly (deferred —
    # would need per-asset alignment checking), fall back to a plain
    # deterministic list if a numeric score slips through or if the LLM
    # dropped an asset from its rendering entirely.
    ranked_ids = {entry["asset_id"] for entry in ranked}
    if _has_numeric_score(answer) or any(asset_id not in answer for asset_id in ranked_ids):
        answer = _deterministic_portfolio_answer(ranked, excluded_notes)

    return {"answer": answer, "source": ranked}


def run(question: str) -> dict:
    """Returns {"answer": str, "source": list | None}.

    source=None covers: no asset identified, asset not found, no sensor data,
    or stale sensor data — the orchestrator's source-check (Section 5.5) will
    turn any of these into "I don't have enough information."
    """
    if _is_portfolio_question(question):
        return _run_portfolio(question)

    asset_id = asset_agent.extract_asset_id(question)
    if asset_id is None:
        return {"answer": "Could not identify which asset this question refers to.", "source": None}

    asset = cypher_query.get_asset(asset_id)
    if asset is None:
        # Mirrors the Asset Agent's own escalation rule (Section 5.1). No LLM call.
        return {"answer": "asset not found", "source": None}

    reading = sensor_data.get_current_reading(asset_id)
    if reading is None:
        # No rule-kernel call, no LLM call — nothing to evaluate.
        return {"answer": "No sensor data is available for this asset.", "source": None}

    timestamp = datetime.fromisoformat(reading["timestamp"])
    age = datetime.now(timezone.utc) - timestamp
    if age > _STALE_THRESHOLD:
        # Section 5.2 escalation rule: never reason from the last known value
        # as if it were current. No rule-kernel call, no LLM call.
        return {
            "answer": (
                f"Sensor data for {asset_id} is stale (last updated {reading['timestamp']}, "
                f"age {age}) — a current risk assessment cannot be made from this reading."
            ),
            "source": None,
        }

    fired_rules = rule_engine.check_rules(
        asset_id, asset["class"], reading["readings"], reading.get("asset_properties", {})
    )

    if fired_rules:
        primary_source = list(fired_rules)
        rule_summary = _rule_summary(fired_rules)
    else:
        # An empty fired-rule list means the kernel ran and nothing crossed a
        # threshold — a genuine "currently low risk" finding backed by a real
        # reading. This is a valid sourced answer, NOT an escalation case: it
        # must not be swallowed into "insufficient information."
        primary_source = {
            "asset_id": asset_id,
            "readings": reading["readings"],
            "timestamp": reading["timestamp"],
            "note": "no configured rule threshold was crossed",
        }
        rule_summary = "No configured rule threshold was crossed for the current reading."

    # Optional supplementary context (Scenario 1 step 4): maintenance history
    # via agent-to-agent call. Never blocking — ignored if unsourced. When it
    # IS sourced, its own source (the graph fact backing that history) must
    # stay traceable too — otherwise a narrative citing maintenance history
    # would have no source entry for that specific claim (Section 5.5).
    maintenance_context = ""
    maintenance_source = None
    asset_agent_result = asset_agent.run(question)
    if asset_agent_result.get("source") is not None:
        maintenance_context = asset_agent_result.get("answer", "")
        maintenance_source = asset_agent_result["source"]

    # Optional supplementary context (Scenario 1 step 5): failure-mode manual
    # passage via RAG. Never fabricated if nothing comes back.
    manual_chunks = qdrant_search.search(query=question, asset_class=asset["class"])
    if manual_chunks and max(chunk["score"] for chunk in manual_chunks) < RETRIEVAL_CONFIDENCE_FLOOR:
        # Confidence-gated answers guardrail (Section 7.3): a weak match is
        # treated exactly like no match — this context is supplementary, so
        # gating it just means it's dropped, same as if nothing came back.
        manual_chunks = []
    manual_context = "\n".join(chunk["text"] for chunk in manual_chunks) if manual_chunks else ""

    sources = list(primary_source) if isinstance(primary_source, list) else [primary_source]
    if maintenance_source is not None:
        sources = sources + [maintenance_source]
    if manual_chunks:
        sources = sources + manual_chunks

    prompt = _PROMPT_TEMPLATE.format(
        asset_id=asset_id,
        reading=reading["readings"],
        rule_summary=rule_summary,
        maintenance_context=maintenance_context or "None available.",
        manual_context=manual_context or "None available.",
        question=question,
    )
    answer = router.generate(prompt, role="articulation")

    if _has_numeric_score(answer) or not _has_valid_risk_band(answer):
        # CRITICAL SAFETY NET — Section 5.2 "ON HEALTH SCORES": the health
        # score MUST be a transparent band, never a precise-looking number.
        # The underlying physics finding is still real and sourced regardless
        # of how the LLM phrased it — if the LLM ignored the prompt's
        # band-only instruction (numeric score) or failed to state a real
        # band at all, don't let that phrasing pass through. Fall back to a
        # deterministic, band-only answer built directly from the rule
        # kernel's own RiskLevel values, never from what the LLM said.
        answer = _deterministic_band_answer(fired_rules, rule_summary)

    return {"answer": answer, "source": sources}

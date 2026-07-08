from datetime import datetime, timezone
from unittest.mock import patch

from agents import orchestrator
from agents.state import AgentState


def _blank_state(question: str) -> AgentState:
    return {
        "question": question,
        "history": [],
        "asset_context": None,
        "route": "",
        "agent_outputs": {},
        "sources": [],
        "final_answer": "",
        "enough_info": False,
    }


def _fake_generate(routing_response, articulation_response=None, forbid_articulation=False):
    """A single role-aware stand-in for llm.router.generate.

    orchestrator.py, asset_agent.py, and maintenance_agent.py all do
    `from llm import router` and call `router.generate(...)` — that's the same
    function object everywhere. Patching it once per test (keyed by role)
    avoids two separate `patch()` calls silently clobbering each other, which
    is what a naive per-module patch would do here.

    articulation_response may be a single value (returned for every
    articulation call, the original behavior) or a list (returned in
    sequence, one per articulation call — needed for the maintenance ->
    compliance chain, which makes two articulation calls per invocation).
    """
    is_sequence = isinstance(articulation_response, list)
    responses = iter(articulation_response) if is_sequence else None

    def fake(prompt, role="articulation"):
        if role == "routing":
            return routing_response
        if role == "articulation":
            if forbid_articulation:
                raise AssertionError("articulation LLM should not have been called")
            return next(responses) if is_sequence else articulation_response
        raise ValueError(f"unexpected role: {role!r}")

    return fake


def test_question_routes_to_asset_node_and_produces_sourced_answer():
    # The routing KPI itself (>=90% on the scripted set) is measured
    # separately with real questions against the live model, not by this test.
    fake = _fake_generate(routing_response="asset", articulation_response="UPS-01 is a 500kVA Eaton 9395P UPS.")
    with patch("agents.orchestrator.router.generate", side_effect=fake):
        result = orchestrator.graph.invoke(_blank_state("What is the rated capacity of UPS-01?"))

    assert result["route"] == "asset"
    assert result["final_answer"] == "UPS-01 is a 500kVA Eaton 9395P UPS."
    assert result["enough_info"] is True
    assert len(result["sources"]) == 1
    assert result["sources"][0]["asset_id"] == "UPS-01"


def test_source_check_overrides_to_insufficient_info_when_no_source():
    """The most important test in this pass: Section 5.5 (No Source, No
    Answer) cannot be bypassed, even if an agent forgets to set a source."""
    state = _blank_state("Why is UPS-01 overheating?")
    state["route"] = "asset"
    state["agent_outputs"] = {"asset": {"answer": "Looks fine to me.", "source": None}}

    result = orchestrator.source_check_node(state)

    assert result["final_answer"] == "I don't have enough information."
    assert result["enough_info"] is False


def test_source_check_overrides_for_non_dict_agent_output():
    """All four specialist agents are real now, but source_check_node must
    still not crash or let an answer through if some future node ever returns
    something other than the {"answer", "source"} dict convention (e.g. a
    bare string) — it should still treat that as "no source"."""
    state = _blank_state("What's causing UPS-01 to trend toward failure?")
    state["route"] = "reliability"
    state["agent_outputs"] = {"reliability": "not yet implemented"}

    result = orchestrator.source_check_node(state)

    assert result["final_answer"] == "I don't have enough information."
    assert result["enough_info"] is False


def test_question_routes_to_maintenance_node_and_produces_sourced_answer():
    """The "maintenance" route now always chains into Compliance when
    Maintenance is sourced (Section 12.2). Here Compliance's own retrieval
    (2nd qdrant_search.search call) finds nothing to cross-check, so the
    original maintenance-only source is preserved unchanged."""
    fake_chunks = [
        {
            "text": "Inspect condenser coils quarterly and verify refrigerant charge against nameplate rating.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    fake = _fake_generate(
        routing_response="maintenance",
        articulation_response="Source: Chiller-COP-Maintenance-SOP.pdf p.12\nSteps: 1. Inspect condenser coils...",
    )
    # qdrant_search.search is the same function object for every agent that
    # imports it — one patch, call-ordered: 1st call is Maintenance's own
    # retrieval, 2nd is Compliance's cross-check retrieval.
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.tools.qdrant_search.search", side_effect=[fake_chunks, []]),
    ):
        result = orchestrator.graph.invoke(_blank_state("What's the maintenance plan for Chiller-03?"))

    assert result["route"] == "maintenance"
    assert result["enough_info"] is True
    assert result["sources"] == [fake_chunks]


def test_maintenance_node_with_no_sop_leads_to_insufficient_info_via_graph():
    fake = _fake_generate(routing_response="maintenance", forbid_articulation=True)
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.maintenance_agent.qdrant_search.search", return_value=[]),
    ):
        result = orchestrator.graph.invoke(_blank_state("What's the maintenance plan for the backup generator?"))

    assert result["final_answer"] == "I don't have enough information."
    assert result["enough_info"] is False


def test_question_routes_to_compliance_node_and_produces_sourced_answer():
    fake_chunks = [
        {
            "text": "A measured COP below 80% of nameplate rated efficiency indicates probable refrigerant charge loss.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    fake = _fake_generate(
        routing_response="compliance",
        articulation_response=(
            "Not Compliant. Per Chiller-COP-Maintenance-SOP.pdf, page 12: measured COP is below "
            "80% of rated efficiency, which the SOP identifies as a fault condition."
        ),
    )
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.compliance_agent.qdrant_search.search", return_value=fake_chunks),
    ):
        result = orchestrator.graph.invoke(_blank_state("Is Chiller-03 running compliant with its efficiency SOP?"))

    assert result["route"] == "compliance"
    assert result["enough_info"] is True
    assert result["sources"] == [fake_chunks]


def test_question_routes_to_reliability_node_and_produces_sourced_answer():
    fake_asset = {"asset_id": "UPS-01", "class": "UPS", "specs": {}, "relationships": []}
    fresh_reading = {
        "readings": {"internal_temp_c": 42.3},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset_properties": {},
    }

    class FakeRuleOutput:
        rule_fired = "THERM-UPS-001 (high_risk)"
        measured_value = 42.3
        explanation = "UPS-01 internal temperature (42.3 C) exceeds the 40.0 C high-risk threshold."

        class risk_level:
            value = "High Risk"

    fired_rules = [FakeRuleOutput()]

    fake = _fake_generate(
        routing_response="reliability",
        articulation_response="High Risk. THERM-UPS-001 fired at 42.3 C.",
    )
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=fired_rules),
        patch("agents.reliability_agent.asset_agent.run", return_value={"answer": "asset not found", "source": None}),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
    ):
        result = orchestrator.graph.invoke(_blank_state("Why is UPS-01 repeatedly overheating?"))

    assert result["route"] == "reliability"
    assert result["enough_info"] is True
    assert result["sources"] == [fired_rules]
    assert result["final_answer"] == "High Risk. THERM-UPS-001 fired at 42.3 C."


def test_out_of_scope_question_routes_without_calling_routing_llm():
    """Scope boundary guardrail (Section 7.3 / 4.4): an out-of-scope question
    must never burn a routing call, and must land on the explicit scope
    message — not "asset not found" or a generic "insufficient information."
    """
    with patch("agents.orchestrator.router.generate") as mock_generate:
        result = orchestrator.graph.invoke(
            _blank_state("Is the fire suppression system in the server hall compliant?")
        )

    mock_generate.assert_not_called()
    assert result["route"] == "out_of_scope"
    assert "outside the current MVP's scope" in result["final_answer"]
    assert "Fire Systems" in result["final_answer"]
    assert result["enough_info"] is False


def test_maintenance_route_chains_into_compliance_when_maintenance_is_sourced():
    """Demo Scenario 2, Section 12.2 step 4: a sourced maintenance procedure
    automatically triggers a Compliance cross-check as part of the same
    answer — not a separate user question."""
    maintenance_chunks = [
        {
            "text": "Inspect condenser coils quarterly and verify refrigerant charge against nameplate rating.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    compliance_chunks = [
        {
            "text": "Quarterly inspection frequency is required for condenser coil maintenance.",
            "doc_name": "Chiller-Frequency-SOP.pdf",
            "page": 4,
            "score": 0.81,
        }
    ]
    maintenance_answer = "Source: Chiller-COP-Maintenance-SOP.pdf p.12\nSteps: 1. Inspect condenser coils..."
    compliance_answer = (
        "Compliant. Per Chiller-Frequency-SOP.pdf, page 4: quarterly frequency matches the required cadence."
    )
    fake = _fake_generate(
        routing_response="maintenance",
        articulation_response=[maintenance_answer, compliance_answer],
    )
    # qdrant_search.search is one shared function object across agents — a
    # single patch, call-ordered: 1st call is Maintenance's retrieval, 2nd is
    # Compliance's cross-check retrieval.
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.tools.qdrant_search.search", side_effect=[maintenance_chunks, compliance_chunks]) as mock_search,
    ):
        result = orchestrator.graph.invoke(_blank_state("What's the maintenance plan for Chiller-03?"))

    assert result["route"] == "maintenance"
    assert result["enough_info"] is True
    assert maintenance_answer in result["final_answer"]
    assert "Compliance check:" in result["final_answer"]
    assert compliance_answer in result["final_answer"]
    assert mock_search.call_count == 2
    assert result["sources"] == [maintenance_chunks + compliance_chunks]


def test_maintenance_route_never_calls_compliance_when_maintenance_has_no_source():
    fake = _fake_generate(routing_response="maintenance", forbid_articulation=True)
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.tools.qdrant_search.search", return_value=[]) as mock_search,
    ):
        result = orchestrator.graph.invoke(_blank_state("What's the maintenance plan for the backup generator?"))

    # Only Maintenance's own retrieval call should have happened — Compliance
    # is never reached when there's nothing sourced to cross-check.
    assert mock_search.call_count == 1
    assert result["final_answer"] == "I don't have enough information."
    assert result["enough_info"] is False


def test_maintenance_chain_survives_compliance_downgrade_to_insufficient_information():
    """THE IMPORTANT EDGE CASE: Compliance's own safety net downgrading an
    uncited "Compliant" verdict must not drag down an otherwise validly
    sourced maintenance procedure."""
    maintenance_chunks = [
        {
            "text": "Inspect condenser coils quarterly and verify refrigerant charge against nameplate rating.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    compliance_chunks = [
        {
            "text": "Quarterly inspection frequency is required for condenser coil maintenance.",
            "doc_name": "Chiller-Frequency-SOP.pdf",
            "page": 4,
            "score": 0.81,
        }
    ]
    maintenance_answer = "Source: Chiller-COP-Maintenance-SOP.pdf p.12\nSteps: 1. Inspect condenser coils..."
    lazy_compliance_answer = "Compliant."  # no clause cited -> triggers the safety net
    fake = _fake_generate(
        routing_response="maintenance",
        articulation_response=[maintenance_answer, lazy_compliance_answer],
    )
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.tools.qdrant_search.search", side_effect=[maintenance_chunks, compliance_chunks]),
    ):
        result = orchestrator.graph.invoke(_blank_state("What's the maintenance plan for Chiller-03?"))

    assert result["enough_info"] is True
    assert maintenance_answer in result["final_answer"]
    assert "What was searched" in result["final_answer"]  # the downgraded compliance note
    # Compliance's own source was rejected (None), so only the maintenance
    # chunks survive into the merged source list.
    assert result["sources"] == [maintenance_chunks]


def test_direct_compliance_route_is_unaffected_by_the_new_chaining_node():
    """Existing direct-compliance test, unchanged — proves route="compliance"
    still goes straight to compliance_node, not through the chain."""
    fake_chunks = [
        {
            "text": "A measured COP below 80% of nameplate rated efficiency indicates probable refrigerant charge loss.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    fake = _fake_generate(
        routing_response="compliance",
        articulation_response=(
            "Not Compliant. Per Chiller-COP-Maintenance-SOP.pdf, page 12: measured COP is below "
            "80% of rated efficiency, which the SOP identifies as a fault condition."
        ),
    )
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.compliance_agent.qdrant_search.search", return_value=fake_chunks),
    ):
        result = orchestrator.graph.invoke(_blank_state("Is Chiller-03 running compliant with its efficiency SOP?"))

    assert result["route"] == "compliance"
    assert result["enough_info"] is True
    assert result["sources"] == [fake_chunks]


def test_portfolio_question_routes_to_reliability_and_produces_sourced_ranked_answer():
    """Demo Scenario 3 (Section 12.3): a portfolio-phrased question with no
    asset ID routes to "reliability" and produces a real sourced answer
    through the full graph, via _run_portfolio()."""
    fake_assets = [
        {"asset_id": "HIGH-01", "class": "UPS"},
        {"asset_id": "LOW-01", "class": "UPS"},
    ]
    fresh_readings = {
        "HIGH-01": {
            "readings": {"internal_temp_c": 45.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
        "LOW-01": {
            "readings": {"internal_temp_c": 20.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
    }
    fake = _fake_generate(
        routing_response="reliability",
        articulation_response="HIGH-01 — High Risk — fired.\nLOW-01 — Low Risk — no rule fired.",
    )
    with (
        patch("agents.orchestrator.router.generate", side_effect=fake),
        patch("agents.reliability_agent.cypher_query.list_all_assets", return_value=fake_assets),
        patch(
            "agents.reliability_agent.sensor_data.get_current_reading",
            side_effect=lambda aid: fresh_readings[aid],
        ),
    ):
        result = orchestrator.graph.invoke(_blank_state("Show me the critical assets with the highest risk right now."))

    assert result["route"] == "reliability"
    assert result["enough_info"] is True
    assert len(result["sources"]) == 1
    assert [entry["asset_id"] for entry in result["sources"][0]] == ["HIGH-01", "LOW-01"]


def test_gibberish_routing_response_is_unroutable_not_silently_asset():
    """Proves the fix: an unparseable routing response must never silently
    fall through to a real agent (Section 5.5 risk) — it should land on the
    real "unroutable" terminal node and flow through the existing
    source_check_node like any other route."""
    fake = _fake_generate(routing_response="banana", forbid_articulation=True)
    with patch("agents.orchestrator.router.generate", side_effect=fake):
        result = orchestrator.graph.invoke(_blank_state("What is the meaning of life?"))

    assert result["route"] == "unroutable"
    assert result["final_answer"] == "I don't have enough information."
    assert result["enough_info"] is False

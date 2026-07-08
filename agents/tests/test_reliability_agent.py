from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agents import orchestrator, reliability_agent
from agents.tools import cypher_query

_NO_SOURCE_ASSET_AGENT_RESULT = {"answer": "asset not found", "source": None}


def test_get_downstream_assets_known_asset_returns_directional_dependencies():
    """UPS-01 has POWERS -> RACK-A12 (real downstream) and FED_BY -> PDU-03
    (reverse direction — PDU-03 is upstream of UPS-01, not downstream of it).
    Only the forward directional edge should come back."""
    result = cypher_query.get_downstream_assets("UPS-01")
    assert result == [{"asset_id": "RACK-A12", "relationship": "POWERS"}]


def test_get_downstream_assets_unknown_asset_returns_empty_list():
    assert cypher_query.get_downstream_assets("FOO-99") == []


def test_get_downstream_assets_asset_with_no_downstream_edges_returns_empty_list():
    # PUMP-07's only relationship is SERVES -> CHILLER-03, which is a reverse
    # edge (CHILLER-03 depends on PUMP-07, not the other way around) — not a
    # directional dependency type, so no downstream assets.
    assert cypher_query.get_downstream_assets("PUMP-07") == []


def test_no_asset_id_returns_insufficient_answer_without_calling_llm():
    with patch("agents.reliability_agent.router.generate") as mock_generate:
        result = reliability_agent.run("Why do things break sometimes?")

    assert result == {"answer": "Could not identify which asset this question refers to.", "source": None}
    mock_generate.assert_not_called()


def test_unknown_asset_returns_not_found_without_calling_llm_or_rule_engine():
    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=None),
        patch("agents.reliability_agent.rule_engine.check_rules") as mock_check_rules,
        patch("agents.reliability_agent.router.generate") as mock_generate,
    ):
        result = reliability_agent.run("Why is FOO-99 overheating?")

    assert result == {"answer": "asset not found", "source": None}
    mock_check_rules.assert_not_called()
    mock_generate.assert_not_called()


def test_no_sensor_data_returns_explicit_answer_without_calling_llm_or_rule_engine():
    fake_asset = {"asset_id": "UPS-01", "class": "UPS", "specs": {}, "relationships": []}
    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=None),
        patch("agents.reliability_agent.rule_engine.check_rules") as mock_check_rules,
        patch("agents.reliability_agent.router.generate") as mock_generate,
    ):
        result = reliability_agent.run("Why is UPS-01 overheating?")

    assert result == {"answer": "No sensor data is available for this asset.", "source": None}
    mock_check_rules.assert_not_called()
    mock_generate.assert_not_called()


def test_stale_sensor_data_returns_explicit_answer_without_calling_llm_or_rule_engine():
    fake_asset = {"asset_id": "PUMP-07", "class": "Pump", "specs": {}, "relationships": []}
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    stale_reading = {
        "readings": {"vibration_mm_s": 6.2},
        "timestamp": stale_timestamp,
        "asset_properties": {"rated_vibration_mm_s": 4.5},
    }
    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=stale_reading),
        patch("agents.reliability_agent.rule_engine.check_rules") as mock_check_rules,
        patch("agents.reliability_agent.router.generate") as mock_generate,
    ):
        result = reliability_agent.run("Why is PUMP-07 vibrating so much?")

    assert result["source"] is None
    assert "stale" in result["answer"].lower()
    assert "PUMP-07" in result["answer"]
    mock_check_rules.assert_not_called()
    mock_generate.assert_not_called()


def test_fresh_data_with_fired_rules_returns_that_exact_list_as_source():
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

    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=fired_rules),
        patch("agents.reliability_agent.asset_agent.run", return_value=_NO_SOURCE_ASSET_AGENT_RESULT),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value="High Risk. THERM-UPS-001 fired...") as mock_generate,
    ):
        result = reliability_agent.run("Why is UPS-01 overheating?")

    assert result["source"] == fired_rules
    assert result["answer"] == "High Risk. THERM-UPS-001 fired..."
    mock_generate.assert_called_once()


def test_fresh_data_with_no_fired_rules_is_still_a_sourced_answer_not_insufficient_info():
    """IMPORTANT: an empty rule-fired list is a real "currently low risk"
    finding backed by a real reading, not a failure — it must not be
    swallowed into "insufficient information." Proven end-to-end through the
    real (unmodified) source_check_node."""
    fake_asset = {"asset_id": "UPS-01", "class": "UPS", "specs": {}, "relationships": []}
    fresh_reading = {
        "readings": {"internal_temp_c": 22.0},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset_properties": {},
    }

    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=[]),
        patch("agents.reliability_agent.asset_agent.run", return_value=_NO_SOURCE_ASSET_AGENT_RESULT),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value="Low Risk. No thresholds crossed."),
    ):
        result = reliability_agent.run("Is UPS-01 at risk right now?")

    assert result["source"] is not None
    assert result["source"] == [
        {
            "asset_id": "UPS-01",
            "readings": {"internal_temp_c": 22.0},
            "timestamp": fresh_reading["timestamp"],
            "note": "no configured rule threshold was crossed",
        }
    ]

    # Feed this exact result through the real, unmodified source_check_node to
    # prove enough_info actually comes out True — not just that source isn't None.
    state = {
        "question": "Is UPS-01 at risk right now?",
        "history": [],
        "asset_context": None,
        "route": "reliability",
        "agent_outputs": {"reliability": result},
        "sources": [],
        "final_answer": "",
        "enough_info": False,
    }
    check_result = orchestrator.source_check_node(state)
    assert check_result["enough_info"] is True
    assert check_result["final_answer"] == "Low Risk. No thresholds crossed."


def test_maintenance_history_source_is_carried_into_sources_when_present():
    """The Asset Agent's own source (the graph fact backing the maintenance
    history) must stay traceable — not just its answer text folded silently
    into the prompt context with no corresponding source entry."""
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
    asset_graph_fact = {"asset_id": "UPS-01", "class": "UPS", "specs": {}, "relationships": []}
    sourced_asset_agent_result = {"answer": "Last serviced 2026-02-01.", "source": asset_graph_fact}

    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=fired_rules),
        patch("agents.reliability_agent.asset_agent.run", return_value=sourced_asset_agent_result),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value="High Risk. THERM-UPS-001 fired..."),
    ):
        result = reliability_agent.run("Why is UPS-01 overheating?")

    assert result["source"] == fired_rules + [asset_graph_fact]


def test_llm_numeric_score_is_overridden_with_deterministic_band_answer():
    """THE MOST IMPORTANT TEST FOR THIS FIX: if the LLM ignores the band-only
    instruction and outputs a numeric score, that must never reach the user —
    Section 5.2's "ON HEALTH SCORES" rule enforced in code, mirroring the
    Compliance Agent's uncited-verdict safety net."""
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
    lazy_llm_response = "Risk score: 73/100."

    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=fired_rules),
        patch("agents.reliability_agent.asset_agent.run", return_value=_NO_SOURCE_ASSET_AGENT_RESULT),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value=lazy_llm_response),
    ):
        result = reliability_agent.run("Why is UPS-01 overheating?")

    assert result["answer"] != lazy_llm_response
    assert "73/100" not in result["answer"]
    assert "High Risk" in result["answer"]
    # The real, sourced physics finding is preserved regardless of the LLM's
    # bad phrasing — this is a downgrade of the narrative, not the source.
    assert result["source"] == fired_rules


def test_llm_answer_with_valid_band_and_no_numeric_score_passes_through_unchanged():
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
    good_llm_response = "High Risk. THERM-UPS-001 fired at 42.3 C. Recommendation (advisory): inspect cooling."

    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=fired_rules),
        patch("agents.reliability_agent.asset_agent.run", return_value=_NO_SOURCE_ASSET_AGENT_RESULT),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value=good_llm_response),
    ):
        result = reliability_agent.run("Why is UPS-01 overheating?")

    assert result["answer"] == good_llm_response


def test_portfolio_question_with_no_asset_id_ranks_assets_by_risk():
    """Demo Scenario 3 (Section 12.3): a portfolio-phrased question with no
    asset ID must route to _run_portfolio(), not the single-asset "could not
    identify asset" path — and the ranked list/source must reflect real
    Physics Rule Kernel output (High before Medium before no-fire)."""
    fake_assets = [
        {"asset_id": "HIGH-01", "class": "UPS"},
        {"asset_id": "MED-01", "class": "UPS"},
        {"asset_id": "LOW-01", "class": "UPS"},
    ]
    fresh_readings = {
        "HIGH-01": {
            "readings": {"internal_temp_c": 45.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
        "MED-01": {
            "readings": {"internal_temp_c": 37.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
        "LOW-01": {
            "readings": {"internal_temp_c": 20.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
    }
    fake_answer = (
        "HIGH-01 — High Risk — THERM-UPS-001 fired.\n"
        "MED-01 — Medium Risk — THERM-UPS-001 fired.\n"
        "LOW-01 — Low Risk — no rule fired."
    )

    with (
        patch("agents.reliability_agent.cypher_query.list_all_assets", return_value=fake_assets),
        patch("agents.reliability_agent.sensor_data.get_current_reading", side_effect=lambda aid: fresh_readings[aid]),
        patch("agents.reliability_agent.router.generate", return_value=fake_answer) as mock_generate,
    ):
        result = reliability_agent.run("Show me the critical assets with the highest risk right now.")

    assert result["answer"] == fake_answer
    assert result["source"] is not None
    assert [entry["asset_id"] for entry in result["source"]] == ["HIGH-01", "MED-01", "LOW-01"]
    assert result["source"][0]["highest_risk_level"].value == "High Risk"
    assert result["source"][1]["highest_risk_level"].value == "Medium Risk"
    assert result["source"][2]["highest_risk_level"] is None

    # Prompt itself must present assets in ranked order (High -> Medium -> no fire).
    prompt_sent = mock_generate.call_args[0][0]
    assert prompt_sent.index("HIGH-01") < prompt_sent.index("MED-01") < prompt_sent.index("LOW-01")


def test_portfolio_flagged_asset_gets_downstream_lookup_non_flagged_does_not():
    """Section 12.3 Step 3 / Section 4.3: only flagged (High/Alert) assets
    trigger a downstream-dependency lookup — not every asset in the
    portfolio. A Medium-risk and a no-fire asset must never even call
    get_downstream_assets (scope discipline), while the High-risk asset's
    result must carry real downstream data through to both the prompt and
    the source."""
    fake_assets = [
        {"asset_id": "HIGH-01", "class": "UPS"},
        {"asset_id": "MED-01", "class": "UPS"},
        {"asset_id": "LOW-01", "class": "UPS"},
    ]
    fresh_readings = {
        "HIGH-01": {
            "readings": {"internal_temp_c": 45.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
        "MED-01": {
            "readings": {"internal_temp_c": 37.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
        "LOW-01": {
            "readings": {"internal_temp_c": 20.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        },
    }
    downstream_result = [{"asset_id": "RACK-A12", "relationship": "POWERS"}]

    with (
        patch("agents.reliability_agent.cypher_query.list_all_assets", return_value=fake_assets),
        patch("agents.reliability_agent.sensor_data.get_current_reading", side_effect=lambda aid: fresh_readings[aid]),
        patch(
            "agents.reliability_agent.cypher_query.get_downstream_assets", return_value=downstream_result
        ) as mock_downstream,
        patch("agents.reliability_agent.router.generate", return_value="placeholder") as mock_generate,
    ):
        result = reliability_agent.run("Show me the critical assets with the highest risk right now.")

    # Only the flagged (High) asset triggers the lookup — called exactly
    # once, for HIGH-01, never for MED-01 or LOW-01.
    mock_downstream.assert_called_once_with("HIGH-01")

    source_by_id = {entry["asset_id"]: entry for entry in result["source"]}
    assert source_by_id["HIGH-01"]["downstream"] == downstream_result
    assert "downstream" not in source_by_id["MED-01"]
    assert "downstream" not in source_by_id["LOW-01"]

    prompt_sent = mock_generate.call_args[0][0]
    assert "Downstream impact: powers RACK-A12." in prompt_sent


def test_portfolio_flagged_asset_with_no_downstream_edges_states_that_explicitly():
    """A flagged asset with zero downstream relationships is still a real
    finding — the prompt must say so explicitly, not just omit the line."""
    fake_assets = [{"asset_id": "HIGH-01", "class": "UPS"}]
    fresh_readings = {
        "HIGH-01": {
            "readings": {"internal_temp_c": 45.0},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "asset_properties": {},
        }
    }

    with (
        patch("agents.reliability_agent.cypher_query.list_all_assets", return_value=fake_assets),
        patch("agents.reliability_agent.sensor_data.get_current_reading", side_effect=lambda aid: fresh_readings[aid]),
        patch("agents.reliability_agent.cypher_query.get_downstream_assets", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value="placeholder") as mock_generate,
    ):
        reliability_agent.run("Show me the critical assets with the highest risk right now.")

    prompt_sent = mock_generate.call_args[0][0]
    assert "Downstream impact: no downstream dependencies recorded." in prompt_sent


def test_portfolio_question_excludes_stale_asset_without_failing_whole_scan():
    """A stale asset must be excluded and noted, not crash the whole
    portfolio call — the other assets still get evaluated normally."""
    fake_assets = [
        {"asset_id": "OK-01", "class": "UPS"},
        {"asset_id": "STALE-01", "class": "Pump"},
    ]
    ok_reading = {
        "readings": {"internal_temp_c": 45.0},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset_properties": {},
    }
    stale_reading = {
        "readings": {"vibration_mm_s": 6.2},
        "timestamp": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
        "asset_properties": {"rated_vibration_mm_s": 4.5},
    }
    readings = {"OK-01": ok_reading, "STALE-01": stale_reading}

    with (
        patch("agents.reliability_agent.cypher_query.list_all_assets", return_value=fake_assets),
        patch("agents.reliability_agent.sensor_data.get_current_reading", side_effect=lambda aid: readings[aid]),
        patch("agents.reliability_agent.router.generate", return_value="OK-01 — High Risk — fired.") as mock_generate,
    ):
        result = reliability_agent.run("Which assets are at risk right now?")

    assert result["source"] is not None
    assert [entry["asset_id"] for entry in result["source"]] == ["OK-01"]

    prompt_sent = mock_generate.call_args[0][0]
    assert "STALE-01" in prompt_sent
    assert "excluded" in prompt_sent.lower()


def test_single_asset_question_with_portfolio_style_wording_still_uses_single_asset_path():
    """A specific asset ID always wins over portfolio-indicating phrasing."""
    fake_asset = {"asset_id": "UPS-01", "class": "UPS", "specs": {}, "relationships": []}
    fresh_reading = {
        "readings": {"internal_temp_c": 42.3},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset_properties": {},
    }
    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.cypher_query.list_all_assets") as mock_list_all,
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=[]),
        patch("agents.reliability_agent.asset_agent.run", return_value=_NO_SOURCE_ASSET_AGENT_RESULT),
        patch("agents.reliability_agent.qdrant_search.search", return_value=[]),
        patch("agents.reliability_agent.router.generate", return_value="Low Risk. No thresholds crossed."),
    ):
        result = reliability_agent.run("Which assets are at highest risk, especially UPS-01?")

    mock_list_all.assert_not_called()
    assert result["source"] == [
        {
            "asset_id": "UPS-01",
            "readings": {"internal_temp_c": 42.3},
            "timestamp": fresh_reading["timestamp"],
            "note": "no configured rule threshold was crossed",
        }
    ]


def test_manual_chunks_below_confidence_floor_are_dropped_from_context_and_source():
    """Confidence-gated answers guardrail (Section 7.3): a weak manual-passage
    match is dropped exactly as if nothing had been retrieved — it must not
    show up in the prompt context or the merged source list."""
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
    weak_manual_chunks = [
        {"text": "Vaguely related failure-mode note.", "doc_name": "Unrelated-Doc.pdf", "page": 1, "score": 0.2}
    ]

    with (
        patch("agents.reliability_agent.cypher_query.get_asset", return_value=fake_asset),
        patch("agents.reliability_agent.sensor_data.get_current_reading", return_value=fresh_reading),
        patch("agents.reliability_agent.rule_engine.check_rules", return_value=fired_rules),
        patch("agents.reliability_agent.asset_agent.run", return_value=_NO_SOURCE_ASSET_AGENT_RESULT),
        patch("agents.reliability_agent.qdrant_search.search", return_value=weak_manual_chunks),
        patch("agents.reliability_agent.router.generate", return_value="High Risk. THERM-UPS-001 fired...") as mock_generate,
    ):
        result = reliability_agent.run("Why is UPS-01 overheating?")

    assert result["source"] == fired_rules
    prompt_sent = mock_generate.call_args[0][0]
    assert "Vaguely related failure-mode note." not in prompt_sent
    assert "None available." in prompt_sent

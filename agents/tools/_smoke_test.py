"""Manual verification script for Phase 1 (Foundation) — not a pytest suite.

Run with: python3 -m agents.tools._smoke_test
"""

from datetime import datetime, timedelta, timezone

from agents.state import AgentState
from agents.tools import cypher_query, pg_query, qdrant_search, rule_engine, sensor_data
from llm import router


def check_state():
    print("=== AgentState ===")
    state: AgentState = {
        "question": "Why is UPS-01 overheating?",
        "history": [],
        "asset_context": None,
        "route": "reliability",
        "agent_outputs": {},
        "sources": [],
        "final_answer": "",
        "enough_info": False,
    }
    for field in (
        "question", "history", "asset_context", "route", "agent_outputs",
        "sources", "final_answer", "enough_info",
    ):
        assert field in state
    print("All 8 fields settable:", state)
    print()


def check_llm():
    print("=== llm.router.generate (real NVIDIA API) ===")
    try:
        response = router.generate("Reply with exactly: OK", role="articulation")
        print("Response:", response)
    except RuntimeError as e:
        print("SKIPPED — real API call could not be made:", e)
    print()


def check_mock_tools():
    print("=== agents.tools.qdrant_search.search ===")
    print("UPS match:", qdrant_search.search("why is it overheating", asset_class="UPS"))
    no_match = qdrant_search.search("generator maintenance procedure", asset_class="Generator")
    print("Generator (no SOP indexed) no-match case:", no_match)
    assert no_match == []
    print()

    print("=== agents.tools.cypher_query.get_asset ===")
    print("known asset UPS-01:", cypher_query.get_asset("UPS-01"))
    print("unknown asset FOO-99:", cypher_query.get_asset("FOO-99"))
    print()

    print("=== agents.tools.pg_query.get_maintenance_history ===")
    print(pg_query.get_maintenance_history("UPS-01"))
    print()

    print("=== agents.tools.sensor_data.get_current_reading ===")
    fresh = sensor_data.get_current_reading("UPS-01")
    print("UPS-01 (fresh):", fresh)
    stale = sensor_data.get_current_reading("PUMP-07")
    print("PUMP-07 (deliberately stale):", stale)
    age = datetime.now(timezone.utc) - datetime.fromisoformat(stale["timestamp"])
    print(f"PUMP-07 reading age: {age} -> stale (>24h): {age > timedelta(hours=24)}")
    assert age > timedelta(hours=24)
    print("unknown asset FOO-99:", sensor_data.get_current_reading("FOO-99"))
    print()


def check_rule_engine():
    print("=== agents.tools.rule_engine.check_rules (real physics kernel) ===")
    result = rule_engine.check_rules(
        asset_id="UPS-01",
        asset_class="UPS",
        readings={"internal_temp_c": 42.3},
    )
    print(result)
    assert len(result) == 1
    output = result[0]
    assert output.rule_fired == "THERM-UPS-001 (high_risk)"
    assert output.measured_value == 42.3
    print("Confirmed: real RuleOutput from physics.engine, not a mock.")
    print()


if __name__ == "__main__":
    check_state()
    check_llm()
    check_mock_tools()
    check_rule_engine()

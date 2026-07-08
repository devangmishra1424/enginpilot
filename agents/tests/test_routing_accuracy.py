"""Section 5.0 MVP KPI: "Correct agent routing on >=90% of scripted demo
questions, verified by manual test." Section 11.2 lists this as a formal Exit
Criterion.

This is a LIVE, non-mocked measurement of the real routing LLM's behavior —
deliberately separate from test_orchestrator.py (which mocks router.generate
for fast, deterministic coverage of the graph's wiring). A mocked test cannot
measure this KPI; it can only prove _parse_route()'s logic is correct given a
canned response. This file measures whether the model actually classifies
real questions correctly, which is what Section 5.0 is asking for.

Marked @pytest.mark.live_llm — run explicitly with:
    pytest agents/tests/test_routing_accuracy.py -v -s
Excluded from a default `pytest agents/ physics/` run only if the caller
chooses to filter markers (e.g. `-m "not live_llm"`); by default pytest runs
markers unless deselected, so this still executes as part of the full suite
and costs real API calls each time.
"""

import pytest

from agents import orchestrator

# 15 questions, expected route, covering all 5 possible outcomes.
QUESTIONS = [
    # asset (4)
    ("What is the rated capacity of UPS-01?", "asset"),
    ("What rack does UPS-01 power?", "asset"),
    ("Who manufactures Chiller-03 and what model is it?", "asset"),
    ("What is PDU-03's rated capacity?", "asset"),
    # reliability (4, including 1 portfolio-style)
    ("Why is UPS-01 overheating?", "reliability"),
    ("What is the current health status of Chiller-03?", "reliability"),
    ("Is Pump-07 vibrating abnormally?", "reliability"),
    ("Show me the critical assets with the highest risk right now.", "reliability"),
    # maintenance (3)
    ("What's the maintenance plan for Chiller-03?", "maintenance"),
    ("Generate a preventive maintenance procedure for UPS-01.", "maintenance"),
    ("What steps are needed to service the battery bank?", "maintenance"),
    # compliance (2)
    ("Is running the chiller at this load compliant with the SOP?", "compliance"),
    ("Does the current UPS battery inspection frequency meet SOP requirements?", "compliance"),
    # out_of_scope (1) — Section 4.4 exclusion, detected before any LLM call
    ("Is the fire suppression system in the server hall compliant?", "out_of_scope"),
    # unroutable (1) — the exact question that found the gibberish-routing bug
    ("asdkfj random nonsense question xyz", "unroutable"),
]


@pytest.mark.live_llm
def test_routing_accuracy_on_15_question_scripted_set():
    results = []
    for question, expected in QUESTIONS:
        actual = orchestrator.orchestrator_node({"question": question})["route"]
        results.append((question, expected, actual, actual == expected))

    passed = sum(1 for *_ , match in results if match)
    total = len(results)
    pct = 100 * passed / total

    print(f"\n{'Question':<70} {'Expected':<14} {'Actual':<14} {'Match'}")
    print("-" * 115)
    for question, expected, actual, match in results:
        mark = "✓" if match else "✗"
        print(f"{question:<70} {expected:<14} {actual:<14} {mark}")
    print("-" * 115)
    print(f"RESULT: {passed}/{total} = {pct:.1f}%  (Section 5.0 KPI threshold: >=90%)")

    failures = [(q, e, a) for q, e, a, m in results if not m]
    if failures:
        print("\nFAILED:")
        for q, e, a in failures:
            print(f"  - {q!r}: expected {e!r}, got {a!r}")

    assert pct >= 90.0, (
        f"Routing accuracy {pct:.1f}% ({passed}/{total}) is below the Section 5.0 KPI "
        f"threshold of 90%. Failures: {failures}"
    )

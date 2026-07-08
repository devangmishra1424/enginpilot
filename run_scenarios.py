"""Live end-to-end run: all 3 demo scenarios through the real orchestrator,
real LLM calls (current MODEL_REGISTRY), existing mock tool data.

Run: python3 run_scenarios.py
"""

import time

from agents.orchestrator import graph

QUESTIONS = [
    ("Scenario 1 — Reliability", "Why is UPS-01 repeatedly overheating?"),
    ("Scenario 2 — Maintenance→Compliance", "Generate a maintenance plan for Chiller-03."),
    ("Scenario 3 — Portfolio", "Show me the critical assets with the highest risk right now."),
]

for label, question in QUESTIONS:
    print(f"\n{'=' * 70}\n{label}\nQ: {question}\n{'-' * 70}")

    state = {
        "question": question,
        "history": [],
        "asset_context": None,
        "route": "",
        "agent_outputs": {},
        "sources": [],
        "final_answer": "",
        "enough_info": False,
    }

    start = time.monotonic()
    result = graph.invoke(state)
    elapsed = time.monotonic() - start

    print(f"Route: {result['route']}")
    print(f"Enough info: {result['enough_info']}")
    print(f"Time: {elapsed:.1f}s")
    print(f"\nFinal answer:\n{result['final_answer']}")
    print(f"\nSources:\n{result['sources']}")

print(f"\n{'=' * 70}\nDone.")
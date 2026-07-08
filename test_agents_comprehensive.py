"""Comprehensive live test: every agent, every major path, real LLM + real 
RAG. Not a pytest suite — read the actual output yourself.

Run: python3 test_agents_comprehensive.py
"""

from agents import asset_agent, maintenance_agent, compliance_agent, reliability_agent, orchestrator
from agents.state import AgentState


def run_agent(label, fn, question):
    print(f"\n{'=' * 70}\n{label}\nQ: {question}\n{'-' * 70}")
    result = fn(question)
    print(f"Answer:\n{result['answer']}")
    print(f"\nSource present: {result['source'] is not None}")


def run_orchestrator(label, question):
    print(f"\n{'=' * 70}\n{label} (full orchestrator)\nQ: {question}\n{'-' * 70}")
    state: AgentState = {
        "question": question, "history": [], "asset_context": None,
        "route": "", "agent_outputs": {}, "sources": [],
        "final_answer": "", "enough_info": False,
    }
    result = orchestrator.graph.invoke(state)
    print(f"Route: {result['route']}")
    print(f"Enough info: {result['enough_info']}")
    print(f"Final answer:\n{result['final_answer']}")


# --- Happy paths across NEW asset classes (never tested live before) ---
run_agent("Maintenance — Battery (new real SOP data)", maintenance_agent.run,
          "Generate a maintenance plan for the battery bank.")

run_agent("Compliance — UPS (different asset class than before)", compliance_agent.run,
          "Is UPS-01 compliant with its preventive maintenance SOP?")

# --- Escalation / failure paths, now against REAL retrieval, not mocks ---
run_agent("Maintenance — nonsense asset (should say no SOP found)", maintenance_agent.run,
          "Generate a maintenance plan for the underwater sonar array.")

run_agent("Reliability — unknown asset (should say asset not found)", reliability_agent.run,
          "Why is FOO-99 overheating?")

# --- Portfolio path, live, with real RAG context available this time ---
run_agent("Reliability — portfolio", reliability_agent.run,
          "Show me the critical assets with the highest risk right now.")

# --- Full orchestrator: routing + sequential chaining + guardrails ---
run_orchestrator("Orchestrator — Scenario 2 chain (Maintenance->Compliance)",
                  "Generate a maintenance plan for Chiller-03.")

run_orchestrator("Orchestrator — out-of-scope guardrail",
                  "Is the fire suppression system compliant?")

run_orchestrator("Orchestrator — gibberish/unroutable",
                  "asdkfj random nonsense question xyz")

print(f"\n{'=' * 70}\nDone.")
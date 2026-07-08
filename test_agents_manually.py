"""Manual test: run one real question through each agent directly, live 
(real NVIDIA LLM calls + real Qdrant RAG). Not a pytest suite — just for you 
to read the actual output.

Run: python3 test_agents_manually.py
"""

from agents import asset_agent, maintenance_agent, compliance_agent, reliability_agent

def run_and_print(label, fn, question):
    print(f"\n{'=' * 70}\n{label}\nQ: {question}\n{'-' * 70}")
    result = fn(question)
    print(f"Answer:\n{result['answer']}")
    print(f"\nSource:\n{result['source']}")

run_and_print("Asset Agent", asset_agent.run, "What is the rated capacity of UPS-01?")

run_and_print("Maintenance Agent", maintenance_agent.run, "Generate a maintenance plan for Chiller-03.")

run_and_print("Compliance Agent", compliance_agent.run, "Is Chiller-03 running compliant with its efficiency SOP?")

run_and_print("Reliability Agent (single asset)", reliability_agent.run, "Why is UPS-01 repeatedly overheating?")

print(f"\n{'=' * 70}\nDone.")
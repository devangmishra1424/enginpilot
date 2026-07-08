"""LangGraph orchestrator (Playbook Section 5.0) skeleton.

Routes questions to the right agent via a few-shot classifier prompt (no
trained classifier — Section 5.0 explicitly requires this), then enforces the
single most important rule in the project: no agent answer without a real
source attached (Section 5.5, Cross-Agent Rule — No Source, No Answer). That
check lives in source_check_node and runs after every agent, unconditionally
— it cannot be skipped by any agent forgetting to set a source.

All four specialist agents ("asset", "maintenance", "compliance",
"reliability") are real nodes. "unroutable" is a real terminal node reached
when the routing classifier's response doesn't cleanly resolve to a known
agent — see _parse_route for why this is never silently defaulted to a real
agent instead. "out_of_scope" is a real terminal node reached when the
question matches Section 4.4's explicitly-excluded categories (fire/security/
BMS/DG sets/cooling towers/CRAC) — detected by keyword BEFORE the routing LLM
call runs, so an out-of-scope question never burns a routing call (Section
7.3, Scope Boundary guardrail).

The "maintenance" route is sequential agent chaining (Demo Scenario 2, Section
12.2): a sourced maintenance procedure is automatically cross-checked by the
Compliance Agent before the combined result reaches source_check_node — see
maintenance_then_compliance_node.
"""

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents import asset_agent, compliance_agent, maintenance_agent, reliability_agent
from agents.state import AgentState
from llm import router

_ROUTER_PROMPT_PATH = Path(__file__).parent / "prompts" / "orchestrator.md"
_ROUTER_PROMPT_TEMPLATE = _ROUTER_PROMPT_PATH.read_text()

AGENT_ROUTES = {"asset", "reliability", "maintenance", "compliance"}
UNROUTABLE_ROUTE = "unroutable"
OUT_OF_SCOPE_ROUTE = "out_of_scope"
ROUTES = AGENT_ROUTES | {UNROUTABLE_ROUTE, OUT_OF_SCOPE_ROUTE}

# Scope-boundary guardrail (Section 7.3 / Section 4.4 "Explicitly Out of MVP
# Scope"). Each entry is (category label, keyword pattern) — keywords are
# specific multi-word phrases or well-scoped abbreviations, not generic single
# words, to avoid false-positiving on an in-scope question that happens to
# share a word (e.g. "security" alone is too generic; "security system" is
# not).
OUT_OF_SCOPE_KEYWORDS = [
    ("Fire Systems", "fire suppression"),
    ("Fire Systems", "fire system"),
    ("Fire Systems", "fire alarm"),
    ("Security Systems", "security system"),
    ("Security Systems", "access control"),
    ("BMS", "building management system"),
    ("BMS", "bms"),
    ("DG Sets", "dg set"),
    ("DG Sets", "diesel generator"),
    ("Cooling Towers", "cooling tower"),
    ("CRAC units", "crac"),
]


def _detect_out_of_scope_category(question: str) -> str | None:
    lowered = question.lower()
    for category, keyword in OUT_OF_SCOPE_KEYWORDS:
        if keyword in lowered:
            return category
    return None


def _parse_route(raw: str) -> str:
    cleaned = raw.strip().lower()
    if cleaned in AGENT_ROUTES:
        return cleaned
    for route in AGENT_ROUTES:
        if route in cleaned:
            return route
    # Do NOT default to a real agent (e.g. "asset") here: a genuinely
    # unroutable question forced through an unrelated agent can come back
    # confidently SOURCED (e.g. if it happens to mention a real asset ID),
    # which is exactly the confidently-wrong-but-looks-right failure Section
    # 5.5 exists to prevent. Route to the "unroutable" terminal instead, which
    # flows through the same source_check_node as any other route.
    return UNROUTABLE_ROUTE


# Section 5.0 lists the Orchestrator's inputs as question + last-5-turn
# history + asset context if selected in UI. This node currently only reads
# state["question"] — state["history"] and state["asset_context"] are not yet
# wired into the routing prompt. Known gap against Section 5.0, deliberately
# deferred to integration week, not silently missing.
def orchestrator_node(state: AgentState) -> dict:
    # Scope-boundary guardrail runs BEFORE the routing LLM call: an
    # out-of-scope question is already known to be out of scope, so there is
    # no reason to burn a routing call on it, and no risk of it accidentally
    # falling through to "asset not found"/"unroutable" instead of the
    # explicit scope message (Section 7.3).
    if _detect_out_of_scope_category(state["question"]) is not None:
        return {"route": OUT_OF_SCOPE_ROUTE}

    prompt = _ROUTER_PROMPT_TEMPLATE.format(question=state["question"])
    raw = router.generate(prompt, role="routing")
    return {"route": _parse_route(raw)}


def asset_node(state: AgentState) -> dict:
    output = asset_agent.run(state["question"])
    agent_outputs = dict(state.get("agent_outputs", {}))
    agent_outputs["asset"] = output
    return {"agent_outputs": agent_outputs}


def maintenance_node(state: AgentState) -> dict:
    output = maintenance_agent.run(state["question"])
    agent_outputs = dict(state.get("agent_outputs", {}))
    agent_outputs["maintenance"] = output
    return {"agent_outputs": agent_outputs}


def maintenance_then_compliance_node(state: AgentState) -> dict:
    """Demo Scenario 2 (Section 12.2, step 4): "Compliance Agent cross-checks
    the procedure against SOP frequency requirements for context." This
    happens automatically as part of answering a maintenance question, not as
    a separate user question — so the "maintenance" route chains through here
    instead of going straight to maintenance_node.

    If the Maintenance Agent itself has no source, there is nothing to
    cross-check — go straight through with just that result, same as before.
    If it does, chain into the Compliance Agent with the generated procedure
    as context, combine both answers, and merge both sources. A Compliance
    downgrade to Insufficient Information (its own uncited-verdict safety net)
    only affects the compliance section of the combined answer — it must not
    erase an otherwise validly-sourced maintenance procedure.
    """
    maintenance_output = maintenance_agent.run(state["question"])
    agent_outputs = dict(state.get("agent_outputs", {}))

    if maintenance_output.get("source") is None:
        agent_outputs["maintenance"] = maintenance_output
        return {"agent_outputs": agent_outputs}

    compliance_output = compliance_agent.run(state["question"], procedure_context=maintenance_output["answer"])

    combined_answer = f"{maintenance_output['answer']}\n\nCompliance check: {compliance_output['answer']}"

    maintenance_source = maintenance_output["source"]
    sources = list(maintenance_source) if isinstance(maintenance_source, list) else [maintenance_source]
    compliance_source = compliance_output.get("source")
    if compliance_source is not None:
        sources = sources + (list(compliance_source) if isinstance(compliance_source, list) else [compliance_source])

    agent_outputs["maintenance"] = {"answer": combined_answer, "source": sources}
    return {"agent_outputs": agent_outputs}


def compliance_node(state: AgentState) -> dict:
    output = compliance_agent.run(state["question"])
    agent_outputs = dict(state.get("agent_outputs", {}))
    agent_outputs["compliance"] = output
    return {"agent_outputs": agent_outputs}


def reliability_node(state: AgentState) -> dict:
    output = reliability_agent.run(state["question"])
    agent_outputs = dict(state.get("agent_outputs", {}))
    agent_outputs["reliability"] = output
    return {"agent_outputs": agent_outputs}


def unroutable_node(state: AgentState) -> dict:
    """Real terminal node, not a placeholder — reached only when the routing
    LLM's response didn't cleanly match a known agent (see _parse_route).
    Returns the same {"answer", "source"} shape as every other agent so it
    flows through the existing source_check_node unmodified and correctly
    produces "I don't have enough information."
    """
    output = {
        "answer": "Could not determine which specialist should handle this question.",
        "source": None,
    }
    agent_outputs = dict(state.get("agent_outputs", {}))
    agent_outputs[UNROUTABLE_ROUTE] = output
    return {"agent_outputs": agent_outputs}


def out_of_scope_node(state: AgentState) -> dict:
    """Real terminal node (same pattern as unroutable_node), reached only when
    orchestrator_node's keyword check already determined the question falls
    outside the MVP's modelled scope (Section 4.4). Recomputes the matched
    category from the question rather than threading it through state, since
    it's a pure function of the question already available here.
    """
    category = _detect_out_of_scope_category(state["question"]) or "This topic"
    output = {
        "answer": (
            f"This question is outside the current MVP's scope — {category} is not modelled "
            "in this system. See Section 4.4 for what's covered."
        ),
        "source": None,
    }
    agent_outputs = dict(state.get("agent_outputs", {}))
    agent_outputs[OUT_OF_SCOPE_ROUTE] = output
    return {"agent_outputs": agent_outputs}


def source_check_node(state: AgentState) -> dict:
    """Section 5.5 enforced in code: no agent output escapes without a real
    source. Convention: agent output is a dict with "answer" and "source"
    keys; source=None (or an output that isn't even that shape, e.g. a
    placeholder string) means no source — either way this overrides the
    final answer to the "insufficient information" response.

    Exception: out_of_scope is a deliberate, definitive terminal message
    (Section 7.3 Scope Boundary guardrail), not an escalation case — its own
    explicit scope message must reach the user rather than being collapsed
    into the generic "insufficient information" text like unroutable is.
    """
    route = state["route"]
    output = state.get("agent_outputs", {}).get(route)

    if route == OUT_OF_SCOPE_ROUTE and isinstance(output, dict):
        return {"final_answer": output.get("answer", ""), "enough_info": False}

    source = output.get("source") if isinstance(output, dict) else None

    if source is None:
        return {"final_answer": "I don't have enough information.", "enough_info": False}

    answer = output.get("answer", "")
    sources = list(state.get("sources", [])) + [source]
    return {"final_answer": answer, "enough_info": True, "sources": sources}


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("asset", asset_node)
    graph.add_node("reliability", reliability_node)
    graph.add_node("maintenance", maintenance_then_compliance_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node(UNROUTABLE_ROUTE, unroutable_node)
    graph.add_node(OUT_OF_SCOPE_ROUTE, out_of_scope_node)
    graph.add_node("source_check", source_check_node)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        lambda state: state["route"],
        {route: route for route in ROUTES},
    )
    for node_name in ROUTES:
        graph.add_edge(node_name, "source_check")
    graph.add_edge("source_check", END)

    return graph.compile()


graph = build_graph()

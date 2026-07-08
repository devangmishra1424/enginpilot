"""Shared orchestrator/agent state (Playbook Section 5.0 — Orchestrator).

This is the contract every agent, tool, and the orchestrator itself is built
against. Get the shape wrong here and it ripples through every downstream file.
"""

from typing import TypedDict


class AgentState(TypedDict):
    question: str
    """Raw user question, natural language, as typed into the copilot chat."""

    history: list
    """Last ~5 conversation turns, oldest first, for the orchestrator's routing
    prompt and any agent that needs conversational context."""

    asset_context: dict | None
    """Asset context if one was selected in the UI (Section 5.0 Orchestrator
    Inputs) — e.g. the asset the user had open when they asked the question.
    None when no asset is selected; agents must not assume one is present."""

    route: str
    """Which agent(s) the orchestrator picked for this question (e.g. "reliability"
    or "asset,reliability" for a multi-agent question)."""

    agent_outputs: dict
    """What each agent returned, keyed by agent name (e.g. "reliability_agent" ->
    that agent's raw output dict). Lets the orchestrator synthesize a final answer
    from multiple agents without losing per-agent detail."""

    sources: list
    """Running list of every cited rule/doc/graph fact across all agents that ran
    for this question. Used by the orchestrator's source-check gate (Section 5.5,
    5.0 Escalation Rule): if this ends up empty, the answer must be overridden
    with an "insufficient information" response.

    KNOWN INCONSISTENCY: entries are not a uniform shape yet — the Asset Agent
    contributes a single dict (the graph fact used), the Maintenance Agent
    contributes a list of dicts (the retrieved chunks used). Fine for now since
    nothing downstream consumes this list yet, but it will need normalizing
    (e.g. always storing a list per agent call) before frontend/dashboard
    integration renders citations consistently."""

    final_answer: str
    """The synthesized response the orchestrator returns to the user, built only
    after the source-check gate passes."""

    enough_info: bool
    """Whether at least one agent returned a result with a real source attached.
    Set False by default; an agent (or the orchestrator) flips it True only when
    a genuine source (fired rule, retrieved doc passage, graph fact) is present."""

"""Golden dataset schema for the EnginPilot evaluation layer.

Field names and Literal values are derived directly from:
  - agents/state.py    — AgentState.route, AgentState.enough_info, AgentState.sources
  - agents/orchestrator.py — ROUTES = {"asset","reliability","maintenance","compliance",
                                         "unroutable","out_of_scope"}

Each GoldenTestCase is one row in evaluation/datasets/golden_v1.json.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class GoldenTestCase(BaseModel):
    """One canonical test case in the golden dataset.

    id:
        Unique slug — used in pytest -k filtering and CI report grouping.
    query:
        The raw natural-language question sent to the LangGraph graph.
    expected_route:
        The route the orchestrator must choose (AgentState.route).
        Must be one of the values in orchestrator.ROUTES.
    expected_sources:
        Non-empty list of substring strings that MUST appear in at least one
        source entry's string representation when enough_info is True.
        Use the real document filename stems (e.g. "sop_ups_preventive_maintenance")
        or a physics rule ID (e.g. "THERM-UPS-001"). Empty list means the
        test does not assert on source content (use only for refuse/escalate cases).
    expected_behavior:
        "answer"   — agent returns a sourced answer (enough_info=True).
        "refuse"   — query is unsafe/dangerous; must produce the fallback string.
        "escalate" — query is in-scope but no evidence found; produces
                     "I don't have enough information."
    expected_risk_band:
        Only relevant for expected_route="reliability".  One of the RiskLevel
        enum string values from physics/schemas.py:
          "High Risk" | "Medium Risk" | "Low Risk" |
          "Alert" | "Warning" | "Inspection Required" | "Reduced Life"
        None for all non-reliability routes.
    """

    id: str
    query: str
    expected_route: Literal[
        "asset", "reliability", "maintenance", "compliance",
        "unroutable", "out_of_scope",
    ]
    expected_sources: list[str] = Field(default_factory=list)
    expected_behavior: Literal["answer", "refuse", "escalate"]
    expected_risk_band: Optional[
        Literal[
            "High Risk", "Medium Risk", "Low Risk",
            "Alert", "Warning", "Inspection Required", "Reduced Life",
        ]
    ] = None

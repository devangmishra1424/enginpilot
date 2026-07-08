"""Data structures for the Physics Rule Kernel.

Naming discipline (Playbook Sections 3 & 6): this is the "Physics Rule Kernel" —
a deterministic threshold engine. Never referred to as "Physics NET", "PINN",
or "physics-validated" anywhere in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class RiskLevel(str, Enum):
    """Transparent risk bands only — never a numeric score (Playbook Section 5.2)."""

    HIGH = "High Risk"
    MEDIUM = "Medium Risk"
    LOW = "Low Risk"
    ALERT = "Alert"
    WARNING = "Warning"
    INSPECTION_REQUIRED = "Inspection Required"
    REDUCED_LIFE = "Reduced Life"


class Operator(str, Enum):
    GT = ">"
    LT = "<"
    IN_RANGE = "in_range"


@dataclass(frozen=True)
class Threshold:
    """A threshold is either a fixed value or relative to a property read off the asset.

    Fixed threshold (e.g. THERM-UPS-001, BATT-DEG-001, ELEC-LOAD-001):
        operator=Operator.GT, value=40.0

    In-range threshold (e.g. THERM-UPS-001 medium band):
        operator=Operator.IN_RANGE, value=(35.0, 40.0)

    Relative threshold (e.g. COOL-COP-001, VIB-PUMP-001) — compares the reading
    against a property read off the asset itself, never a fabricated constant:
        operator=Operator.LT, relative_to="rated_efficiency", relative_factor=0.8
        operator=Operator.GT, relative_to="rated_vibration_mm_s", relative_factor=1.0
    """

    operator: Operator
    value: Optional[Union[float, tuple[float, float]]] = None
    relative_to: Optional[str] = None
    relative_factor: float = 1.0

    @property
    def is_relative(self) -> bool:
        return self.relative_to is not None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    asset_class: str
    input_field: str
    threshold: Threshold
    risk_level: RiskLevel
    band_label: str  # e.g. "high", "medium" — used to build rule_fired, e.g. "THERM-UPS-001 (high)"
    explanation_template: str  # may use {asset_id}, {measured_value}, {threshold_desc}
    source_standard: str
    version: str = "0.1-mvp"


@dataclass
class RuleInput:
    asset_id: str
    asset_class: str
    readings: dict[str, float] = field(default_factory=dict)
    asset_properties: dict[str, float] = field(default_factory=dict)


@dataclass
class RuleOutput:
    # Mandatory 3 elements (Playbook Section 6.3):
    rule_fired: str
    measured_value: float
    explanation: str
    # Carried for the Reliability Agent to consume programmatically:
    risk_level: RiskLevel
    asset_id: str

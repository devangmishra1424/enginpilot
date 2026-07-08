"""The 5 rules from Playbook Section 6.1, assembled into Rule objects.

Exactly 5 rules, no more, no less:
  1. THERM-UPS-001 (two bands, one input: high + medium)
  2. BATT-DEG-001
  3. COOL-COP-001  (relative threshold)
  4. ELEC-LOAD-001
  5. VIB-PUMP-001  (relative threshold)
"""

from physics.schemas import Operator, Rule, RiskLevel, Threshold
from physics import thresholds as t

# Deliberate MVP decision (Playbook Section 6.2): we have no vendor manuals or
# SME-validated standards yet, so every rule's source is honestly marked as a
# placeholder rather than fabricating a citation.
PLACEHOLDER_SOURCE = "PLACEHOLDER — needs SME validation"

THERM_UPS_001_HIGH = Rule(
    rule_id="THERM-UPS-001",
    asset_class="UPS",
    input_field="internal_temp_c",
    threshold=Threshold(operator=Operator.GT, value=t.UPS_HIGH_RISK_TEMP_C),
    risk_level=RiskLevel.HIGH,
    band_label="high_risk",
    explanation_template=(
        "{asset_id} internal temperature ({measured_value} C) exceeds the "
        f"{t.UPS_HIGH_RISK_TEMP_C} C high-risk threshold. Sustained operation above "
        "this level accelerates capacitor and battery degradation."
    ),
    source_standard=PLACEHOLDER_SOURCE,
)

THERM_UPS_001_MEDIUM = Rule(
    rule_id="THERM-UPS-001",
    asset_class="UPS",
    input_field="internal_temp_c",
    threshold=Threshold(operator=Operator.IN_RANGE, value=t.UPS_MEDIUM_RISK_RANGE_C),
    risk_level=RiskLevel.MEDIUM,
    band_label="medium_risk",
    explanation_template=(
        "{asset_id} internal temperature ({measured_value} C) is within the "
        f"{t.UPS_MEDIUM_RISK_RANGE_C[0]}-{t.UPS_MEDIUM_RISK_RANGE_C[1]} C medium-risk band. "
        "Monitor for further increase."
    ),
    source_standard=PLACEHOLDER_SOURCE,
)

BATT_DEG_001 = Rule(
    rule_id="BATT-DEG-001",
    asset_class="Battery",
    input_field="battery_temp_c",
    threshold=Threshold(operator=Operator.GT, value=t.BATTERY_REDUCED_LIFE_TEMP_C),
    risk_level=RiskLevel.REDUCED_LIFE,
    band_label="reduced_life",
    explanation_template=(
        "{asset_id} battery temperature ({measured_value} C) exceeds "
        f"{t.BATTERY_REDUCED_LIFE_TEMP_C} C, indicating an elevated degradation rate."
    ),
    source_standard=PLACEHOLDER_SOURCE,
)

COOL_COP_001 = Rule(
    rule_id="COOL-COP-001",
    asset_class="Chiller",
    input_field="measured_cop",
    threshold=Threshold(
        operator=Operator.LT,
        relative_to=t.CHILLER_RATED_EFFICIENCY_PROPERTY,
        relative_factor=t.CHILLER_COP_RATIO_OF_RATED,
    ),
    risk_level=RiskLevel.ALERT,
    band_label="alert",
    explanation_template=(
        "{asset_id} measured COP ({measured_value}) is below "
        f"{int(t.CHILLER_COP_RATIO_OF_RATED * 100)}% of its rated efficiency "
        "({threshold_desc}), indicating efficiency degradation."
    ),
    source_standard=PLACEHOLDER_SOURCE,
)

ELEC_LOAD_001 = Rule(
    rule_id="ELEC-LOAD-001",
    asset_class="PDU",
    input_field="load_pct",
    threshold=Threshold(operator=Operator.GT, value=t.PDU_WARNING_LOAD_PCT),
    risk_level=RiskLevel.WARNING,
    band_label="warning",
    explanation_template=(
        "{asset_id} load ({measured_value}%) exceeds {threshold_desc}% of rated capacity, "
        "indicating capacity risk."
    ),
    source_standard=PLACEHOLDER_SOURCE,
)

VIB_PUMP_001 = Rule(
    rule_id="VIB-PUMP-001",
    asset_class="Pump",
    input_field="vibration_mm_s",
    threshold=Threshold(
        operator=Operator.GT,
        relative_to=t.PUMP_RATED_VIBRATION_PROPERTY,
        relative_factor=1.0,
    ),
    risk_level=RiskLevel.INSPECTION_REQUIRED,
    band_label="inspection_required",
    explanation_template=(
        "{asset_id} vibration ({measured_value} mm/s RMS) exceeds its rated ISO 10816 "
        "limit ({threshold_desc} mm/s), requiring inspection."
    ),
    source_standard=PLACEHOLDER_SOURCE,
)

ALL_RULES: list[Rule] = [
    THERM_UPS_001_HIGH,
    THERM_UPS_001_MEDIUM,
    BATT_DEG_001,
    COOL_COP_001,
    ELEC_LOAD_001,
    VIB_PUMP_001,
]

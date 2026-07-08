"""Raw threshold constants for the Physics Rule Kernel (Playbook Section 6.1).

These are the numeric bands and asset-property keys the 5 rules are built from.
Kept separate from rules.py so the numbers are easy to find and audit.
"""

# THERM-UPS-001 — UPS internal temperature (C)
UPS_HIGH_RISK_TEMP_C = 40.0  # strict ">" — 40.0 exactly is NOT high risk
UPS_MEDIUM_RISK_RANGE_C = (35.0, 40.0)  # inclusive both ends

# BATT-DEG-001 — battery temperature (C)
BATTERY_REDUCED_LIFE_TEMP_C = 30.0

# COOL-COP-001 — chiller measured COP vs the asset's OWN rated efficiency
CHILLER_COP_RATIO_OF_RATED = 0.80  # < 80% of rated_efficiency triggers Alert
CHILLER_RATED_EFFICIENCY_PROPERTY = "rated_efficiency"

# ELEC-LOAD-001 — circuit/PDU load (% of rated)
PDU_WARNING_LOAD_PCT = 90.0

# VIB-PUMP-001 — pump vibration (mm/s RMS) vs the asset's OWN rated ISO 10816 limit
PUMP_RATED_VIBRATION_PROPERTY = "rated_vibration_mm_s"

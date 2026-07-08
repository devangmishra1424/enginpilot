"""Deterministic tests for the Physics Rule Kernel (Playbook Section 6, 2.5 KPI)."""

from physics.engine import evaluate, evaluate_portfolio, rank_by_risk
from physics.schemas import RiskLevel, RuleInput


# ---------------------------------------------------------------------------
# THERM-UPS-001 (two bands, one input)
# ---------------------------------------------------------------------------


def test_therm_ups_001_high_fires():
    result = evaluate(RuleInput(asset_id="UPS-01", asset_class="UPS", readings={"internal_temp_c": 42.3}))
    assert len(result) == 1
    assert result[0].rule_fired == "THERM-UPS-001 (high_risk)"
    assert result[0].risk_level == RiskLevel.HIGH


def test_therm_ups_001_no_fire_when_normal():
    result = evaluate(RuleInput(asset_id="UPS-02", asset_class="UPS", readings={"internal_temp_c": 20.0}))
    assert result == []


def test_therm_ups_001_boundary_40_is_medium_not_high():
    result = evaluate(RuleInput(asset_id="UPS-03", asset_class="UPS", readings={"internal_temp_c": 40.0}))
    assert len(result) == 1
    assert result[0].rule_fired == "THERM-UPS-001 (medium_risk)"
    assert result[0].risk_level == RiskLevel.MEDIUM


def test_therm_ups_001_medium_band():
    result = evaluate(RuleInput(asset_id="UPS-04", asset_class="UPS", readings={"internal_temp_c": 37.0}))
    assert len(result) == 1
    assert result[0].rule_fired == "THERM-UPS-001 (medium_risk)"
    assert result[0].risk_level == RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# BATT-DEG-001
# ---------------------------------------------------------------------------


def test_batt_deg_001_fires():
    result = evaluate(RuleInput(asset_id="BATT-01", asset_class="Battery", readings={"battery_temp_c": 35.0}))
    assert len(result) == 1
    assert result[0].rule_fired == "BATT-DEG-001 (reduced_life)"
    assert result[0].risk_level == RiskLevel.REDUCED_LIFE


def test_batt_deg_001_no_fire():
    result = evaluate(RuleInput(asset_id="BATT-02", asset_class="Battery", readings={"battery_temp_c": 25.0}))
    assert result == []


# ---------------------------------------------------------------------------
# COOL-COP-001 (relative threshold)
# ---------------------------------------------------------------------------


def test_cool_cop_001_fires_with_rated_property_present():
    result = evaluate(
        RuleInput(
            asset_id="CHILLER-01",
            asset_class="Chiller",
            readings={"measured_cop": 3.0},
            asset_properties={"rated_efficiency": 4.0},  # 80% of rated = 3.2, 3.0 < 3.2
        )
    )
    assert len(result) == 1
    assert result[0].rule_fired == "COOL-COP-001 (alert)"
    assert result[0].risk_level == RiskLevel.ALERT


def test_cool_cop_001_no_fire_with_rated_property_present():
    result = evaluate(
        RuleInput(
            asset_id="CHILLER-02",
            asset_class="Chiller",
            readings={"measured_cop": 3.9},
            asset_properties={"rated_efficiency": 4.0},  # 3.9 > 3.2, no fault
        )
    )
    assert result == []


def test_cool_cop_001_skips_when_rated_property_missing():
    result = evaluate(
        RuleInput(
            asset_id="CHILLER-03",
            asset_class="Chiller",
            readings={"measured_cop": 1.0},  # would fire against any plausible rating
            asset_properties={},
        )
    )
    assert result == []


# ---------------------------------------------------------------------------
# ELEC-LOAD-001
# ---------------------------------------------------------------------------


def test_elec_load_001_fires():
    result = evaluate(RuleInput(asset_id="PDU-01", asset_class="PDU", readings={"load_pct": 95.0}))
    assert len(result) == 1
    assert result[0].rule_fired == "ELEC-LOAD-001 (warning)"
    assert result[0].risk_level == RiskLevel.WARNING


def test_elec_load_001_no_fire():
    result = evaluate(RuleInput(asset_id="PDU-02", asset_class="PDU", readings={"load_pct": 50.0}))
    assert result == []


# ---------------------------------------------------------------------------
# VIB-PUMP-001 (relative threshold)
# ---------------------------------------------------------------------------


def test_vib_pump_001_fires_with_rated_property_present():
    result = evaluate(
        RuleInput(
            asset_id="PUMP-01",
            asset_class="Pump",
            readings={"vibration_mm_s": 6.0},
            asset_properties={"rated_vibration_mm_s": 4.5},
        )
    )
    assert len(result) == 1
    assert result[0].rule_fired == "VIB-PUMP-001 (inspection_required)"
    assert result[0].risk_level == RiskLevel.INSPECTION_REQUIRED


def test_vib_pump_001_no_fire_with_rated_property_present():
    result = evaluate(
        RuleInput(
            asset_id="PUMP-02",
            asset_class="Pump",
            readings={"vibration_mm_s": 3.0},
            asset_properties={"rated_vibration_mm_s": 4.5},
        )
    )
    assert result == []


def test_vib_pump_001_skips_when_rated_property_missing():
    result = evaluate(
        RuleInput(
            asset_id="PUMP-03",
            asset_class="Pump",
            readings={"vibration_mm_s": 100.0},  # would fire against any plausible rating
            asset_properties={},
        )
    )
    assert result == []


# ---------------------------------------------------------------------------
# General engine behavior
# ---------------------------------------------------------------------------


def test_unknown_asset_class_returns_empty():
    result = evaluate(RuleInput(asset_id="GEN-01", asset_class="Generator", readings={"output_kw": 500.0}))
    assert result == []


def test_output_has_three_mandatory_elements():
    result = evaluate(RuleInput(asset_id="UPS-05", asset_class="UPS", readings={"internal_temp_c": 45.0}))
    assert len(result) == 1
    output = result[0]
    assert output.rule_fired
    assert isinstance(output.measured_value, float)
    assert output.explanation and isinstance(output.explanation, str)
    # Carried fields for the Reliability Agent:
    assert output.risk_level
    assert output.asset_id == "UPS-05"


# ---------------------------------------------------------------------------
# Seeded-fault batch (Playbook Section 2.5 / Sprint Tracker Day 7 KPI: >=90%)
# ---------------------------------------------------------------------------

SEEDED_CASES = [
    # (label, RuleInput, expect_fire)
    ("UPS-01 thermal high fault", RuleInput("UPS-01", "UPS", {"internal_temp_c": 45.0}), True),
    ("UPS-02 thermal medium fault", RuleInput("UPS-02", "UPS", {"internal_temp_c": 37.0}), True),
    ("UPS-03 thermal normal", RuleInput("UPS-03", "UPS", {"internal_temp_c": 25.0}), False),
    ("BATT-01 battery degradation fault", RuleInput("BATT-01", "Battery", {"battery_temp_c": 33.0}), True),
    ("BATT-02 battery normal", RuleInput("BATT-02", "Battery", {"battery_temp_c": 22.0}), False),
    (
        "CHILLER-01 cooling efficiency fault",
        RuleInput("CHILLER-01", "Chiller", {"measured_cop": 2.5}, {"rated_efficiency": 4.0}),
        True,
    ),
    (
        "CHILLER-02 cooling normal",
        RuleInput("CHILLER-02", "Chiller", {"measured_cop": 3.9}, {"rated_efficiency": 4.0}),
        False,
    ),
    ("PDU-01 electrical load fault", RuleInput("PDU-01", "PDU", {"load_pct": 95.0}), True),
    (
        "PUMP-01 vibration fault",
        RuleInput("PUMP-01", "Pump", {"vibration_mm_s": 6.0}, {"rated_vibration_mm_s": 4.5}),
        True,
    ),
    (
        "PUMP-02 vibration normal",
        RuleInput("PUMP-02", "Pump", {"vibration_mm_s": 3.0}, {"rated_vibration_mm_s": 4.5}),
        False,
    ),
]


def test_seeded_fault_detection_rate_at_least_90_percent():
    correct = 0
    for label, rule_input, expect_fire in SEEDED_CASES:
        fired = len(evaluate(rule_input)) > 0
        is_correct = fired == expect_fire
        correct += int(is_correct)
        print(f"{label}: expected_fire={expect_fire} actual_fire={fired} correct={is_correct}")

    detection_rate = correct / len(SEEDED_CASES)
    print(f"Seeded-fault detection rate: {detection_rate:.1%} ({correct}/{len(SEEDED_CASES)})")

    assert detection_rate >= 0.90


# ---------------------------------------------------------------------------
# evaluate_portfolio() / rank_by_risk() (Demo Scenario 3, Section 12.3)
# ---------------------------------------------------------------------------


def test_evaluate_portfolio_returns_dict_keyed_by_asset_id():
    rule_inputs = [
        RuleInput(asset_id="UPS-01", asset_class="UPS", readings={"internal_temp_c": 42.3}),  # high
        RuleInput(asset_id="UPS-02", asset_class="UPS", readings={"internal_temp_c": 37.0}),  # medium
        RuleInput(asset_id="UPS-03", asset_class="UPS", readings={"internal_temp_c": 20.0}),  # no fire
    ]

    result = evaluate_portfolio(rule_inputs)

    assert set(result.keys()) == {"UPS-01", "UPS-02", "UPS-03"}
    assert len(result["UPS-01"]) == 1
    assert result["UPS-01"][0].risk_level == RiskLevel.HIGH
    assert len(result["UPS-02"]) == 1
    assert result["UPS-02"][0].risk_level == RiskLevel.MEDIUM
    assert result["UPS-03"] == []


def test_rank_by_risk_orders_high_medium_then_no_risk_last():
    rule_inputs = [
        RuleInput(asset_id="UPS-01", asset_class="UPS", readings={"internal_temp_c": 42.3}),  # high
        RuleInput(asset_id="UPS-02", asset_class="UPS", readings={"internal_temp_c": 37.0}),  # medium
        RuleInput(asset_id="UPS-03", asset_class="UPS", readings={"internal_temp_c": 20.0}),  # no fire
    ]
    portfolio_results = evaluate_portfolio(rule_inputs)

    ranked = rank_by_risk(portfolio_results)

    assert [entry["asset_id"] for entry in ranked] == ["UPS-01", "UPS-02", "UPS-03"]
    assert ranked[0]["highest_risk_level"] == RiskLevel.HIGH
    assert ranked[1]["highest_risk_level"] == RiskLevel.MEDIUM
    assert ranked[2]["highest_risk_level"] is None
    assert ranked[2]["fired_rules"] == []


def test_rank_by_risk_with_empty_portfolio_returns_empty_list():
    assert rank_by_risk({}) == []

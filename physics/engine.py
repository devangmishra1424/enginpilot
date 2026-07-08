"""Physics Rule Kernel evaluation loop.

evaluate(rule_input) -> list[RuleOutput]

For each rule matching the input's asset_class: read the measured value, resolve
the threshold (fixed or relative-to-an-asset-property), and emit a RuleOutput for
every rule that fires. Unknown asset classes, missing readings, or missing asset
properties for a relative threshold all result in that rule being skipped — never
guessed or fabricated.
"""

from physics.rules import ALL_RULES
from physics.schemas import Operator, Rule, RuleInput, RuleOutput, Threshold


def _resolve_threshold_value(threshold: Threshold, rule_input: RuleInput) -> float | tuple[float, float] | None:
    """Return the concrete comparison value for this threshold, or None if unresolvable."""
    if not threshold.is_relative:
        return threshold.value

    rated_value = rule_input.asset_properties.get(threshold.relative_to)
    if rated_value is None:
        return None
    return rated_value * threshold.relative_factor


def _check(operator: Operator, measured_value: float, threshold_value) -> bool:
    if operator == Operator.GT:
        return measured_value > threshold_value
    if operator == Operator.LT:
        return measured_value < threshold_value
    if operator == Operator.IN_RANGE:
        low, high = threshold_value
        return low <= measured_value <= high
    raise ValueError(f"Unknown operator: {operator}")


def _format_threshold_desc(threshold_value) -> str:
    if isinstance(threshold_value, tuple):
        return f"{threshold_value[0]}-{threshold_value[1]}"
    return f"{threshold_value:g}"


def _build_output(rule: Rule, measured_value: float, threshold_value, asset_id: str) -> RuleOutput:
    explanation = rule.explanation_template.format(
        asset_id=asset_id,
        measured_value=measured_value,
        threshold_desc=_format_threshold_desc(threshold_value),
    )
    return RuleOutput(
        rule_fired=f"{rule.rule_id} ({rule.band_label})",
        measured_value=measured_value,
        explanation=explanation,
        risk_level=rule.risk_level,
        asset_id=asset_id,
    )


def evaluate(rule_input: RuleInput) -> list[RuleOutput]:
    outputs: list[RuleOutput] = []

    for rule in ALL_RULES:
        if rule.asset_class != rule_input.asset_class:
            continue

        measured_value = rule_input.readings.get(rule.input_field)
        if measured_value is None:
            continue

        threshold_value = _resolve_threshold_value(rule.threshold, rule_input)
        if threshold_value is None:
            # Relative threshold with no rated value on the asset — skip, never guess.
            continue

        if _check(rule.threshold.operator, measured_value, threshold_value):
            outputs.append(_build_output(rule, measured_value, threshold_value, rule_input.asset_id))

    return outputs


def evaluate_portfolio(rule_inputs: list[RuleInput]) -> dict[str, list[RuleOutput]]:
    """Evaluates every asset in the list, returning a dict keyed by asset_id.

    Just calls evaluate() per asset — no new rule logic, this is purely a
    batch wrapper (Demo Scenario 3, Playbook Section 12.3, step 2: "Agent
    queries Rule Kernel state across all curated assets"). An asset with an
    empty result list is a real 'no risk currently' finding, same semantics
    as evaluate() for a single asset — not treated differently here.
    """
    return {rule_input.asset_id: evaluate(rule_input) for rule_input in rule_inputs}


# The physics kernel has 7 RiskLevel bands with no defined total ordering
# across all of them (Playbook Section 5.2/6 never ranks Alert vs. Warning vs.
# Inspection Required vs. Reduced Life against each other). For portfolio
# ranking purposes we only need to distinguish "the top 3 severity bands"
# from everything else; within "everything else" all bands are treated as
# equally elevated. This is a simplification for Scenario 3's ranked list,
# not a claim that the kernel defines a real ordering for all 7 bands.
_RANK_ORDER = {
    "High Risk": 0,
    "Medium Risk": 1,
    "Low Risk": 2,
}
_UNRANKED_SEVERITY = 3  # Alert, Warning, Inspection Required, Reduced Life — all tied.


def _highest_risk_level(fired_rules: list[RuleOutput]):
    if not fired_rules:
        return None
    return min((r.risk_level for r in fired_rules), key=lambda level: _RANK_ORDER.get(level.value, _UNRANKED_SEVERITY))


def rank_by_risk(portfolio_results: dict[str, list[RuleOutput]]) -> list[dict]:
    """Returns a list sorted by risk severity (highest first).

    Each entry is shaped as {"asset_id": str, "highest_risk_level":
    RiskLevel | None, "fired_rules": list[RuleOutput]}. Assets with no fired
    rules (highest_risk_level=None) sort last, not first or randomly.
    """
    entries = [
        {
            "asset_id": asset_id,
            "highest_risk_level": _highest_risk_level(fired_rules),
            "fired_rules": fired_rules,
        }
        for asset_id, fired_rules in portfolio_results.items()
    ]

    def _sort_key(entry: dict):
        level = entry["highest_risk_level"]
        if level is None:
            return (1, 0)
        return (0, _RANK_ORDER.get(level.value, _UNRANKED_SEVERITY))

    entries.sort(key=_sort_key)
    return entries

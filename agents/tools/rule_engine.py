"""Real wrapper around the Physics Rule Kernel (physics/engine.py) — NOT a mock.

Adapts the agent-facing call shape (asset_id, asset_class, readings,
asset_properties as plain args) into a physics.schemas.RuleInput and delegates
straight to physics.engine.evaluate(). No rule logic lives here.
"""

from physics.engine import evaluate
from physics.schemas import RuleInput, RuleOutput


def check_rules(
    asset_id: str,
    asset_class: str,
    readings: dict,
    asset_properties: dict | None = None,
) -> list[RuleOutput]:
    rule_input = RuleInput(
        asset_id=asset_id,
        asset_class=asset_class,
        readings=readings,
        asset_properties=asset_properties or {},
    )
    return evaluate(rule_input)

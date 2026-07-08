"""MOCK graph lookup — stands in for Sam's real templated Neo4j Cypher query
(Playbook Section 5.1: templated queries only, never freeform LLM-generated Cypher).

Contract (must match when the real query function swaps in):
    { "asset_id": str, "class": str, "specs": {...}, "relationships": [...] }

Unknown asset IDs return None — the Asset Agent's escalation rule (Section 5.1)
depends on this: never let the LLM guess at specs for an asset that doesn't exist.
"""

_FAKE_ASSETS = {
    "UPS-01": {
        "asset_id": "UPS-01",
        "class": "UPS",
        "specs": {"rated_capacity_kva": 500, "manufacturer": "Eaton", "model": "9395P"},
        "relationships": [
            {"type": "POWERS", "target": "RACK-A12"},
            {"type": "FED_BY", "target": "PDU-03"},
        ],
    },
    "CHILLER-03": {
        "asset_id": "CHILLER-03",
        "class": "Chiller",
        "specs": {"rated_efficiency": 4.0, "manufacturer": "Carrier", "model": "30XA"},
        "relationships": [
            {"type": "COOLS", "target": "CRAH-02"},
        ],
    },
    "PDU-03": {
        "asset_id": "PDU-03",
        "class": "PDU",
        "specs": {"rated_capacity_kva": 250, "manufacturer": "Schneider Electric", "model": "PD250G"},
        "relationships": [
            {"type": "FEEDS", "target": "UPS-01"},
        ],
    },
    "PUMP-07": {
        "asset_id": "PUMP-07",
        "class": "Pump",
        "specs": {"rated_vibration_mm_s": 4.5, "manufacturer": "Grundfos", "model": "CR64"},
        "relationships": [
            {"type": "SERVES", "target": "CHILLER-03"},
        ],
    },
}


def get_asset(asset_id: str) -> dict | None:
    return _FAKE_ASSETS.get(asset_id)


def list_all_assets() -> list[dict]:
    """Returns [{"asset_id": str, "class": str}, ...] for every asset in the
    curated mock dataset. Needed for portfolio-wide evaluation (Demo Scenario
    3) — enumerates the same assets already known to get_asset(), just
    without needing to know an ID up front.
    """
    return [{"asset_id": a["asset_id"], "class": a["class"]} for a in _FAKE_ASSETS.values()]


# Directional dependency-type edges only — these mean "target depends on
# source" (source's failure affects target), which is the actual downstream
# direction Section 4.3 cares about ("which racks lose cooling if CRAH-02
# fails"). FED_BY, SERVES, etc. are the reverse direction (source depends on
# target) and must NOT be treated as downstream — including them would claim
# an asset impacts something it's actually fed/served BY.
_DOWNSTREAM_RELATIONSHIP_TYPES = {"POWERS", "COOLS", "FEEDS"}


def get_downstream_assets(asset_id: str) -> list[dict]:
    """Returns the assets that DEPEND ON (are downstream of / would be
    affected by the failure of) the given asset_id — e.g. for a UPS, what it
    POWERS; for a Chiller/CRAH, what it COOLS. Walks the mock asset's
    "relationships" list for directional dependency-type edges (POWERS,
    COOLS, FEEDS) and returns [{"asset_id": str, "relationship": str}, ...].
    Returns [] if the asset has no such relationships or doesn't exist —
    never fabricate a dependency.
    """
    asset = _FAKE_ASSETS.get(asset_id)
    if asset is None:
        return []
    return [
        {"asset_id": rel["target"], "relationship": rel["type"]}
        for rel in asset["relationships"]
        if rel["type"] in _DOWNSTREAM_RELATIONSHIP_TYPES
    ]

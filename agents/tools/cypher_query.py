"""Graph lookup adapter for the agent layer.

This module keeps the current mock dataset as a fallback, but can also use a
real Neo4j connection when the environment is configured. The public contract
stays the same for the agents:

    - get_asset(asset_id) -> dict | None
    - list_all_assets() -> list[dict]
    - get_downstream_assets(asset_id) -> list[dict]

Unknown asset IDs return None or [] depending on the call. That preserves the
Asset Agent and Reliability Agent escalation rules.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover - optional dependency
    GraphDatabase = None


_FAKE_ASSETS = {
    "UPS-01": {
        "asset_id": "UPS-01",
        "class": "UPS",
        "specs": {
            "rated_capacity_kva": 500,
            "manufacturer": "Eaton",
            "model": "9PX G2",
            "model_family": "9PX G2",
            # frequency_hz intentionally omitted: corpus UPS manuals have
            # frequency_hz=None in their payloads — passing 60 here would
            # cause the FieldCondition filter to block every UPS manual.
        },
        "relationships": [
            {"type": "POWERS", "target": "RACK-A12"},
            {"type": "FED_BY", "target": "PDU-03"},
        ],
    },
    "CHILLER-03": {
        "asset_id": "CHILLER-03",
        "class": "Chiller",
        "specs": {
            "rated_efficiency": 4.0,
            "manufacturer": "Carrier",
            "model": "30XA",
            "model_family": "30XA",
            # frequency_hz intentionally omitted: the primary Carrier IOM
            # (03_carrier_30xa_chiller_iom_meta.json) is tagged 50Hz in the
            # corpus. Passing 60 would block the IOM and return only the
            # SmartVu controls UI guide — the wrong document for reliability
            # queries. model_family="30XA" is sufficient to isolate both docs.
        },
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

_DOWNSTREAM_RELATIONSHIP_TYPES = {"POWERS", "COOLS", "FEEDS"}


def _driver():
    if GraphDatabase is None:
        return None

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not password:
        return None

    return GraphDatabase.driver(uri, auth=(user, password))


def _use_mock() -> bool:
    return os.getenv("ENGINPILOT_USE_MOCK_GRAPH", "0") == "1"


def _shape_asset(record: dict[str, Any] | None) -> dict | None:
    if record is None:
        return None

    asset = {
        "asset_id": record["asset_id"],
        "class": record["class"],
        "specs": record.get("specs", {}),
        "relationships": record.get("relationships", []),
    }
    return asset


def _fallback_get_asset(asset_id: str) -> dict | None:
    return _FAKE_ASSETS.get(asset_id)


def _fallback_list_all_assets() -> list[dict]:
    return [{"asset_id": a["asset_id"], "class": a["class"]} for a in _FAKE_ASSETS.values()]


def _fallback_get_downstream_assets(asset_id: str) -> list[dict]:
    asset = _FAKE_ASSETS.get(asset_id)
    if asset is None:
        return []
    return [
        {"asset_id": rel["target"], "relationship": rel["type"]}
        for rel in asset["relationships"]
        if rel["type"] in _DOWNSTREAM_RELATIONSHIP_TYPES
    ]


def _run_query(query: str, parameters: dict[str, Any]) -> list[dict]:
    driver = _driver()
    if driver is None:
        return []

    with driver.session() as session:
        result = session.run(query, **parameters)
        return [record.data() for record in result]


def get_asset(asset_id: str) -> dict | None:
    if _use_mock():
        return _fallback_get_asset(asset_id)

    driver = _driver()
    if driver is None:
        return _fallback_get_asset(asset_id)

    rows = _run_query(
        """
        MATCH (asset {asset_id: $asset_id})
        OPTIONAL MATCH (asset)-[relationship]->(target)
        RETURN asset.asset_id AS asset_id,
               labels(asset)[0] AS class,
               properties(asset) AS specs,
               collect({type: type(relationship), target: target.asset_id}) AS relationships
        LIMIT 1
        """,
        {"asset_id": asset_id},
    )
    if not rows:
        return None

    record = rows[0]
    if record.get("asset_id") is None:
        return None

    return _shape_asset(record)


def list_all_assets() -> list[dict]:
    if _use_mock():
        return _fallback_list_all_assets()

    driver = _driver()
    if driver is None:
        return _fallback_list_all_assets()

    rows = _run_query(
        """
        MATCH (asset)
        WHERE asset.asset_id IS NOT NULL
        RETURN asset.asset_id AS asset_id,
               labels(asset)[0] AS class
        ORDER BY asset.asset_id
        """,
        {},
    )
    if not rows:
        return []

    return [{"asset_id": row["asset_id"], "class": row["class"]} for row in rows if row.get("asset_id")]


def get_downstream_assets(asset_id: str) -> list[dict]:
    if _use_mock():
        return _fallback_get_downstream_assets(asset_id)

    driver = _driver()
    if driver is None:
        return _fallback_get_downstream_assets(asset_id)

    rows = _run_query(
        """
        MATCH (asset {asset_id: $asset_id})-[relationship]->(target)
        WHERE type(relationship) IN $relationship_types
        RETURN target.asset_id AS asset_id,
               type(relationship) AS relationship
        ORDER BY target.asset_id
        """,
        {"asset_id": asset_id, "relationship_types": sorted(_DOWNSTREAM_RELATIONSHIP_TYPES)},
    )
    if not rows:
        return []

    return [{"asset_id": row["asset_id"], "relationship": row["relationship"]} for row in rows if row.get("asset_id")]

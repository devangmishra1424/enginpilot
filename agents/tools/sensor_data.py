"""MOCK sensor history — stands in for Devang's real seeded sensor data.

Contract:
    { "readings": {...same shape rule_engine expects}, "timestamp": <ISO str>,
      "asset_properties": {...rated values if relevant} }

Unknown asset IDs return None. PUMP-07 is deliberately seeded with a stale
(>24h old) timestamp so the Reliability Agent's escalation rule (Section 5.2 —
"if sensor data is missing or stale, state that explicitly, never reason from
the last known value as if it were current") can actually be exercised.
"""

from datetime import datetime, timedelta, timezone

_NOW = datetime.now(timezone.utc)

_FAKE_READINGS = {
    "UPS-01": {
        "readings": {"internal_temp_c": 42.3},
        "timestamp": _NOW.isoformat(),
        "asset_properties": {},
    },
    "CHILLER-03": {
        "readings": {"measured_cop": 3.0},
        "timestamp": _NOW.isoformat(),
        "asset_properties": {"rated_efficiency": 4.0},
    },
    "PUMP-07": {
        "readings": {"vibration_mm_s": 6.2},
        "timestamp": (_NOW - timedelta(hours=30)).isoformat(),  # deliberately stale
        "asset_properties": {"rated_vibration_mm_s": 4.5},
    },
    "PDU-03": {
        # Deliberately below the 90% warning threshold — a real "no risk
        # currently" portfolio entry, not just a firing/stale mix.
        "readings": {"load_pct": 65.0},
        "timestamp": _NOW.isoformat(),
        "asset_properties": {},
    },
}


def get_current_reading(asset_id: str) -> dict | None:
    return _FAKE_READINGS.get(asset_id)

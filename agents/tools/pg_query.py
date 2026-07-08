"""MOCK maintenance-record lookup — stands in for Sam's real PostgreSQL query.

Contract (must match when the real query function swaps in):
    list of { "date": str, "type": str, "notes": str }
"""

_FAKE_HISTORY = {
    "UPS-01": [
        {"date": "2026-04-12", "type": "Preventive", "notes": "Battery cabinet inspection, no anomalies."},
        {"date": "2026-02-01", "type": "Corrective", "notes": "Replaced failed cooling fan, unit ran hot for ~2 days."},
    ],
    "CHILLER-03": [
        {"date": "2026-05-20", "type": "Preventive", "notes": "Condenser coil cleaning, refrigerant charge verified."},
    ],
}


def get_maintenance_history(asset_id: str) -> list[dict]:
    return _FAKE_HISTORY.get(asset_id, [])

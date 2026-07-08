"""MOCK RAG retrieval — stands in for Devang's real Qdrant search (Playbook 7.1).

Contract (must match when the real retriever swaps in):
    { "text": str, "doc_name": str, "page": int, "score": float }
Source metadata (doc_name, page) is always attached — never stripped
(Section 7.1, Source Attachment).
"""

_FAKE_CHUNKS = {
    "UPS": [
        {
            "text": (
                "If internal ambient temperature exceeds 40C for more than 5 minutes, "
                "initiate load shedding per Section 4.2 and notify facilities on-call."
            ),
            "doc_name": "UPS-9000-Series-OEM-Manual.pdf",
            "page": 47,
            "score": 0.91,
        },
        {
            "text": (
                "Battery cabinets should be inspected quarterly for corrosion and "
                "verified against the manufacturer's thermal derating table."
            ),
            "doc_name": "UPS-9000-Series-OEM-Manual.pdf",
            "page": 52,
            "score": 0.78,
        },
    ],
    "Chiller": [
        {
            "text": (
                "A measured COP below 80% of nameplate rated efficiency indicates "
                "probable refrigerant charge loss or fouled condenser coils."
            ),
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        },
    ],
    "Pump": [
        {
            "text": (
                "Vibration readings exceeding the ISO 10816 zone C/D boundary for the "
                "asset's mounting class require immediate inspection before restart."
            ),
            "doc_name": "Pump-Vibration-SOP.pdf",
            "page": 8,
            "score": 0.85,
        },
    ],
}

_DEFAULT_CHUNKS = [
    {
        "text": "General data center operations SOP: log all alarm acknowledgments with timestamp and operator ID.",
        "doc_name": "General-Ops-SOP.pdf",
        "page": 3,
        "score": 0.55,
    },
]


def search(query: str, asset_class: str | None = None) -> list[dict]:
    if asset_class is None:
        return _DEFAULT_CHUNKS
    # A real Qdrant search filtered by asset-class metadata returns nothing if no
    # document matches that filter — never fall back to unrelated chunks. This is
    # the no-match case the Maintenance/Compliance escalation rules depend on
    # (Playbook Sections 5.3, 5.4).
    return _FAKE_CHUNKS.get(asset_class, [])

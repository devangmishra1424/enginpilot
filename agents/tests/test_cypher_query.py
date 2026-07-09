from agents.tools import cypher_query


def test_cypher_query_falls_back_to_mock_dataset(monkeypatch):
    monkeypatch.setenv("ENGINPILOT_USE_MOCK_GRAPH", "1")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    asset = cypher_query.get_asset("UPS-01")

    assert asset is not None
    assert asset["asset_id"] == "UPS-01"
    assert asset["class"] == "UPS"


def test_cypher_query_returns_expected_downstream_assets(monkeypatch):
    monkeypatch.setenv("ENGINPILOT_USE_MOCK_GRAPH", "1")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    downstream = cypher_query.get_downstream_assets("UPS-01")

    assert downstream == [{"asset_id": "RACK-A12", "relationship": "POWERS"}]


def test_cypher_query_lists_curated_assets(monkeypatch):
    monkeypatch.setenv("ENGINPILOT_USE_MOCK_GRAPH", "1")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    assets = cypher_query.list_all_assets()

    assert assets == [
        {"asset_id": "UPS-01", "class": "UPS"},
        {"asset_id": "CHILLER-03", "class": "Chiller"},
        {"asset_id": "PDU-03", "class": "PDU"},
        {"asset_id": "PUMP-07", "class": "Pump"},
    ]
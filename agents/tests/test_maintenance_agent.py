from unittest.mock import patch

from agents import maintenance_agent


def test_indexed_asset_class_returns_answer_with_chunk_source():
    fake_chunks = [
        {
            "text": "Inspect condenser coils quarterly and verify refrigerant charge against nameplate rating.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    with (
        patch("agents.maintenance_agent.qdrant_search.search", return_value=fake_chunks) as mock_search,
        patch(
            "agents.maintenance_agent.router.generate",
            return_value="Source: Chiller-COP-Maintenance-SOP.pdf p.12\nSteps: 1. Inspect condenser coils...",
        ) as mock_generate,
    ):
        result = maintenance_agent.run("What's the maintenance plan for Chiller-03?")

    assert mock_search.called
    assert mock_generate.called
    assert result["source"] == fake_chunks
    assert "Chiller-COP-Maintenance-SOP.pdf" in result["answer"]


def test_no_indexed_sop_returns_insufficient_info_without_calling_llm():
    with (
        patch("agents.maintenance_agent.qdrant_search.search", return_value=[]) as mock_search,
        patch("agents.maintenance_agent.router.generate") as mock_generate,
    ):
        result = maintenance_agent.run("What's the maintenance plan for the backup generator?")

    assert mock_search.called
    mock_generate.assert_not_called()
    assert result["source"] is None
    assert "What was searched" in result["answer"]
    assert "Why it did not resolve" in result["answer"]
    assert "What would help" in result["answer"]


def test_chunks_below_confidence_floor_are_treated_as_no_match_without_calling_llm():
    """Confidence-gated answers guardrail (Section 7.3): a weak retrieval
    match must never reach the LLM as if it were a real find — same
    escalation path as an empty result."""
    weak_chunks = [
        {
            "text": "Vaguely related maintenance note.",
            "doc_name": "Unrelated-Doc.pdf",
            "page": 1,
            "score": 0.3,
        }
    ]
    with (
        patch("agents.maintenance_agent.qdrant_search.search", return_value=weak_chunks) as mock_search,
        patch("agents.maintenance_agent.router.generate") as mock_generate,
    ):
        result = maintenance_agent.run("What's the maintenance plan for Chiller-03?")

    assert mock_search.called
    mock_generate.assert_not_called()
    assert result["source"] is None
    assert "What was searched" in result["answer"]

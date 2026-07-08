from unittest.mock import patch

from agents import compliance_agent


def test_no_sop_returns_insufficient_information_without_calling_llm():
    with (
        patch("agents.compliance_agent.qdrant_search.search", return_value=[]) as mock_search,
        patch("agents.compliance_agent.router.generate") as mock_generate,
    ):
        result = compliance_agent.run("Is running the backup generator at this load compliant with the SOP?")

    assert mock_search.called
    mock_generate.assert_not_called()
    assert result["source"] is None
    # Insufficient Information template (Section 7.4): What was searched /
    # Why it did not resolve / What would help — not a flat sentence.
    assert "What was searched" in result["answer"]
    assert "Why it did not resolve" in result["answer"]
    assert "What would help" in result["answer"]


def test_not_compliant_with_clause_cited_passes_through_with_source():
    fake_chunks = [
        {
            "text": "A measured COP below 80% of nameplate rated efficiency indicates probable refrigerant charge loss.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    llm_response = (
        "Not Compliant. Per Chiller-COP-Maintenance-SOP.pdf, page 12: measured COP is below "
        "80% of rated efficiency, which the SOP identifies as a fault condition."
    )
    with (
        patch("agents.compliance_agent.qdrant_search.search", return_value=fake_chunks),
        patch("agents.compliance_agent.router.generate", return_value=llm_response),
    ):
        result = compliance_agent.run("Is Chiller-03 running compliant with its efficiency SOP?")

    assert result["answer"] == llm_response
    assert result["source"] == fake_chunks


def test_compliant_with_clear_clause_citation_passes_through_with_source():
    fake_chunks = [
        {
            "text": "Battery cabinets should be inspected quarterly for corrosion.",
            "doc_name": "UPS-9000-Series-OEM-Manual.pdf",
            "page": 52,
            "score": 0.78,
        }
    ]
    llm_response = (
        "Compliant. Per UPS-9000-Series-OEM-Manual.pdf, page 52: quarterly battery cabinet "
        "inspections have been performed as required, with no corrosion noted."
    )
    with (
        patch("agents.compliance_agent.qdrant_search.search", return_value=fake_chunks),
        patch("agents.compliance_agent.router.generate", return_value=llm_response),
    ):
        result = compliance_agent.run("Is UPS-01's battery inspection schedule compliant?")

    assert result["answer"] == llm_response
    assert result["source"] == fake_chunks


def test_uncited_compliant_verdict_is_downgraded_to_insufficient_information():
    """THE MOST IMPORTANT TEST: a lazy/bad LLM response asserting "Compliant"
    with no specific clause cited must never pass through as a real verdict —
    this is the Section 5.4 KPI (zero false compliant verdicts) enforced in
    code."""
    fake_chunks = [
        {
            "text": "A measured COP below 80% of nameplate rated efficiency indicates probable refrigerant charge loss.",
            "doc_name": "Chiller-COP-Maintenance-SOP.pdf",
            "page": 12,
            "score": 0.88,
        }
    ]
    lazy_llm_response = "Compliant."
    with (
        patch("agents.compliance_agent.qdrant_search.search", return_value=fake_chunks),
        patch("agents.compliance_agent.router.generate", return_value=lazy_llm_response),
    ):
        result = compliance_agent.run("Is Chiller-03 running compliant with its efficiency SOP?")

    assert result["source"] is None
    assert result["answer"] != lazy_llm_response
    # Downgraded answer must still follow the Insufficient Information
    # template, and its "why" must reflect the uncited-verdict reason
    # specifically (distinct from the no-chunks-retrieved case).
    assert "What was searched" in result["answer"]
    assert "Why it did not resolve" in result["answer"]
    assert "without citing a specific clause" in result["answer"]
    assert "What would help" in result["answer"]


def test_chunks_below_confidence_floor_are_treated_as_no_match_without_calling_llm():
    """Confidence-gated answers guardrail (Section 7.3): a weak retrieval
    match must never reach the LLM as if it were a real find — same
    escalation path as an empty result."""
    weak_chunks = [
        {
            "text": "Vaguely related SOP note.",
            "doc_name": "Unrelated-Doc.pdf",
            "page": 1,
            "score": 0.4,
        }
    ]
    with (
        patch("agents.compliance_agent.qdrant_search.search", return_value=weak_chunks) as mock_search,
        patch("agents.compliance_agent.router.generate") as mock_generate,
    ):
        result = compliance_agent.run("Is Chiller-03 running compliant with its efficiency SOP?")

    assert mock_search.called
    mock_generate.assert_not_called()
    assert result["source"] is None
    assert "What was searched" in result["answer"]

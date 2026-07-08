from unittest.mock import patch

from agents import asset_agent


def test_known_asset_returns_answer_with_source():
    with patch("agents.asset_agent.router.generate", return_value="UPS-01 is a 500kVA Eaton 9395P UPS.") as mock_generate:
        result = asset_agent.run("What is the rated capacity of UPS-01?")

    assert mock_generate.called
    assert result["answer"] == "UPS-01 is a 500kVA Eaton 9395P UPS."
    assert result["source"] is not None
    assert result["source"]["asset_id"] == "UPS-01"


def test_unknown_asset_returns_not_found_without_calling_llm():
    with patch("agents.asset_agent.router.generate") as mock_generate:
        result = asset_agent.run("What is the rated capacity of FOO-99?")

    assert result == {"answer": "asset not found", "source": None}
    mock_generate.assert_not_called()


def test_question_with_no_asset_id_returns_not_found_without_calling_llm():
    with patch("agents.asset_agent.router.generate") as mock_generate:
        result = asset_agent.run("What is the weather like today?")

    assert result == {"answer": "asset not found", "source": None}
    mock_generate.assert_not_called()

"""Pytest fixtures for the EnginPilot evaluation layer.

Session-scoped fixtures load the embedding model, Qdrant client, and dataset
once per `pytest` process — NOT once per test.  The embedding model load is
the expensive step (~30s); without session scope it runs for every test.

Environment variable set here (not in CI yaml) so every fixture that imports
agents.* picks it up before any agent module-level code runs:
    ENGINPILOT_USE_MOCK_GRAPH=1
    — forces cypher_query._use_mock() → True
    — avoids any Neo4j connection attempt in CI
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

import pytest

from dotenv import load_dotenv

# Set mock-graph env var BEFORE any agent imports fire their module-level code.
os.environ.setdefault("ENGINPILOT_USE_MOCK_GRAPH", "1")

# Load environment keys from workspace root or fallback
root_env = Path(__file__).parent.parent / ".env"
retrieval_env = Path(__file__).parent.parent / "backend" / "src" / "enginpilot" / "retrieval" / ".env"

if root_env.exists():
    load_dotenv(dotenv_path=root_env)
elif retrieval_env.exists():
    load_dotenv(dotenv_path=retrieval_env)
else:
    load_dotenv()

from evaluation.schemas import GoldenTestCase  # noqa: E402  (must come after env set)


_DATASET_PATH = Path(__file__).parent / "datasets" / "golden_v1.json"


@pytest.fixture(scope="session")
def golden_dataset() -> list[GoldenTestCase]:
    """Load and validate the full golden dataset once per session.

    Validation via Pydantic catches schema drift (e.g. someone adds a route
    to orchestrator.py but forgets to update a test case) at fixture time,
    before any graph invocation runs.
    """
    raw = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    return [GoldenTestCase.model_validate(tc) for tc in raw]


@pytest.fixture(scope="session")
def langgraph_app():
    """Compile and return the LangGraph app once per session.

    agents/orchestrator.py graph = build_graph() runs at import time, so this
    fixture just imports the already-compiled graph object.  The embedding
    model load happens inside retriever.py's module-level import chain —
    that's the expensive step, paid once here rather than per-test.

    Qdrant is NOT required for mock-graph mode: mock_graph=1 means
    cypher_query never opens a Neo4j connection, and qdrant_search.search()
    will still attempt a real Qdrant call — tests that need to run without
    Qdrant must patch qdrant_search.search via unittest.mock (see runner.py).
    """
    from agents.orchestrator import graph  # noqa: PLC0415
    return graph


@pytest.fixture(scope="session")
def eval_metrics():
    """Instantiate the three custom metrics once per session.

    Returns a dict keyed by metric class name for explicit access in tests.
    """
    from evaluation.metrics import (  # noqa: PLC0415
        RiskBandFormatMetric,
        SafetyRefusalMetric,
        SourceCitationMetric,
    )
    return {
        "source_citation": SourceCitationMetric(),
        "risk_band_format": RiskBandFormatMetric(),
        "safety_refusal": SafetyRefusalMetric(),
    }

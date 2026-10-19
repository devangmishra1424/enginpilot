# EnginPilot — RAG retriever, agents and evaluation (data-centre asset copilot)

EnginPilot answers maintenance, compliance and reliability questions about data-centre assets (UPS, PDU, chiller, CRAH, pump, transformer, battery) from OEM manuals and internal SOPs, and refuses to answer without a source.

This repository contains the **retrieval, agent and evaluation layer** only. `ARCHITECTURE.md` is the original three-person build contract and also describes components (FastAPI backend, Next.js frontend, Postgres tables, authentication, Docker CI) that are **not part of this repository**; treat it as a plan, not a description of what is here.

## What is in the repo

| Path | What it is |
|---|---|
| `scripts/extract_and_prepare.py` | Converts source PDFs to markdown with Docling and attaches a per-document metadata registry (asset class, manufacturer, model family, frequency, provenance, doc type, SHA-256). The PDFs themselves are not committed; the extracted output is in `infra/seed/extracted/`. |
| `ingest_qdrant.py` | Splits the markdown by headers, embeds chunks with `BAAI/bge-large-en-v1.5` (1024-d) and loads them into a local Qdrant collection `enginpilot_docs`. It deletes and rebuilds the collection on each run. |
| `backend/src/enginpilot/retrieval/retriever.py` | `retrieve()`: metadata filtering, cosine search, cross-encoder re-ranking and confidence gating, parent-section evidence expansion. |
| `agents/` | LangGraph orchestrator and the asset, reliability, maintenance and compliance agents; tools for the Neo4j graph (with a mock fallback), sensor data, the rule engine and the Qdrant retriever. |
| `physics/` | Deterministic rule engine for the five risk rules (thresholds are marked as placeholders pending SME validation). |
| `llm/` | NVIDIA-hosted model routing. |
| `evaluation/` | Golden dataset (`datasets/golden_v1.json`, 5 cases), three deterministic DeepEval metrics, and the pytest runner. |
| `rag_*.py`, `run_gauntlet.py`, `audit_qdrant_payloads.py` | Read-only retrieval diagnostics; the matching `*_report.json` files are saved outputs. `RAG_ROADMAP.md` explains the findings. |

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # installs from pyproject.toml / uv.lock
docker compose up -d qdrant  # local Qdrant on :6333
```

`requirements.txt` is a pinned snapshot of the agent-layer dependencies only; use `uv sync` for the full environment (retrieval, ingestion and evaluation).

### Environment variables

| Variable | Used for |
|---|---|
| `NVIDIA_API_KEY` | LLM calls (routing and articulation). Without it the evaluation runner uses mocks. |
| `QDRANT_URL`, `QDRANT_API_KEY` | Qdrant Cloud. If unset or unreachable, the retriever uses `localhost:6333`, then a local on-disk store. |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Optional real graph (install the `graph` extra: `uv sync --extra graph`). |
| `ENGINPILOT_USE_MOCK_GRAPH=1` | Force the built-in mock asset graph (the graph data in this repo is mock data). |

## Build the index

Place the source PDFs in `infra/seed/sample_pdfs/` (not committed), then:

```bash
uv run python scripts/extract_and_prepare.py   # PDFs -> infra/seed/extracted/*.md + *_meta.json
uv run python ingest_qdrant.py                 # embed + load into Qdrant (local)
```

## Tests and evaluation

```bash
uv run pytest physics/tests agents/tests/test_cypher_query.py      # fast, no ML models
uv run pytest evaluation/runner.py -v                              # golden-set agent evaluation
uv run python rag_quality_eval.py                                  # retrieval diagnostics (needs a populated Qdrant)
```

Importing the retriever loads the BGE-large embedding model, so the agent tests need the full `uv sync` environment. With `NVIDIA_API_KEY` unset, `evaluation/runner.py` replaces the LLM and retrieval with mocks and therefore only checks the pipeline plumbing and the "no source, no answer" gate, not retrieval or answer quality.

## Known limitations

- The golden set has only 5 cases; the diagnostic scripts report weaker results for table completeness, multi-step procedure completeness and paraphrase robustness (see `RAG_ROADMAP.md` and the `*_report.json` files).
- `retrieve()` contains a small hard-coded safety-triage list that matches specific test strings; it is a stop-gap, not a general classifier.
- Graph and sensor data used by the agents are mock data.
- `page` is always `None` in retrieved chunks because ingestion does not record page numbers.

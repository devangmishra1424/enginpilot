# ENGINPILOT — Master Architecture & Build Contract
### Single source of truth for the 3-person parallel build. Drop this in at repo root as `/ARCHITECTURE.md`.

> Governing spec: EP-MVP-DC-001 v1.1. This document does not repeat *what* ENGINPILOT is or *why* each component exists — that's already covered in the team's reading material. This document is the **contract layer**: the exact shapes, signatures, schemas, and ownership boundaries that let three people build in three different codebases on three different machines and have it all click together on merge, with zero "wait, what does your function return again?" conversations.

---

## 0. How To Use This Document

Read your own role section in full (Section 9) before writing any code. Everything in **Section 5 (Boundary Contracts)** is law — if you need to change a function signature, a schema field, or an event shape that's marked as a contract, you stop and sync with whoever's on the other side of it before touching it, not after. Everything outside the boundary contracts (the internals of your own files) is yours to build however you want — nobody needs to approve your prompt wording or your Cypher query structure.

Three roles are used throughout:

- **RAG Lead** — owns retrieval, ingestion, dataset generation, evaluation
- **Agentic Lead** — owns LangGraph agents, physics kernel, LLM routing
- **Full-Stack Lead** — owns frontend, API, databases (Postgres + Neo4j), infra, auth

---

## 1. System Overview (Condensed)

```
User → Next.js → FastAPI → LangGraph Orchestrator → 4 Agents → {Neo4j, PostgreSQL, Physics Kernel, Qdrant} → NVIDIA LLM → SSE → Frontend
```

Core invariant: **every layer below the LLM is deterministic.** The LLM is the last step in the chain, not the first — it articulates facts that were already established by a rule engine, a graph traversal, or a retrieved document. Nothing in this system is allowed to skip that order.

---

## 2. Day 0 — Decisions Locked Before Day 1

These are not Day 1 tasks. These are *before* Day 1 — a 30–45 minute joint call, all three people present, before anyone opens an editor.

| # | Decision | Resolution | Owner to action it |
|---|---|---|---|
| 1 | Embedding model | **`nvidia/nv-embedqa-e5-v5`** via NVIDIA Build (1024-dim), primary. Fallback: **`BAAI/bge-large-en-v1.5`** locally via `sentence-transformers` (also 1024-dim — Qdrant collection config doesn't change if you switch). *Verify model slug still exists in the NVIDIA Build catalog at implementation time — catalogs change.* | RAG Lead, locked before Day 1 |
| 2 | Qdrant collection name + schema | `enginpilot_docs`, 1024-dim, Cosine distance (full schema in §6.3) | RAG Lead |
| 3 | Python package/dep manager | **`uv`** workspace at repo root — fast, native local-package resolution, avoids `pip install -e` drift between three machines | Full-Stack Lead, bootstraps Day 1 |
| 4 | `shared/` contents frozen | Section 5.1 below is the literal content — copy it in verbatim, all three read and ack it in this call | All three, in this call |
| 5 | Repo + branch protection | Repo created, `main` protected (no direct push), PR required for anything touching `shared/`, `agents/state.py`, `retrieval/retriever.py`'s public signature, or `schemas/chat.py` | Full-Stack Lead |
| 6 | NVIDIA Build API key provisioned | One shared key in a password manager, not three separate trial accounts (avoids rate-limit confusion during the demo) | Whoever has the account |
| 7 | Recursion + timeout constants | `LANGGRAPH_RECURSION_LIMIT=15`, `LLM_TIMEOUT_SECONDS=3`, `RETRIEVAL_CONFIDENCE_FLOOR=0.55` — written into `.env.example` (provided below), not hardcoded anywhere | Agentic Lead defines, Full-Stack Lead wires into config |
| 8 | Daily sync cadence | 15-minute standup, same time every day, structured around "what did you ship yesterday that someone else depends on" — not generic status theater | All three |

---

## 3. Repo Structure — Canonical Tree

This **adopts** MVP_BLUEPRINT.md's tree as-is (it's good — don't refight it) with the gap-fixes from the alignment review folded in. Additions are marked `[NEW]`.

```
enginpilot/
├── .github/workflows/{ci.yml, docker-build.yml, e2e.yml}
├── .env.example                          # see §15 — full content provided
├── docker-compose.yml                    # see §15 — full content provided
├── ARCHITECTURE.md                       # ← THIS FILE
├── pyproject.toml                        # uv workspace root
│
├── backend/
│   └── src/enginpilot/
│       ├── main.py, config.py, deps.py            [Full-Stack Lead]
│       ├── api/
│       │   ├── router.py, health.py
│       │   ├── auth.py                            [NEW — Full-Stack Lead]
│       │   ├── assets.py, alerts.py, reports.py, ingestion.py
│       │   └── chat.py                            ← consumes Agentic Lead's orchestrator
│       ├── models/
│       │   ├── base.py, asset.py, sensor.py, sop.py, rule.py, report.py
│       │   └── user.py                            [NEW — Full-Stack Lead]
│       ├── schemas/
│       │   ├── asset.py, sensor.py, sop.py, rule.py, report.py
│       │   └── chat.py                            ← BOUNDARY: mirrors §5.7 exactly
│       ├── services/
│       │   ├── asset_service.py, sensor_service.py, report_service.py, graph_service.py
│       │   └── sop_service.py                     ← thin wrapper, see §5.8
│       ├── core/
│       │   └── redis_client.py, session.py         [NEW — Full-Stack Lead]
│       ├── agents/                                 [Agentic Lead — entire subtree]
│       │   ├── state.py                            ← BOUNDARY: §5.6
│       │   ├── orchestrator.py                     ← BOUNDARY: §5.7
│       │   ├── asset_agent.py, reliability_agent.py, maintenance_agent.py, compliance_agent.py
│       │   ├── prompts/*.md
│       │   └── tools/{cypher_query.py, pg_query.py, qdrant_search.py, rule_engine.py, report_gen.py}
│       ├── physics/                                [Agentic Lead — entire subtree]
│       │   ├── schemas.py, rules.py, thresholds.py, engine.py
│       │   └── tests/test_engine.py
│       ├── retrieval/                              [RAG Lead — entire subtree]
│       │   ├── ingest.py, chunker.py, embeddings.py, retriever.py, metadata.py
│       ├── graph/                                  [Full-Stack Lead — owns client/schema; Agentic Lead consumes via §5.3]
│       │   ├── client.py, schema.py
│       │   └── queries/{asset_neighbors.py, power_chain.py, cooling_chain.py, impact_analysis.py}
│       ├── llm/                                    [Agentic Lead]
│       │   └── nvidia.py, ollama.py, router.py
│       └── utils/
│           ├── logging.py, errors.py, telemetry.py [Full-Stack Lead, freeze by Day 2]
│       ├── scripts/
│       │   ├── seed_pg.py, seed_neo4j.py, reset_db.py    [Full-Stack Lead]
│       │   ├── seed_qdrant.py                            [RAG Lead]
│       │   └── run_rules.py                              ← BOUNDARY: §5.5, owned by Agentic Lead
│       └── tests/ (mirrors ownership of the subtree under test)
│
├── frontend/                              [Full-Stack Lead — entire subtree]
│   └── (exactly as MVP_BLUEPRINT.md §15 lists it — no changes)
│
├── infra/
│   ├── docker/{Dockerfile.api, Dockerfile.web, Dockerfile.ollama}   [Full-Stack Lead]
│   ├── db/
│   │   ├── postgres/{init.sql, seed_data/*.csv}                    [Full-Stack Lead schema; RAG Lead populates CSVs — §5.9]
│   │   ├── neo4j/{seed.cypher, constraints.cypher}                 ← CANONICAL location, delete the duplicate under backend/graph/
│   │   └── qdrant/collections.json                                 [RAG Lead]
│   └── seed/
│       ├── generate_dataset.py, generate_sensor_data.py, generate_alarm_events.py  [RAG Lead]
│       └── sample_pdfs/*.pdf (8 OEM manuals)                       [RAG Lead]
│
├── shared/                                ← FROZEN Day 0, see §5.1
│   ├── types/{asset.py, rule.py, common.py}
│   └── constants/{risk_levels.py, asset_types.py}
│
├── evaluation/                            [RAG Lead owns harness; all three contribute questions in their domain]
│   ├── datasets/*.json, judges/*.py, run_eval.py, eval_config.yaml
│
└── docs/
    ├── architecture.md → this file, or a generated split of it
    └── decisions/ (ADR log — see §17)
```

**Fixing the duplicate:** `graph/seed.cypher` (listed inside `backend/src/enginpilot/graph/` in the blueprint) is deleted. `infra/db/neo4j/seed.cypher` is canonical — seed data is environment/demo-data, not application code, and lives with the other seed data. `graph/schema.py` (the Python node/relationship definitions used by the actual app) stays in `backend/`.

---

## 4. Ownership Map

| Path | Owner | Consumed by |
|---|---|---|
| `agents/`, `physics/`, `llm/` | **Agentic Lead** | `api/chat.py` (Full-Stack), `scripts/run_rules.py` (self) |
| `retrieval/` | **RAG Lead** | `agents/tools/qdrant_search.py` (Agentic), `services/sop_service.py` (Full-Stack) |
| `api/`, `models/`, `schemas/`, `services/`, `core/`, `graph/client.py` + `graph/schema.py`, `frontend/` | **Full-Stack Lead** | Everyone (it's the integration surface) |
| `graph/queries/*.py` | **Full-Stack Lead writes, Agentic Lead specifies what's needed** | `agents/tools/cypher_query.py` |
| `shared/` | **Joint — frozen Day 0, PR-gated after** | Everyone |
| `infra/seed/`, `evaluation/` | **RAG Lead** | `scripts/seed_*.py`, Day 13 eval run |
| `infra/db/postgres/init.sql` (schema) | **Full-Stack Lead** | `scripts/seed_pg.py` (Full-Stack), seed CSVs (RAG Lead must match this schema) |
| `docker-compose.yml`, `.env.example` | **Full-Stack Lead is sole editor** | Everyone — others request additions, don't edit directly |

---

## 5. The Boundary Contracts

This is the part that actually matters. Everything below is what makes three independent codebases merge without friction. Treat every code block in this section as **the literal interface** — names, types, and shapes included.

### 5.1 `shared/` — Frozen Day 0

```python
# shared/constants/risk_levels.py
from enum import Enum

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

# shared/constants/asset_types.py
class AssetClass(str, Enum):
    UPS = "UPS"
    BATTERY = "Battery"
    TRANSFORMER = "Transformer"
    SWITCHGEAR = "Switchgear"
    PDU = "PDU"
    CHILLER = "Chiller"
    CRAH = "CRAH"
    PUMP = "Pump"
    RACK = "Rack"

# shared/types/common.py
from pydantic import BaseModel
from datetime import datetime

class Citation(BaseModel):
    type: str          # "rule" | "document" | "graph"
    label: str          # e.g. "THERM-UPS-001" or "UPS Manual, Section 4.2"
    detail: str          # explanation or excerpt
    ref_id: str | None = None
```

**Why this exists:** `RiskLevel` and `AssetClass` get referenced by Postgres CHECK constraints, Neo4j node labels, Pydantic schemas across three subtrees, and a manually-mirrored TypeScript type on the frontend. If two people each independently type `"High"` vs `"HIGH"` vs `"high_risk"`, every string comparison in the system silently breaks. This is the single highest-leverage 20 minutes of the whole sprint.

**Threshold values themselves (40°C, 90%, etc.) do NOT live here** — those are Agentic Lead's specialized domain knowledge and live in `physics/thresholds.py`. `shared/` holds taxonomy (what categories exist), not engineering values (what the cutoffs are).

---

### 5.2 Retriever Contract — RAG Lead implements, Agentic Lead consumes

```python
# backend/src/enginpilot/retrieval/retriever.py

from pydantic import BaseModel
from shared.constants.asset_types import AssetClass
from typing import Literal

class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    source_document: str
    section: str | None
    page: int | None
    asset_class: AssetClass | None
    manufacturer: str | None
    score: float                       # 0–1 cosine similarity

class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    retrieval_time_ms: float
    below_confidence_floor: bool       # True if best score < RETRIEVAL_CONFIDENCE_FLOOR (0.55)

def retrieve(
    query: str,
    top_k: int = 5,
    asset_class: AssetClass | None = None,
    doc_type: Literal["oem_manual", "sop"] | None = None,
) -> RetrievalResult:
    """The ONLY entry point Agentic Lead's code calls into this package."""
    ...
```

**Stub required Day 1.** RAG Lead ships a fake implementation on Day 1 that returns 2–3 hardcoded `RetrievedChunk` objects matching this exact shape — not a real Qdrant call, just enough to unblock Agentic Lead from Day 1 instead of Day 5. Swap the function body for the real implementation by Day 5; the signature does not change, so Agentic Lead's code needs zero edits when the swap happens.

**Freeze point:** Day 5, end of day (matches the original sprint's Day 5 acceptance criterion). After that, this signature is PR-gated.

---

### 5.3 Graph Query Contract — Full-Stack Lead implements, Agentic Lead consumes

```python
# backend/src/enginpilot/graph/queries/impact_analysis.py

def get_downstream_assets(asset_id: str, relationship: Literal["FEEDS", "COOLS"]) -> list[dict]:
    """Returns [{"asset_id": ..., "asset_class": ...}, ...] for everything
    downstream of asset_id along the given relationship chain, up to 5 hops."""
    ...

def get_asset_node(asset_id: str) -> dict | None:
    """Returns the full node properties for one asset, or None if not found.
    Asset Agent's escalation rule depends on this returning None cleanly —
    do not raise an exception for an unknown asset_id."""
    ...
```

Agentic Lead's `agents/tools/cypher_query.py` imports these two functions and nothing else from `graph/`. It does **not** write its own Cypher. If a new traversal pattern is needed mid-sprint, Agentic Lead requests it, Full-Stack Lead adds the function here — this keeps all graph query correctness in one reviewable place instead of scattered across agent code.

**Freeze point:** Day 6, matching the original Demo Scenario 3 acceptance criterion.

---

### 5.4 Physics Engine Contract — Agentic Lead, internal, but two consumers depend on the shape

```python
# backend/src/enginpilot/physics/engine.py

from shared.constants.risk_levels import RiskLevel
from shared.constants.asset_types import AssetClass
from pydantic import BaseModel
from datetime import datetime

class RuleInput(BaseModel):
    asset_id: str
    asset_class: AssetClass
    measurements: dict[str, float]     # e.g. {"internal_temp_c": 42.3}
    timestamp: datetime

class FiredRule(BaseModel):
    rule_id: str
    risk_level: RiskLevel
    measured_value: float
    threshold: float
    explanation: str
    source_standard: str

class RuleEvaluation(BaseModel):
    asset_id: str
    fired_rules: list[FiredRule]
    overall_risk: RiskLevel            # max() of fired rules, LOW if none fired
    evaluated_at: datetime

def evaluate(rule_input: RuleInput) -> RuleEvaluation: ...
def evaluate_portfolio(inputs: list[RuleInput]) -> list[RuleEvaluation]: ...
```

`evaluate_portfolio` exists specifically for Demo Scenario 3 ("show me the critical assets with the highest risk right now") and for `scripts/run_rules.py` — both need to evaluate every asset at once, not one at a time through the chat flow. Don't make either of those callers loop over `evaluate()` themselves.

**Freeze point:** Day 7, matching the original Rule Kernel acceptance criterion.

---

### 5.5 Risk-State Write Contract — `run_rules.py` (Agentic Lead) writes through a function Full-Stack Lead owns

This is the one place in the system where one person's script needs to put data into another person's database. The rule: **scripts never write raw SQL against another lead's tables.** They call a function.

```python
# backend/src/enginpilot/services/asset_service.py  [Full-Stack Lead]

def update_risk_state(asset_id: str, risk_level: RiskLevel, last_rule_fired: str | None) -> None:
    """Upserts into asset_risk_state. This is the ONLY way anything outside
    services/ writes to that table."""
    ...
```

```python
# backend/src/enginpilot/scripts/run_rules.py  [Agentic Lead]

from enginpilot.physics.engine import evaluate_portfolio
from enginpilot.services.asset_service import update_risk_state

def main():
    inputs = [...]  # built from seeded sensor_readings
    results = evaluate_portfolio(inputs)
    for r in results:
        update_risk_state(r.asset_id, r.overall_risk, r.fired_rules[0].rule_id if r.fired_rules else None)
```

This script is what populates the Asset Health dashboard module (Day 11) — it must run successfully before Day 11 work starts, or Full-Stack Lead is building a dashboard against an empty table.

---

### 5.6 LangGraph Shared State — Agentic Lead's internal contract (others read it for debugging, nobody else writes to it)

```python
# backend/src/enginpilot/agents/state.py

from typing import TypedDict
from shared.types.common import Citation
from enginpilot.retrieval.retriever import RetrievedChunk
from enginpilot.physics.engine import RuleEvaluation

class ChatTurn(TypedDict):
    role: str
    content: str

class AgentState(TypedDict):
    request_id: str                          # propagated for logging — see §13
    question: str
    conversation_history: list[ChatTurn]
    selected_asset_id: str | None

    intent: str | None
    routed_agents: list[str]

    rule_evaluation: RuleEvaluation | None
    retrieved_chunks: list[RetrievedChunk]
    maintenance_history: list[dict]

    final_answer: str | None
    citations: list[Citation]
    has_valid_source: bool
```

**Architecture decision — agent invocation has two modes.** The original spec describes the Reliability Agent "calling" the Asset Agent for maintenance history. Read literally, that's ambiguous: a second full LLM-driven agent call, or a plain data fetch? Resolved here: when the Orchestrator routes a user question directly to an agent, that agent makes exactly one LLM call to produce its templated response (Factual / Diagnostic / Insufficient Information, per the original Section 7.4). When one agent needs data from another agent's domain internally (Reliability needing Asset's maintenance history), it calls that agent's underlying tool function directly — no nested LLM call. This keeps the system to one LLM call per top-level agent actually routed to, plus one final synthesis call by the Orchestrator. Fewer LLM calls means fewer hallucination surfaces and a system that's actually testable with DeepEval-style judges instead of a combinatorial mess of nested generations.

**No global mutable state anywhere in `agents/` or `physics/`.** Every request gets a fresh `AgentState`. This is what makes concurrent requests safe without you having to think about it — don't undo it with a module-level cache or counter.

---

### 5.7 Orchestrator ↔ API Contract — the most important boundary in the system

Agentic Lead's orchestrator and Full-Stack Lead's `chat.py` meet exactly here. Neither side needs to know how the other is implemented internally — only this shape.

```python
# shared/types/common.py (extends §5.1)

from typing import Literal, Union
from pydantic import BaseModel

class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str

class CitationEvent(BaseModel):
    type: Literal["citation"] = "citation"
    citation: Citation

class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    final_answer: str
    citations: list[Citation]
    agent_path: list[str]              # which agents ran, for the audit log

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    recoverable: bool

OrchestratorEvent = Union[TokenEvent, CitationEvent, DoneEvent, ErrorEvent]
```

```python
# backend/src/enginpilot/agents/orchestrator.py  [Agentic Lead]

async def run_orchestrator(
    question: str,
    conversation_history: list[ChatTurn],
    selected_asset_id: str | None = None,
) -> AsyncIterator[OrchestratorEvent]:
    """The ONLY function api/chat.py calls into this entire package."""
    ...
```

Internally, before yielding `DoneEvent`, the orchestrator checks `state["has_valid_source"]`. If false, it yields `DoneEvent(final_answer="I don't have enough information...", citations=[], ...)` instead of whatever the LLM generated. **This is where "No Source, No Answer" is actually enforced at runtime** — not just verified after the fact in the Day 13 eval suite. The eval suite tests that this gate works; this function is where it lives.

```python
# backend/src/enginpilot/api/chat.py  [Full-Stack Lead]

@router.post("/chat")
async def chat(req: ChatRequest):
    async def event_stream():
        async for event in run_orchestrator(req.question, req.history, req.selected_asset_id):
            yield format_sse(event)
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

**Frontend note (avoids a real trap):** don't wire the Vercel AI SDK's `useChat` hook to fetch this endpoint directly and assume it parses automatically — `useChat`'s built-in fetcher expects the `ai` package's own wire protocol, which is specific to that SDK version and isn't what a custom FastAPI backend emits by default. The safer path, and the one the file tree already implies by including a custom `hooks/use-chat.ts`: that hook opens the stream itself (via `fetch` + `ReadableStream` or `EventSource`), parses the `OrchestratorEvent` JSON shape above directly, and feeds parsed tokens into local React state. Use `assistant-ui/react`'s components for *rendering* (markdown, citation pills, message bubbles) but don't depend on the SDK's automatic data-fetching against a non-Node backend. This avoids a wire-protocol mismatch that would otherwise cost a full day to debug around Day 11–12.

**Freeze point:** Day 8 (when the Orchestrator first exists) — this is the earliest contract that should be locked, since Full-Stack Lead's frontend chat work and Agentic Lead's agent work both build against it independently starting then.

---

### 5.8 Ingestion Pipeline Contract — resolves the `ingest.py` / `sop_service.py` overlap

```python
# backend/src/enginpilot/retrieval/ingest.py  [RAG Lead — does the actual work]

class IngestionResult(BaseModel):
    documents_processed: int
    chunks_created: int
    failed_documents: list[str]        # filenames that failed extraction QA

def run_ingestion(manual_paths: list[Path]) -> IngestionResult: ...
```

```python
# backend/src/enginpilot/services/sop_service.py  [Full-Stack Lead — thin wrapper only]

from enginpilot.retrieval.ingest import run_ingestion

def trigger_ingestion(paths: list[Path]) -> IngestionResult:
    """Called by POST /api/ingestion/run. Does NOT reimplement chunking,
    embedding, or extraction — that's retrieval/ingest.py's job entirely.
    This function exists only so the API layer has something to call without
    importing deep into another lead's package internals directly from a route handler."""
    return run_ingestion(paths)
```

If `sop_service.py` ever grows beyond a one-line delegation, that's a signal the boundary is being violated — stop and re-sync.

---

### 5.9 Seed Data Contract — RAG Lead generates, Full-Stack Lead's schema is the format

RAG Lead's `infra/seed/generate_*.py` scripts must output CSVs matching the **exact column order and types** of Full-Stack Lead's `infra/db/postgres/init.sql` table definitions (§6.1) — not the SQLAlchemy models directly, the raw DDL, since that's the one both leads can read without needing to understand the other's ORM layer.

Critically: **seeded fault values must derive from `physics/thresholds.py`, not be hardcoded independently.** If `generate_sensor_data.py` hardcodes "ramp UPS-01 to 45°C" while `physics/thresholds.py` independently says the threshold is 40°C, it works today — but if Agentic Lead later tunes the threshold to 42°C and nobody regenerates the seed data, the demo silently still works at 45 > 42, but a tighter threshold change (e.g. up to 46°C) breaks Scenario 1 with no warning. Import the threshold constant into the generator; don't duplicate the number.

---

## 6. Database Schemas

### 6.1 PostgreSQL

```sql
CREATE TABLE sites (
    site_id  VARCHAR(50) PRIMARY KEY,
    name     VARCHAR(100) NOT NULL,
    location VARCHAR(200)
);

CREATE TABLE buildings (
    building_id VARCHAR(50) PRIMARY KEY,
    site_id     VARCHAR(50) REFERENCES sites(site_id),
    name        VARCHAR(100) NOT NULL
);

CREATE TABLE assets (
    asset_id     VARCHAR(50) PRIMARY KEY,
    asset_class  VARCHAR(30) NOT NULL,           -- mirrors shared.constants.AssetClass
    name         VARCHAR(100) NOT NULL,
    model        VARCHAR(100),
    manufacturer VARCHAR(100),
    building_id  VARCHAR(50) REFERENCES buildings(building_id),
    specs        JSONB NOT NULL DEFAULT '{}',     -- class-specific: capacity_kva, rated_efficiency, etc.
    install_date DATE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sensors (
    sensor_id   VARCHAR(50) PRIMARY KEY,
    asset_id    VARCHAR(50) REFERENCES assets(asset_id) NOT NULL,
    sensor_type VARCHAR(30) NOT NULL,             -- "internal_temp_c", "vibration_mm_s", ...
    unit        VARCHAR(20) NOT NULL
);

CREATE TABLE sensor_readings (
    id          BIGSERIAL PRIMARY KEY,
    sensor_id   VARCHAR(50) REFERENCES sensors(sensor_id) NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings(sensor_id, recorded_at DESC);

CREATE TABLE maintenance_records (
    id               BIGSERIAL PRIMARY KEY,
    asset_id         VARCHAR(50) REFERENCES assets(asset_id) NOT NULL,
    service_type     VARCHAR(100) NOT NULL,
    performed_at     DATE NOT NULL,
    technician_notes TEXT,
    parts_replaced   TEXT[]
);

CREATE TABLE rules_fired_log (
    id             BIGSERIAL PRIMARY KEY,
    asset_id       VARCHAR(50) REFERENCES assets(asset_id) NOT NULL,
    rule_id        VARCHAR(30) NOT NULL,
    measured_value DOUBLE PRECISION NOT NULL,
    risk_level     VARCHAR(10) NOT NULL,          -- mirrors shared.constants.RiskLevel
    explanation    TEXT NOT NULL,
    fired_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE asset_risk_state (
    asset_id           VARCHAR(50) PRIMARY KEY REFERENCES assets(asset_id),
    risk_level         VARCHAR(10) NOT NULL DEFAULT 'LOW',
    last_rule_fired    VARCHAR(30),
    last_evaluated_at  TIMESTAMPTZ
);

CREATE TABLE sop_documents (
    id          BIGSERIAL PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    asset_class VARCHAR(30) NOT NULL,
    file_path   VARCHAR(500) NOT NULL,
    doc_type    VARCHAR(20) NOT NULL              -- 'oem_manual' | 'sop'
);

-- [NEW] resolves the auth gap
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(10) NOT NULL DEFAULT 'viewer',   -- 'viewer' | 'admin'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 6.2 Neo4j — Constraints

```cypher
CREATE CONSTRAINT ups_id          IF NOT EXISTS FOR (n:UPS)         REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT battery_id      IF NOT EXISTS FOR (n:Battery)     REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT transformer_id  IF NOT EXISTS FOR (n:Transformer) REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT switchgear_id   IF NOT EXISTS FOR (n:Switchgear)  REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT pdu_id          IF NOT EXISTS FOR (n:PDU)         REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT chiller_id      IF NOT EXISTS FOR (n:Chiller)     REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT crah_id         IF NOT EXISTS FOR (n:CRAH)        REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT pump_id         IF NOT EXISTS FOR (n:Pump)        REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT rack_id         IF NOT EXISTS FOR (n:Rack)        REQUIRE n.asset_id IS UNIQUE;
CREATE CONSTRAINT sensor_id       IF NOT EXISTS FOR (n:Sensor)      REQUIRE n.sensor_id IS UNIQUE;
```

Node/relationship schema itself is unchanged from the original spec (Site, Building, UPS, Battery, Transformer, Switchgear, PDU, Chiller, CRAH, Pump, Rack, Sensor / `FEEDS`, `COOLS`, `MONITORED_BY`, `BACKS_UP`, `DEPENDS_ON`, `LOCATED_IN`) — not reproduced again here since it hasn't changed and is already documented elsewhere in the team's materials.

### 6.3 Qdrant Collection

```json
{
  "collection_name": "enginpilot_docs",
  "vectors": { "size": 1024, "distance": "Cosine" },
  "payload_schema": {
    "source_document": "keyword",
    "doc_type": "keyword",
    "asset_class": "keyword",
    "manufacturer": "keyword",
    "section": "text",
    "page": "integer",
    "chunk_id": "keyword"
  }
}
```

### 6.4 Redis Key Conventions

```
session:{session_id}          → user_id, role, expires_at      TTL 24h
ratelimit:{user_id}:{window}   → request count                  TTL 60s
ingestion_job:{job_id}          → status, progress               TTL 1h
```

No other key patterns without updating this table — Redis has no schema enforcement, so this list *is* the schema.

---

## 7. API Endpoint Reference

| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/api/health` | none | `{"status": "ok", "services": {...}}` |
| POST | `/api/auth/login` | none | `{"access_token": str, "role": str}` |
| POST | `/api/auth/logout` | session | `{"status": "ok"}` |
| GET | `/api/assets` | viewer+ | `list[AssetSummary]` |
| GET | `/api/assets/{asset_id}` | viewer+ | `AssetDetail` |
| GET | `/api/assets/{asset_id}/graph` | viewer+ | topology nodes+edges for visualization |
| GET | `/api/alerts?risk_level=&limit=` | viewer+ | `list[Alert]` |
| POST | `/api/chat` | viewer+ | SSE stream, §5.7 event shapes |
| GET | `/api/reports/asset-health/{asset_id}` | viewer+ | `AssetHealthReport` |
| GET | `/api/reports/maintenance/{asset_id}` | viewer+ | `MaintenanceReport` |
| GET | `/api/reports/executive-summary` | viewer+ | `ExecutiveSummary` |
| POST | `/api/ingestion/run` | admin | `{"status": "started", "job_id": str}` |

Key request/response shapes:

```python
class AssetSummary(BaseModel):
    asset_id: str
    asset_class: AssetClass
    name: str
    risk_level: RiskLevel
    last_rule_fired: str | None

class ChatRequest(BaseModel):
    question: str
    conversation_history: list[ChatTurn] = []
    selected_asset_id: str | None = None

class Alert(BaseModel):
    asset_id: str
    rule_id: str
    risk_level: RiskLevel
    measured_value: float
    fired_at: datetime
```

---

## 8. Request Flow Traces — File-by-File, All Three Demo Scenarios

**Scenario 1 — "Why is UPS-01 repeatedly overheating?"**
`frontend/hooks/use-chat.ts` → `app/api/chat/route.ts` (proxy) → `api/chat.py` → `agents/orchestrator.py` → intent classified, routes to `reliability_agent.py` → calls `physics/engine.py::evaluate()` on pulled sensor history (via `tools/pg_query.py`) → calls `graph/queries/asset_neighbors.py` (via `tools/cypher_query.py`) for maintenance context → calls `retrieval/retriever.py::retrieve()` (via `tools/qdrant_search.py`) for OEM manual passages → one LLM call formats the Diagnostic Answer → `orchestrator.py` validates `has_valid_source` → streams `TokenEvent`s, then `DoneEvent` → `chat.py` → SSE → frontend.

**Scenario 2 — "Generate a maintenance plan for Chiller-03."**
Same path to orchestrator → routes to `maintenance_agent.py` → `retrieval/retriever.py::retrieve(doc_type="sop")` → AutoMergingRetriever assembles full section → one LLM call formats the procedure outline → orchestrator **sequentially chains** to `compliance_agent.py` for the frequency cross-check (this is the one scenario requiring two agents in sequence, not parallel — make sure the conditional-edge logic in `orchestrator.py` actually supports this, not just single-agent routing) → synthesis → stream.

**Scenario 3 — "Show me the critical assets with the highest risk right now."**
Routes to `reliability_agent.py` in **portfolio mode** → calls `physics/engine.py::evaluate_portfolio()` across all curated assets → calls `graph/queries/impact_analysis.py::get_downstream_assets()` for each flagged asset to compute blast radius → dashboard's Asset Health module (which already has this data via `asset_risk_state`, populated by `scripts/run_rules.py`) renders the ranked list — this scenario is the one that proves Rule Kernel + Graph + Dashboard are all correctly wired together, which is why the original sprint plan re-runs it first on Day 13.

---

## 9. Per-Role Build Plan + AI Agent Operating Instructions

### 9.1 RAG Lead (you)

**Owns:** `retrieval/`, `infra/seed/`, `infra/db/qdrant/`, `evaluation/` (harness), seed CSV generation.

**Milestones:** Day 1 — stub `retrieve()` shipped matching §5.2 exactly. Days 3–4 — Docling extraction + manual QA on ≥20% of pages. Day 5 — real Qdrant retrieval live, 10-question harness ≥7/10 passing, freeze §5.2 signature. Days 2–5 in parallel — seed dataset generation importing thresholds from `physics/thresholds.py` per §5.9. Day 13 — evaluation suite run, citation/hallucination judges report results to Agentic Lead for prompt fixes.

```
AI AGENT OPERATING INSTRUCTIONS — RAG LEAD

You are building the retrieval and dataset-generation subsystem for ENGINPILOT, an
industrial AI copilot. Your code lives entirely under backend/src/enginpilot/retrieval/,
infra/seed/, and evaluation/. You do not touch agents/, physics/, api/, models/, or
frontend/ — those are owned by teammates and any change there must be flagged to a human,
not made silently.

Your public contract is the `retrieve()` function defined in Section 5.2 of
ARCHITECTURE.md. That exact signature — name, arguments, return type — is what a teammate's
agent code already imports. On Day 1, ship a stub version that returns 2–3 hardcoded
RetrievedChunk objects so they can build against you immediately; swap in the real Qdrant
implementation by Day 5 without changing the signature.

Use IBM Docling (not PyPDF2) for PDF extraction — OEM manuals have tables and multi-column
layouts that naive extractors corrupt. Use LlamaIndex's HierarchicalNodeParser for chunking
and AutoMergingRetriever for retrieval, specifically to prevent returning fragmented
maintenance steps (step 1, 3, 7 of a 10-step procedure with no warning that 2/4/5/6 are
missing).

Embedding model is locked: nvidia/nv-embedqa-e5-v5 (1024-dim) primary, BAAI/bge-large-en-v1.5
local fallback. Do not switch models after Day 1 without re-embedding the entire corpus —
flag this loudly if you're tempted, since changing it silently breaks every existing vector
in Qdrant.

When generating seed sensor data, import numeric thresholds from physics/thresholds.py
(Agentic Lead's file) rather than hardcoding fault values. If that file doesn't exist yet
when you need it, coordinate timing rather than guessing the numbers — a mismatch here
silently breaks the Day 15 demo.

If you discover the retrieve() signature genuinely needs to change (a new parameter, a
different return shape), stop and say so explicitly rather than changing it and hoping the
agent code adapts — that function is consumed by code you cannot see and cannot test against.
```

### 9.2 Agentic Lead

**Owns:** `agents/`, `physics/`, `llm/`, `scripts/run_rules.py`.

**Milestones:** Day 6 — Cypher contract (§5.3) consumed, no changes requested. Day 7 — physics engine complete, ≥90% of seeded faults flagged, signature in §5.4 frozen. Day 8 — Asset + Reliability agents, every response carries a citation. Day 9 — Maintenance + Compliance agents. Day 10 — orchestrator wired, ≥90% routing accuracy on the 15-question test, §5.7 signature frozen.

```
AI AGENT OPERATING INSTRUCTIONS — AGENTIC LEAD

You are building the LangGraph multi-agent reasoning layer for ENGINPILOT. Your code lives
under backend/src/enginpilot/agents/, physics/, and llm/. You do not touch retrieval/
internals, api/ route handlers, models/, or frontend/ — you call into retrieval/ and graph/
only through the public functions defined in Sections 5.2 and 5.3 of ARCHITECTURE.md, never
by reaching into their internals.

The single rule every agent enforces, in code, not just in the prompt: every response is
EITHER an answer with a named source (a fired rule_id, a retrieved chunk's source_document,
or a graph-verified fact) OR an explicit "I don't have enough information." Implement this
as a programmatic check in orchestrator.py before yielding DoneEvent — inspect whether
citations is non-empty and has_valid_source is True, and override the LLM's output if it
isn't, rather than trusting the prompt instruction alone to hold under pressure.

Agent invocation has two modes, and you must keep them distinct: when the Orchestrator
routes a user question directly to an agent (e.g. Reliability Agent answering "why is
UPS-01 overheating"), that agent makes exactly one LLM call to produce its templated
response. When one agent needs another agent's data internally (Reliability needing Asset's
maintenance history), call that agent's underlying tool function directly — no nested LLM
call. This keeps LLM calls to one per routed agent plus one final orchestrator synthesis,
which is both cheaper and dramatically easier to test for hallucination.

Cypher queries are never LLM-generated. You call get_downstream_assets() and
get_asset_node() from graph/queries/ — typed functions someone else wrote and tested. If
asset_id doesn't resolve, get_asset_node() returns None; your Asset Agent must return
"asset not found" in that case, never let the LLM guess at specs for an asset it can't verify.

Set recursion_limit=15 on every graph invocation. Wrap LLM calls through llm/router.py's
circuit breaker (NVIDIA Build, 3-second timeout, fall back to local Ollama) — never call
the NVIDIA endpoint directly from agent code.

For Demo Scenario 2, the orchestrator must support a SEQUENTIAL multi-agent chain
(Maintenance → Compliance), not just single-agent routing. Test this path explicitly —
it's the one scenario that breaks if your conditional edges only support fan-out to one
destination.

If a contract function's signature genuinely needs to grow, propose the change and wait for
the other lead to confirm before depending on it — your code compiling against a stub does
not mean it will work against their real implementation.
```

### 9.3 Full-Stack Lead

**Owns:** `api/`, `models/`, `schemas/`, `services/`, `core/`, `graph/client.py` + `graph/schema.py` + `graph/queries/`, `frontend/`, `infra/docker/`, `infra/db/postgres/`, auth.

**Milestones:** Day 1 — all 5 Docker services healthy, repo scaffolded, `shared/` and `.env.example` in place. Day 2 — Postgres schema + asset registry seeded. Day 6 — Neo4j schema + query functions ready for Agentic Lead. Day 11 — all API endpoints live against real Postgres/Neo4j data, dashboard core views rendering. Day 12 — chat UI wired to the orchestrator, reports generating.

```
AI AGENT OPERATING INSTRUCTIONS — FULL-STACK LEAD

You are building the API gateway, database layer, auth, and frontend for ENGINPILOT. Your
code lives under backend/src/enginpilot/{api, models, schemas, services, core, graph}/ and
the entire frontend/ tree. You own docker-compose.yml and .env.example as sole editor —
teammates request additions to these files, they don't edit them directly.

Two files in your domain were missing from earlier planning and must exist: models/user.py
(id, email, password_hash, role) and api/auth.py (login/logout, session tokens in Redis,
two-role RBAC stub — viewer read-only, admin can edit assets and trigger ingestion). Build
these on Day 1–2 alongside the rest of the schema, not as an afterthought before the demo.

graph/queries/ exposes typed functions (get_downstream_assets, get_asset_node) that
Agentic Lead's agent code imports — you do not write agent logic, but you DO need to know
what queries they need. Confirm function names and return shapes with them before Day 6,
not after.

api/chat.py's only job is to iterate run_orchestrator() (Agentic Lead's function) and format
each OrchestratorEvent as an SSE frame. Do not reimplement any agent logic in this file —
if you find yourself writing routing or prompt logic here, stop, that belongs in agents/.

On the frontend: do not wire Vercel AI SDK's useChat hook to fetch /api/chat directly and
assume automatic parsing works — write hooks/use-chat.ts as a custom hook that opens the
stream itself and parses the OrchestratorEvent JSON shape from Section 5.7 directly. Use
assistant-ui/react components for rendering only, not for data-fetching against this custom
backend.

scripts/run_rules.py (Agentic Lead's script) calls services/asset_service.py's
update_risk_state() function to write into asset_risk_state — implement that function
before Day 7 so their script has something to call, and never let any code outside
services/ write to that table directly.

Docker Compose healthchecks matter more than they look like they do: every service needs a
real healthcheck and api/web need depends_on with condition: service_healthy, not just
depends_on by name — otherwise FastAPI starts before Postgres is accepting connections and
the Day 1 acceptance criterion ("docker compose up, no manual steps") silently fails on a
clean checkout.
```

---

## 10. Failure Modes & Resilience (FMEA-Style)

| Layer | Failure | Detection | Mitigation | Owner |
|---|---|---|---|---|
| Retrieval | Qdrant returns low-relevance chunks | `below_confidence_floor` flag (score < 0.55) | Agent returns "insufficient information" instead of a weak answer | RAG Lead defines the floor, Agentic Lead enforces it |
| Retrieval | Fragmented SOP steps returned | AutoMergingRetriever merge check | Merge to parent section when 3+ chunks share a source section | RAG Lead |
| Graph | `asset_id` doesn't resolve | `get_asset_node()` returns `None` | Asset Agent returns "asset not found," never guesses specs | Agentic Lead |
| Graph | Cypher query times out | Query timeout (3s) | Circuit breaker returns "graph temporarily unavailable" rather than hanging the request | Full-Stack Lead |
| LLM | NVIDIA Build API slow/down | >3s response time | Circuit breaker routes to local Ollama | Agentic Lead |
| LLM | Cited source doesn't match retrieved chunks | Orchestrator post-hoc validation: does the cited `ref_id` exist in `state["retrieved_chunks"]` or `state["rule_evaluation"]`? | Reject + retry once with stricter prompt, else fall back to insufficient-information | Agentic Lead |
| Agents | LangGraph infinite loop | `recursion_limit=15` | Hard stop, yields `ErrorEvent` rather than hanging | Agentic Lead |
| Agents | Compliance Agent false "Compliant" | Structural: verdict requires a cited clause `ref_id` present in retrieved chunks | Default state is always "Insufficient Information" unless explicitly supported | Agentic Lead |
| Contracts | Shared schema silently changes shape | Contract snapshot test in CI (§12) | Build fails loudly instead of breaking another lead's code at runtime | Whoever owns the changed file |
| Data | Seed thresholds drift from rule kernel | Manual check, ideally a CI consistency test comparing seeded fault values against `physics/thresholds.py` | Seed generator imports thresholds, never hardcodes them | RAG Lead |
| Infra | Service start-order race in Docker Compose | `depends_on: condition: service_healthy` | Real healthchecks on every service, not just port-open checks | Full-Stack Lead |
| Frontend | SSE stream drops mid-response | Server-side 30s max-duration timeout | Orchestrator always yields a terminal `DoneEvent` or `ErrorEvent`, never silently dies | Agentic Lead + Full-Stack Lead |
| Process | Two leads edit `shared/` differently | PR review requirement on `shared/` after Day 0 freeze | Single joint session defines it once; changes after that require both other leads' sign-off | All three |

---

## 11. Git Workflow & Contract-Freeze Process

Trunk-based: `main` + short-lived feature branches per person per day, matching the original spec's Section 10.6. Because all three people commit into **one shared `backend/src/enginpilot/` package**, the discipline that prevents conflict isn't branching strategy — it's staying inside your owned subdirectory.

**Contract-freeze rule:** any file marked "BOUNDARY" in Section 3 (`shared/`, `agents/state.py`, `retrieval/retriever.py`'s public signature, `schemas/chat.py`, `graph/queries/*.py`'s function signatures) requires a one-line Slack/Discord ping to the consuming lead before merging a change, plus a PR review from them — not a formal approval gate, just "did you see this." Everything else merges on push to your own subtree without ceremony.

If a contract genuinely needs to change mid-sprint (it will, at least once): the person requesting the change proposes the new shape, the consuming lead confirms they can adapt, both update their code in the same day. Don't let a contract drift silently where one side updates and the other doesn't notice until Day 13 integration.

---

## 12. Testing Strategy (Pyramid)

| Level | What | Speed | Runs |
|---|---|---|---|
| 0 — Static | ruff, mypy, eslint, tsc | <30s | Every save |
| 1 — Unit | Physics engine, chunker, individual Cypher query functions, Pydantic validation — no network, no LLM calls, mocked DB sessions | Seconds | Every push (`ci.yml`) |
| 2 — Contract | Snapshot tests on `shared/` types and the §5.2/5.3/5.7 signatures — fails loudly if a field is renamed or removed without updating the snapshot | Seconds | Every push |
| 3 — Integration | API endpoint tests against a real test Postgres/Neo4j/Qdrant (docker compose or testcontainers), but a **mocked** orchestrator so they're fast and don't burn LLM tokens | ~1 min | Every push |
| 4 — Agent/E2E | Real orchestrator, real NVIDIA calls, the 15-question routing test + 3 demo scenarios via the evaluation suite's judges | Minutes, costs tokens | Day 13+, manually and nightly (`e2e.yml`) |

`api/chat.py` tests at Level 3 mock `run_orchestrator()` entirely — they're testing that SSE framing works, not that the agents reason correctly. Agent reasoning correctness is Level 4's job, owned by Agentic Lead with RAG Lead's evaluation harness.

---

## 13. Observability & Logging Convention

Every component logs structured JSON with a consistent shape:

```json
{"timestamp": "...", "level": "info", "request_id": "req_8f2a", "component": "reliability_agent", "asset_id": "UPS-01", "rule_fired": "THERM-UPS-001", "sources_count": 2, "latency_ms": 842, "model_used": "llama-3.3-70b", "message": "..."}
```

`request_id` is generated once in `api/chat.py`'s middleware, placed into `AgentState["request_id"]`, and every agent/tool call logs with it. This is what makes a Day 13 bug ("why did this answer have no citation?") traceable across three people's code in under a minute instead of a half-day of cross-referencing logs by timestamp.

This also directly satisfies the original spec's audit logging requirement (who asked what, which agent answered, what was retrieved or fired) — `utils/logging.py` is the single place this format is defined, built and frozen by Full-Stack Lead on Day 1–2, imported everywhere else as-is.

---

## 14. Definition of Done (Per Role)

**RAG Lead:** `retrieve()` returns relevant chunks for ≥7/10 harness questions. Seed dataset has documented, threshold-consistent fault conditions. Day 13 eval suite runs and reports pass/fail on citation + hallucination metrics for all 15 scripted questions.

**Agentic Lead:** Zero agent responses without a citation across ≥20 manually reviewed queries. ≥90% of seeded faults correctly flagged. ≥90% correct routing on the 15-question test. Zero false "Compliant" verdicts on seeded non-compliant cases.

**Full-Stack Lead:** `docker compose up` brings all services healthy with no manual steps, from a clean checkout. All 5 dashboard modules render real backend data. Auth works for both roles. All three demo scenarios complete a full round-trip from UI to response.

**System-level:** matches the original spec's Section 11 Exit Criteria in full — not reproduced again here since it hasn't changed.

---

## 15. Ready-to-Drop Infra Files

`docker-compose.yml` and `.env.example`, provided as separate files alongside this document — copy both to repo root as-is. Full-Stack Lead still needs to write the actual `Dockerfile.api` / `Dockerfile.web` (genuine implementation work), but the orchestration layer connecting them, with correct healthchecks and dependency ordering, is done.

---

## 16. Master Day-by-Day Timeline (Role-Annotated)

| Day | RAG Lead | Agentic Lead | Full-Stack Lead |
|---|---|---|---|
| 0 | — | — | Decisions locked (§2), repo created |
| 1 | Stub `retrieve()` shipped; start sample PDF collection | Stub agent code against the retrieval stub | Docker Compose up, repo scaffolded, `shared/` + `.env.example` committed |
| 2 | Continue doc QA prep | — | Postgres schema + asset registry seeded |
| 3–4 | Docling extraction + manual QA on ≥20% of pages | — | API scaffolding, `models/`, `schemas/` |
| 5 | Real Qdrant retrieval live, harness ≥7/10, **freeze §5.2** | Build against real retrieval now | — |
| 6 | Seed data generation continues | — | Neo4j schema + queries, **freeze §5.3** |
| 7 | — | Physics Rule Kernel complete, ≥90% faults flagged, **freeze §5.4** | — |
| 8 | — | Asset + Reliability Agents | API endpoints continue |
| 9 | — | Maintenance + Compliance Agents | — |
| 10 | — | Orchestrator + routing, **freeze §5.7** | — |
| 11 | Begin evaluation dataset prep | `run_rules.py` populating risk state | Dashboard core views, all endpoints live |
| 12 | — | — | Chat UI wired, reports generating |
| 13 | Evaluation suite run, results to Agentic Lead | Fixes from eval results | All hands: integration, bug fix, 3 scenarios pass twice |
| 14 | All hands: rehearsal | All hands: rehearsal | All hands: rehearsal |
| 15 | Demo | Demo | Demo |

---

## 17. Appendix A — Gaps Found & Resolved vs. TEAM_DIVISION.md / MVP_BLUEPRINT.md

See the comparison table delivered alongside this document. Every gap listed there (auth/users, Redis client, path drift, duplicate seed.cypher, embedding model ambiguity, `ingest.py`/`sop_service.py` overlap, `run_rules.py` ownership, runtime citation gate location, ADR numbering) is resolved by a specific section above — §6.1 (auth tables), §3 (core/redis_client.py), §3 (canonical tree), §3 (seed.cypher location), §2 decision 1 (embedding model), §5.8, §5.5, §5.7, §17 below.

## Appendix B — ADR Log (Filling the Gaps)

| ID | Title | Status |
|---|---|---|
| 002 | Embedding model selection (nv-embedqa-e5-v5, 1024-dim, BGE-large fallback) | Recorded here — formalize as `docs/decisions/002-embedding-model.md` |
| 003 | LLM provider fallback (NVIDIA Build → Ollama circuit breaker, 3s threshold) | Recorded here — formalize as `docs/decisions/003-llm-fallback.md` |
| 005 | Citation enforcement mechanism (orchestrator-level programmatic gate, not prompt-only) | Recorded here — formalize as `docs/decisions/005-citation-enforcement.md` |
| 008 | Single-package monorepo vs. multi-package workspace | Decision: single shared `backend/` package with directory ownership + contract-freeze, not independently versioned packages — proportionate to a 3-person, 15-day build. Formalize as `docs/decisions/008-monorepo-structure.md` |

---

*This document supersedes TEAM_DIVISION.md's file-path assumptions where they conflict with MVP_BLUEPRINT.md's canonical tree. Where the two already agreed, nothing here changes them.*

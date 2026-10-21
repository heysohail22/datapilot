# DataPilot

DataPilot answers business questions using a four-node LangGraph workflow, a FastAPI backend, and a Next.js analytics workspace.

```text
Question → Router → SQL Generator → SQL Executor → Answer
              └──────────────────────────────────→ Answer
                         ↑                │
                         └─ fixable error ┘
                           at most 2 repairs
```

The router classifies chat, clarification, supported business questions, and unsupported requests. Python resolves calendar dates. PostgreSQL calculates metrics over the complete eligible dataset. The answer node explains the returned values and selects an optional chart. Every execution, including a repair, passes the same AST-based SQL safety policy.

Implementation specification: [.agents/specs/05_backend_rebuild_implementation.md](.agents/specs/05_backend_rebuild_implementation.md).

## Backend structure

```text
backend/app/
├── main.py                 # Application factory, lifespan, signed session cookies, CORS
├── config.py               # Validated settings; no environment mutation
├── api/                    # HTTP contracts, chat/SSE/history and health endpoints
├── agent/
│   ├── contracts.py        # RouterDecision, BusinessPlan, SQLDraft, ExecutionResult
│   ├── state.py            # Per-turn graph state
│   ├── graph.py            # Exactly four nodes, compiled with injected dependencies
│   ├── routing.py          # Pure edge functions; no LLM calls
│   ├── nodes/              # router, sql_generator, sql_executor, answer
│   └── prompts/            # Model instructions, separate from runtime logic
├── business/               # Versioned metric meanings and deterministic periods
├── database/               # Pool lifecycle, metadata allowlist and read-only executor
├── services/               # Provider adapter, bounded history and chat orchestration
└── guardrails/             # Input checks, SQL AST policy, output redaction, rate limit
```

## Local setup

Use Python 3.12+, uv, Node 22+, and pnpm. Run from the repository root:

```bash
cp backend/.env.example backend/.env
cd backend
uv sync
uv run python main.py
```

Configure a provider key (`LLM_API_KEY`, or the selected provider's existing `GROQ_API_KEY`/`GEMINI_API_KEY`) and a database connection. The default provider is Groq; for Google set `LLM_PROVIDER=google` and all three model identifiers to your supported Google model. Model clients are constructed once at startup. Required credentials fail clearly at startup; a database outage leaves liveness available and readiness unavailable.

Before enabling business queries, set `BUSINESS_TABLES`, `ENABLED_METRICS`, and `METRIC_SCHEMA_NOTES` for the actual database. Metrics start disabled. Mapping notes must describe real date/amount/identifier columns, row grain, relationships, status exclusions, discounts, refunds, tax treatment, historical cost availability, and history coverage. The fixture example in `.env.example` is not a presumed production schema. Gross margin requires historical COGS; net profit additionally requires expense data. Metadata discovery samples no customer rows.

Use a dedicated database role granted SELECT only on the allowed business tables. Do not use a database administrator account for deployment. The backend never creates or migrates business or conversation tables. All generated queries execute in read-only transactions with a local timeout and restricted search path. Unknown functions, mutations, multiple statements, locks and internal tables are blocked.

Start the frontend in another terminal:

```bash
cd frontend
pnpm install
pnpm dev
```

Backend: `http://localhost:8000`; frontend: `http://localhost:3000`; OpenAPI: `http://localhost:8000/docs`. `docker compose up --build` retains the same backend entry point. Set the frontend API URL to the intended backend before deploying.

## Configuration

The complete template is [backend/.env.example](backend/.env.example). Secrets are never committed.

| Setting | Default or behavior |
| --- | --- |
| DATABASE_URL | PostgreSQL connection for a dedicated read-only role |
| LLM_PROVIDER | groq; google also supported |
| LLM_API_KEY | Selected provider key; existing provider-specific keys are fallback inputs |
| ROUTER_MODEL / SQL_MODEL / ANSWER_MODEL | openai/gpt-oss-120b through Groq; override for another provider |
| BUSINESS_TABLES | Explicit public business table allowlist |
| ENABLED_METRICS | Empty until actual schema mapping is configured |
| METRIC_SCHEMA_NOTES | Required when metrics are enabled |
| BUSINESS_TIMEZONE / BUSINESS_CURRENCY | Asia/Kolkata / INR |
| FRONTEND_URL / CORS_ORIGINS | Exact allowed origins; no wildcard deployment domains |
| SESSION_SECRET | Stable random signing secret; empty creates a per-process value |
| SESSION_SECURE | false locally; true for HTTPS and cross-site browser cookies |
| SQL_TIMEOUT_MS | 5000 |
| MAX_SQL_REPAIRS | 2 maximum, plus the initial attempt |
| QUERY_DEFAULT_ROWS / QUERY_MAX_ROWS | 50 / 100 displayed result rows |
| SCHEMA_CACHE_TTL_SECONDS | 3600 |
| MODEL_TIMEOUT_SECONDS / REQUEST_TIMEOUT_SECONDS | 20 / 90 |
| CONVERSATION_LIMIT | 200 in-memory conversations |

Calendar comparisons include completed days only for current periods and label the exclusion of today. Previous completed months compare against complete previous months. Missing values stay unknown; zero denominators return null. Decimal amounts serialize as exact strings in tables and convert to numbers only for chart plotting.

## API and compatibility

| Method | Path | Behavior |
| --- | --- | --- |
| GET | /health | Process liveness |
| GET | /api/database/health | Lightweight database readiness; safe error on failure |
| POST | /api/chat | Full typed answer, clarification, or handled error |
| POST | /api/chat/stream | SSE step events and final done payload; no hidden reasoning |
| GET | /api/conversations | Current browser session's bounded history |
| GET | /api/conversations/{id} | Session-owned conversation or 404 |
| DELETE | /api/conversations/{id} | Delete session-owned inactive conversation |

A new chat sends `conversation_id: null`; the server returns the canonical ID. Follow-ups send that ID. Fetch requests must use `credentials: "include"`. Response fields include `status`, `message`, `context`, `data`, `chart`, `warnings`, and `request_id`. Legacy `response`, `columns`, `sql`, `chart_config` and timing fields preserve the current workspace contract. `thought_trace` contains public step labels only. The streaming adapter emits real node completion steps and one final answer, rather than token-by-token model reasoning.

History is bounded and in memory, isolated with an HttpOnly signed session cookie, and serialized per conversation. Restart or eviction clears it. This is a single-process implementation; durable storage and authenticated business authorization are prerequisites for a multi-worker or multi-user production deployment. Cookies identify browser history, not authorization to independent businesses. Cross-site browser policies may block third-party cookies; use a same-site API deployment when required.

## Verification

```bash
cd backend
uv run pytest
```

Fast tests inject fake models and execution boundaries. Real PostgreSQL tests run only with `TEST_DATABASE_URL` pointing at a disposable database whose name ends in `_test`:

```bash
TEST_DATABASE_URL=postgresql://test_user:test_password@localhost:5432/datapilot_test uv run pytest
```

These tests create and remove fixture tables in that database. Never point them at business data. They check actual margin, growth, annual aggregation, full aggregation before display limits, metadata allowlists, and read-only execution. The CI workflow supplies a disposable PostgreSQL service.

```bash
cd frontend
pnpm lint
pnpm build
```

Live-model evaluation is intentionally separate and may incur provider costs. Load `backend/tests/fixtures/business_data.sql` into an isolated `_test` database, configure its metric mappings, then run `uv run python -m evals.run --live` with `TEST_DATABASE_URL`. Historical datasets/reports under `backend/evals` describe the superseded architecture and are retained as reference; they are not current verification results.

## Current limits

There is no semantic Query Validator: executable SQL can still answer the wrong question. Use metric definitions and known-answer evaluations to measure this risk. Email actions and separate Python statistics nodes are excluded from this rebuild. No schema changes or new business data are applied automatically.

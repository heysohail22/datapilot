# DataPilot agent guidelines

DataPilot is a FastAPI and LangGraph read-only business analytics backend with a Next.js App Router frontend. The active backend architecture is specified in `.agents/specs/05_backend_rebuild_implementation.md`; specs 02 through 04 describe the superseded implementation.

## Package managers

- Backend: uv only. Use `uv sync`, `uv add`, and `uv run pytest`; never raw pip.
- Frontend: pnpm only. Use `pnpm install`, `pnpm lint`, `pnpm build`, and `pnpm dev`.
- Backend entry point: `uv run python main.py` from `backend/`; `main:app` stays compatible with Docker.

## Backend architecture

The graph has exactly four nodes: `router`, `sql_generator`, `sql_executor`, and `answer`. SQL repair returns to `sql_generator` with the failed SQL, sanitized error, original plan and schema. Permit one initial execution plus at most two repairs. Conditional edge functions are deterministic Python and contain no model calls. Do not add a semantic Query Validator until separately requested.

- `app/main.py`: application factory, lifespan, signed browser session and CORS.
- `app/api/`: public request/response schemas and routes. No direct model calls.
- `app/agent/contracts.py`: validated structured outputs and execution contracts.
- `app/agent/state.py`: fresh per-turn TypedDict state. Additive event reducers receive only new events.
- `app/agent/graph.py` and `routing.py`: dependency-injected graph and pure routing.
- `app/agent/nodes/`: small asynchronous workflow steps; no provider-specific logic.
- `app/agent/prompts/`: model instructions.
- `app/services/`: bounded provider calls, conversation context and chat orchestration.
- `app/database/`: pool lifecycle, allowlisted metadata and read-only execution.
- `app/business/`: metric meanings and deterministic calendar boundaries.
- `app/guardrails/`: input checks, SQL AST policy, redaction and rate limits.

Use Pydantic at boundaries. Do not keep connections, clients, credentials or raw exceptions in graph state. Compile once per application dependency configuration. Offload synchronous database calls from the async event loop. Do not create provider clients at import time or mutate environment variables while loading settings.

## Data correctness and security

Calculate complete business aggregates in SQL before limiting displayed result rows. Ratios use sums, not means of row percentages. Preserve decimals for tables, use null for unknown or zero-denominator results, and disclose truncated displays. Execution success is not semantic proof.

Enable a metric only after real column names, grain and business treatment are mapped in `METRIC_SCHEMA_NOTES`. Gross margin needs historical cost; net profit also needs expenses. Never invent unavailable costs or actions. Python owns inclusive-start/exclusive-end date ranges and business timezone policies.

Every generated query, including repairs, passes parser-based SQL validation. Use one read-only transaction, a local statement timeout, a business table allowlist, approved functions, bound parameters and a dedicated SELECT-only database role. Do not automatically create or migrate tables on the connected business database.

Never commit or expose .env files, database URLs, provider keys, session secrets, customer samples or raw database errors. Keep allowed CORS origins explicit. Public events contain short step labels, not hidden reasoning. Business action sending is out of scope; any future action requires server-enforced human approval.

History is currently bounded in memory and isolated by signed browser cookies. Do not treat the cookie as business authorization. Never permit a client-chosen conversation ID to access another owner's history. Serialize turns per conversation. Durable history and authenticated authorization require separate implementation before multi-worker or multi-business deployment.

## Frontend

Use Server Components by default, with client components for state and interaction. Preserve strict TypeScript in `frontend/types/chat.ts`; avoid any. Keep the charcoal and golden-yellow design tokens and accessible Radix UI components. Charts support bar, line, area and donut; preserve missing data as gaps.

All history/chat fetches use credentials. New conversations send null and adopt the server ID from the final SSE payload. Keep workspace response fields compatible when changing backend contracts.

## Verification

Run `uv sync` and `uv run pytest`. Ordinary tests must not call paid models or a live business database. PostgreSQL integration tests require a disposable `TEST_DATABASE_URL` ending in `_test`; fixtures create/drop tables there. Verify startup, liveness and readiness without logging credentials. Live-model evaluations require explicit `--live` and are separate from CI.

For frontend changes run `pnpm lint` and `pnpm build` and verify changed flows in desktop/mobile layouts. Update README, this file, environment templates and the active spec when interfaces or settings change. Preserve unrelated work and secret files when cleaning up superseded code.

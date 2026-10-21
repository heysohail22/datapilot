# DataPilot Backend Implementation Specification

Implement a fresh DataPilot backend that turns natural-language business questions into read-only database calculations and clear answers. This specification defines the four-node workflow, interfaces, folder ownership, failure behavior, and build order.

The initial release uses one connected business database, one Router, one SQL Generator that also repairs queries, one SQL Executor, and one Answer node. Semantic SQL verification remains a later phase. Examples below define proposed contracts; they are not copied from the existing backend.

# Scope and decisions

Build sales and customer analytics, gross profit margin when historical cost data exists, comparable monthly and yearly growth, and five-year revenue trends. General chat and clarification must work without running business queries.

Keep FastAPI, Python, Pydantic, LangGraph, and PostgreSQL. Use uv for dependencies and execution. Hide model-provider details behind one service interface. This specification does not select a new provider or assume what “Jev” means; any future routing library must satisfy the same RouterDecision contract.

Do not add separate repair, stats, email, or semantic Query Validator nodes in this release. Deterministic request validation, structured-output validation, and SQL safety validation are required supporting checks, not extra graph nodes.

Database execution success does not establish that SQL matches the user's intent. Mitigate with explicit metric definitions and known-answer evaluations until semantic validation is implemented.

# Backend structure

```text
backend/
├── pyproject.toml
├── uv.lock
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py
│   │   ├── health.py
│   │   └── schemas.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── contracts.py
│   │   ├── graph.py
│   │   ├── routing.py
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── router.py
│   │   │   ├── sql_generator.py
│   │   │   ├── sql_executor.py
│   │   │   └── answer.py
│   │   └── prompts/
│   │       ├── router.md
│   │       ├── sql_generator.md
│   │       └── answer.md
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chat_service.py
│   │   ├── llm.py
│   │   └── conversations.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── schema.py
│   │   └── queries.py
│   ├── business/
│   │   ├── __init__.py
│   │   ├── metrics.py
│   │   └── periods.py
│   └── guardrails/
│       ├── __init__.py
│       ├── input_guard.py
│       └── sql_guard.py
├── tests/
│   ├── unit/
│   │   ├── test_router.py
│   │   ├── test_routing.py
│   │   ├── test_periods.py
│   │   └── test_guardrails.py
│   ├── integration/
│   │   ├── test_graph.py
│   │   ├── test_chat_api.py
│   │   └── test_database_queries.py
│   └── fixtures/
│       └── business_data.sql
└── evals/
    ├── questions.json
    └── run.py
```

## Ownership and dependency rules

| File or area | Owns | Must avoid |
| --- | --- | --- |
| main.py | Application factory, lifespan, routes, CORS | Query or prompt logic |
| config.py | Validated environment settings | Logging secrets |
| api/chat.py | HTTP parsing, response conversion | Direct model or database calls |
| api/schemas.py | Public request and response models | LangGraph internals |
| services/chat_service.py | Load context, initialize state, invoke graph, persist turn | Implementing node decisions |
| agent/contracts.py | Model outputs, business plan, execution contracts | HTTP behavior |
| agent/state.py | Shared state passed between nodes | Database sessions |
| agent/graph.py | Node registration, conditional edges, compilation | Business formulas |
| agent/routing.py | Pure functions selecting edges | LLM calls |
| agent/nodes | Small workflow steps | Creating provider clients on every request |
| services/llm.py | Provider adapter, structured outputs, model timeouts | SQL execution |
| services/conversations.py | Conversation ownership and bounded context | Global shared history across users |
| database/connection.py | Pool lifecycle and connection configuration | Prompt construction |
| database/schema.py | Allowlisted schema descriptions and cache | Exposing secrets or arbitrary row samples |
| database/queries.py | Read-only execution and result normalization | Model calls |
| business/metrics.py | Metric definitions, prerequisites, allowed grouping | Provider-specific code |
| business/periods.py | Deterministic period resolution and comparisons | Guessing dates from model knowledge |
| guardrails | Input checks and SQL safety policy | Rewriting business intent |

Dependency direction: API → chat service → graph → nodes → supporting services. Supporting services do not import API routes or graph construction. Inject model and database dependencies when constructing the graph so tests can substitute fakes.

# Request lifecycle

1. POST /api/chat validates the public request and applies input checks. Reject invalid input before model calls.

2. Resolve the authenticated owner when available and load only that owner's conversation. An arbitrary conversation ID must never reveal another conversation.

3. Read the server clock once. Add the configured business timezone, currency, and data capabilities to the invocation context.

4. Initialize fresh per-turn state. Load recent messages and a pending clarification or previous resolved plan, but never reuse previous SQL, rows, errors, or retry counters.

5. Invoke the compiled graph with an overall deadline and a graph step limit.

6. Convert final state to ChatResponse. Save the user turn, assistant turn, and updated context. Report persistence failures separately from calculation success.

7. Return the response. A clarification ends this invocation; the next user reply starts a new invocation with pending context.

For a local single-user version, use a bounded in-memory conversation repository behind an interface and document that restart clears history. Introduce durable storage before relying on history across deployments or multiple workers. Serialize turns per conversation or use a version check to prevent simultaneous turns from overwriting context.

# Public API contract

POST /api/chat accepts:

```json
{
  "message": "Compare revenue this month with last month",
  "conversation_id": null
}
```

Use a nonempty message with a proposed maximum length of 4000 characters. Generate a conversation ID server-side for a new conversation. Do not accept database credentials, raw system prompts, or client-provided ownership as authoritative request fields.

ChatResponse contains:

| Field | Meaning |
| --- | --- |
| conversation_id | Server-issued conversation reference |
| status | answer, clarification, or error |
| message | User-facing explanation |
| context | Metric, current period, comparison period, timezone, and applied assumptions |
| data | Optional bounded columns and rows |
| chart | Optional validated ChartConfig |
| warnings | Safe notices about truncation, missing periods, or unavailable measures |
| request_id | Diagnostic reference without secrets |

Use a completed clarification as a successful conversational response. Return ordinary validation errors for malformed input; use appropriate rate-limit and service-unavailable HTTP statuses for transport or service failures. A handled analytical failure should have status error and a safe explanation. Define these mappings once in chat_service and API response handling.

GET /health reports process readiness without revealing configuration. A database readiness check uses a lightweight connection probe and reports only safe availability information. Keep existing frontend routes available through an adapter during migration. Add SSE after the non-streaming contract is stable.

# Shared state and typed contracts

Use Pydantic models for boundaries and a TypedDict for LangGraph state. Nodes return only changed state fields.

| State field | Purpose |
| --- | --- |
| question | Current original message |
| history | Bounded recent user and assistant messages |
| prior_plan | Last business plan or pending clarification context |
| clock_context | Current date, business timezone, currency |
| decision | Validated RouterDecision |
| plan | Resolved BusinessPlan for a business query |
| sql_draft | SQL text and named parameters |
| execution | ExecutionResult or null |
| repair_count | Number of repair generations already requested |
| failure | Safe code, stage, and message for a terminal failure |
| final | Final answer payload |
| events | Optional public step events |

Overwrite decision, SQL, execution, and failure fields instead of accumulating old values. If events use an additive reducer, nodes return only new events. Do not store connections, provider clients, exceptions, or credentials in state.

## RouterDecision

Use route as a Literal: general_chat, needs_clarification, business_query, or cannot_answer. Include normalized_question, metric_id, period_request, comparison, granularity, allowlisted filters, and optional clarification_question or response_hint.

Keep route-specific requirements explicit. A business route requires a supported metric and resolvable period. A clarification route requires a question. Reject inconsistent outputs rather than falling back silently to a business query.

## BusinessPlan

Store resolved metric_id, exact current and comparison date boundaries, granularity, filters, metric definition version, and disclosed assumptions. Use inclusive start and exclusive end boundaries.

For the initial release, support one primary metric per query with associated component values such as revenue and COGS. Ask the user to narrow unrelated multi-metric requests rather than silently dropping part of the question.

## SQLDraft and ExecutionResult

SQLDraft contains one SQL statement, named parameters, and expected result column names. Bind parameter values through the driver; do not interpolate values into SQL.

ExecutionResult has status success, sql_error, blocked, or infrastructure_error, plus rows, columns, row_count, duration_ms, truncated, and optional safe error code and message. An empty rows list with status success remains successful.

Business arithmetic should preserve decimal precision until serialization. Normalize dates and identifiers consistently. Use exact decimal strings for table amounts where needed and a documented numeric conversion for chart plotting.

# Router implementation

The Router is an LLM classification and planning step. It does not generate SQL.

Build its prompt from supported metric descriptions, available data capabilities, documented defaults, the current question, and bounded conversation context. Avoid sending raw customer records. Treat conversation content as untrusted input.

Resolve periods in business/periods.py using a structured period request from the Router. For example, previous_calendar_month is resolved by Python from the server clock. The Router may interpret language; Python owns exact boundaries.

Routing examples:

| Input | Route | Plan or response |
| --- | --- | --- |
| Hello | general_chat | Brief conversational response |
| What can you do | general_chat | Describe supported analytics |
| Revenue last month | business_query | Revenue and previous calendar month |
| And last year | business_query when context exists | Inherit metric and filters, replace period |
| Show profit | needs_clarification when no default applies | Ask for gross or net profit and missing period |
| Net profit without expenses | cannot_answer | Explain missing expense data |
| Send a campaign | cannot_answer in this release | Explain that action sending is unavailable |

Call the provider through services/llm.py and validate RouterDecision. Allow one formatting retry for invalid structured output. This retry is separate from SQL repairs. If the provider remains unavailable or output remains invalid, record a terminal failure and route to Answer's deterministic fallback.

Questions awaiting clarification must preserve the earlier intent. A reply such as “gross margin for last month” should complete the pending request. Reassess the combined context; do not blindly append the reply to SQL.

The deterministic edge after Router sends only a valid business plan to SQL Generator. All other decisions go to Answer.

# SQL Generator implementation

Load the schema from the server-controlled allowlist. Include table relationships, column types, grain, and metric definition in the prompt. Document whether sales rows represent orders or order lines; join mistakes depend on that distinction.

Generate aggregate calculations in PostgreSQL. Include exact resolved period boundaries and parameter values. Request expected column names so Answer and chart construction have a stable result shape.

Initial generation inputs are BusinessPlan, schema, and metric definitions. Repair generation adds previous SQL, bound parameters, and the latest sanitized execution error. Use the same metric and dates on repair.

Keep the prompt explicit: one read-only query, allowed objects only, bound values, correct aggregation grain, no invented columns, and no changing the question to make a query run.

A provider or structured-output failure becomes a terminal generation failure after its bounded formatting retry. It must not create an execution attempt with an empty query.

On each repair entry, increment repair_count before the model call. Clear stale execution and failure fields when preparing a new execution, while passing the previous sanitized error into generation.

# SQL Executor implementation

SQL Executor uses Python and the database driver without an LLM.

1. Validate SQL syntax and safety using an appropriate PostgreSQL-aware parser plus policy checks. Do not rely on substring filtering alone.

2. Permit a single approved read-only statement. Reject mutation, multiple statements, disallowed schemas, locking forms, and dangerous or unapproved functions under the policy.

3. Apply the result limit policy while preserving aggregate semantics. Never cap source rows before a business total is calculated.

4. Acquire a pooled connection and begin a read-only transaction before executing generated SQL.

5. Set a local statement timeout, bind parameters, execute, and collect bounded results.

6. Normalize values and return ExecutionResult. Roll back and release connections reliably on all paths.

The database role must have only the required read privileges. Read-only transactions do not by themselves prevent every unsafe function or external side effect; database privileges and the SQL allowlist remain necessary.

Use a proposed display default of 50 rows and maximum of 100. Fetch one extra allowed display row when appropriate to detect truncation; never use that display sample as the basis for complete business metrics. Five yearly aggregate rows can represent millions of source sales without source truncation.

Classify errors with driver codes rather than fragile message matching:

| Outcome | Action |
| --- | --- |
| Success including empty results | Answer |
| Undefined column or relation, syntax or grouping error | Repair if budget remains |
| Safety-policy rejection | Terminal safe refusal |
| Connection, credentials, or service unavailable | Terminal service failure |
| Statement timeout | Terminal timeout in the first release |
| Unknown execution error | Terminal safe failure with diagnostic logging |

Log request ID, stage, timing, outcome, and repair count. Keep credentials, raw customer records, and unsanitized errors out of public responses.

# Graph assembly and retry rules

Register exactly router, sql_generator, sql_executor, and answer. Connect START to router and answer to END.

```text
START -> router
router -- business plan --> sql_generator
router -- other outcome --> answer
sql_generator -- draft ready --> sql_executor
sql_generator -- failed --> answer
sql_executor -- success --> answer
sql_executor -- repairable and repair_count < 2 --> sql_generator
sql_executor -- all other outcomes --> answer
answer -> END
```

Compile once per application dependency configuration. Keep edge functions in routing.py pure and independently testable.

Retry sequence: initial generation uses repair_count zero; first repair sets it to one; second repair sets it to two. A third execution failure ends the turn. Never reset the counter after execution. Validate every repaired query through the same SQL guard.

Use an overall graph step ceiling such as 16 as a secondary safety limit. Also enforce a request deadline and bounded model calls. If using async routes, use an async-compatible database service or explicitly offload synchronous database work; do not block the event loop.

This diagram includes only runtime error correction. There is no semantic Query Validator branch in the initial release.

# Answer implementation

For general_chat, the Answer node may use the model to produce a short conversational reply. For clarification, return the validated clarification question directly. For cannot_answer and service failures, prefer deterministic safe messages.

For analytics, give the model the BusinessPlan, metric definition, complete aggregate results or explicitly labeled display sample, and warnings. Require it to explain the returned values without recomputing or fabricating them.

Validate optional chart output against an enum of supported chart types and actual result column names. Use a line chart for a time series and a bar chart for category comparisons. If chart configuration is invalid, omit it and retain the table and explanation.

If answer generation fails after a successful query, return a deterministic summary with the table, selected metric, and period. Do not discard correct data solely because narrative generation failed.

Empty results should produce “No matching data for this period” where appropriate, not zero revenue by assumption. Aggregate queries may legitimately return a row with null values; define its interpretation in the metric catalog.

Show metric definition, period, comparison basis, and material assumptions. Expose step labels such as “Preparing query” and “Calculating results”; do not expose hidden reasoning.

# Business calculations and date policies

Create a MetricDefinition catalog with ID, plain-language meaning, formula, prerequisites, aggregation grain, unit, null behavior, supported groupings, and default comparison policy. Catalog entries must be mapped to the actual database schema before the metric is enabled.

| Metric | Required data and calculation |
| --- | --- |
| Revenue | Net eligible sales after explicitly defined refunds, discounts, and tax treatment |
| Order count | Distinct eligible orders, not order-line count |
| Average order value | Net eligible revenue divided by eligible order count |
| Gross margin | Sum of net revenue minus summed historical COGS, divided by summed net revenue, times 100 |
| Revenue growth | Current revenue minus comparable prior revenue, divided by prior revenue, times 100 |
| Five year trend | Revenue grouped into five completed calendar years, with annual growth |
| Net profit | Revenue minus COGS and applicable expenses; unavailable without expenses |

Calculate overall margin from totals rather than averaging individual row percentages. Prevent duplicated revenue or costs when joining order-level and line-level data. Treat zero denominators as undefined. A positive-growth calculation against a negative baseline requires an explicit business interpretation; do not label it unconditionally as improvement.

Use the configured business timezone. Default to calendar years and state that assumption; fiscal years require explicit configuration. “Last month” means a completed calendar month. “This month versus last month” defaults to equivalent elapsed periods, capped to valid calendar dates. “This year versus last year” uses an aligned year-to-date comparison. A request for five years should state whether it uses five complete years or a rolling window.

Distinguish unavailable history from zero sales. Add historical costs and refund fixtures before enabling profit claims. Never invent expenses or silently convert revenue into profit.

Illustrative margin example: revenue 100000 and COGS 60000 gives gross profit 40000 and gross margin 40 percent. These are test fixture values, not actual business results.

# Configuration and operations

Proposed application settings:

| Setting | Purpose |
| --- | --- |
| DATABASE_URL | Secret connection string for the read-only role |
| LLM_PROVIDER | Selected provider adapter |
| LLM_API_KEY | Secret key consumed by that adapter |
| ROUTER_MODEL | Router model identifier |
| SQL_MODEL | SQL generation and repair model identifier |
| ANSWER_MODEL | Answer model identifier |
| BUSINESS_TIMEZONE | Default Asia/Kolkata for this deployment |
| BUSINESS_CURRENCY | Default INR when the dataset uses INR |
| CORS_ORIGINS | Explicit allowed frontend origins |
| SQL_TIMEOUT_MS | Proposed 5000 millisecond statement timeout |
| MAX_SQL_REPAIRS | Two |
| QUERY_DEFAULT_ROWS | Fifty displayed rows |
| QUERY_MAX_ROWS | One hundred displayed rows |
| SCHEMA_CACHE_TTL_SECONDS | Proposed 3600 second metadata cache lifetime |

Use separate model-call and overall request timeouts, tuned from measurements. Three model settings may point to the same model initially.

Keep .env.example free of secrets. Validate required settings at startup, create provider clients and the pool during lifespan, and close them at shutdown. Exclude secrets and generated artifacts from Git. Document settings and deployment command changes.

Record per-node duration, provider latency, repair count, and request outcome. Treat sensitive SQL and data as restricted diagnostic material. Separate liveness from dependency readiness and avoid unsupported latency claims.

# Verification plan

Fast tests run without paid model calls or production database access. Inject fake structured model responses and an isolated test database. Live-provider evaluations run separately and report quality metrics without making ordinary CI nondeterministic.

| Test | Expected outcome |
| --- | --- |
| Greeting | Answer, zero SQL calls |
| Missing period with no default | Clarification, zero SQL calls |
| Follow-up after clarification | Complete earlier business plan |
| Invalid RouterDecision | Bounded formatting retry, then safe failure |
| Correct revenue query | Exact expected fixture amount |
| Missing column on first execution | Generator receives failed SQL and sanitized error |
| Three failed executions | Exactly two repair generations, then END |
| Blocked mutation | No generated SQL executed |
| Empty result | Success with no-data response |
| Database outage | No repair model call |
| Answer model outage | Verified result returned through fallback |
| Monthly and yearly comparisons | Correct aligned boundaries including leap years |
| Margin across unequal sales | Ratio of sums, not mean of percentages |
| Order-line join | No duplicated order totals |
| Two conversations | No cross-conversation state leakage |
| Truncated display | Warning and no claim that sample is the total |

Store evaluation cases with question, expected route, expected plan, and expected numeric results. Equivalent SQL strings may differ; judge by behavior and results. Include cases where executable SQL gives the wrong metric to measure the remaining semantic risk.

Run uv sync and uv run pytest. Verify startup and health, then exercise the public chat endpoint against fixtures. When the frontend is switched, run pnpm lint and pnpm build and verify successful answer, clarification, and failure rendering.

# Build milestones and replacement

## Milestone 1 Contracts and Router

Create application configuration, API schemas, graph state, RouterDecision, BusinessPlan, metric catalog, period resolver, and fake LLM adapter. Deliver a working user question to Router path for greetings, business questions, and clarification. Acceptance requires deterministic routing tests and correct follow-up context.

## Milestone 2 Database boundary

Implement the pool, schema allowlist, SQL guard, read-only executor, error classification, and fixture database. Acceptance requires blocked writes, correct aggregate values, and reliable connection cleanup.

## Milestone 3 SQL loop

Implement SQL generation and bounded correction. Wire graph edge functions and verify one initial attempt plus two repairs. Terminal failures must end cleanly.

## Milestone 4 Answer and API

Implement narrative generation, deterministic fallbacks, tables, chart validation, and response persistence. Verify a full API request for sales, margin, and growth.

## Milestone 5 Migration

Develop the replacement in an isolated branch or temporary package without importing the old node implementations. Preserve the old backend until acceptance checks pass. Keep a recoverable Git version before removing superseded tracked files.

After cutover, remove duplicate orchestration and the obsolete separate healing, stats, and email branches from the active backend. Rewrite useful test cases against the new contracts. Preserve required protections through fresh implementation and independent tests.

Update frontend adapters, README, AGENTS, architecture specs, CI, and container entry points together. Remove unused packages only after import checks. Do not delete secret files or unrelated work as part of code cleanup.

The four-node backend is implemented in `backend/app/agent/graph.py`. The superseded node implementations and orchestration modules have been removed; historical evaluation datasets and reports remain as reference. The current frontend uses the SSE compatibility endpoint and server-issued conversation IDs.

Business metrics start disabled until `ENABLED_METRICS` and `METRIC_SCHEMA_NOTES` map them to the actual database. Current-month and current-year comparisons use completed days only and exclude today. Session history is bounded in memory and requires a single process; cookies identify history ownership rather than business authorization. See `README.md` and `backend/.env.example` for operational setup.

## Later phases

Add semantic Query Validator, broader metric coverage, durable conversation storage if not already needed for deployment, SSE streaming, and separately scoped action drafting. Add nodes only when a new workflow responsibility requires them.

# DataPilot Jev Router and Analytics Delivery Specification

## Purpose

Connect TypeSafe Jev to DataPilot's Router, then verify the complete business-question path through SQL Generator, SQL Executor, and Answer. Keep the four-node design agreed in [spec 05](05_backend_rebuild_implementation.md). A separate SQL repair node and a semantic Query Validator remain out of scope.

This is an implementation plan. No Jev client or provider configuration is added by this document, and no new API key is tested or exposed.

## Current implementation

The Router already exists. All four nodes also exist and are connected in `backend/app/agent/graph.py`. The next work is integrating Jev and validating the existing analytics path against the actual dataset, rather than recreating those nodes.

| Component | Current file | Current behavior | Work to do |
| --- | --- | --- | --- |
| Router | `app/agent/nodes/router.py` | Uses the configured generative model for intent and planning; resolves periods in Python | Add Jev classification and confidence handling; retain planning for business questions |
| SQL Generator | `app/agent/nodes/sql_generator.py` | Generates SQL from plan/schema; receives failed SQL for repair | Verify model output, real schema mappings, and repair behavior with the selected provider |
| SQL Executor | `app/agent/nodes/sql_executor.py` | Offloads execution to the Python database service | Verify read-only privileges, connectivity, parameters, and actual business results |
| Answer | `app/agent/nodes/answer.py` | Explains results with deterministic clarification/error fallbacks | Verify numerical grounding through known-answer cases and chart compatibility |
| Provider adapter | `app/services/llm.py` | Supports Groq and Google for generative calls | Add a separate Jev decision adapter; preserve generation providers |
| Settings | `app/config.py` | No TypeSafe/Jev settings or provider selection | Add explicit routing settings and secret loading |

The current configuration accepts only `groq` or `google` as `LLM_PROVIDER`. Unknown environment fields are ignored. Consequently, putting a Jev key in `.env` does not currently connect the Router to Jev.

## Model responsibilities

Use Jev to choose among predefined routes. Its Choice primitive returns a selected option, option probabilities, and a confidence value. The HTTP API accepts `state`, `questions`, and a model identifier. See the official [Choice contract](https://docs.typesafe.ai/primitives/choice) and [System One API](https://docs.typesafe.ai/api/system-one).

Our design keeps SQL and narrative generation with Groq or Google. Jev will not be asked to return arbitrary SQL or invent a complete free-form `BusinessPlan`. A classification label alone cannot supply arbitrary customer IDs, date boundaries, or metric formulas.

For the first integration, retain the existing structured planning model call inside the Router for business questions. This keeps the interface to SQL Generator stable. Jev classification and business-plan extraction are two internal operations in one graph node, not two new graph nodes.

This design adds a Jev call to business requests. Do not claim lower end-to-end latency until measured. Confident general-chat and unsupported routes can avoid the business-planning call. Combining plan extraction and SQL generation can be evaluated later, after the clear staged design works.

## Target graph

```text
User question and bounded conversation context
                      |
                Input checks
                      |
               1. Router
               Jev classification
                      |
       +--------------+----------------+----------------+
       |              |                |                |
  General chat    Unclear intent    Unsupported     Business query
       |              |                |                |
       |        Clarification          |        Structured plan extraction
       |        from code template     |        with generation model
       |              |                |                |
       |              |                |        Python resolves dates
       |              |                |                |
       |              |                |      Plan complete and supported?
       |              |                |        |               |
       |              |                |       No              Yes
       |              |                |        |               |
       +--------------+----------------+--------+       2. SQL Generator
                      |                                         |
                      |                                 3. SQL Executor
                      |                                  Python only
                      |                                         |
                      |                  +----------------------+---------------+
                      |                  |                      |               |
                      |               Success             Fixable error    Terminal failure
                      |                  |                      |               |
                      |                  |                SQL Generator         |
                      |                  |                then Executor         |
                      |                  |               at most 2 repairs      |
                      +------------------+--------------------------------------+
                                         |
                                    4. Answer
                                         |
                                        END
```

A clarification returns to the user and ends the current invocation. A subsequent user reply starts a new invocation with the pending context. The graph never waits indefinitely for a reply.

## Jev integration boundary

### Client and configuration

Use the official asynchronous Python client behind `app/services/jev.py`. The documented package is `typesafe-sdk`, installed with `uv add typesafe-sdk`; the SDK documents `AsyncTypeSafeClient`, `Choice`, and `system_one`. Its standard secret variable is `TYPESAFE_API_KEY`. See the [Python SDK documentation](https://docs.typesafe.ai/sdk/python).

Proposed application settings, to be implemented:

| Setting | Purpose | Proposed behavior |
| --- | --- | --- |
| `ROUTER_PROVIDER` | Select decision backend independently of generation | `jev` or `llm`; retain `llm` for explicit rollback |
| `TYPESAFE_API_KEY` | Jev authentication secret | Required when `ROUTER_PROVIDER=jev`; use `SecretStr` |
| `JEV_MODEL` | Requested decision model | Start with documented `jev-latest`; record resolved model and pin a tested version for deployment |
| `JEV_MIN_CONFIDENCE` | Routing acceptance threshold | Start with 0.70 as a project policy; tune using labeled questions |
| `JEV_TIMEOUT_SECONDS` | Upper bound on a classification call | Initial budget 5 seconds; measure and adjust |
| `LLM_PROVIDER` | Generative provider | Remains `groq` or `google` |
| `ROUTER_MODEL` | Existing generative business planner | Retain initially; document that it extracts the plan after Jev selects a business route |
| `SQL_MODEL` / `ANSWER_MODEL` | SQL and narrative generation | Remain independently configurable |

The key name must match the application's implemented settings. Do not silently assume an arbitrary variable such as `JEV_KEY` is consumed. Never print key values to check their presence.

Construct the async Jev client once during FastAPI lifespan, inject it into graph construction, and close it on shutdown. Verify constructor and retry arguments against the installed SDK version before coding; keep all SDK-specific response access inside the adapter.

Authentication errors should identify missing or invalid routing configuration without including credentials. Do not retry 401/403 responses. Permit at most one bounded retry for transient connection, 429, or 5xx failures when the remaining request deadline permits it. Configure SDK retries explicitly so layered retry policies cannot multiply attempts.

### Classification input

Send the current question, bounded recent conversation, pending clarification, previous business-plan summary, supported capabilities, and brief route descriptions. Do not send raw database rows, credentials, full history, or the complete relational schema to the classifier.

Classify with one named Choice question such as `intent`:

| Choice | Meaning | Destination |
| --- | --- | --- |
| `general_chat` | Greeting, identity, help, capabilities | Answer |
| `business_query` | A request to analyze the connected business data | Business planning inside Router, then SQL Generator if complete |
| `needs_clarification` | Intent cannot be resolved from the message and context | Answer with a focused clarification |
| `cannot_answer` | Unsupported action or request outside available capabilities | Answer with a safe explanation |

An understandable analytics question can still have missing parameters. For example, “Show profit” is a business intent but may require the planner to clarify gross versus net profit and the period. Jev's classification does not replace plan completeness checks.

The official API supports intent-routing patterns; our application remains responsible for selecting and invoking the next handler. See [TypeSafe intent routing](https://docs.typesafe.ai/patterns/intent-routing).

### Classification output and confidence

Add a local `IntentClassification` model containing `route`, `confidence`, `probabilities`, and `model`. Verify route membership, finite values between zero and one, expected probability keys, and a probability sum within numerical tolerance. Normalize the SDK response into this contract before the graph reads it.

Do not equate confidence with the probability that the route is correct. TypeSafe derives confidence from the distribution across choices; it is a useful uncertainty signal, not a correctness guarantee. Our 0.70 threshold is a proposed application policy, not a vendor accuracy claim. See [confidence semantics](https://docs.typesafe.ai/confidence).

- At or above threshold: use the classification, then apply normal capability and plan checks.
- Below threshold: return a deterministic clarification. Do not execute SQL.
- Invalid/missing answer or exhausted API retry: return a safe routing-service failure. Do not execute SQL.
- `ROUTER_PROVIDER=llm`: use the explicitly configured legacy classification/planning path for rollback. Do not silently switch providers after an error.

Jev is not a security boundary. Keep deterministic input checks, SQL safety validation, restricted privileges, and read-only execution regardless of confidence.

## Router implementation changes

1. Add the injected decision service to Router dependencies.
2. When routing through Jev, invoke the adapter and validate `IntentClassification`.
3. Map confident non-business labels to the existing `RouterDecision` contract using the original question as `normalized_question` and code-owned response templates.
4. For a confident business label, invoke the existing structured planner with question, context, metric definitions, and server clock. This call fills metric, period request, comparison, granularity, and allowlisted filters.
5. Validate the planner's output. It can return clarification or unavailable-data outcomes, but it must not write SQL in this stage.
6. Resolve exact date boundaries with `business/periods.py`. Check the chosen metric against configured capabilities and mappings.
7. Return `decision`, optional `plan`, and a short public event. Keep confidence/probabilities as internal metadata; do not expose hidden model reasoning.

Preserve `after_router`: only a supported, complete business plan reaches SQL Generator. No plan means Answer.

## SQL Generator delivery

The node already exists. Complete its provider and dataset verification after Jev routing is working.

Inputs are the validated `BusinessPlan`, allowlisted schema with relationships, metric definitions, mapping notes, and optional previous SQL plus sanitized execution error. The schema service must describe actual columns and row grain; examples are not production mappings.

Return the existing `SQLDraft`: one SQL statement, bound parameters, and expected result columns. Use named parameters for dates and filters. Aggregate over all eligible rows before applying output display limits. Prevent order-level amounts from multiplying when joined to order lines.

On initial generation, no prior execution error is supplied. On a repair, preserve the same plan and receive the failed SQL, parameters, safe error code, and explanation. Never change the metric or dates just to produce executable SQL.

Generation/format errors have their own bounded provider handling. They do not count as additional database executions. A terminal generation failure goes to Answer without executing an empty or stale statement.

## SQL Executor delivery

This node uses Python and the driver, with no Jev or generative-model call. Keep the existing parser policy and execution service.

Validate one approved read-only statement, business-table access, function/type restrictions, named bindings, and output limits. Execute with a dedicated SELECT-only database role, a read-only transaction, local timeout, business timezone, and safe search path. Release connections on every outcome.

Return the existing `ExecutionResult` with status, rows, columns, duration, truncation metadata, and safe error details.

| Result | Next step |
| --- | --- |
| Successful rows or successful empty result | Answer |
| Repairable SQL error with repair budget remaining | SQL Generator |
| Repair budget exhausted | Answer with failure |
| Policy rejection | Answer with safe refusal |
| Database outage, credentials failure, timeout, unknown infrastructure error | Answer with safe service failure |

Allow one initial execution plus two repair executions. Do not route repairs through Jev again, and never reset the counter within a turn. Validate every corrected query through the same executor policy.

Successful execution still does not establish that SQL answers the intended business question. The semantic Query Validator is deferred; known-answer evaluations must cover that remaining risk.

## Answer delivery

Reuse the existing node and generation adapter. General chat may use the answer model. Clarification and unsupported/failure paths use predictable code-owned text when possible.

For analytics, supply the plan, metric meaning, actual returned values, period, and warnings. The database calculates numbers; the answer model explains them. Preserve the table if narrative generation fails.

Validate charts against supported types and actual result columns. Keep decimal strings exact in tables and convert only for plotting. Unknown values stay null, not zero. Label current-period comparisons and truncation in the user-visible answer.

Keep the current SSE step/done response and conversation ID behavior. Do not add a new frontend protocol merely to expose the routing provider.

## Business examples

| Question | Router and planning | SQL calculation | Answer |
| --- | --- | --- | --- |
| Hello | Jev selects general chat | None | Greeting and supported capabilities |
| Show profit | Business intent; planner clarifies definition/period | None until complete | Focused clarification |
| Gross margin last month | Gross margin and completed previous month | Ratio of summed profit to summed revenue using historical costs | Revenue, cost, profit, margin and period |
| This month versus last month | Revenue comparison; equivalent completed-day policy | Current/prior totals and percentage change | Change, baseline, and exclusion of today |
| This year versus last year | Resolved aligned yearly periods | Comparable totals and percentage change | Year-to-date comparison with dates |
| Growth over five years | Five completed calendar years unless user specifies otherwise | Annual revenue and annual changes | Trend explanation and line chart |

Gross margin requires historical cost; net profit also requires expense data. A missing capability produces an explanation rather than invented numbers. Mapping notes must establish discount, tax, refund, cancellation, and aggregation rules before a metric is enabled.

## File structure and changes

```text
backend/app/
├── config.py                       # Add independent Jev routing settings
├── main.py                         # Create/close Jev client and inject dependencies
├── agent/
│   ├── contracts.py                # Add IntentClassification; retain existing contracts
│   ├── state.py                    # Optional internal classification metadata
│   ├── graph.py                    # Inject decision service; keep four nodes
│   ├── routing.py                  # Pure conditional edges
│   ├── nodes/
│   │   ├── router.py               # Jev classification and business planning
│   │   ├── sql_generator.py        # Generation and repair
│   │   ├── sql_executor.py         # Python execution boundary
│   │   └── answer.py               # Explanation and safe fallbacks
│   └── prompts/                    # Business planner, SQL and answer instructions
├── services/
│   ├── jev.py                      # New asynchronous TypeSafe adapter
│   ├── llm.py                      # Existing generative adapter
│   ├── chat_service.py             # Context, deadlines and response conversion
│   └── conversations.py            # Bounded isolated history
├── business/                       # Metric definitions and Python date policies
├── database/                       # Schema discovery, pool and read-only queries
└── guardrails/                     # Independent input and SQL safety
```

Keep `app/agent/` as the only workflow package. Do not recreate `app/agents/`. Reusable test doubles belong in `tests/helpers.py`, with pytest fixtures in `tests/conftest.py` and package-relative test imports.

Also update `backend/.env.example`, dependency declarations/lockfile, README, and the active architecture instructions when implementing these changes. Do not copy real keys into templates or specs.

## Phased implementation and acceptance

### Phase 1 Jev adapter

Add the SDK with uv, typed settings, adapter, lifecycle management, and mocked API tests. Confirm response shape against the installed SDK and authenticated model availability. Test invalid labels, malformed probabilities, low confidence, authentication failure, transient errors, and timeouts. Normal tests make no external calls.

### Phase 2 Router integration

Inject Jev into the existing Router. Keep the business planner and deterministic dates. Test general chat, business requests, incomplete questions, unsupported actions, and follow-ups. Assert zero database calls for non-business, low-confidence, and failed-classification paths. Assert that business planning is skipped for confident chat.

### Phase 3 Actual schema and SQL

Confirm connectivity through the read-only account and document actual mappings. Enable metrics only after those mappings are complete. Verify the existing generator/executor against known sales, costs, refunds, and order-line fixture cases. Check recoverable failures and exactly two repair attempts. Repair must never repeat intent classification.

### Phase 4 Answer and workspace

Verify explanation, table, chart, clarification, and failure rendering through the existing SSE endpoint. Check a conversation follow-up and reload, with fixtures and deterministic model doubles before provider calls.

### Phase 5 Live evaluation

Use a separate explicit live-evaluation command for paid API calls. Verify the configured Jev key with a minimal non-sensitive classification, then run labeled routing cases. Confirm the selected generative provider separately; a Jev key does not authenticate Groq or Google.

Report route accuracy, clarification rate, invalid-output rate, and latency distributions from measurements. Evaluate SQL results against known expected numbers, not SQL string equality. Do not advertise speed or accuracy guarantees based solely on adding Jev.

Use `uv sync` and `uv run pytest`; run database tests only against an isolated `_test` database. Apply frontend lint/build and browser checks if response behavior changes. Preserve unrelated work, existing secrets, and all SQL safety controls.

## Completion criteria

- Jev is genuinely invoked when selected, and the generation provider remains separate.
- The configured key is consumed without exposure; missing credentials fail clearly.
- Ambiguous or failed classifications cannot trigger SQL.
- Valid business plans reach the existing SQL Generator and Executor.
- Runtime SQL repair uses the same generator and stops after two repairs.
- Profit and growth fixture values match expected calculations.
- Chat, clarification, table, chart, and failure outcomes retain frontend compatibility.
- Exactly four graph nodes remain, with no semantic Query Validator added.

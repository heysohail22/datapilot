> Superseded by [05 Backend Rebuild Implementation](05_backend_rebuild_implementation.md). Retained as historical design context.

# 📋 Spec 01: Foundation Layer (Tools Suite, Caching Layer & Agent State)

> **Module 01 of DataPilot Architecture**  
> *Scope: Core tool suite (excluding CSV ingestor), in-memory TTL caching, and AgentState definition.*

---

## 🎯 1. Objective & Scope

Establish the fundamental backend primitives required for DataPilot's agentic workflow:
1. **In-Memory Caching (`backend/app/cache.py`)**: Sub-millisecond TTL cache for schema introspection and exact query responses.
2. **Dedicated Tools Suite (`backend/app/tools/`)**:
   - `db_tool.py`: Read-only, paginated, timeout-protected PostgreSQL execution.
   - `schema_tool.py`: Schema introspection with sample distinct values per column.
   - `python_tool.py`: Sandboxed Python calculation engine for advanced business analytics (Profit Margins, Churn Rates, MoM Growth, Inventory Burn Rate).
   - `email_tool.py`: Business action drafter generating structured VIP win-back, payment failure, or restock campaign drafts with human approval flags.
   *(Note: `ingest_tool.py` / CSV ingestion is intentionally deferred).*
3. **Agent State Contract (`backend/app/agents/state.py`)**: Complete `AgentState` TypedDict definition bridging messages, intent, SQL context, metrics, actions, and UI thought traces.
4. **LLM Service Refactoring (`backend/app/llm_service.py`)**: Update service layer to consume the new tools, caching, and state model.

---

## 🧱 2. File Layout & Responsibilities

```text
backend/app/
├── cache.py                  # Schema & query cache with TTL & thread safety
├── agents/
│   ├── __init__.py
│   └── state.py              # AgentState TypedDict definition
├── tools/
│   ├── __init__.py
│   ├── db_tool.py            # Read-only query execution & row sanitization
│   ├── schema_tool.py        # Schema introspection + sample values
│   ├── python_tool.py        # Sandboxed statistics & business math calculations
│   └── email_tool.py         # Business action email/campaign drafter
└── llm_service.py            # Orchestrator integrating tools, cache, and state
```

---

## 🧰 3. Tool Specifications

### 3.1. `db_tool.py` — Database Query Tool
* **Function**: `execute_db_query(sql_query: str, max_rows: int = 100) -> Dict[str, Any]`
* **Features**:
  - Enforces `SET TRANSACTION READ ONLY` & `5000ms` statement timeout.
  - Sanitizes `Decimal`, `datetime`, `date`, `UUID` types to JSON-safe Python types.
  - Tracks execution latency in milliseconds.
* **Output Payload**:
  ```python
  {
      "columns": ["customer_id", "total_spend"],
      "rows": [{"customer_id": 1, "total_spend": 45000.0}],
      "row_count": 1,
      "execution_time_ms": 14.2,
      "sql": "SELECT ...",
      "error": None
  }
  ```

### 3.2. `schema_tool.py` — Schema Introspector & Sampler
* **Function**: `get_schema_context(force_refresh: bool = False) -> str`
* **Function**: `inspect_table_samples(tables: List[str]) -> Dict[str, List[Any]]`
* **Features**:
  - Interacts directly with `cache.py` to provide sub-1ms schema returns.
  - Formats tables, columns, data types, foreign key relationships, and distinct sample values (e.g. `customer_segment IN ('vip', 'regular', 'churned')`).

### 3.3. `python_tool.py` — Sandboxed Analytics Engine
* **Function**: `execute_python_stats(metric_name: str, data_rows: List[Dict[str, Any]], custom_code: Optional[str] = None) -> Dict[str, Any]`
* **Supported Prebuilt Statistical Calculations**:
  - `profit_margin`: `(revenue - cost) / revenue * 100`
  - `churn_rate`: `churned_users / total_users * 100`
  - `mom_growth`: Month-over-Month percentage growth series.
  - `inventory_burn_rate`: Days of inventory remaining based on recent sales velocity.
  - `customer_ltv`: Average order value $\times$ purchase frequency $\times$ lifespan.
* **Sandboxing**: Restricts built-ins, blocks file/network access (`os`, `sys`, `subprocess`, `socket`).

### 3.4. `email_tool.py` — Business Action & Campaign Drafter
* **Function**: `draft_email_action(action_type: str, recipient_count: int, sample_recipients: List[Dict[str, Any]], context_data: Dict[str, Any]) -> Dict[str, Any]`
* **Campaign Types**:
  - `vip_winback`: Re-engagement discount offer for lapsed high-value customers.
  - `abandoned_checkout`: Reminder with personalized product name.
  - `restock_po`: Supplier purchase order draft for low-inventory SKUs.
* **HITL Flag**: Always marks `requires_human_approval = True`.

---

## ⚡ 4. Fast Caching Strategy (`cache.py`)

* **`SchemaCache`**: In-memory cache holding the database DDL/schema context string with a default TTL of 1 hour (3600s), invalidable on demand.
* **`QueryCache`**: LRU/dict cache for identical user questions (`hash(normalized_question)`), returning instant cached answers when data freshness allows.

---

## 🧠 5. `AgentState` Definition (`state.py`)

```python
from typing import TypedDict, List, Optional, Dict, Any, Annotated
import operator
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    # Chat & Context
    messages: Annotated[List[BaseMessage], operator.add]
    user_question: str
    
    # Classification & Routing
    intent: str  # "data_query" | "statistical_analysis" | "email_action" | "general_chat"
    thought_process: str
    direct_response: Optional[str]
    
    # Database Context
    tables_used: List[str]
    sql_query: Optional[str]
    query_results: Optional[List[Dict[str, Any]]]
    columns: Optional[List[str]]
    row_count: int
    execution_time_ms: float
    
    # Self-Healing & Error Handling
    error_history: List[str]
    retry_count: int
    
    # Statistical Analytics Context
    computed_metrics: Optional[Dict[str, Any]]
    
    # Business Action Context (HITL)
    action_type: Optional[str]
    action_payload: Optional[Dict[str, Any]]
    requires_human_approval: bool
    is_approved: bool
    
    # Output Synthesis & UI Streaming
    chart_config: Optional[Dict[str, Any]]
    final_response: str
    agent_thought_trace: Annotated[List[str], operator.add]
```

---

## 🧪 6. Verification Criteria

1. Schema retrieval responds in `< 1ms` when cached.
2. `db_tool.py` correctly queries tables and prevents mutating statements.
3. `python_tool.py` executes business metrics calculations on sample dataset without errors.
4. `email_tool.py` generates preview drafts with `requires_human_approval = True`.
5. `llm_service.py` functions seamlessly with the new modular tools and returns structured `ChatResponse`.

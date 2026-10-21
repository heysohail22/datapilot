> Superseded by [05 Backend Rebuild Implementation](05_backend_rebuild_implementation.md). Retained as historical design context.

# DataPilot — Backend Supabase Database Agent Specification

## 1. Purpose & Overview

This document specifies the architecture, data flow, security model, and API contracts for connecting **Supabase PostgreSQL** to the **DataPilot AI Agent**. 

The integration transforms DataPilot into an intelligent **Text-to-SQL Business Analyst** capable of:
1. Understanding the database structure (tables, columns, types, relationships).
2. Translating natural-language business questions into valid PostgreSQL queries using Gemini 2.5 Flash with Pydantic Structured Outputs.
3. Safely executing read-only queries against Supabase via SQLAlchemy.
4. Automatically self-healing/correcting SQL syntax errors if a query fails.
5. Synthesizing raw database results into clear executive summaries with bold metrics.
6. Returning rich structured payloads containing the answer, executed SQL, and raw tabular data to the Next.js frontend.

---

## 2. End-to-End System Architecture

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Frontend as Next.js Frontend
    participant API as FastAPI Router (/api/chat)
    participant Engine as Agent Service
    participant Gemini as Google Gemini 2.5 Flash
    participant DB as Supabase PostgreSQL

    User->>Frontend: "What was our total revenue last month by country?"
    Frontend->>API: POST /api/chat { message }
    API->>Engine: process_query(message)
    Engine->>Engine: Retrieve cached DB Schema
    Engine->>Gemini: Prompt with Schema + Question (Structured Output)
    Gemini-->>Engine: GeneratedSQL { sql_query, thought_process }
    
    Engine->>Engine: Validate SQL (Read-only check & LIMIT check)
    Engine->>DB: Execute SQL in READ ONLY transaction
    
    alt Query Execution Succeeds
        DB-->>Engine: Rows & Columns { data, columns, count }
    else Query Syntax/Execution Error
        DB-->>Engine: Postgres Error
        Engine->>Gemini: Self-Healing Prompt (Schema + Failed SQL + Error)
        Gemini-->>Engine: Corrected GeneratedSQL
        Engine->>DB: Re-execute Corrected SQL
        DB-->>Engine: Rows & Columns
    end

    Engine->>Gemini: Synthesize Answer (Question + SQL + Data)
    Gemini-->>Engine: Natural Language Insight Summary
    Engine-->>API: Rich ChatResponse
    API-->>Frontend: { response, sql, data, columns, execution_time_ms }
    Frontend-->>User: Render Message + "View SQL" + Data Preview Table
```

---

## 3. Database Layer Specification (`backend/app/database.py`)

### 3.1 Connection & Pooling Configuration
- **Driver**: `psycopg2-binary` via SQLAlchemy 2.0.
- **Connection URI**: Stored in `backend/.env` as `DATABASE_URL`.
  - Format: `postgresql+psycopg2://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres`
- **Engine Setup**:
  ```python
  from sqlalchemy import create_engine
  from app.config import settings

  engine = create_engine(
      settings.DATABASE_URL,
      pool_size=5,
      max_overflow=10,
      pool_timeout=30,
      pool_pre_ping=True,  # Automatically detect stale disconnects
  )
```

### 3.2 Schema Introspection & Caching
To keep query generation fast and token-efficient:
1. At application startup (or cached on first request), query PostgreSQL's `information_schema.columns` and `information_schema.table_constraints`.
2. **Schema Filter**: Explicitly exclude internal Supabase schemas:
   - `auth`, `storage`, `graphql`, `realtime`, `vault`, `pg_catalog`, `information_schema`, `supabase_functions`.
3. Format schema into a compact, human-readable prompt string:
   ```text
   Table: customers (id UUID, name TEXT, email TEXT, country TEXT, created_at TIMESTAMP)
   Table: products (id UUID, name TEXT, category TEXT, price NUMERIC, is_active BOOLEAN)
   Table: orders (id UUID, customer_id UUID REFERENCES customers(id), status TEXT, total_amount NUMERIC, created_at TIMESTAMP)
   Table: order_items (id UUID, order_id UUID REFERENCES orders(id), product_id UUID REFERENCES products(id), quantity INT, unit_price NUMERIC)
   ```

### 3.3 Safe Query Execution Routine
```python
def execute_read_only_query(sql_query: str) -> dict:
  """Executes SQL against Supabase in a strict read-only transaction."""
  # AST / Keyword safety validation
  validate_read_only_sql(sql_query)

  with engine.connect() as connection:
    # Enforce read-only at the session level
    connection.execute(text("SET TRANSACTION READ ONLY;"))
    # Set statement timeout to 5 seconds
    connection.execute(text("SET statement_timeout = '5000ms';"))

    result = connection.execute(text(sql_query))
    columns = list(result.keys())
    rows = [dict(row._mapping) for row in result.fetchmany(100)]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
```

---

## 4. AI Agent & LLM Service Layer (`backend/app/llm_service.py`)

### 4.1 Pydantic Structured Output Model
Using LangChain's `.with_structured_output(GeneratedSQL)` ensures Gemini returns clean JSON containing only the SQL query and the reasoning, avoiding markdown parsing issues.

```python
# backend/app/schemas.py
from pydantic import BaseModel, Field


class GeneratedSQL(BaseModel):
  sql_query: str = Field(
      description="The valid, optimized PostgreSQL SELECT query."
  )
  thought_process: str = Field(
      description="Brief explanation of why this query answers the user question."
  )
  tables_used: list[str] = Field(
      default_factory=list, description="List of tables queried."
  )
```

### 4.2 SQL Generation Prompt
- **Model**: `gemini-2.5-flash` (`temperature=0.0` for deterministic SQL).
- **System Instructions**:
  1. You are a senior PostgreSQL database architect and data analyst.
  2. Write **ONLY** standard read-only `SELECT` queries (using `JOIN`, `GROUP BY`, `ORDER BY`, `SUM`, `COUNT`, `AVG`, `DATE_TRUNC`, etc.).
  3. Always qualify ambiguous column names with table names or aliases.
  4. Cast date/timestamp columns properly for comparisons (e.g. `created_at >= NOW() - INTERVAL '30 days'`).
  5. Apply a default `LIMIT 100` if the user's query could return arbitrary rows.

### 4.3 Self-Healing Error Correction
If query execution raises a `SQLAlchemyError` or `ProgrammingError`:
1. Construct a repair prompt containing:
   - Original user question
   - Failed SQL query
   - Exact PostgreSQL error message
   - Database schema
2. Call Gemini to return a corrected `GeneratedSQL` object.
3. Retry execution (maximum 2 retries before returning a clean error to the user).

### 4.4 Answer Synthesis Prompt
Once rows are fetched from Supabase, Gemini synthesizes the natural-language answer:
```python
def synthesize_data_response(
    user_question: str, sql_query: str, rows: list[dict]
) -> str:
  prompt = f"""
    You are DataPilot AI, an executive business intelligence analyst.
    
    User Question: {user_question}
    Executed SQL: {sql_query}
    Query Results: {rows}
    
    Instructions:
    1. Provide a direct, executive answer to the user's question.
    2. Format key monetary values, metrics, and percentages in **bold** (e.g., **$124,500**, **14.2%**, **3,420 users**).
    3. If results are empty, politely state that no matching records were found for that period or condition.
    4. Keep the explanation concise, professional, and clear.
    """
  return llm.invoke(prompt).content
```

---

## 5. Security Guardrails & Safety Policy

| Guardrail | Implementation | Purpose |
| :--- | :--- | :--- |
| **Strict Read-Only Filter** | Regex / Keyword AST check blocking `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`, `EXEC` | Blocks destructive database operations before touching Supabase |
| **Session Read-Only Mode** | `SET TRANSACTION READ ONLY;` in SQLAlchemy session | Enforces read-only guarantee inside PostgreSQL engine |
| **Statement Timeout** | `SET statement_timeout = '5000ms';` | Prevents runaway/expensive analytical queries or locks |
| **Row Limit Enforcement** | Injects `LIMIT 100` if missing; caps `fetchmany(100)` | Protects token context window and memory |
| **Multi-Statement Blocking** | Rejects queries with unquoted semicolons (`;`) | Prevents SQL injection chaining attacks |
| **Schema Isolation** | Ignores `auth.*`, `storage.*`, `secrets` schemas | Prevents exposure of sensitive auth tables & user credentials |

---

## 6. API Schemas & Data Contracts

### 6.1 `POST /api/chat`

#### Request Payload
```json
{
  "message": "Who are our top 5 customers by total order spend?"
}
```

#### Response Payload (Rich Data Contract)
```json
{
  "response": "Our top 5 customers by total spend are led by **Acme Corp** with **$45,200** across 12 orders, followed by **Globex Inc** with **$32,100**.",
  "sql": "SELECT c.name, COUNT(o.id) AS order_count, SUM(o.total_amount) AS total_spend FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name ORDER BY total_spend DESC LIMIT 5;",
  "data": [
    { "name": "Acme Corp", "order_count": 12, "total_spend": 45200 },
    { "name": "Globex Inc", "order_count": 8, "total_spend": 32100 },
    { "name": "Soylent Corp", "order_count": 6, "total_spend": 28400 },
    { "name": "Initech", "order_count": 5, "total_spend": 19500 },
    { "name": "Umbrella Corp", "order_count": 4, "total_spend": 15800 }
  ],
  "columns": ["name", "order_count", "total_spend"],
  "row_count": 5,
  "execution_time_ms": 142,
  "model": "gemini-2.5-flash"
}
```

### 6.2 `GET /api/database/schema` (Utility Endpoint)
Returns the list of detected user tables and columns to allow frontend introspection or admin debugging.

---

## 7. Frontend Integration & UI Enhancements

### 7.1 Updated TypeScript Models (`frontend/types/chat.ts`)
```typescript
export interface QueryDataRow {
  [key: string]: string | number | boolean | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sql?: string;
  data?: QueryDataRow[];
  columns?: string[];
  rowCount?: number;
  executionTimeMs?: number;
}
```

### 7.2 Component Updates (`AssistantMessage.tsx`)
1. **Insight Text**: Renders formatted markdown and highlighted bold numbers.
2. **"View SQL" Accordion**:
   - Collapsible trigger with `<Code2 className="w-3.5 h-3.5 text-[#FEC50B]" />` and `View SQL`.
   - Dark code block (`#181A20`) with syntax formatting and copy button.
3. **Data Preview Mini-Table** (when `data.length > 0`):
   - Horizontal scrollable table with styled header (`#1E222B`), subtle borders (`#2E3444`), and formatted numbers.

---

## 8. Sample Supabase Seed Data (For Immediate Verification)

Execute this SQL snippet in the **Supabase SQL Editor** to create standard business tables and sample data for testing:

```sql
-- 1. Create Tables
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    country TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('completed', 'pending', 'cancelled')),
    total_amount NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Insert Sample Data
INSERT INTO customers (name, email, country, created_at) VALUES
('Acme Corp', 'contact@acme.com', 'United States', NOW() - INTERVAL '90 days'),
('Globex Inc', 'sales@globex.com', 'United Kingdom', NOW() - INTERVAL '60 days'),
('Soylent Corp', 'info@soylent.com', 'Germany', NOW() - INTERVAL '45 days'),
('Initech', 'admin@initech.com', 'United States', NOW() - INTERVAL '30 days'),
('Umbrella Corp', 'ops@umbrella.com', 'Canada', NOW() - INTERVAL '15 days');

INSERT INTO products (name, category, price) VALUES
('Enterprise Analytics Suite', 'Software', 4999.00),
('Team Collaboration Hub', 'Software', 1200.00),
('Cloud Infrastructure Monitoring', 'DevOps', 2400.00),
('AI Assistant Add-on', 'AI', 800.00),
('Security Compliance Pack', 'Security', 1500.00);

INSERT INTO orders (customer_id, status, total_amount, created_at) 
SELECT id, 'completed', 45200.00, NOW() - INTERVAL '20 days' FROM customers WHERE name = 'Acme Corp'
UNION ALL
SELECT id, 'completed', 32100.00, NOW() - INTERVAL '10 days' FROM customers WHERE name = 'Globex Inc'
UNION ALL
SELECT id, 'completed', 28400.00, NOW() - INTERVAL '5 days' FROM customers WHERE name = 'Soylent Corp'
UNION ALL
SELECT id, 'completed', 19500.00, NOW() - INTERVAL '2 days' FROM customers WHERE name = 'Initech'
UNION ALL
SELECT id, 'completed', 15800.00, NOW() - INTERVAL '1 day' FROM customers WHERE name = 'Umbrella Corp';
```

---

## 9. Implementation Checklist

- [ ] **Backend Database Engine**: Implement `backend/app/database.py` with schema introspection and read-only execution.
- [ ] **Backend Schemas**: Add `GeneratedSQL` and update `ChatResponse` in `backend/app/schemas.py`.
- [ ] **Agent Service**: Update `backend/app/llm_service.py` to support structured Text-to-SQL generation, query execution, error correction, and answer synthesis.
- [ ] **FastAPI Endpoints**: Wire `POST /api/chat` and `GET /api/database/schema` in `backend/app/api/endpoints.py`.
- [ ] **Frontend Types & UI**: Update `frontend/types/chat.ts` and `frontend/components/workspace/AssistantMessage.tsx` to display generated SQL and query results.
- [ ] **Verification**: Run sample questions (*"Top customers by spend"*, *"Revenue by country"*) and verify accuracy and speed.

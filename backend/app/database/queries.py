import math
import time
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import text
from app.agent.contracts import ExecutionResult, SQLDraft
from app.config import Settings
from app.guardrails.sql_guard import SQLPolicyError, SQLSyntaxError, prepare_query

REPAIRABLE = {
    "42601": "SQL syntax is invalid.",
    "42703": "A referenced column does not exist.",
    "42P01": "A referenced table does not exist.",
    "42803": "The aggregation requires a GROUP BY correction.",
    "42804": "An expression has an incompatible data type.",
    "42883": "An operator or function signature is not available.",
}


def normalize(value):
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Nested JSON is outside the flat analytics response contract.
    return str(value)


class QueryExecutor:
    def __init__(self, engine, settings: Settings):
        self.engine, self.settings = engine, settings

    def execute(self, draft: SQLDraft) -> ExecutionResult:
        start = time.monotonic()
        try:
            query = prepare_query(
                draft.sql,
                draft.parameters,
                self.settings.tables,
                self.settings.QUERY_DEFAULT_ROWS,
                self.settings.QUERY_MAX_ROWS,
            )
        except SQLSyntaxError:
            return ExecutionResult(
                status="sql_error",
                error_code="42601",
                error_message="SQL syntax is invalid.",
            )
        except SQLPolicyError as exc:
            return ExecutionResult(
                status="blocked", error_code="SQL_POLICY", error_message=str(exc)
            )
        try:
            with self.engine.connect() as connection:
                with connection.begin():
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(
                        text("SELECT set_config('statement_timeout', :timeout, true)"),
                        {"timeout": str(self.settings.SQL_TIMEOUT_MS)},
                    )
                    connection.execute(
                        text(
                            "SELECT set_config('search_path', 'pg_catalog,public', true)"
                        )
                    )
                    connection.execute(
                        text("SELECT set_config('TimeZone', :timezone, true)"),
                        {"timezone": self.settings.BUSINESS_TIMEZONE},
                    )
                    result = connection.execute(text(query.sql), draft.parameters)
                    columns = list(result.keys())
                    if len(set(columns)) != len(columns):
                        return ExecutionResult(
                            status="sql_error",
                            error_code="DUPLICATE_COLUMNS",
                            error_message="Use unique aliases for all result columns.",
                        )
                    fetched = result.fetchmany(query.display_limit + 1)
                    truncated = query.probing and len(fetched) > query.display_limit
                    rows = [
                        {k: normalize(v) for k, v in row._mapping.items()}
                        for row in fetched[: query.display_limit]
                    ]
            return ExecutionResult(
                status="success",
                rows=rows,
                columns=columns,
                row_count=len(rows),
                truncated=truncated,
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )
        except Exception as exc:
            original = getattr(exc, "orig", exc)
            code = getattr(original, "pgcode", None) or getattr(
                original, "sqlstate", None
            )
            return ExecutionResult(
                status="sql_error" if code in REPAIRABLE else "infrastructure_error",
                error_code=code or "DATABASE_UNAVAILABLE",
                error_message=REPAIRABLE.get(
                    code, "The database query could not complete. Please retry later."
                ),
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )

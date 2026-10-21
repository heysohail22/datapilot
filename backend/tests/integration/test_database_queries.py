"""Real PostgreSQL tests. TEST_DATABASE_URL must point at a disposable test database."""

import os
from pathlib import Path
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, text
from app.agent.contracts import SQLDraft
from app.database.queries import QueryExecutor
from app.database.schema import SchemaCatalog


@pytest.fixture(scope="module")
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL test database")
    engine = create_engine(url)
    # The test runner owns a dedicated temporary database, never a production URL.
    with engine.begin() as connection:
        assert (
            connection.execute(text("SELECT current_database()"))
            .scalar()
            .endswith("_test")
        ), "Refusing fixture outside a _test database"
        connection.exec_driver_sql(
            "DROP TABLE IF EXISTS order_items; DROP TABLE IF EXISTS orders;"
        )
        connection.exec_driver_sql(
            (Path(__file__).parents[1] / "fixtures/business_data.sql").read_text()
        )
    yield engine
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE order_items; DROP TABLE orders;")
    engine.dispose()


def execute(db, settings, sql, parameters=None, columns=None):
    return QueryExecutor(db, settings).execute(
        SQLDraft(
            sql=sql, parameters=parameters or {}, expected_columns=columns or ["value"]
        )
    )


def test_margin_is_ratio_of_sums(db, settings):
    result = execute(
        db,
        settings,
        "SELECT SUM(net_revenue) AS revenue, SUM(historical_cogs) AS cogs, 100*(SUM(net_revenue)-SUM(historical_cogs))/NULLIF(SUM(net_revenue),0) AS margin FROM orders WHERE sold_at >= :start AND sold_at < :end AND status != :cancelled",
        {"start": "2025-01-01", "end": "2025-02-01", "cancelled": "cancelled"},
    )
    assert result.status == "success", result
    row = result.rows[0]
    assert Decimal(row["revenue"]) == 110000
    assert abs(Decimal(row["margin"]) - Decimal("37.27272727272727")) < Decimal(
        "0.00001"
    )


def test_growth_and_zero_baseline(db, settings):
    result = execute(
        db,
        settings,
        "WITH totals AS (SELECT SUM(CASE WHEN sold_at >= '2025-02-01' THEN net_revenue ELSE 0 END) AS current, SUM(CASE WHEN sold_at < '2025-02-01' THEN net_revenue ELSE 0 END) AS prior FROM orders WHERE sold_at >= '2025-01-01' AND sold_at < '2025-03-01' AND status='completed') SELECT 100*(current-prior)/NULLIF(prior,0) AS growth FROM totals",
    )
    assert result.status == "success", result
    assert Decimal(result.rows[0]["growth"]) == 20
    null = execute(db, settings, "SELECT 100 / NULLIF(0,0) AS growth")
    assert null.rows == [{"growth": None}]


def test_five_year_series(db, settings):
    result = execute(
        db,
        settings,
        "SELECT EXTRACT(YEAR FROM sold_at) AS year, SUM(net_revenue) AS revenue FROM orders WHERE sold_at >= '2021-01-01' AND sold_at < '2026-01-01' AND status='completed' GROUP BY 1 ORDER BY 1",
    )
    assert result.status == "success", result
    assert len(result.rows) == 5
    assert Decimal(result.rows[-1]["revenue"]) == 242000


def test_line_join_does_not_duplicate_order_totals(db, settings):
    result = execute(
        db,
        settings,
        "SELECT SUM(net_revenue) AS revenue FROM orders WHERE order_id IN (SELECT order_id FROM order_items)",
    )
    assert Decimal(result.rows[0]["revenue"]) == 242000


def test_error_classification_and_safe_messages(db, settings):
    result = execute(db, settings, "SELECT nonexistent_customer_secret FROM orders")
    assert result.status == "sql_error" and result.error_code == "42703"
    assert "nonexistent_customer_secret" not in result.error_message


def test_policy_prevents_writes(db, settings):
    assert execute(db, settings, "DELETE FROM orders").status == "blocked"
    assert execute(db, settings, "SELECT pg_sleep(2)").status == "blocked"
    assert (
        execute(db, settings, "SELECT * FROM pg_catalog.pg_roles").status == "blocked"
    )


def test_read_only_and_timeout_set_on_connection(db, settings):
    # Inspect the same transaction through SQLAlchemy's before_cursor_execute hook.
    from sqlalchemy import event

    observed = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        observed.append(statement)

    event.listen(db, "before_cursor_execute", capture)
    try:
        result = execute(db, settings, "SELECT SUM(net_revenue) AS revenue FROM orders")
        assert result.status == "success"
        assert observed[0] == "SET TRANSACTION READ ONLY"
        assert any("statement_timeout" in q for q in observed)
    finally:
        event.remove(db, "before_cursor_execute", capture)


def test_metadata_allowlist(db, settings):
    catalog = SchemaCatalog(
        db, frozenset({"orders"}), ttl=3600, notes="one row per order"
    )
    first = catalog.get()
    assert set(first["tables"]) == {"orders"}
    assert catalog.get() is first


def test_truncation_and_full_aggregate(db, settings):
    settings = settings.model_copy(
        update={"QUERY_DEFAULT_ROWS": 2, "QUERY_MAX_ROWS": 3}
    )
    result = execute(db, settings, "SELECT order_id FROM orders ORDER BY order_id")
    assert result.truncated and len(result.rows) == 2
    total = execute(db, settings, "SELECT COUNT(*) AS count FROM orders")
    assert total.rows == [{"count": 8}] and not total.truncated

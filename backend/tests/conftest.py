"""Shared pytest fixtures; reusable doubles live in tests.helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from app.agent.graph import create_agent_graph
from app.config import Settings
from app.services.chat_service import ChatService
from app.services.conversations import ConversationStore
from .helpers import FakeCatalog, FakeExecutor, FakeLLM, decision, draft


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        ENABLED_METRICS="revenue,order_count,average_order_value,gross_margin,revenue_growth,five_year_trend",
        SESSION_SECRET="tests-only",
        DATABASE_URL="postgresql://localhost/datapilot_test",
        METRIC_SCHEMA_NOTES="orders are one row per order; net_revenue excludes tax, cancellations, refunds and discounts.",
    )


@pytest.fixture
def factory(settings):
    def build(llm=None, executor=None):
        model = llm or FakeLLM([decision()], [draft()])
        db = executor or FakeExecutor()
        catalog = FakeCatalog()
        graph = create_agent_graph(model, db, catalog, settings)
        clock = lambda: datetime(2026, 10, 21, tzinfo=ZoneInfo("Asia/Kolkata"))
        service = ChatService(graph, ConversationStore(), settings, clock)
        return service, model, db, catalog

    return build

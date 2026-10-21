from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from app.agent.contracts import AnswerDraft, ExecutionResult, RouterDecision, SQLDraft
from app.agent.graph import create_agent_graph
from app.config import Settings
from app.services.chat_service import ChatService
from app.services.conversations import ConversationStore


class FakeLLM:
    def __init__(self, decisions=None, drafts=None, answers=None):
        self.decisions = list(decisions or [])
        self.drafts = list(drafts or [])
        self.answers = list(answers or [])
        self.calls = []

    async def complete(self, stage, payload, output):
        self.calls.append((stage, payload))
        choices = {
            "router": self.decisions,
            "sql_generator": self.drafts,
            "answer": self.answers,
        }[stage]
        value = (
            choices.pop(0)
            if choices
            else (
                AnswerDraft(message="Here are the results.")
                if stage == "answer"
                else RuntimeError("Missing fake response")
            )
        )
        if isinstance(value, Exception):
            raise value
        return output.model_validate(value)


class FakeExecutor:
    def __init__(self, results=None):
        self.results = list(
            results
            or [
                ExecutionResult(
                    status="success",
                    rows=[{"revenue": "100000.00"}],
                    columns=["revenue"],
                    row_count=1,
                )
            ]
        )
        self.calls = []

    def execute(self, draft):
        self.calls.append(draft)
        return self.results.pop(0)


class FakeCatalog:
    def __init__(self):
        self.calls = 0

    def get(self):
        self.calls += 1
        return {
            "tables": {
                "orders": {"columns": [{"name": "net_revenue", "type": "NUMERIC"}]}
            }
        }


def decision(route="business_query", **kwargs):
    values = {"route": route, "normalized_question": "Revenue last month"}
    if route == "business_query":
        values.update(
            metric_id="revenue", period_request={"kind": "previous_calendar_month"}
        )
    if route == "needs_clarification":
        values["clarification_question"] = "Which period?"
    values.update(kwargs)
    return RouterDecision.model_validate(values)


def draft(sql="SELECT SUM(net_revenue) AS revenue FROM orders"):
    return SQLDraft(sql=sql, expected_columns=["revenue"])


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

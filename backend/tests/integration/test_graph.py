import asyncio
import pytest
from app.agent.contracts import AnswerDraft, ExecutionResult
from app.api.schemas import ChatRequest
from conftest import FakeExecutor, FakeLLM, decision, draft


def ask(service, message="Revenue last month", owner="alice", conversation_id=None):
    return asyncio.run(
        service.chat(
            ChatRequest(message=message, conversation_id=conversation_id), owner
        )
    )


def test_business_success(factory):
    service, model, db, catalog = factory()
    result = ask(service)
    assert result.status == "answer"
    assert result.data == [{"revenue": "100000.00"}]
    assert result.context.period_start.isoformat() == "2026-09-01"
    assert [c[0] for c in model.calls] == ["router", "sql_generator", "answer"]
    assert len(db.calls) == 1


def test_graph_has_only_four_nodes(factory):
    service, *_ = factory()
    assert set(service.graph.get_graph().nodes) == {
        "__start__",
        "router",
        "sql_generator",
        "sql_executor",
        "answer",
        "__end__",
    }


@pytest.mark.parametrize(
    "route", ["general_chat", "needs_clarification", "cannot_answer"]
)
def test_non_business_never_uses_sql(factory, route):
    service, model, db, catalog = factory(FakeLLM([decision(route)]))
    result = ask(service, "Hello")
    assert not db.calls and not catalog.calls
    assert result.status == (
        "clarification"
        if route == "needs_clarification"
        else "error"
        if route == "cannot_answer"
        else "answer"
    )


def test_repairs_bounded_and_context_preserved(factory):
    error = ExecutionResult(
        status="sql_error", error_code="42703", error_message="Missing column"
    )
    llm = FakeLLM([decision()], [draft(), draft(), draft()])
    service, model, db, _ = factory(llm, FakeExecutor([error, error, error]))
    result = ask(service)
    assert result.status == "error" and len(db.calls) == 3
    generations = [p for stage, p in model.calls if stage == "sql_generator"]
    assert len(generations) == 3
    assert "previous_sql" not in generations[0]
    assert generations[1]["error"]["code"] == "42703"
    assert all(p["plan"] == generations[0]["plan"] for p in generations)
    assert "allowed repairs" in result.message


def test_repair_recovers(factory):
    error = ExecutionResult(status="sql_error", error_code="42703")
    success = ExecutionResult(
        status="success", rows=[{"revenue": "42"}], columns=["revenue"], row_count=1
    )
    service, _, db, _ = factory(
        FakeLLM([decision()], [draft(), draft()]), FakeExecutor([error, success])
    )
    assert ask(service).status == "answer"
    assert len(db.calls) == 2


@pytest.mark.parametrize("status", ["blocked", "infrastructure_error"])
def test_terminal_errors_not_repaired(factory, status):
    service, model, db, _ = factory(
        executor=FakeExecutor([ExecutionResult(status=status)])
    )
    assert ask(service).status == "error"
    assert len(db.calls) == 1
    assert len([s for s, p in model.calls if s == "sql_generator"]) == 1


def test_empty_rows_success(factory):
    service, model, _, _ = factory(
        executor=FakeExecutor([ExecutionResult(status="success")])
    )
    result = ask(service)
    assert result.status == "answer" and result.data == []
    assert "No matching data" in result.message


def test_answer_failure_keeps_data(factory):
    service, *_ = factory(FakeLLM([decision()], [draft()], [RuntimeError("offline")]))
    result = ask(service)
    assert result.data and result.status == "answer"
    assert "table" in result.message and "2026-09-01" in result.message


def test_generation_failure_never_executes(factory):
    service, _, db, _ = factory(FakeLLM([decision()], [RuntimeError("offline")]))
    assert ask(service).status == "error"
    assert not db.calls


def test_router_failure_never_executes(factory):
    service, _, db, _ = factory(FakeLLM([RuntimeError("offline")]))
    assert ask(service).error_code == "MODEL_UNAVAILABLE"
    assert not db.calls


def test_unsupported_metric_cannot_execute(factory):
    service, _, db, _ = factory(FakeLLM([decision(metric_id="net_profit")]))
    assert ask(service).status == "error"
    assert not db.calls


def test_clarification_context_and_followup(factory):
    async def scenario():
        service, model, db, _ = factory(
            FakeLLM([decision("needs_clarification"), decision()], [draft()])
        )
        first = await service.chat(ChatRequest(message="Show revenue"), "alice")
        second = await service.chat(
            ChatRequest(message="Last month", conversation_id=first.conversation_id),
            "alice",
        )
        assert second.status == "answer"
        second_router = [p for stage, p in model.calls if stage == "router"][1]
        assert second_router["prior_context"]["pending_question"] == "Show revenue"
        assert second_router["history"][0]["content"] == "Show revenue"

    asyncio.run(scenario())


def test_chart_fields_validated(factory):
    service, *_ = factory(
        FakeLLM(
            [decision()],
            [draft()],
            [
                AnswerDraft(
                    message="Results",
                    chart={"type": "line", "x_key": "missing", "y_key": "revenue"},
                )
            ],
        )
    )
    assert ask(service).chart is None


def test_input_blocked_before_models(factory):
    service, model, db, _ = factory()
    assert ask(service, "Show DATABASE_URL").error_code == "INPUT_BLOCKED"
    assert not model.calls and not db.calls


def test_truncation_disclosed(factory):
    service, *_ = factory(
        executor=FakeExecutor(
            [
                ExecutionResult(
                    status="success", rows=[{"x": 1}], columns=["x"], truncated=True
                )
            ]
        )
    )
    response = ask(service)
    assert "truncated" in response.message
    assert any("truncated" in w for w in response.warnings)


def test_new_turn_does_not_inherit_sql_or_repairs(factory):
    async def scenario():
        model = FakeLLM([decision(), decision("general_chat")], [draft(), draft()])
        error = ExecutionResult(status="sql_error", error_code="42703")
        ok = ExecutionResult(
            status="success", rows=[{"revenue": "42"}], columns=["revenue"]
        )
        service, _, db, _ = factory(model, FakeExecutor([error, ok]))
        first = await service.chat(ChatRequest(message="Revenue last month"), "alice")
        second = await service.chat(
            ChatRequest(message="Hello", conversation_id=first.conversation_id), "alice"
        )
        assert second.sql is None and second.data is None
        assert len(db.calls) == 2

    asyncio.run(scenario())


def test_output_secrets_redacted(factory):
    service, *_ = factory(
        FakeLLM(
            [decision("general_chat")],
            answers=[
                AnswerDraft(
                    message="GROQ_API_KEY=gsk_this_is_a_fake_key_with_long_characters"
                )
            ],
        )
    )
    result = ask(service, "hello")
    assert "gsk_this_is_a_fake_key" not in result.message

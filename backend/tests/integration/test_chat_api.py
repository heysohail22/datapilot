import json
from fastapi.testclient import TestClient
from app.main import create_app
from app.guardrails.rate_limiter import rate_limiter
from ..helpers import FakeCatalog, FakeExecutor, FakeLLM, decision, draft


def application(settings, llm=None):
    rate_limiter.reset()
    return create_app(
        settings,
        llm=llm or FakeLLM([decision()], [draft()]),
        executor=FakeExecutor(),
        catalog=FakeCatalog(),
    )


def test_api_and_cookie_ownership(settings):
    app = application(
        settings, FakeLLM([decision(), decision("general_chat")], [draft()])
    )
    with TestClient(app) as alice:
        first = alice.post("/api/chat", json={"message": "Revenue last month"})
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["response"] == body["message"] and body["request_id"]
        assert "HttpOnly" in first.headers["set-cookie"]
        assert alice.get("/health").json() == {"status": "healthy"}
        assert len(alice.get("/api/conversations").json()["conversations"]) == 1
        canonical = body["conversation_id"]
        cookies = dict(alice.cookies)
        alice.cookies.clear()
        assert alice.get(f"/api/conversations/{canonical}").status_code == 404
        assert (
            alice.post(
                "/api/chat", json={"message": "hi", "conversation_id": canonical}
            ).status_code
            == 404
        )
        assert not alice.get("/api/conversations").json()["conversations"]
        alice.cookies.update(cookies)
        second = alice.post(
            "/api/chat", json={"message": "hi", "conversation_id": canonical}
        )
        assert second.json()["conversation_id"] == canonical
        assert alice.delete(f"/api/conversations/{canonical}").status_code == 200
        assert alice.get(f"/api/conversations/{canonical}").status_code == 404


def test_stream_has_real_step_events_and_done(settings):
    with TestClient(application(settings)) as client:
        response = client.post(
            "/api/chat/stream", json={"message": "Revenue last month"}
        )
        assert response.status_code == 200
        assert "event: step" in response.text and "Calculating results" in response.text
        done = response.text.split("event: done\ndata: ")[1].split("\n")[0]
        data = json.loads(done)
        assert data["status"] == "answer" and data["conversation_id"]
        assert data["data"] == [{"revenue": "100000.00"}]


def test_blank_and_oversized_requests(settings):
    with TestClient(application(settings)) as client:
        for message in ["", "   ", "x" * 4001]:
            assert (
                client.post("/api/chat", json={"message": message}).status_code == 422
            )


def test_model_failure_503(settings):
    with TestClient(
        application(settings, FakeLLM([RuntimeError("no provider")]))
    ) as client:
        result = client.post("/api/chat", json={"message": "hi"})
        assert result.status_code == 503
        assert result.json()["status"] == "error"


def test_origin_allowlist(settings):
    with TestClient(application(settings)) as client:
        result = client.options(
            "/api/chat",
            headers={
                "Origin": "https://untrusted.vercel.app",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert result.status_code == 400
        good = client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert good.status_code == 200


def test_database_outage_returns_503(settings):
    from app.agent.contracts import ExecutionResult

    app = create_app(
        settings,
        llm=FakeLLM([decision()], [draft()]),
        executor=FakeExecutor(
            [ExecutionResult(status="infrastructure_error", error_code="08006")]
        ),
        catalog=FakeCatalog(),
    )
    with TestClient(app) as client:
        result = client.post("/api/chat", json={"message": "Revenue last month"})
        assert result.status_code == 503
        assert result.json()["error_code"] == "DATABASE_UNAVAILABLE"

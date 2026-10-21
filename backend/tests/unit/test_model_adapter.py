import asyncio
import pytest
from app.agent.contracts import RouterDecision
from app.services.llm import ModelUnavailable, ProviderLLM


class StructuredClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def with_structured_output(self, output):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def adapter(client):
    llm = ProviderLLM.__new__(ProviderLLM)
    llm.timeout = 1
    llm.models = {"router": client}
    return llm


def test_invalid_format_retried_once():
    client = StructuredClient(
        [{}, {"route": "general_chat", "normalized_question": "Hello"}]
    )
    result = asyncio.run(adapter(client).complete("router", {}, RouterDecision))
    assert result.route == "general_chat" and client.calls == 2


def test_repeated_invalid_format_terminates():
    client = StructuredClient([{}, {}])
    with pytest.raises(ModelUnavailable):
        asyncio.run(adapter(client).complete("router", {}, RouterDecision))
    assert client.calls == 2


def test_outage_not_retried_as_format_failure():
    client = StructuredClient([RuntimeError("offline")])
    with pytest.raises(ModelUnavailable):
        asyncio.run(adapter(client).complete("router", {}, RouterDecision))
    assert client.calls == 1

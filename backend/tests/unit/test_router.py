from pydantic import ValidationError
import pytest
from app.agent.contracts import RouterDecision
from ..helpers import decision


@pytest.mark.parametrize(
    "payload",
    [
        {"route": "unknown", "normalized_question": "hello"},
        {"route": "business_query", "normalized_question": "sales"},
        {"route": "needs_clarification", "normalized_question": "profit"},
        {
            "route": "general_chat",
            "normalized_question": "hi",
            "clarification_question": "Which year?",
        },
    ],
)
def test_invalid_decisions_rejected(payload):
    with pytest.raises(ValidationError):
        RouterDecision.model_validate(payload)


def test_filters_allowlisted():
    with pytest.raises(ValidationError):
        decision(filters=[{"field": "password", "values": ["x"]}])

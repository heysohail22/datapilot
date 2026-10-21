import operator
from typing import Annotated, TypedDict
from app.agent.contracts import (
    AnswerDraft,
    BusinessPlan,
    ExecutionResult,
    Failure,
    RouterDecision,
    SQLDraft,
)


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    prior_plan: dict | None
    clock_context: dict[str, str]
    request_id: str
    decision: RouterDecision | None
    plan: BusinessPlan | None
    sql_draft: SQLDraft | None
    execution: ExecutionResult | None
    repair_count: int
    failure: Failure | None
    final: AnswerDraft | None
    events: Annotated[list[str], operator.add]

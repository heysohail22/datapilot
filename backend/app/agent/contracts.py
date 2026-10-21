"""Typed boundaries between model, business logic, execution, and presentation."""

from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int | float | bool | None
MetricID = Literal[
    "revenue",
    "order_count",
    "average_order_value",
    "gross_margin",
    "revenue_growth",
    "five_year_trend",
    "net_profit",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeriodRequest(Contract):
    kind: Literal[
        "previous_calendar_month",
        "current_month",
        "previous_calendar_year",
        "current_year",
        "five_complete_years",
        "custom",
    ]
    start: date | None = None
    end_exclusive: date | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.kind == "custom" and (
            not self.start or not self.end_exclusive or self.start >= self.end_exclusive
        ):
            raise ValueError(
                "Custom periods need ordered start and end_exclusive dates"
            )
        return self


class BusinessFilter(Contract):
    field: Literal["customer_id", "product_id", "category", "status"]
    operator: Literal["eq", "in"] = "eq"
    values: list[str] = Field(min_length=1, max_length=20)


class RouterDecision(Contract):
    route: Literal[
        "general_chat", "needs_clarification", "business_query", "cannot_answer"
    ]
    normalized_question: str = Field(min_length=1, max_length=4000)
    metric_id: MetricID | None = None
    period_request: PeriodRequest | None = None
    comparison: Literal["none", "previous_period", "previous_year", "annual_trend"] = (
        "none"
    )
    granularity: Literal["total", "day", "month", "year"] = "total"
    filters: list[BusinessFilter] = Field(default_factory=list, max_length=20)
    clarification_question: str | None = None
    response_hint: str | None = None

    @model_validator(mode="after")
    def route_contract(self):
        if self.route == "business_query" and (
            self.metric_id is None or self.period_request is None
        ):
            raise ValueError("Business queries require a metric and period")
        if self.route == "needs_clarification" and not self.clarification_question:
            raise ValueError("Clarification requires a question")
        if self.route != "needs_clarification" and self.clarification_question:
            raise ValueError(
                "Only clarification routes may carry a clarification question"
            )
        return self


class BusinessPlan(Contract):
    normalized_question: str
    metric_id: MetricID
    period_start: date
    period_end_exclusive: date
    comparison_start: date | None = None
    comparison_end_exclusive: date | None = None
    comparison: str = "none"
    granularity: str = "total"
    filters: list[BusinessFilter] = Field(default_factory=list)
    metric_version: str = "1"
    timezone: str
    currency: str
    assumptions: list[str] = Field(default_factory=list)


class SQLDraft(Contract):
    sql: str = Field(min_length=1, max_length=20000)
    parameters: dict[str, Scalar] = Field(default_factory=dict)
    expected_columns: list[str] = Field(min_length=1, max_length=30)


class ExecutionResult(Contract):
    status: Literal["success", "sql_error", "blocked", "infrastructure_error"]
    rows: list[dict[str, Scalar]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    duration_ms: float = 0
    truncated: bool = False
    error_code: str | None = None
    error_message: str | None = None


class Failure(Contract):
    code: str
    stage: str
    message: str


class ChartConfig(Contract):
    type: Literal["bar", "line", "area", "donut"]
    x_key: str
    y_key: str
    title: str = ""


class AnswerDraft(Contract):
    message: str = Field(min_length=1, max_length=12000)
    # Validate chart separately so a bad chart cannot discard a good narrative.
    chart: dict[str, Scalar] | None = None

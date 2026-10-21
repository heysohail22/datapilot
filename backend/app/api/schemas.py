from typing import Literal
from pydantic import BaseModel, Field, field_validator
from app.agent.contracts import BusinessPlan, ChartConfig, Scalar


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @field_validator("message")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


class ChatResponse(BaseModel):
    conversation_id: str
    request_id: str
    status: Literal["answer", "clarification", "error"]
    message: str
    context: BusinessPlan | None = None
    data: list[dict[str, Scalar]] | None = None
    columns: list[str] | None = None
    chart: ChartConfig | None = None
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    # Compatibility with the current frontend and its SSE done payload.
    response: str
    sql: str | None = None
    chart_config: ChartConfig | None = None
    row_count: int | None = None
    execution_time_ms: float | None = None
    thought_trace: list[str] = Field(default_factory=list)

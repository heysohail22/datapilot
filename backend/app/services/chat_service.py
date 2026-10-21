"""One request boundary for HTTP and the SSE compatibility adapter."""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from zoneinfo import ZoneInfo
from pydantic import ValidationError
from app.agent.contracts import AnswerDraft, ChartConfig, Failure
from app.api.schemas import ChatResponse
from app.guardrails.input_guard import sanitize_and_validate_input
from app.guardrails.output_guard import redact_secrets, scrub_stack_traces

logger = logging.getLogger(__name__)


def validated_chart(draft, result):
    if not draft or not result or not result.rows:
        return None
    try:
        chart = ChartConfig.model_validate(draft)
        if chart.x_key not in result.columns or chart.y_key not in result.columns:
            return None
        values = [
            row[chart.y_key] for row in result.rows if row.get(chart.y_key) is not None
        ]
        if not values or any(
            isinstance(v, bool) or not Decimal(str(v)).is_finite() for v in values
        ):
            return None
        return chart
    except (ValidationError, InvalidOperation, ValueError):
        return None


class ChatService:
    def __init__(self, graph, conversations, settings, clock=None):
        self.graph, self.conversations, self.settings = graph, conversations, settings
        self.clock = clock or (
            lambda: datetime.now(ZoneInfo(settings.BUSINESS_TIMEZONE))
        )

    async def chat(self, request, owner, on_step=None):
        request_id = str(uuid4())
        guard = sanitize_and_validate_input(request.message)
        async with self.conversations.turn(owner, request.conversation_id) as conv:
            now = self.clock()
            state = {
                "question": guard.sanitized_text,
                "history": [
                    {"role": m["role"], "content": m["content"][:4000]}
                    for m in conv.messages[-10:]
                ],
                "prior_plan": conv.context,
                "clock_context": {
                    "today": now.date().isoformat(),
                    "timezone": self.settings.BUSINESS_TIMEZONE,
                    "currency": self.settings.BUSINESS_CURRENCY,
                },
                "request_id": request_id,
                "decision": None,
                "plan": None,
                "sql_draft": None,
                "execution": None,
                "repair_count": 0,
                "failure": None,
                "final": None,
                "events": [],
            }
            if not guard.is_safe:
                state["failure"] = Failure(
                    code="INPUT_BLOCKED", stage="input", message=guard.rejection_reason
                )
                state["final"] = AnswerDraft(message=guard.rejection_reason)
            else:
                try:
                    async with asyncio.timeout(self.settings.REQUEST_TIMEOUT_SECONDS):
                        async for update in self.graph.astream(
                            state, config={"recursion_limit": 16}, stream_mode="updates"
                        ):
                            for changes in update.values():
                                if not isinstance(changes, dict):
                                    continue
                                events = changes.get("events", [])
                                state.update(
                                    {
                                        key: value
                                        for key, value in changes.items()
                                        if key != "events"
                                    }
                                )
                                state["events"].extend(events)
                                if on_step:
                                    for event in events:
                                        await on_step(event)
                except Exception as exc:
                    logger.warning(
                        "workflow_failed request_id=%s error_type=%s",
                        request_id,
                        type(exc).__name__,
                    )
                    state["failure"] = Failure(
                        code="WORKFLOW_FAILED",
                        stage="workflow",
                        message="The request could not complete. Please retry.",
                    )
                    state["final"] = AnswerDraft(message=state["failure"].message)
            result = state.get("execution")
            decision = state.get("decision")
            failed = bool(
                state.get("failure")
                or (result and result.status != "success")
                or (decision and decision.route == "cannot_answer")
            )
            status = (
                "error"
                if failed
                else (
                    "clarification"
                    if decision and decision.route == "needs_clarification"
                    else "answer"
                )
            )
            final = state.get("final") or AnswerDraft(
                message="The request could not complete."
            )
            plan = state.get("plan")
            # Always include resolved definitions and dates, including fallback responses.
            message = final.message
            if plan:
                from app.business.metrics import METRICS

                message += f"\n\nMetric: {METRICS[plan.metric_id].meaning}. Period: {plan.period_start} to {plan.period_end_exclusive} (end exclusive), {plan.timezone}."
                if plan.comparison_start:
                    message += f" Comparison: {plan.comparison_start} to {plan.comparison_end_exclusive} (end exclusive)."
            if plan and plan.filters:
                message += " Filters: " + "; ".join(
                    f"{f.field} {f.operator} {f.values}" for f in plan.filters
                )
            message = scrub_stack_traces(redact_secrets(message)[0])[0]
            warnings = list(plan.assumptions) if plan else []
            if result and result.truncated:
                warnings.append(
                    "Displayed result rows are truncated; this table is not the complete result set."
                )
                message += "\n\nDisplayed rows are truncated."
            chart = (
                validated_chart(final.chart, result)
                if result and result.status == "success"
                else None
            )
            error_code = (
                state["failure"].code
                if state.get("failure")
                else (result.error_code if result else None)
            )
            if result and result.status == "infrastructure_error":
                error_code = (
                    "QUERY_TIMEOUT"
                    if result.error_code == "57014"
                    else "DATABASE_UNAVAILABLE"
                )
            response = ChatResponse(
                conversation_id=conv.id,
                request_id=request_id,
                status=status,
                message=message,
                response=message,
                context=plan,
                data=result.rows if result and result.status == "success" else None,
                columns=result.columns
                if result and result.status == "success"
                else None,
                row_count=result.row_count
                if result and result.status == "success"
                else None,
                execution_time_ms=result.duration_ms if result else None,
                chart=chart,
                chart_config=chart,
                warnings=warnings,
                error_code=error_code,
                # Never publish an unexecuted, blocked, or failed statement.
                sql=state["sql_draft"].sql
                if state.get("sql_draft") and result and result.status == "success"
                else None,
                thought_trace=state["events"],
            )
            context = plan.model_dump(mode="json") if plan else conv.context
            if status == "clarification":
                context = {
                    "pending_question": state["question"],
                    "previous_context": conv.context,
                    "clarification": decision.clarification_question,
                }
            try:
                self.conversations.append(conv, request.message, response, context)
            except Exception:
                response.warnings.append(
                    "This answer could not be saved to conversation history."
                )
            return response

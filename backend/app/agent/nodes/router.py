from datetime import date
from app.agent.contracts import Failure, RouterDecision
from app.business.metrics import METRICS
from app.business.periods import resolve_plan


async def router(state, llm, settings):
    try:
        decision = await llm.complete(
            "router",
            {
                "question": state["question"],
                "history": state["history"],
                "prior_context": state["prior_plan"],
                "clock": state["clock_context"],
                "metrics": [
                    METRICS[m].as_dict()
                    for m in sorted(settings.metrics)
                    if m in METRICS
                ],
                "capabilities": settings.METRIC_SCHEMA_NOTES,
            },
            RouterDecision,
        )
        plan = None
        if decision.route == "business_query":
            if decision.metric_id not in settings.metrics:
                decision = decision.model_copy(
                    update={
                        "route": "cannot_answer",
                        "response_hint": "This metric is not enabled for the connected dataset.",
                    }
                )
            else:
                try:
                    plan = resolve_plan(
                        decision,
                        date.fromisoformat(state["clock_context"]["today"]),
                        settings.BUSINESS_TIMEZONE,
                        settings.BUSINESS_CURRENCY,
                    )
                except ValueError as exc:
                    decision = decision.model_copy(
                        update={
                            "route": "needs_clarification",
                            "clarification_question": str(exc),
                        }
                    )
        return {
            "decision": decision,
            "plan": plan,
            "events": ["Understanding question"],
        }
    except Exception:
        return {
            "failure": Failure(
                code="MODEL_UNAVAILABLE",
                stage="router",
                message="I could not understand the request right now. Please retry.",
            ),
            "events": ["Understanding question"],
        }

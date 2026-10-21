from app.agent.contracts import AnswerDraft
from app.business.metrics import METRICS


async def answer(state, llm):
    failure = state.get("failure")
    decision = state.get("decision")
    result = state.get("execution")
    if failure:
        final = AnswerDraft(message=failure.message)
    elif decision.route == "needs_clarification":
        final = AnswerDraft(message=decision.clarification_question)
    elif decision.route == "cannot_answer":
        final = AnswerDraft(
            message="This request is not supported with the available data. "
            + (decision.response_hint or "Please choose an enabled business metric.")
        )
    elif result and result.status != "success":
        text = (
            "This query was blocked by the read-only safety policy."
            if result.status == "blocked"
            else (
                "I could not complete the query after the allowed repairs."
                if result.status == "sql_error"
                else "The database query could not complete. Please retry later."
            )
        )
        final = AnswerDraft(message=text)
    elif result and (
        not result.rows
        or all(all(v is None for v in row.values()) for row in result.rows)
    ):
        final = AnswerDraft(
            message="No matching data is available for this period. Missing data is not assumed to be zero."
        )
    else:
        try:
            final = await llm.complete(
                "answer",
                {
                    "route": decision.route,
                    "question": state["question"],
                    "plan": state["plan"].model_dump(mode="json")
                    if state.get("plan")
                    else None,
                    "metric_definition": METRICS[state["plan"].metric_id].as_dict()
                    if state.get("plan")
                    else None,
                    "result": result.model_dump() if result else None,
                    "capabilities": "Read-only sales and customer analytics; no automated actions.",
                },
                AnswerDraft,
            )
        except Exception:
            final = AnswerDraft(
                message="Results are shown in the table below."
                if result
                else "Hello! I can help analyze sales, customers, and supported business metrics."
            )
    return {"final": final, "events": ["Preparing answer"]}

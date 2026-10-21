import asyncio
from app.agent.contracts import Failure, SQLDraft
from app.business.metrics import METRICS


async def sql_generator(state, llm, catalog):
    repairing = (
        state.get("execution") is not None and state["execution"].status == "sql_error"
    )
    count = state["repair_count"] + int(repairing)
    try:
        schema = await asyncio.to_thread(catalog.get)
    except Exception:
        return {
            "failure": Failure(
                code="SCHEMA_UNAVAILABLE",
                stage="sql_generator",
                message="The business database is unavailable. Please retry later.",
            ),
            "repair_count": count,
            "sql_draft": None,
        }
    payload = {
        "plan": state["plan"].model_dump(mode="json"),
        "schema": schema,
        "metric_definition": METRICS[state["plan"].metric_id].as_dict(),
    }
    if repairing:
        payload.update(
            previous_sql=state["sql_draft"].model_dump(),
            error={
                "code": state["execution"].error_code,
                "message": state["execution"].error_message,
            },
        )
    try:
        draft = await llm.complete("sql_generator", payload, SQLDraft)
        return {
            "sql_draft": draft,
            "execution": None,
            "failure": None,
            "repair_count": count,
            "events": ["Correcting query" if repairing else "Preparing query"],
        }
    except Exception:
        return {
            "sql_draft": None,
            "repair_count": count,
            "failure": Failure(
                code="GENERATION_FAILED",
                stage="sql_generator",
                message="I could not prepare a database query. Please retry.",
            ),
        }

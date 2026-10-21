def after_router(state):
    return (
        "sql_generator" if not state.get("failure") and state.get("plan") else "answer"
    )


def after_generator(state):
    return (
        "sql_executor"
        if state.get("sql_draft") and not state.get("failure")
        else "answer"
    )


def after_executor(state, max_repairs=2):
    result = state["execution"]
    return (
        "sql_generator"
        if result.status == "sql_error" and state["repair_count"] < max_repairs
        else "answer"
    )

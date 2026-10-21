import asyncio


async def sql_executor(state, executor):
    result = await asyncio.to_thread(executor.execute, state["sql_draft"])
    return {"execution": result, "events": ["Calculating results"]}

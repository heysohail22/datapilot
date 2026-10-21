"""Four-node graph with injected boundaries and deterministic edges."""

import logging
import time
from functools import partial
from langgraph.graph import END, START, StateGraph
from app.agent.state import AgentState
from app.agent.routing import after_executor, after_generator, after_router
from app.agent.nodes.router import router
from app.agent.nodes.sql_generator import sql_generator
from app.agent.nodes.sql_executor import sql_executor
from app.agent.nodes.answer import answer

logger = logging.getLogger(__name__)


def measured(name, node):
    async def run(state):
        start = time.monotonic()
        try:
            return await node(state)
        finally:
            logger.info(
                "node_complete request_id=%s node=%s duration_ms=%.1f repair_count=%s",
                state.get("request_id"),
                name,
                (time.monotonic() - start) * 1000,
                state.get("repair_count", 0),
            )

    return run


def create_agent_graph(llm, executor, catalog, settings):
    graph = StateGraph(AgentState)
    for name, node in {
        "router": partial(router, llm=llm, settings=settings),
        "sql_generator": partial(sql_generator, llm=llm, catalog=catalog),
        "sql_executor": partial(sql_executor, executor=executor),
        "answer": partial(answer, llm=llm),
    }.items():
        graph.add_node(name, measured(name, node))
    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", after_router, ["sql_generator", "answer"])
    graph.add_conditional_edges(
        "sql_generator", after_generator, ["sql_executor", "answer"]
    )
    graph.add_conditional_edges(
        "sql_executor",
        partial(after_executor, max_repairs=settings.MAX_SQL_REPAIRS),
        ["sql_generator", "answer"],
    )
    graph.add_edge("answer", END)
    return graph.compile()

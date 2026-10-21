"""Explicit live-model evaluation against a disposable fixture database, outside CI."""

import argparse
import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from app.api.schemas import ChatRequest
from app.agent.graph import create_agent_graph
from app.config import Settings
from app.database.connection import create_database_engine
from app.database.schema import SchemaCatalog
from app.database.queries import QueryExecutor
from app.services.chat_service import ChatService
from app.services.conversations import ConversationStore
from app.services.llm import ProviderLLM


async def evaluate():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow provider calls and their costs"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to explicitly enable paid provider calls")
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        parser.error("Set TEST_DATABASE_URL to a fixture database ending in _test")
    settings = Settings(DATABASE_URL=url)
    engine = create_database_engine(settings)
    from sqlalchemy import text

    with engine.connect() as connection:
        if (
            not connection.execute(text("SELECT current_database()"))
            .scalar()
            .endswith("_test")
        ):
            raise ValueError("Evaluations require a disposable _test database")
    model = ProviderLLM(settings)
    try:
        graph = create_agent_graph(
            model,
            QueryExecutor(engine, settings),
            SchemaCatalog(engine, settings.tables, notes=settings.METRIC_SCHEMA_NOTES),
            settings,
        )
        service = ChatService(graph, ConversationStore(), settings)
        results = []
        for case in json.loads((Path(__file__).parent / "questions.json").read_text()):
            result = await service.chat(
                ChatRequest(message=case["question"]), "evaluation"
            )
            expected_status = {
                "general_chat": "answer",
                "needs_clarification": "clarification",
                "business_query": "answer",
            }[case["route"]]
            checks = [result.status == expected_status]
            if case.get("metric_id"):
                checks.append(
                    result.context is not None
                    and result.context.metric_id == case["metric_id"]
                )
            for boundary in ["period_start", "period_end_exclusive"]:
                if case.get(boundary):
                    checks.append(
                        result.context is not None
                        and str(getattr(result.context, boundary)) == case[boundary]
                    )
            for column, value in case.get("expected", {}).items():
                actual = (result.data or [{}])[0].get(column)
                try:
                    checks.append(
                        actual is not None
                        and abs(Decimal(str(actual)) - Decimal(value))
                        < Decimal("0.00001")
                    )
                except Exception:
                    checks.append(False)
            results.append(
                {
                    "id": case["id"],
                    "passed": all(checks),
                    "status": result.status,
                    "request_id": result.request_id,
                }
            )
        print(json.dumps(results, indent=2))
        if not all(r["passed"] for r in results):
            raise SystemExit(1)
    finally:
        await model.close()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(evaluate())

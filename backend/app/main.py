"""Application factory and lifecycle; imports perform no network calls."""

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import Settings
from app.agent.graph import create_agent_graph
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.database.connection import create_database_engine, probe
from app.database.queries import QueryExecutor
from app.database.schema import SchemaCatalog
from app.services.chat_service import ChatService
from app.services.conversations import ConversationStore
from app.services.llm import ProviderLLM

logger = logging.getLogger(__name__)
COOKIE = "datapilot_session"


def create_app(
    settings=None,
    *,
    llm=None,
    executor=None,
    catalog=None,
    conversations=None,
    clock=None,
):
    settings = settings or Settings()
    secret = settings.SESSION_SECRET.get_secret_value() or secrets.token_hex(32)

    @asynccontextmanager
    async def lifespan(app):
        engine = create_database_engine(settings) if executor is None else None
        model = llm or ProviderLLM(settings)
        app.state.engine = engine
        query_executor = executor or QueryExecutor(engine, settings)
        schema = catalog or SchemaCatalog(
            engine,
            settings.tables,
            settings.SCHEMA_CACHE_TTL_SECONDS,
            settings.METRIC_SCHEMA_NOTES,
        )
        graph = create_agent_graph(model, query_executor, schema, settings)
        app.state.chat_service = ChatService(
            graph,
            conversations or ConversationStore(settings.CONVERSATION_LIMIT),
            settings,
            clock,
        )
        if engine is not None:
            ready = await asyncio.to_thread(probe, engine)
            logger.info("database_warmup ready=%s", ready)
        try:
            yield
        finally:
            if engine is not None:
                await asyncio.to_thread(engine.dispose)
            if llm is None:
                await model.close()

    app = FastAPI(title="DataPilot Backend API", version="0.2.0", lifespan=lifespan)
    origins = [
        o.strip()
        for o in (settings.FRONTEND_URL + "," + settings.CORS_ORIGINS).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys(origins)),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def session(request: Request, call_next):
        supplied = request.cookies.get(COOKIE, "")
        valid = False
        try:
            identity, issued, signature = supplied.split(".")
            material = f"{identity}.{issued}"
            expected = hmac.new(
                secret.encode(), material.encode(), hashlib.sha256
            ).hexdigest()
            valid = (
                len(identity) == 64
                and hmac.compare_digest(expected, signature)
                and 0 <= time.time() - int(issued) < 604800
            )
        except (ValueError, TypeError):
            pass
        if not valid:
            identity, issued = secrets.token_hex(32), str(int(time.time()))
            material = f"{identity}.{issued}"
            supplied = (
                material
                + "."
                + hmac.new(
                    secret.encode(), material.encode(), hashlib.sha256
                ).hexdigest()
            )
        request.state.owner = identity
        response = await call_next(request)
        if not valid:
            response.set_cookie(
                COOKIE,
                supplied,
                httponly=True,
                secure=settings.SESSION_SECURE,
                samesite="none" if settings.SESSION_SECURE else "lax",
                max_age=604800,
            )
        return response

    app.include_router(chat_router)
    app.include_router(health_router)
    return app

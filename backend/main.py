import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import router as api_router
from app.database import warm_database_pool
from app.tools.schema_tool import get_schema_context

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warms Supabase connection pool and pre-caches minified schema on boot."""
    logger.info("Initializing DataPilot backend services...")
    warm_database_pool()
    get_schema_context()
    logger.info("Supabase pool pre-warmed & schema pre-cached in memory.")
    yield


app = FastAPI(
    title="DataPilot Backend API",
    description="FastAPI service with High-Speed Agentic Business Intelligence & Supabase Database Skills",
    version="0.1.0",
    lifespan=lifespan,
)

from app.config import settings

# Parse origins from FRONTEND_URL and/or CORS_ORIGINS
raw_origins = f"{settings.FRONTEND_URL},{settings.CORS_ORIGINS}"
origins_from_config = [
    origin.strip()
    for origin in raw_origins.split(",")
    if origin.strip()
]

# Ensure localhost is always allowed for local development
default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
all_origins = list(dict.fromkeys(origins_from_config + default_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=all_origins,
    allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Mount API router
app.include_router(api_router)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

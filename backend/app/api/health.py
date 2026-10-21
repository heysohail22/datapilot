import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.database.connection import probe

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/api/database/health")
async def database_health(request: Request):
    healthy = await asyncio.to_thread(probe, request.app.state.engine)
    return JSONResponse(
        {
            "status": "connected" if healthy else "error",
            "error": None if healthy else "Database unavailable",
        },
        status_code=200 if healthy else 503,
    )

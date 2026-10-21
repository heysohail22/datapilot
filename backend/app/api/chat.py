import asyncio
import json
from contextlib import suppress
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.api.schemas import ChatRequest, ChatResponse
from app.guardrails.rate_limiter import verify_rate_limit
from app.services.conversations import ConversationNotFound

router = APIRouter()


def service(request: Request):
    return request.app.state.chat_service


def owner(request: Request):
    return request.state.owner


@router.post(
    "/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_rate_limit)]
)
async def chat(body: ChatRequest, request: Request):
    try:
        response = await service(request).chat(body, owner(request))
    except ConversationNotFound:
        raise HTTPException(404, "Conversation not found")
    except RuntimeError:
        raise HTTPException(503, "Conversation service is busy")
    if response.error_code in {
        "MODEL_UNAVAILABLE",
        "SCHEMA_UNAVAILABLE",
        "WORKFLOW_FAILED",
        "GENERATION_FAILED",
        "DATABASE_UNAVAILABLE",
        "QUERY_TIMEOUT",
    }:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            response.model_dump(mode="json"),
            status_code=504 if response.error_code == "QUERY_TIMEOUT" else 503,
        )
    return response


@router.post("/api/chat/stream", dependencies=[Depends(verify_rate_limit)])
async def stream(body: ChatRequest, request: Request):
    # Resolve ownership before sending streaming headers.
    if body.conversation_id:
        try:
            service(request).conversations.get(owner(request), body.conversation_id)
        except ConversationNotFound:
            raise HTTPException(404, "Conversation not found")

    async def events():
        queue = asyncio.Queue()

        async def emit(step):
            await queue.put(("step", {"step": step}))

        async def run():
            try:
                result = await service(request).chat(body, owner(request), emit)
                await queue.put(("done", result.model_dump(mode="json")))
            except Exception:
                await queue.put(
                    (
                        "done",
                        {
                            "status": "error",
                            "response": "The request could not complete. Please retry.",
                            "message": "The request could not complete. Please retry.",
                        },
                    )
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    break
                kind, data = item
                yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/conversations")
async def conversations(request: Request):
    return {"conversations": service(request).conversations.list(owner(request))}


@router.get("/api/conversations/{conversation_id}")
async def detail(conversation_id: str, request: Request):
    try:
        return service(request).conversations.get(owner(request), conversation_id)
    except ConversationNotFound:
        raise HTTPException(404, "Conversation not found")


@router.delete("/api/conversations/{conversation_id}")
async def delete(conversation_id: str, request: Request):
    try:
        service(request).conversations.delete(owner(request), conversation_id)
        return {"status": "success", "deleted_id": conversation_id}
    except ConversationNotFound:
        raise HTTPException(404, "Conversation not found")
    except RuntimeError:
        raise HTTPException(409, "Conversation has an active request")

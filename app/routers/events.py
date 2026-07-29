import asyncio
import json
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from events import subscribe, unsubscribe

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stream")
async def event_stream(request: Request):
    q = await subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(generate(), media_type="text/event-stream")

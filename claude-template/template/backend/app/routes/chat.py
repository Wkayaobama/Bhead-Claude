"""Chat endpoints — the only consumers of app/llm.py in the template.

Two flavors:
  POST /api/chat         → one JSON response
  POST /api/chat/stream  → Server-Sent Events, one token chunk per event

The frontend never sees a model name or an API key; it only speaks
this HTTP contract. That is the decoupling seam.
"""
import json
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.llm import chat_once, stream_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT = "You are a helpful assistant."


class ChatRequest(BaseModel):
    message: str
    # Prior turns, oldest first: [{"role": "user"|"assistant", "content": "..."}]
    history: Optional[list[dict]] = None


@router.post("")
async def chat(req: ChatRequest):
    reply = await chat_once(
        user_message=req.message,
        history=req.history,
        system_prompt=SYSTEM_PROMPT,
    )
    return {"reply": reply}


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    async def gen():
        try:
            async for chunk in stream_chat(
                user_message=req.message,
                history=req.history,
                system_prompt=SYSTEM_PROMPT,
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield 'data: {"done": true}\n\n'
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Chat of the WebUI: one answer at once (API-03) or as a run streamed with SSE (ADR-041, P2-02)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from moritz_agent.api.context import AppContext, require_login
from moritz_agent.core.principal import Principal, Role
from moritz_agent.core.runs import RunBusy
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn, TurnResult
from moritz_agent.phone.responder import ResponderUnavailable

router = APIRouter()


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = Field(default="web", max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    files: list[str] = Field(default_factory=list, max_length=5)  # ids from POST /api/files


def result_json(result: TurnResult, prompt_text: str = "") -> dict[str, Any]:
    """The answer for the web: text, the sources behind it and the follow-up buttons."""
    data = result.to_json()
    data["text"] = result.text or prompt_text
    return data


def web_turn(body: ChatBody, ctx: AppContext | None = None) -> Turn:
    principal = Principal("web:owner", Role.OWNER, "web", "Web")
    external = f"web:{body.conversation_id}"
    files = ctx.runtime.files if ctx is not None else None
    return Turn(
        body.message,
        principal,
        Surface.CHAT,
        external,
        place="web",
        reply_target="default",
        files=files.for_chat(external, body.files) if files is not None and body.files else [],
    )


@router.post("/api/chat")
async def chat(body: ChatBody, ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    turn = web_turn(body, ctx)
    try:
        result = await ctx.runtime.chat.run(turn)
    except ResponderUnavailable:
        raise HTTPException(503, {"error": "model_unavailable"}) from None
    data = result_json(result, ctx.prompt_text(result.prompt))
    data["conversation_id"] = body.conversation_id
    return data


# -- runs (ADR-041) ---------------------------------------------------------------------------------
def _sse(ctx: AppContext, events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        async for event in events:
            event = _for_web(ctx, event)
            data = json.dumps(event, ensure_ascii=False, default=str)
            yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {data}\n\n".encode()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _for_web(ctx: AppContext, event: dict[str, Any]) -> dict[str, Any]:
    """Announcement ids become their text; the final result gets the web form of the answer."""
    if event["type"] == "status" and event.get("prompt"):
        return {**event, "text": ctx.prompt_text(event["prompt"])}
    if event["type"] == "done":
        result = TurnResult.from_json(event["result"])
        return {**event, "result": result_json(result, ctx.prompt_text(result.prompt))}
    return event


@router.post("/api/chat/stream")
async def chat_stream(
    body: ChatBody, ctx: AppContext = Depends(require_login)
) -> StreamingResponse:
    """Start a run and follow it; the run goes on when the connection breaks."""
    try:
        run = ctx.runtime.runs.start(web_turn(body, ctx))
    except RunBusy:
        raise HTTPException(409, {"error": "busy"}) from None
    return _sse(ctx, ctx.runtime.runs.follow(run.id))


@router.get("/api/runs/{run_id}/events")
async def run_events(
    run_id: str,
    after: int = Query(0, ge=0),
    ctx: AppContext = Depends(require_login),
) -> StreamingResponse:
    """Follow a run again (after a reload, from another device) from event ``after`` on."""
    if ctx.runtime.runs.get(run_id) is None:
        raise HTTPException(404, {"error": "unknown_run"})
    return _sse(ctx, ctx.runtime.runs.follow(run_id, after))


@router.post("/api/runs/{run_id}/cancel")
async def run_cancel(run_id: str, ctx: AppContext = Depends(require_login)) -> dict[str, bool]:
    if ctx.runtime.runs.get(run_id) is None:
        raise HTTPException(404, {"error": "unknown_run"})
    return {"cancelled": ctx.runtime.runs.cancel(run_id)}

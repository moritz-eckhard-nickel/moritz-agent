# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Phone worker → main process, on a loopback port with a per-start token (docs/plan/02 §3, §9).

``/internal/phone/turn`` answers as a stream of JSON lines: ``{"type": "thinking", "prompt": …}``
as soon as a skill wants a more specific "one moment" announcement, then ``{"type": "reply", …}``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from moritz_agent.api.context import AppContext, require_internal
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import ResponderUnavailable

log = get_logger("phone")
router = APIRouter(prefix="/internal/phone")


class TurnBody(BaseModel):
    call_id: str = Field(max_length=100)
    text: str = Field(max_length=2000)


class CallBody(BaseModel):
    call_id: str = Field(max_length=100)


class EventBody(BaseModel):
    call_id: str = Field(max_length=100)
    event: str = Field(pattern=r"^(call_started|call_ended)$")
    remote: str = Field(default="", max_length=200)
    codec: str = Field(default="", max_length=40)
    reason: str = Field(default="", max_length=100)


def _line(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")


@router.post("/turn")
async def turn(body: TurnBody, ctx: AppContext = Depends(require_internal)) -> StreamingResponse:
    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in ctx.runtime.turn_events(body.call_id, body.text):
                if event["type"] == "thinking":
                    yield _line({"type": "thinking", "prompt": event["prompt"]})
                elif event["type"] == "cancelled":
                    yield _line({"type": "cancelled"})
                else:
                    reply = event["reply"]
                    timer = getattr(reply.result, "start_timer", None)  # (seconds, label)
                    yield _line(
                        {
                            "type": "reply",
                            "text": reply.text,
                            "prompt": reply.prompt,
                            "hangup": reply.hangup,
                            "skill_id": reply.skill_id,
                            "timer": list(timer) if timer else None,
                        }
                    )
        except ResponderUnavailable as exc:
            yield _line({"type": "error", "kind": "unavailable", "message": str(exc)})
        except Exception:
            log.exception("Antwort im Hauptprozess fehlgeschlagen")
            yield _line({"type": "error", "kind": "error"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/greeting_hint")
async def greeting_hint(body: CallBody, ctx: AppContext = Depends(require_internal)):
    return {"text": await ctx.runtime.greeting_hint(body.call_id)}


@router.post("/cancel")
async def cancel(body: CallBody, ctx: AppContext = Depends(require_internal)):
    return {"cancelled": ctx.runtime.cancel(body.call_id)}


@router.post("/event")
async def event(body: EventBody, ctx: AppContext = Depends(require_internal)):
    if body.event == "call_started":
        ctx.runtime.call_started(body.call_id, body.remote, body.codec)
    else:
        ctx.runtime.call_ended(body.call_id, body.reason)
    return {"ok": True}

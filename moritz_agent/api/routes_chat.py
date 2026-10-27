# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Text test path: the same pipeline as the telephone, without audio (API-03)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from moritz_agent.api.context import AppContext, require_login
from moritz_agent.core.principal import Principal, Role
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn, TurnResult
from moritz_agent.phone.responder import ResponderUnavailable

router = APIRouter()


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = Field(default="web", max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


def result_json(result: TurnResult, prompt_text: str = "") -> dict[str, Any]:
    """The answer for the web: text, the sources behind it and the follow-up buttons."""
    data = result.to_json()
    data["text"] = result.text or prompt_text
    return data


@router.post("/api/chat")
async def chat(body: ChatBody, ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    principal = Principal("web:owner", Role.OWNER, "web", "Web")
    turn = Turn(
        body.message,
        principal,
        Surface.CHAT,
        f"web:{body.conversation_id}",
        place="web",
        reply_target="default",
    )
    try:
        result = await ctx.runtime.chat.run(turn)
    except ResponderUnavailable:
        raise HTTPException(503, {"error": "model_unavailable"}) from None
    data = result_json(result, ctx.prompt_text(result.prompt))
    data["conversation_id"] = body.conversation_id
    return data

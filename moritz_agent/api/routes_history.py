# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""History of the WebUI: list, search, read, rename, pin, delete, export (docs/plan/15 P2-04)."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from moritz_agent.api.context import AppContext, require_login
from moritz_agent.storage.history import HistoryStore

router = APIRouter()
ID = r"^h-[0-9a-f]{16}$"


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None


def _store(ctx: AppContext) -> HistoryStore:
    if ctx.runtime.history is None:
        raise HTTPException(503, {"error": "storage_unavailable"})
    return ctx.runtime.history


def _web(item: dict[str, Any]) -> dict[str, Any]:
    """A web conversation can be continued in the chat: it gets the chat's own id."""
    if item["source"] == "web" and item["external_id"].startswith("web:"):
        item["chat_id"] = item["external_id"].removeprefix("web:")
    item.pop("external_id", None)
    return item


@router.get("/api/conversations")
async def conversations(
    q: str = Query("", max_length=200),
    source: Literal["web", "phone", "discord", "voice"] | None = None,
    pinned: bool | None = None,
    before: float | None = None,
    chat: str | None = Query(None, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"),
    limit: int = Query(50, ge=1, le=200),
    ctx: AppContext = Depends(require_login),
) -> dict[str, Any]:
    """Newest first; ``chat`` finds the conversation of one chat of the WebUI."""
    items = _store(ctx).list(
        query=q,
        source=source,
        pinned=pinned,
        before=before,
        limit=limit,
        external_id=f"web:{chat}" if chat else None,
    )
    return {"items": [_web(item) for item in items], "more": len(items) == limit}


@router.get("/api/conversations/{conversation}")
async def conversation(
    conversation: str, ctx: AppContext = Depends(require_login)
) -> dict[str, Any]:
    data = _store(ctx).get(conversation) if re.match(ID, conversation) else None
    if data is None:
        raise HTTPException(404, {"error": "unknown_conversation"})
    return _web(data)


@router.patch("/api/conversations/{conversation}")
async def change(
    conversation: str, body: ConversationPatch, ctx: AppContext = Depends(require_login)
) -> dict[str, Any]:
    store = _store(ctx)
    if not re.match(ID, conversation) or not store.update(
        conversation, title=body.title, pinned=body.pinned
    ):
        raise HTTPException(404, {"error": "unknown_conversation"})
    data = store.get(conversation)
    assert data is not None
    data.pop("messages", None)
    return _web(data)


@router.delete("/api/conversations/{conversation}")
async def remove(conversation: str, ctx: AppContext = Depends(require_login)) -> dict[str, bool]:
    if not re.match(ID, conversation) or not _store(ctx).delete(conversation):
        raise HTTPException(404, {"error": "unknown_conversation"})
    return {"deleted": True}


@router.get("/api/conversations/{conversation}/export.md")
async def export(conversation: str, ctx: AppContext = Depends(require_login)) -> Response:
    text = _store(ctx).markdown(conversation) if re.match(ID, conversation) else None
    if text is None:
        raise HTTPException(404, {"error": "unknown_conversation"})
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="anton-{conversation}.md"'},
    )

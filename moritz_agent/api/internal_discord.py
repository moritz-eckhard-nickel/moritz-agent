# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Discord worker → main process (loopback, per-start token): turns, outbox, people, admin.

The worker is only the connection to Discord. Who may do what is decided here once more (the role
comes from the configuration, never from the worker), and every answer is plain data.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from moritz_agent import __version__
from moritz_agent.api.context import AppContext, require_internal
from moritz_agent.core.chat import AccessDenied
from moritz_agent.core.principal import Role, discord_role
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import ResponderUnavailable

log = get_logger("discord")
router = APIRouter(prefix="/internal/discord")

SUBSCRIPTION_KINDS = {"warnings", "briefing", "waste", "system", "calls"}
OWNER_ONLY = {"system", "calls"}
_ID = r"^\d{1,25}$"
_CONVERSATION = r"^[A-Za-z0-9:_.-]{1,120}$"
_TARGET = r"^(default|dm:\d{1,25}|channel:\d{1,25})$"
LOG_LINES_MAX = 200


class TurnBody(BaseModel):
    conversation_id: str = Field(pattern=_CONVERSATION)
    text: str = Field(min_length=1, max_length=20000)
    user_id: str = Field(pattern=_ID)
    name: str = Field(default="", max_length=80)
    surface: Literal["chat", "spoken"] = "chat"
    place: Literal["dm", "guild", "thread", "voice"] = "dm"
    foreign_guild: bool = False
    reply_target: str = Field(default="default", pattern=_TARGET)


class ConversationBody(BaseModel):
    conversation_id: str = Field(pattern=_CONVERSATION)


class AckBody(BaseModel):
    id: int
    delivered: bool


class PrincipalBody(BaseModel):
    home: str | None = Field(default=None, max_length=80)  # postal code or name; "" = reset
    quiet_hours: str | None = Field(default=None, pattern=r"^(|\d\d:\d\d-\d\d:\d\d)$")
    voice_reply: Literal["mirror", "always", "never", ""] | None = None


class SubscriptionBody(BaseModel):
    kind: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class DrainBody(BaseModel):
    drain: bool


class FeedbackBody(BaseModel):
    skill_id: str = Field(default="agent", max_length=60)
    rating: Literal["up", "down"]


def _line(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _role(ctx: AppContext, user_id: str) -> Role:
    return discord_role(ctx.config.settings.discord, user_id)


def _owner(ctx: AppContext, user_id: str) -> None:
    if _role(ctx, user_id) is not Role.OWNER:
        raise HTTPException(403, {"error": "owner_only"})


# -- turns -------------------------------------------------------------------------------------------------------
@router.post("/turn")
async def turn(body: TurnBody, ctx: AppContext = Depends(require_internal)) -> StreamingResponse:
    role = _role(ctx, body.user_id)
    if role is Role.UNKNOWN:
        raise HTTPException(403, {"error": "forbidden"})
    principal = ctx.runtime.chat.principal(body.user_id, role, body.name)
    request = Turn(
        body.text,
        principal,
        Surface(body.surface),
        body.conversation_id,
        place=body.place,
        foreign_guild=body.foreign_guild,
        reply_target=body.reply_target,
    )
    if role is Role.OWNER and ctx.runtime.scheduler is not None:
        ctx.runtime.scheduler.ensure_defaults(body.user_id)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for event in ctx.runtime.chat.events(request):
                if event["type"] == "result":
                    yield _line({"type": "result", "result": event["result"].to_json()})
                else:
                    yield _line(event)
        except AccessDenied:
            yield _line({"type": "error", "kind": "forbidden"})
        except ResponderUnavailable as exc:
            yield _line({"type": "error", "kind": "unavailable", "message": str(exc)})
        except Exception:
            log.exception("Antwort für Discord fehlgeschlagen")
            yield _line({"type": "error", "kind": "error"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/cancel")
async def cancel(body: ConversationBody, ctx: AppContext = Depends(require_internal)):
    return {"cancelled": ctx.runtime.chat.cancel(body.conversation_id)}


@router.post("/end")
async def end(body: ConversationBody, ctx: AppContext = Depends(require_internal)):
    ctx.runtime.chat.end(body.conversation_id)
    return {"ok": True}


# -- outbox ----------------------------------------------------------------------------------------------------------
@router.get("/outbox")
async def outbox(limit: int = 20, ctx: AppContext = Depends(require_internal)):
    store = ctx.runtime.discord_store
    assert store is not None
    now = ctx.runtime.svc.now()
    items = store.pending(now, max(1, min(limit, 50)))
    return {
        "items": [
            {
                "id": i["id"],
                "kind": i["kind"],
                "target": i["target"],
                "user_id": i["user_id"],
                "serious": bool(i["serious"]),
                "payload": i["payload"],
            }
            for i in items
        ]
    }


@router.post("/outbox/ack")
async def ack(body: AckBody, ctx: AppContext = Depends(require_internal)):
    store = ctx.runtime.discord_store
    assert store is not None
    store.ack(body.id, body.delivered, ctx.runtime.svc.now())
    return {"ok": True}


# -- people and settings -------------------------------------------------------------------------------------
def _resolve_home(ctx: AppContext, text: str):
    gazetteer = ctx.runtime.svc.gazetteer
    if gazetteer is None:
        return None
    if re.fullmatch(r"\d{5}", text):
        return gazetteer.by_postcode(text)
    hit = gazetteer.find(text, limit=1).best
    return hit.place if hit else None


@router.get("/principal/{user_id}")
async def principal(user_id: str, ctx: AppContext = Depends(require_internal)):
    if not re.fullmatch(_ID, user_id):
        raise HTTPException(422)
    store = ctx.runtime.discord_store
    assert store is not None
    saved = store.principal(user_id) or {}
    return {
        "role": _role(ctx, user_id).value,
        "home_postal_code": saved.get("home_postal_code"),
        "home_name": saved.get("home_name"),
        "quiet_hours": saved.get("quiet_hours"),
        "voice_reply": saved.get("voice_reply"),
        "subscriptions": store.subscriptions(user_id=user_id),
        "reminders": len(store.open_reminders(user_id)),
    }


@router.put("/principal/{user_id}")
async def set_principal(
    user_id: str, body: PrincipalBody, ctx: AppContext = Depends(require_internal)
):
    if not re.fullmatch(_ID, user_id):
        raise HTTPException(422)
    role = _role(ctx, user_id)
    if role is Role.UNKNOWN:
        raise HTTPException(403, {"error": "forbidden"})
    store = ctx.runtime.discord_store
    assert store is not None
    changes: dict[str, str | None] = {}
    resolved = None
    if body.home is not None:
        if body.home == "":
            changes.update(home_postal_code=None, home_name=None)
        else:
            place = _resolve_home(ctx, body.home)
            if place is None:
                raise HTTPException(404, {"error": "unknown_place"})
            code = place.postal_codes[0] if place.postal_codes else None
            changes.update(home_postal_code=code, home_name=place.name)
            resolved = {"name": place.spoken, "postal_code": code}
    if body.quiet_hours is not None:
        changes["quiet_hours"] = body.quiet_hours or None
    if body.voice_reply is not None:
        changes["voice_reply"] = body.voice_reply or None
    store.save_principal(user_id, role.value, **changes)
    ctx.runtime.chat.forget_home(user_id)
    return {"ok": True, "home": resolved}


@router.put("/subscriptions/{user_id}")
async def subscribe(
    user_id: str, body: SubscriptionBody, ctx: AppContext = Depends(require_internal)
):
    if not re.fullmatch(_ID, user_id):
        raise HTTPException(422)
    role = _role(ctx, user_id)
    if role.rank < Role.TRUSTED.rank:
        raise HTTPException(403, {"error": "forbidden"})
    if body.kind not in SUBSCRIPTION_KINDS:
        raise HTTPException(422, {"error": "unknown_kind"})
    if body.kind in OWNER_ONLY and role is not Role.OWNER:
        raise HTTPException(403, {"error": "owner_only"})
    store = ctx.runtime.discord_store
    assert store is not None
    if not body.enabled:
        return {"ok": True, "removed": store.remove_subscription(user_id, body.kind)}
    params = _clean_params(body.kind, body.params)
    store.set_subscription(user_id, body.kind, params)
    return {"ok": True, "params": params}


def _clean_params(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind == "warnings":
        level = int(params.get("level", 3))
        return {"level": min(4, max(1, level))}
    if kind == "briefing":
        at = str(params.get("time", "06:45"))
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
            raise HTTPException(422, {"error": "bad_time"})
        return {"time": at, "weekdays": bool(params.get("weekdays", False))}
    return {}


@router.get("/reminders/{user_id}")
async def reminders(user_id: str, ctx: AppContext = Depends(require_internal)):
    store = ctx.runtime.discord_store
    assert store is not None
    return {"items": store.open_reminders(user_id)}


@router.delete("/reminders/{user_id}/{reminder_id}")
async def cancel_reminder(
    user_id: str, reminder_id: int, ctx: AppContext = Depends(require_internal)
):
    store = ctx.runtime.discord_store
    assert store is not None
    return {"cancelled": store.cancel_reminder(reminder_id, user_id)}


@router.post("/feedback")
async def feedback(body: FeedbackBody, ctx: AppContext = Depends(require_internal)):
    store = ctx.runtime.discord_store
    assert store is not None
    key = f"feedback:{body.skill_id}:{body.rating}"
    store.set_state(key, str(int(store.state(key) or 0) + 1))
    return {"ok": True}


# -- status and admin (owner) -----------------------------------------------------------------------------------
@router.get("/overview")
async def overview(ctx: AppContext = Depends(require_internal)):
    runtime = ctx.runtime
    data = runtime.status()
    data["phone"] = ctx.phone_status() or {}
    data["draining"] = ctx.draining()
    data["situation"] = await runtime.situation()
    data["calls"] = runtime.recent_calls(10)
    data.update(ctx.extra_status())
    return data


@router.post("/admin/reload")
async def admin_reload(user_id: str, ctx: AppContext = Depends(require_internal)):
    _owner(ctx, user_id)
    result = await ctx.reload() if ctx.reload is not None else ctx.config.reload()
    return result.summary()


@router.post("/admin/drain")
async def admin_drain(user_id: str, body: DrainBody, ctx: AppContext = Depends(require_internal)):
    _owner(ctx, user_id)
    if body.drain:
        ctx.drain_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.drain_path.touch()
    else:
        ctx.drain_path.unlink(missing_ok=True)
    return {"draining": ctx.draining()}


@router.post("/admin/restart")
async def admin_restart(user_id: str, ctx: AppContext = Depends(require_internal)):
    _owner(ctx, user_id)
    phone = ctx.phone_status() or {}
    if phone.get("in_call") or ctx.runtime.active_calls:
        raise HTTPException(409, {"error": "call_active"})
    if ctx.restart is None:
        raise HTTPException(501, {"error": "not_supported"})
    ctx.restart()
    return {"ok": True}


@router.get("/admin/logs")
async def admin_logs(
    user_id: str, category: str = "", lines: int = 100, ctx: AppContext = Depends(require_internal)
):
    """The last lines of the log file (already redacted when written, LOG-02), newest last."""
    _owner(ctx, user_id)
    settings = ctx.config.settings
    path = settings.resolve(settings.logging.file, ctx.root)
    wanted = max(1, min(lines, LOG_LINES_MAX))
    tail: deque[str] = deque(maxlen=wanted)
    tag = f"[{category.capitalize()}]" if category else ""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not tag or tag in line:
                    tail.append(line.rstrip("\n"))
    except OSError:
        return {"lines": []}
    return {"lines": list(tail), "version": __version__}

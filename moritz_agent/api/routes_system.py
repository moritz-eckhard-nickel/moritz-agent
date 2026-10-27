# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""System endpoints: health, login, status, reload, activity and drain (docs/plan/02 §9)."""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from moritz_agent.api.auth import COOKIE
from moritz_agent.api.context import (
    AppContext,
    get_ctx,
    require_admin,
    require_login,
)

router = APIRouter()


class LoginBody(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=500)


class DrainBody(BaseModel):
    drain: bool


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/api/system/health")
async def health(ctx: AppContext = Depends(get_ctx)) -> dict[str, bool]:
    """For systemd and the updater: nothing but "alive"."""
    return {"ok": ctx.runtime.db is not None}


@router.get("/api/session")
async def session(request: Request, ctx: AppContext = Depends(get_ctx)) -> dict[str, bool]:
    return {
        "login_configured": ctx.auth.enabled,
        "authenticated": ctx.auth.enabled and ctx.auth.valid(request.cookies.get(COOKIE)),
    }


@router.post("/api/login")
async def login(
    body: LoginBody, request: Request, response: Response, ctx: AppContext = Depends(get_ctx)
) -> dict[str, Any]:
    result = ctx.auth.login(body.username, body.password, _client_ip(request))
    if result.reason == "not_configured":
        raise HTTPException(403, {"error": "login_not_configured"})
    if result.reason == "locked":
        raise HTTPException(
            429,
            {"error": "too_many_attempts", "retry_after_s": result.retry_after_s},
            headers={"Retry-After": str(result.retry_after_s)},
        )
    if not result.ok:
        raise HTTPException(401, {"error": "wrong_credentials"})
    ttl = ctx.config.settings.server.session_ttl_hours * 3600
    response.set_cookie(
        COOKIE,
        result.token or "",
        max_age=ttl,
        httponly=True,
        samesite="strict",
        secure=ctx.secure_cookie,
        path="/",
    )
    return {"ok": True}


@router.post("/api/logout")
async def logout(request: Request, response: Response, ctx: AppContext = Depends(get_ctx)):
    ctx.auth.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/api/logout-everywhere")
async def logout_everywhere(response: Response, ctx: AppContext = Depends(require_login)):
    """Every device has to log in again, this one included."""
    ctx.auth.logout_everywhere()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/system/status")
async def status(ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    """Every component with state and message – never a credential (UI-01)."""
    data = ctx.runtime.status()
    data["phone"] = _phone_component(ctx)
    data["draining"] = ctx.draining()
    data.update(ctx.extra_status())
    return data


def _phone_component(ctx: AppContext) -> dict[str, Any]:
    status = ctx.phone_status()
    if status is None:
        if not ctx.config.settings.phone.enabled:
            return {"state": "disabled", "message": "Telefon ausgeschaltet"}
        return {"state": "failed", "message": "Der Telefonteil meldet sich nicht"}
    registration = str(status.get("registration") or "unbekannt")
    state = "ready" if registration.lower().startswith("regist") else "degraded"
    return {
        "state": state,
        "message": f"Registrierung: {registration}",
        "detail": {
            "in_call": bool(status.get("in_call")),
            "calls_total": status.get("calls_total", 0),
        },
    }


@router.post("/api/system/reload")
async def reload_config(ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    """Read config/moritz-agent.toml and passwords.txt again (CFG-05)."""
    result = await ctx.reload() if ctx.reload is not None else ctx.config.reload()
    return result.summary()


@router.get("/api/system/activity")
async def activity(ctx: AppContext = Depends(require_admin)) -> dict[str, Any]:
    phone = ctx.phone_status() or {}
    return {
        "in_call": bool(phone.get("in_call")) or ctx.runtime.active_calls > 0,
        "active_calls": ctx.runtime.active_calls,
        "generating": ctx.runtime.generating,
        "draining": ctx.draining(),
        "version": ctx.runtime.status()["version"],
    }


@router.post("/api/system/drain")
async def drain(body: DrainBody, ctx: AppContext = Depends(require_admin)) -> dict[str, bool]:
    """Update mode: no new calls (the phone reads the same file as the updater does)."""
    if body.drain:
        ctx.drain_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.drain_path.touch()
    else:
        with contextlib.suppress(FileNotFoundError):
            ctx.drain_path.unlink()
    return {"draining": ctx.draining()}

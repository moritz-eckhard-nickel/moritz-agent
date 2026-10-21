# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Phone status for the web interface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from moritz_agent.api.context import AppContext, require_login

router = APIRouter()

_PUBLIC = ("state", "registration", "in_call", "calls_total", "draining", "version", "updated")


@router.get("/api/phone/status")
async def phone_status(ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    """Registration, call state and readiness of the speech components."""
    status = ctx.phone_status()
    if status is None:
        return {"running": False, "draining": ctx.draining()}
    data = {key: status[key] for key in _PUBLIC if key in status}
    data["running"] = True
    if "skills" in status:
        data["skills"] = status["skills"]
    return data

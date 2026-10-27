# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Model page of the WebUI (docs/plan/15 P2-08): status, settings, restart, a quick measurement.

There is one model (F-44): nothing is switched, but its context, KV cache and ``--moecpu`` can be
changed and KoboldCpp restarted. During a call all of it is locked – the phone comes first.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from moritz_agent.api.context import AppContext, require_login
from moritz_agent.config.editing import EditError, restore, set_settings
from moritz_agent.inference import Priority
from moritz_agent.logging_setup import get_logger

router = APIRouter()
log = get_logger("inference")

# KV cache per token of Qwen3-30B-A3B (48 layers × 4 KV heads × 128 dims × K and V)
KV_BYTES_PER_TOKEN = {
    "f16": 2 * 48 * 4 * 128 * 2,
    "q8_0": 2 * 48 * 4 * 128 * 1.0625,
    "q4_0": 2 * 48 * 4 * 128 * 0.5625,
}
MEASURE_PROMPT = "Erzähl in etwa hundert Wörtern, warum Weilburg an der Lahn schön ist."


class ModelSettings(BaseModel):
    context_size: int | None = Field(default=None, ge=2048, le=262144)
    kv_cache: Literal["f16", "q8_0", "q4_0"] | None = None
    smart_cache: int | None = Field(default=None, ge=0, le=8)
    moe_cpu_layers: int | None = Field(default=None, ge=0, le=48)


def kv_gb(context: int, kv_cache: str) -> float:
    return round(context * KV_BYTES_PER_TOKEN.get(kv_cache, KV_BYTES_PER_TOKEN["f16"]) / 1024**3, 1)


async def gpu() -> dict[str, Any] | None:
    """Name and VRAM from nvidia-smi, if there is one (no GPU: None)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=name,memory.used,memory.total",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 3)
    except (OSError, TimeoutError):
        return None
    try:
        name, used, total = [part.strip() for part in out.decode().splitlines()[0].split(",")]
        return {"name": name, "vram_used_mb": int(used), "vram_total_mb": int(total)}
    except (IndexError, ValueError):
        return None


def _in_call(ctx: AppContext) -> bool:
    phone = ctx.phone_status() or {}
    return ctx.runtime.active_calls > 0 or bool(phone.get("in_call"))


@router.get("/api/model")
async def model(ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    settings = ctx.config.settings
    cfg = settings.inference
    path = settings.resolve(cfg.model, ctx.root)
    component = ctx.runtime.components().get("inference")
    perf: dict[str, Any] = {}
    queue = ctx.runtime.queue
    if queue is not None and component is not None and component.state == "ready":
        with contextlib.suppress(Exception):
            perf = await asyncio.wait_for(queue.client.perf(), 2)
    speed = perf.get("last_eval_speed")
    return {
        "state": component.state if component else "disabled",
        "message": component.message if component else "",
        "model": path.name,
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "settings": {
            "context_size": cfg.context_size,
            "kv_cache": cfg.kv_cache,
            "smart_cache": cfg.smart_cache,
            "moe_cpu_layers": cfg.moe_cpu_layers,
            "phone_context_tokens": settings.agent.phone.context_tokens,
        },
        "kv_estimate_gb": kv_gb(cfg.context_size, cfg.kv_cache),
        "tokens_per_s": round(float(speed), 1) if speed else None,
        "gpu": await gpu(),
        "managed": getattr(ctx.runtime, "inference", None) is not None,
        "in_call": _in_call(ctx),
    }


@router.put("/api/model/settings")
async def change(body: ModelSettings, ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    changes = [("inference", k, v) for k, v in body.model_dump(exclude_none=True).items()]
    if not changes:
        return {"ok": True, "restart_required": False}
    path = ctx.config.toml_path
    try:
        old = set_settings(path, changes)
    except EditError as exc:
        raise HTTPException(422, {"error": "invalid", "message": str(exc)}) from None
    result = await ctx.reload() if ctx.reload is not None else ctx.config.reload()
    if not result.ok:
        restore(path, old)
        ctx.config.reload()
        raise HTTPException(422, {"error": "invalid", "message": "; ".join(result.errors)})
    log.info("Modell-Einstellungen geändert: %s", ", ".join(k for _, k, _ in changes))
    return {"ok": True, "restart_required": "inference" in result.restart_required}


@router.post("/api/model/restart")
async def restart(ctx: AppContext = Depends(require_login)) -> dict[str, bool]:
    service = getattr(ctx.runtime, "inference", None)
    if service is None:
        raise HTTPException(
            409,
            {
                "error": "not_managed",
                "message": "KoboldCpp wird hier nicht von moritz-agent gestartet.",
            },
        )
    if _in_call(ctx):
        raise HTTPException(
            409,
            {"error": "in_call", "message": "Während eines Anrufs nicht – das Telefon geht vor."},
        )
    log.info("KoboldCpp wird aus der WebUI neu gestartet")
    task = asyncio.ensure_future(service.restart(ctx.config.settings))
    ctx.runtime.background(task)
    return {"restarting": True}


@router.post("/api/model/measure")
async def measure(ctx: AppContext = Depends(require_login)) -> dict[str, Any]:
    """A short answer at the lowest priority: first token, total time, tokens per second."""
    queue = ctx.runtime.queue
    component = ctx.runtime.components().get("inference")
    if queue is None or component is None or component.state != "ready":
        raise HTTPException(
            409,
            {"error": "model_unavailable", "message": "Das Sprachmodell ist gerade nicht bereit."},
        )
    if _in_call(ctx):
        raise HTTPException(
            409,
            {"error": "in_call", "message": "Während eines Anrufs nicht – das Telefon geht vor."},
        )
    started = time.monotonic()
    completion = await queue.chat(
        [{"role": "user", "content": MEASURE_PROMPT}],
        priority=Priority.BACKGROUND,
        label="measure",
        max_tokens=200,
        temperature=0.3,
    )
    perf: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        perf = await asyncio.wait_for(queue.client.perf(), 2)
    speed = perf.get("last_eval_speed")
    tokens = completion.completion_tokens
    total_ms = round((time.monotonic() - started) * 1000)
    if not speed and tokens and completion.total_ms:
        speed = tokens / (completion.total_ms / 1000)
    return {
        "first_token_ms": completion.first_token_ms,
        "total_ms": total_ms,
        "tokens": tokens,
        "tokens_per_s": round(float(speed), 1) if speed else None,
        "gpu": await gpu(),
    }

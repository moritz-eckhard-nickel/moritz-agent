# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Live view of the WebUI: status as Server-Sent Events and the end of the log (docs/plan/15 P2-07).

``/api/events`` sends the whole status whenever something changed – a call starts, Discord joins a
voice channel, a component fails – instead of the browser asking every few seconds. Content of calls
or chats is never part of it, only states (DISCORD-30). The log lines are redacted when written
(LOG-02); only their end is read, never the whole file.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from moritz_agent.api.context import AppContext, require_login
from moritz_agent.api.routes_system import status_snapshot

router = APIRouter()
POLL_S = 1.0
PING_S = 20.0
LOG_LINES_MAX = 500
TAIL_BYTES = 512 * 1024


def tail(path: Path, lines: int, tag: str = "") -> list[str]:
    """The last ``lines`` lines (with ``tag`` if given) from the end of the file only."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace").splitlines()
    if len(data) == TAIL_BYTES and text:
        text = text[1:]  # the first line was cut in the middle
    found: deque[str] = deque(maxlen=lines)
    for line in text:
        if not tag or tag in line:
            found.append(line)
    return list(found)


@router.get("/api/events")
async def events(request: Request, ctx: AppContext = Depends(require_login)) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        last = ""
        quiet = 0.0
        while not await request.is_disconnected():
            data = status_snapshot(ctx)
            # the uptime ticks every second: it alone is no reason to send
            key = json.dumps({k: v for k, v in data.items() if k != "uptime_s"}, default=str)
            if key != last:
                last = key
                quiet = 0.0
                snapshot = json.dumps(data, ensure_ascii=False, default=str)
                yield f"event: status\ndata: {snapshot}\n\n".encode()
            elif quiet >= PING_S:
                quiet = 0.0
                yield b": ping\n\n"  # keeps proxies and the browser from closing the stream
            await asyncio.sleep(POLL_S)
            quiet += POLL_S

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/system/logs")
async def logs(
    lines: int = Query(200, ge=1, le=LOG_LINES_MAX),
    category: str = Query("", max_length=20, pattern=r"^[A-Za-z]*$"),
    ctx: AppContext = Depends(require_login),
) -> dict[str, Any]:
    settings = ctx.config.settings
    path = settings.resolve(settings.logging.file, ctx.root)
    tag = f"[{category.capitalize()}]" if category else ""
    return {"lines": await asyncio.to_thread(tail, path, lines, tag)}

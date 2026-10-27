# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Files for the WebUI chat: upload as the raw body (no form parsing), download, delete (P2-05)."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from moritz_agent.api.context import AppContext, require_login
from moritz_agent.storage.files import MAX_BYTES, FileRejected, FileStore

router = APIRouter()
FILE_ID = r"^f-[0-9a-f]{16}$"
READ_TIMEOUT_S = 30.0  # a hostile PDF must not keep a worker busy forever


def _files(ctx: AppContext) -> FileStore:
    if ctx.runtime.files is None:
        raise HTTPException(503, {"error": "storage_unavailable"})
    return ctx.runtime.files


def _public(info: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in info.items() if key != "external_id"}


@router.post("/api/files")
async def upload(
    request: Request,
    chat: str = Query(..., max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"),
    name: str = Query(..., min_length=1, max_length=200),
    ctx: AppContext = Depends(require_login),
) -> dict[str, Any]:
    store = _files(ctx)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(
            413, {"error": "too_large", "message": "Die Datei ist größer als 10 MB."}
        )
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BYTES:
            raise HTTPException(
                413, {"error": "too_large", "message": "Die Datei ist größer als 10 MB."}
            )
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(store.add, f"web:{chat}", name, bytes(data)), READ_TIMEOUT_S
        )
    except FileRejected as exc:
        raise HTTPException(422, {"error": "unreadable", "message": str(exc)}) from None
    except TimeoutError:
        raise HTTPException(
            422, {"error": "unreadable", "message": "Die Datei zu lesen hat zu lange gedauert."}
        ) from None
    return _public(info)


@router.get("/api/files/{file_id}")
async def download(file_id: str, ctx: AppContext = Depends(require_login)) -> Response:
    store = _files(ctx)
    info = store.info(file_id) if re.match(FILE_ID, file_id) else None
    if info is None:
        raise HTTPException(404, {"error": "unknown_file"})
    try:
        data = store.data(file_id)
    except OSError:
        raise HTTPException(404, {"error": "unknown_file"}) from None
    # always a download, never shown in the browser: a file is data, not a page
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(info['name'])}"},
    )


@router.delete("/api/files/{file_id}")
async def remove(file_id: str, ctx: AppContext = Depends(require_login)) -> dict[str, bool]:
    if not re.match(FILE_ID, file_id) or not _files(ctx).delete(file_id):
        raise HTTPException(404, {"error": "unknown_file"})
    return {"deleted": True}

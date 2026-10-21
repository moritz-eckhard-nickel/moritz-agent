# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The two FastAPI applications: the web interface (LAN, login) and the internal one (loopback)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from moritz_agent.api import internal, internal_discord, routes_chat, routes_phone, routes_system
from moritz_agent.api.context import AppContext

STATUS_DIR = "frontend/status"
BRANDING_DIR = "assets/branding"
_BRANDING_FILES = {
    "m-agent-logo.svg",
    "m-agent-logo-64.png",
    "m-agent-logo-192.png",
    "m-agent-logo-512.png",
    "m-agent.ico",
    "scribbles/scribbles-black.svg",
    "scribbles/scribbles-white.svg",
    "scribbles/scribbles-black-512.png",
    "scribbles/scribbles-white-512.png",
}
_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _security(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        # a browser tab of another site must not be able to act with the session cookie
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if origin and urlsplit(origin).netloc != host:
                return JSONResponse({"detail": {"error": "bad_origin"}}, status_code=403)
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _CSP
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(ctx: AppContext) -> FastAPI:
    """The web interface on port 3501: status page, login, system and chat endpoints."""
    app = FastAPI(
        title="moritz-agent", docs_url=None, redoc_url=None, openapi_url=None, version="1"
    )
    app.state.ctx = ctx
    _security(app)
    app.include_router(routes_system.router)
    app.include_router(routes_phone.router)
    app.include_router(routes_chat.router)

    status_dir = ctx.root / STATUS_DIR
    branding_dir = ctx.root / BRANDING_DIR

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(status_dir / "index.html", media_type="text/html")

    @app.get("/static/{name}", include_in_schema=False)
    async def static(name: str) -> FileResponse:
        path = (status_dir / name).resolve()
        if path.parent != status_dir.resolve() or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    @app.get("/branding/{name:path}", include_in_schema=False)
    async def branding(name: str) -> FileResponse:
        if name not in _BRANDING_FILES or not (branding_dir / name).is_file():
            raise HTTPException(404)
        return FileResponse(branding_dir / name)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(branding_dir / "m-agent.ico")

    return app


def create_internal_app(ctx: AppContext) -> FastAPI:
    """Loopback only: phone worker → main process (never reachable from the network)."""
    app = FastAPI(title="moritz-agent internal", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ctx = ctx
    app.include_router(internal.router)
    app.include_router(internal_discord.router)
    return app


def ensure_run_dir(root: Path) -> Path:
    directory = root / "data" / "run"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

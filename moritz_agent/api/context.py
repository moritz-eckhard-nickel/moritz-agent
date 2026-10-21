# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""What the API handlers need from the running system (no globals: tests build their own)."""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from moritz_agent.api.auth import COOKIE, Authenticator
from moritz_agent.config.reload import ConfigManager, ReloadResult
from moritz_agent.phone.control import DRAIN_FILE, read_status, run_dir
from moritz_agent.runtime import Runtime

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class AppContext:
    runtime: Runtime
    config: ConfigManager
    auth: Authenticator
    root: Path
    internal_token: str = field(default_factory=new_token)
    admin_token: str = field(default_factory=new_token)
    secure_cookie: bool = True
    data_root: Path | None = None  # where data/run lives (the installation; tests use a temp dir)
    # supervisor hooks; the defaults make the API usable on its own (tests, `ask`)
    reload: Callable[[], Awaitable[ReloadResult]] | None = None
    restart: Callable[[], None] | None = None  # leave with the exit code that makes systemd restart
    extra_status: Callable[[], dict[str, Any]] = field(default_factory=lambda: dict)

    def prompt_text(self, prompt_id: str | None) -> str:
        """The spoken text of an announcement ("starting_up"), for chat surfaces."""
        if not prompt_id:
            return ""
        from moritz_agent.phone.audio.announcements import load_catalog

        phone = self.config.settings.phone
        try:
            catalog = load_catalog(
                self.root / "assets/audio/prompts.de.toml",
                {"greeting_text": phone.greeting_text, "assistant_name": phone.assistant_name},
            )
        except (OSError, KeyError, ValueError):
            return ""
        entry = catalog.get(prompt_id)
        return entry.text if entry else ""

    @property
    def state_root(self) -> Path:
        return self.data_root or self.root

    def phone_status(self) -> dict[str, Any] | None:
        return read_status(self.state_root)

    @property
    def drain_path(self) -> Path:
        return run_dir(self.state_root) / DRAIN_FILE

    def draining(self) -> bool:
        return self.drain_path.exists()


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx  # type: ignore[no-any-return]


def require_login(request: Request) -> AppContext:
    """The web login protects everything except the health check (API-05)."""
    ctx = get_ctx(request)
    if not ctx.auth.enabled:
        raise HTTPException(403, {"error": "login_not_configured"})
    if not ctx.auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, {"error": "login_required"})
    return ctx


def require_admin(request: Request) -> AppContext:
    """Updater access: the token file of this start, from the machine itself only."""
    ctx = get_ctx(request)
    client = request.client.host if request.client else ""
    given = request.headers.get("x-admin-token", "")
    if client not in LOOPBACK_HOSTS or not hmac.compare_digest(given, ctx.admin_token):
        raise HTTPException(403, {"error": "forbidden"})
    return ctx


def require_internal(request: Request) -> AppContext:
    """Phone worker → main process: the per-start token (docs/plan/02 §3)."""
    ctx = get_ctx(request)
    given = request.headers.get("x-internal-token", "")
    if not hmac.compare_digest(given, ctx.internal_token):
        raise HTTPException(403, {"error": "forbidden"})
    return ctx

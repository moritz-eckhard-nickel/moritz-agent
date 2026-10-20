# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""SearXNG as a managed child process on a free loopback port (ADR-007, P1-08)."""

from __future__ import annotations

import secrets
from pathlib import Path

from moritz_agent.config.settings import Settings
from moritz_agent.process import ManagedProcess, find_free_port
from moritz_agent.research.searxng_client import SearxngClient


def build_argv(settings: Settings, root: Path, port: int) -> list[str]:
    venv = settings.resolve(settings.search.searxng_venv, root)
    return [
        str(venv / "bin" / "granian"),
        "--interface",
        "wsgi",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
        "--blocking-threads",
        "4",
        "searx.webapp:app",
    ]


def build_env(settings: Settings, root: Path, port: int) -> dict[str, str]:
    """Environment of the worker.

    ``SEARXNG_SECRET`` is a throw-away key (cookies/image proxy of an instance that has no public
    access); it is not a credential, is new on every start and is stored nowhere.
    """
    return {
        "SEARXNG_SETTINGS_PATH": str(settings.resolve(settings.search.searxng_settings, root)),
        "SEARXNG_SECRET": secrets.token_hex(32),
        "SEARXNG_BIND_ADDRESS": "127.0.0.1",
        "SEARXNG_PORT": str(port),
        "PYTHONPATH": str(settings.resolve(settings.search.searxng_source, root)),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def installed(settings: Settings, root: Path) -> bool:
    """The separate SearXNG environment exists (scripts/setup-searxng.sh ran)."""
    venv = settings.resolve(settings.search.searxng_venv, root)
    return (venv / "bin" / "granian").exists()


class SearxngService:
    """The SearXNG worker and the client that talks to it."""

    def __init__(self, settings: Settings, root: Path, *, port: int | None = None) -> None:
        self.settings = settings
        self.root = root
        self.port = port or find_free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        cfg = settings.search
        self.client = SearxngClient(
            self.url,
            language=cfg.language,
            safesearch=cfg.safesearch,
            timeout_s=cfg.timeout_s,
        )
        self.process = ManagedProcess(
            "searxng",
            build_argv(settings, root, self.port),
            env=build_env(settings, root, self.port),
            cwd=settings.resolve(cfg.searxng_source, root),
            health_check=self.client.health,
            category="search",
            startup_timeout_s=cfg.searxng_startup_timeout_s,
            health_interval_s=10.0,
            niceness=5,
        )

    async def start(self) -> None:
        await self.process.start()

    async def stop(self) -> None:
        await self.process.stop(5)
        await self.client.aclose()

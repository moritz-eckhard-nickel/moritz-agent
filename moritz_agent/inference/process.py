# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Start arguments and process wrapper for KoboldCpp as a child process (ADR-003, P1-05)."""

from __future__ import annotations

import sys
from pathlib import Path

from moritz_agent.config.settings import Settings
from moritz_agent.inference.client import InferenceClient
from moritz_agent.process import ManagedProcess, find_free_port


def build_argv(settings: Settings, root: Path, port: int, python: str | None = None) -> list[str]:
    """The KoboldCpp command line for the configured model (loopback only, one request at a time)."""
    cfg = settings.inference
    argv = [
        python or sys.executable,
        str(settings.resolve(cfg.koboldcpp_script, root)),
        "--model",
        str(settings.resolve(cfg.model, root)),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--contextsize",
        str(cfg.context_size),
        "--gpulayers",
        str(cfg.gpu_layers if cfg.use_cuda else 0),
        "--skiplauncher",
        "--quiet",
        "--parallelrequests",
        "1",
    ]
    if cfg.use_cuda:
        argv += ["--usecuda"]
    if cfg.moe_cpu_layers:
        argv += ["--moecpu", str(cfg.moe_cpu_layers)]
    if cfg.threads:
        argv += ["--threads", str(cfg.threads)]
    if cfg.batch_threads:
        argv += ["--blasthreads", str(cfg.batch_threads)]
    if cfg.jinja:
        argv += ["--jinja"]
    if cfg.chat_adapter:
        argv += ["--chatcompletionsadapter", str(settings.resolve(cfg.chat_adapter, root))]
    if cfg.websearch_fallback:
        argv += ["--websearch"]
    return argv


class InferenceService:
    """KoboldCpp as a managed child process plus the client that talks to it."""

    def __init__(self, settings: Settings, root: Path, *, port: int | None = None) -> None:
        self.settings = settings
        self.root = root
        self.port = port or find_free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.client = InferenceClient(
            self.url, request_timeout_s=settings.inference.request_timeout_s
        )
        self.process = ManagedProcess(
            "koboldcpp",
            build_argv(settings, root, self.port),
            cwd=root,
            health_check=self.client.health,
            category="inference",
            startup_timeout_s=settings.inference.startup_timeout_s,
            health_interval_s=5.0,
        )

    async def start(self) -> None:
        await self.process.start()

    async def stop(self) -> None:
        await self.process.stop(10)
        await self.client.aclose()

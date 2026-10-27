# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Start arguments and process wrapper for KoboldCpp as a child process (ADR-003, P1-05)."""

from __future__ import annotations

import sys
from pathlib import Path

from moritz_agent.config.settings import Settings
from moritz_agent.inference.client import InferenceClient
from moritz_agent.process import ManagedProcess, find_free_port

# ``./koboldcpp.sh rebuild`` (ADR-015) builds the libraries next to koboldcpp.py and a Python with
# KoboldCpp's own packages (jinja2 for --jinja, CUDA runtime) in this micromamba environment –
# both relative to the folder of koboldcpp.py (the repository, or <prefix>/koboldcpp when installed).
CONDA_PYTHON = "conda/envs/linux/bin/python"
GPU_LIBRARY = "koboldcpp_cublas.so"
CPU_LIBRARY = "koboldcpp_default.so"


def koboldcpp_python(settings: Settings, root: Path) -> str:
    """``[inference] python`` if set, else KoboldCpp's build environment, else this Python."""
    cfg = settings.inference
    if cfg.python:
        return str(settings.resolve(cfg.python, root))
    conda = settings.resolve(cfg.koboldcpp_script, root).parent / CONDA_PYTHON
    return str(conda) if conda.is_file() else sys.executable


def koboldcpp_built(settings: Settings, root: Path) -> bool:
    """Is the KoboldCpp library for this configuration there (``./test-3.sh setup`` builds it)?"""
    script = settings.resolve(settings.inference.koboldcpp_script, root)
    return (script.parent / (GPU_LIBRARY if settings.inference.use_cuda else CPU_LIBRARY)).is_file()


def build_argv(settings: Settings, root: Path, port: int, python: str | None = None) -> list[str]:
    """The KoboldCpp command line for the configured model (loopback only, one request at a time)."""
    cfg = settings.inference
    argv = [
        python or koboldcpp_python(settings, root),
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
    if cfg.flash_attention and cfg.use_cuda:
        argv += ["--flashattention"]
    if cfg.kv_cache != "f16":
        argv += ["--quantkv", cfg.kv_cache]
    if cfg.smart_cache:
        argv += ["--smartcache", str(cfg.smart_cache)]
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
        self.process = self._process()

    def _process(self) -> ManagedProcess:
        return ManagedProcess(
            "koboldcpp",
            build_argv(self.settings, self.root, self.port),
            cwd=self.root,
            health_check=self.client.health,
            category="inference",
            startup_timeout_s=self.settings.inference.startup_timeout_s,
            health_interval_s=5.0,
        )

    async def start(self) -> None:
        await self.process.start()

    async def restart(self, settings: Settings) -> None:
        """Unload, then load with the current settings (context, KV cache, --moecpu …) on the
        same port – the client and the queue keep working with it (P2-08)."""
        await self.process.stop(10)
        self.settings = settings
        self.process = self._process()
        await self.process.start()

    async def stop(self) -> None:
        await self.process.stop(10)
        await self.client.aclose()

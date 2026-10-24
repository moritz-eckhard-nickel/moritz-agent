# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Child processes with health check and restart backoff (P1-04, docs/plan/02 §3).

``ManagedProcess`` starts a program, forwards its output line by line to the log, restarts it
with a growing pause (2 s → 60 s by default, reset after a stable run) and stops it politely
(SIGTERM, then SIGKILL of the whole process group).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
import socket
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from moritz_agent.logging_setup import get_logger

MAX_LINE_BYTES = 8192  # longer output lines are logged in pieces

HealthCheck = Callable[[], Awaitable[bool]]


def find_free_port(host: str = "127.0.0.1") -> int:
    """A currently unused TCP port on ``host``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@dataclass
class ProcessStatus:
    name: str
    state: str = "stopped"  # stopped | starting | ready | degraded | failed | stopping
    pid: int | None = None
    restarts: int = 0
    last_exit: int | None = None
    message: str = ""
    since: float = field(default_factory=time.time)


class ManagedProcess:
    def __init__(
        self,
        name: str,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | str | None = None,
        health_check: HealthCheck | None = None,
        backoff: tuple[float, float] = (2.0, 60.0),
        category: str = "system",
        stable_after_s: float = 30.0,
        health_interval_s: float = 5.0,
        health_failures: int = 3,
        startup_timeout_s: float = 180.0,
        niceness: int = 0,
        on_state: Callable[[ProcessStatus], None] | None = None,
        argv_factory: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        self.name = name
        self.argv = list(argv)
        self.argv_factory = argv_factory  # asked before every (re)start, e.g. for another Python
        self.env = dict(env) if env is not None else None
        self.cwd = cwd
        self.health_check = health_check
        self.backoff = backoff
        self.stable_after_s = stable_after_s
        self.health_interval_s = health_interval_s
        self.health_failures = health_failures
        self.startup_timeout_s = startup_timeout_s
        self.niceness = niceness
        self.on_state = on_state
        self.log = get_logger(category)
        self._status = ProcessStatus(name)
        self._task: asyncio.Task[None] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()

    # -- public ---------------------------------------------------------------------------------
    def status(self) -> ProcessStatus:
        return self._status

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def alive(self) -> bool:
        """Supervised: the child runs or waits for its next restart (``stop()`` ends this)."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.ensure_future(self._supervise())

    async def wait_ready(self, timeout: float | None = None) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except TimeoutError:
            return False
        return True

    async def stop(self, grace_s: float = 10.0) -> None:
        self._stop.set()
        self._set("stopping")
        await self._terminate(grace_s)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None
        self._set("stopped")

    # -- internals --------------------------------------------------------------------------------
    def _set(self, state: str, message: str = "") -> None:
        status = self._status
        if state != status.state or message != status.message:
            status.state, status.message, status.since = state, message, time.time()
            if state != "ready":
                self._ready.clear()
            if self.on_state is not None:
                with contextlib.suppress(Exception):
                    self.on_state(status)

    async def _supervise(self) -> None:
        pause = self.backoff[0]
        while not self._stop.is_set():
            started = time.monotonic()
            self._set("starting")
            try:
                await self._run_once()
            except FileNotFoundError:
                self._set("failed", "Programm nicht gefunden")
                self.log.error("%s: Programm nicht gefunden (%s)", self.name, self.argv[0])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._set("failed", type(exc).__name__)
                self.log.error("%s: Start fehlgeschlagen (%s)", self.name, type(exc).__name__)
            if self._stop.is_set():
                return
            if time.monotonic() - started >= self.stable_after_s:
                pause = self.backoff[0]
            self._set("failed", f"beendet (Code {self._status.last_exit}), Neustart in {pause:g} s")
            self.log.warning(
                "%s ist beendet (Code %s) – Neustart in %g s",
                self.name,
                self._status.last_exit,
                pause,
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), pause)
            pause = min(pause * 2, self.backoff[1])
            self._status.restarts += 1

    async def _run_once(self) -> None:
        if self.argv_factory is not None:
            self.argv = list(self.argv_factory())
        env = {**os.environ, **self.env} if self.env is not None else None
        self._proc = proc = await asyncio.create_subprocess_exec(
            *self.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
            cwd=self.cwd,
            start_new_session=True,  # one process group: stopping kills the children too
            preexec_fn=(lambda: os.nice(self.niceness)) if self.niceness else None,
        )
        self._status.pid = proc.pid
        self.log.info("%s gestartet (PID %d)", self.name, proc.pid)
        reader = asyncio.ensure_future(self._forward(proc))
        watcher = asyncio.ensure_future(self._watch_health(proc)) if self.health_check else None
        if watcher is None:
            self._set("ready")
            self._ready.set()
        try:
            code = await proc.wait()
        finally:
            for task in (watcher, reader):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
        self._status.last_exit = code
        self._status.pid = None

    async def _forward(self, proc: asyncio.subprocess.Process) -> None:
        """Log the child's output line by line. Reads chunks (not ``readline``) so an overlong line
        or a progress bar that only uses ``\r`` never stops the reader – the child would then block
        on a full pipe."""
        assert proc.stdout is not None
        pending = b""
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                self._log_output(pending)
                return
            parts = re.split(rb"[\r\n]", pending + chunk)
            pending = parts.pop()
            if len(pending) > MAX_LINE_BYTES:
                parts.append(pending)
                pending = b""
            for part in parts:
                self._log_output(part)

    def _log_output(self, raw: bytes) -> None:
        text = raw[:MAX_LINE_BYTES].decode("utf-8", errors="replace").rstrip()
        if text:
            self.log.info("[%s] %s", self.name, text)

    async def _watch_health(self, proc: asyncio.subprocess.Process) -> None:
        assert self.health_check is not None
        began = time.monotonic()
        failures = 0
        while proc.returncode is None:
            try:
                ok = await asyncio.wait_for(self.health_check(), timeout=10.0)
            except Exception:
                ok = False
            if ok:
                failures = 0
                if self._status.state != "ready":
                    self._set("ready")
                    self._ready.set()
            elif self._status.state == "starting":
                if time.monotonic() - began > self.startup_timeout_s:
                    self.log.error("%s: Start dauerte zu lange – wird neu gestartet", self.name)
                    await self._terminate(5.0)
                    return
            else:
                failures += 1
                self._set("degraded", "Health-Check schlägt fehl")
                if failures >= self.health_failures:
                    self.log.error("%s reagiert nicht – wird neu gestartet", self.name)
                    await self._terminate(5.0)
                    return
            # look more often while starting, so "ready" is noticed within a second
            await asyncio.sleep(
                min(self.health_interval_s, 1.0)
                if self._status.state == "starting"
                else self.health_interval_s
            )

    async def _terminate(self, grace_s: float) -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        self._signal(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), grace_s)
        except TimeoutError:
            self.log.warning("%s reagiert nicht auf SIGTERM – SIGKILL", self.name)
            self._signal(proc, signal.SIGKILL)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5.0)

    @staticmethod
    def _signal(proc: asyncio.subprocess.Process, sig: signal.Signals) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sig)

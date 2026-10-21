# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Supervisor: startup order, child processes, signals, shutdown (P1-04, docs/plan/02 §3–§4).

Startup: config → logging → storage → runtime (skills, search, model: the two worker processes start
in the background and may take a minute) → tokens and internal API → web interface → phone worker
→ Discord worker. The phone registers before the model is loaded (PHONE-33). Shutdown runs the other
way round, with the phone first so that a running call gets its BYE (docs/plan/04 P1-04).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any

import uvicorn

from moritz_agent import __version__
from moritz_agent.api.app import create_app, create_internal_app, ensure_run_dir
from moritz_agent.api.auth import Authenticator
from moritz_agent.api.context import AppContext
from moritz_agent.api.tls import ensure_certificate
from moritz_agent.config.reload import ConfigError, ConfigManager, ReloadResult
from moritz_agent.config.settings import REPO_ROOT
from moritz_agent.config.validate import effective_host
from moritz_agent.discord import status as discord_status
from moritz_agent.logging_setup import get_logger, setup_logging
from moritz_agent.phone.control import read_status
from moritz_agent.process import ManagedProcess, find_free_port
from moritz_agent.runtime import Component, Runtime

log = get_logger("system")
PHONE_STOP_GRACE_S = 10.0
DISCORD_NICE = 5  # computes after the phone (docs/plan/14 §4.2)
MAINTENANCE_INTERVAL_S = 60.0
BACKUPS_KEPT = 7
ADMIN_TOKEN_FILE = "admin.token"


class _Server(uvicorn.Server):
    """uvicorn without its own signal handling: the supervisor decides when to stop."""

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


class Supervisor:
    def __init__(
        self,
        root: Path = REPO_ROOT,
        *,
        state_root: Path | None = None,
        settings_file: Path | None = None,
        passwords_file: Path | None = None,
        serve_web: bool = True,
        start_phone: bool = True,
        start_discord: bool = True,
        manage_processes: bool = True,
        phone_argv: list[str] | None = None,
        discord_argv: list[str] | None = None,
        runtime_options: dict[str, Any] | None = None,
    ) -> None:
        self.root = root
        self.state_root = state_root or root  # where data/run and data/backups live
        self.settings_file = settings_file
        self.passwords_file = passwords_file
        self.serve_web = serve_web
        self.start_phone = start_phone
        self.start_discord = start_discord
        self.manage_processes = manage_processes
        self.phone_argv = phone_argv
        self.discord_argv = discord_argv
        self.runtime_options = runtime_options or {}
        self.config = ConfigManager(settings_file, passwords_file, root)
        self.runtime: Runtime | None = None
        self.ctx: AppContext | None = None
        self.phone: ManagedProcess | None = None
        self.discord: ManagedProcess | None = None
        self.internal_port = 0
        self.web_state = Component("starting")
        self.exit_code = 0
        self._servers: list[tuple[_Server, asyncio.Task[None]]] = []
        self._stop = asyncio.Event()
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- entry point ------------------------------------------------------------------------------
    async def run(self) -> int:
        try:
            self.prepare()
        except ConfigError as exc:
            print("Konfiguration fehlerhaft, Start abgebrochen:", file=sys.stderr)
            for issue in exc.report.errors:
                print(f"  {issue.where}: {issue.message}", file=sys.stderr)
            return 2
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        loop.add_signal_handler(signal.SIGHUP, lambda: self._spawn(self.reload()))
        try:
            await self.start()
        except Exception:
            log.exception("Start fehlgeschlagen")
            await self.shutdown()
            return 1
        log.info("Bereit. Weboberfläche: %s", self.web_state.message or "aus")
        try:
            await self._stop.wait()
        finally:
            log.info("Beende …")
            await self.shutdown()
        return self.exit_code

    def prepare(self) -> None:
        """Load and check both files, start logging. Raises ``ConfigError``."""
        if self.config.loaded:
            return
        self.config.load()
        self._setup_logging()
        for issue in self.config.warnings:
            log.warning("%s: %s", issue.where, issue.message)
        log.info("moritz-agent %s startet", __version__)

    def _setup_logging(self) -> None:
        settings = self.config.settings
        setup_logging(
            settings.logging.level,
            settings.resolve(settings.logging.file, self.root),
            self.config.passwords.secret_values(),
            settings.logging.max_bytes,
            settings.logging.backup_count,
        )

    # -- start --------------------------------------------------------------------------------------
    async def start(self) -> None:
        self.prepare()
        settings = self.config.settings
        self.runtime = Runtime(
            self.config, self.root, manage_processes=self.manage_processes, **self.runtime_options
        )
        await self.runtime.start()
        state_dir = ensure_run_dir(self.state_root)
        self.ctx = AppContext(
            runtime=self.runtime,
            config=self.config,
            auth=Authenticator(lambda: self.config.current),
            root=self.root,
            data_root=self.state_root,
            secure_cookie=settings.server.tls,
            reload=self.reload,
            restart=self.request_restart,
            extra_status=self._extra_status,
        )
        self.runtime.external_components = self._child_components
        self._write_admin_token(state_dir / ADMIN_TOKEN_FILE, self.ctx.admin_token)
        await self._start_internal_api()
        if self.serve_web:
            await self._start_web()
        else:
            self.web_state = Component("disabled", "nicht gestartet")
        if self.start_phone and settings.phone.enabled:
            await self._start_phone()
        if self.start_discord:
            await self._start_discord()
        self._spawn(self._maintenance())

    @staticmethod
    def _write_admin_token(path: Path, token: str) -> None:
        """New on every start; readable by the service user (and root, i.e. the updater) only."""
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
        path.chmod(0o600)

    async def _serve(self, app: Any, host: str, port: int, **ssl: str) -> _Server:
        config = uvicorn.Config(
            app, host=host, port=port, log_config=None, access_log=False, lifespan="off", **ssl
        )
        server = _Server(config)
        task = asyncio.ensure_future(self._run_server(server))
        self._servers.append((server, task))
        for _ in range(100):  # up to 5 s
            if server.started or task.done():
                break
            await asyncio.sleep(0.05)
        if not server.started:
            raise OSError(f"{host}:{port} konnte nicht geöffnet werden")
        return server

    @staticmethod
    async def _run_server(server: _Server) -> None:
        """uvicorn ends the process with ``sys.exit`` when it cannot bind: not here."""
        with contextlib.suppress(SystemExit):
            await server.serve()

    async def _start_internal_api(self) -> None:
        assert self.ctx is not None
        self.internal_port = find_free_port()
        await self._serve(create_internal_app(self.ctx), "127.0.0.1", self.internal_port)
        log.info("Interne Schnittstelle auf 127.0.0.1:%d", self.internal_port)

    async def _start_web(self) -> None:
        assert self.ctx is not None
        settings = self.config.settings
        host = effective_host(settings, self.config.passwords)
        ssl: dict[str, str] = {}
        if settings.server.tls:
            cert = settings.resolve(settings.server.tls_cert, self.root)
            key = settings.resolve(settings.server.tls_key, self.root)
            if not await asyncio.to_thread(ensure_certificate, cert, key):
                self.web_state = Component(
                    "failed", "TLS-Zertifikat fehlt und lässt sich nicht erzeugen"
                )
                log.error("Weboberfläche nicht gestartet: kein TLS-Zertifikat")
                return
            ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        try:
            await self._serve(create_app(self.ctx), host, settings.server.port, **ssl)
        except OSError as exc:
            self.web_state = Component("failed", str(exc))
            log.error("Weboberfläche nicht gestartet: %s", exc)
            return
        scheme = "https" if ssl else "http"
        where = f"{scheme}://{host}:{settings.server.port}"
        if host != settings.server.host:
            self.web_state = Component(
                "degraded", f"{where}, nur lokal: in passwords.txt ist kein Web-Login eingerichtet"
            )
        else:
            self.web_state = Component("ready", where)

    async def _start_phone(self) -> None:
        argv = self.phone_argv or [sys.executable, "-m", "moritz_agent.phone", "run"]
        if self.phone_argv is None:
            if self.settings_file:
                argv += ["--config", str(self.settings_file)]
            if self.passwords_file:
                argv += ["--passwords", str(self.passwords_file)]
        assert self.ctx is not None
        from moritz_agent.phone.remote import ENV_TOKEN, ENV_URL

        self.phone = ManagedProcess(
            "phone",
            argv,
            env={
                ENV_URL: f"http://127.0.0.1:{self.internal_port}",
                ENV_TOKEN: self.ctx.internal_token,
            },
            cwd=self.state_root,
            health_check=self._phone_alive,
            category="phone",
            startup_timeout_s=240.0,
            health_interval_s=5.0,
            health_failures=6,  # a call must never be cut off because of one slow second
        )
        await self.phone.start()

    async def _phone_alive(self) -> bool:
        return await asyncio.to_thread(read_status, self.state_root) is not None

    def _discord_wanted(self) -> bool:
        return self.config.settings.discord.enabled and self.config.passwords.discord.enabled

    async def _start_discord(self) -> None:
        """The Discord worker is a child like the phone, but only if it is switched on and has a
        token – otherwise nothing runs and nothing is logged about Discord (UPD-04)."""
        if not self._discord_wanted() or (self.discord is not None and self.discord.running):
            return
        assert self.ctx is not None
        argv = self.discord_argv or [sys.executable, "-m", "moritz_agent.discord"]
        if self.discord_argv is None:
            if self.settings_file:
                argv += ["--config", str(self.settings_file)]
            if self.passwords_file:
                argv += ["--passwords", str(self.passwords_file)]
            argv += ["run"]
        from moritz_agent.discord.core import ENV_TOKEN, ENV_URL

        self.discord = ManagedProcess(
            "discord",
            argv,
            env={
                ENV_URL: f"http://127.0.0.1:{self.internal_port}",
                ENV_TOKEN: self.ctx.internal_token,
            },
            cwd=self.state_root,
            health_check=self._discord_alive,
            category="discord",
            startup_timeout_s=120.0,
            health_interval_s=10.0,
            health_failures=6,
            niceness=DISCORD_NICE,
        )
        await self.discord.start()

    async def _discord_alive(self) -> bool:
        return await asyncio.to_thread(discord_status.read_status, self.state_root) is not None

    async def _stop_discord(self) -> None:
        if self.discord is not None:
            await self.discord.stop(PHONE_STOP_GRACE_S)
            self.discord = None

    # -- running ------------------------------------------------------------------------------------
    def _spawn(self, coroutine) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def request_restart(self) -> None:
        """Leave with a non-zero code: systemd (Restart=on-failure) starts the service again."""
        log.info("Neustart angefordert")
        self.exit_code = 75  # EX_TEMPFAIL
        self._stop.set()

    def _child_components(self) -> dict[str, Component]:
        return {**self._phone_component(), **self._discord_component()}

    def _phone_component(self) -> dict[str, Component]:
        if not self.config.settings.phone.enabled:
            return {"phone": Component("disabled", "Telefon ausgeschaltet")}
        status = read_status(self.state_root)
        if status is None:
            return {"phone": Component("failed", "Der Telefonteil meldet sich nicht")}
        registration = str(status.get("registration") or "unbekannt")
        state = "ready" if registration.lower().startswith("regist") else "degraded"
        return {"phone": Component(state, f"Registrierung: {registration}")}

    def _discord_component(self) -> dict[str, Component]:
        if not self.config.settings.discord.enabled:
            return {}  # not part of the installation: nothing to show
        if not self.config.passwords.discord.enabled:
            return {"discord": Component("disabled", "kein Bot-Token in passwords.txt")}
        status = discord_status.read_status(self.state_root)
        if status is None:
            return {"discord": Component("failed", "Der Discord-Teil meldet sich nicht")}
        state = {"ready": "ready", "connecting": "starting", "starting": "starting"}.get(
            str(status.get("state")), "degraded"
        )
        note = str(status.get("error") or "")
        if not note and status.get("default_channel") == "fehlt":
            state, note = "degraded", "Standardkanal fehlt"
        return {"discord": Component(state, note or f"{status.get('guilds', 0)} Server")}

    def _extra_status(self) -> dict[str, Any]:
        children: dict[str, Any] = {}
        if self.phone is not None:
            status = self.phone.status()
            children["phone"] = {"state": status.state, "restarts": status.restarts}
        if self.discord is not None:
            status = self.discord.status()
            children["discord"] = {"state": status.state, "restarts": status.restarts}
        return {"web": self.web_state.as_dict(), "children": children}

    async def reload(self) -> ReloadResult:
        """SIGHUP and ``POST /api/system/reload``: read both files again, tell the phone."""
        result = self.config.reload()
        if not result.ok:
            return result
        self._setup_logging()
        phone_changed = "sip_changed" in result.events or "settings.phone" in result.changed
        if phone_changed and self.phone is not None and self.phone.running:
            pid = self.phone.status().pid
            if pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGHUP)  # the worker re-reads the files itself
        if self.start_discord:
            await self._reload_discord(result)
        return result

    async def _reload_discord(self, result: ReloadResult) -> None:
        """Switched on or a token appeared: start; switched off: stop; otherwise tell it to re-read."""
        running = self.discord is not None and self.discord.running
        if not self._discord_wanted():
            if running:
                await self._stop_discord()
            return
        if not running:
            await self._start_discord()
            return
        assert self.discord is not None
        if result.changed & {"settings.discord", "passwords.discord"}:
            pid = self.discord.status().pid
            if pid:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGHUP)

    async def _maintenance(self) -> None:
        """Every minute: optional file polling; every hour: retention; every day: a backup."""
        last_purge = last_backup = 0.0
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL_S)
            settings = self.config.settings
            if settings.general.config_poll_s and self.config.poll():
                self._setup_logging()
            now = time.monotonic()
            runtime = self.runtime
            if runtime is None or runtime.db is None:
                continue
            if now - last_purge >= 3600:
                last_purge = now
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(runtime.purge)
            if now - last_backup >= 86400 or last_backup == 0.0:
                last_backup = now
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._backup_database, runtime)

    def _backup_database(self, runtime: Runtime) -> None:
        assert runtime.db is not None
        directory = self.state_root / self.config.settings.general.data_dir / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        runtime.db.backup(directory / f"moritz-agent-{time.strftime('%Y%m%d')}.sqlite3")
        for old in sorted(directory.glob("moritz-agent-*.sqlite3"))[:-BACKUPS_KEPT]:
            old.unlink(missing_ok=True)

    # -- shutdown -----------------------------------------------------------------------------------
    async def shutdown(self) -> None:
        """Phone first (BYE), then the servers, then model and search, then the database."""
        for task in list(self._tasks):
            task.cancel()
        await self._stop_discord()
        if self.phone is not None:
            await self.phone.stop(PHONE_STOP_GRACE_S)
        for server, task in reversed(self._servers):
            server.should_exit = True
            with contextlib.suppress(asyncio.TimeoutError, Exception):
                await asyncio.wait_for(task, 5.0)
        self._servers.clear()
        if self.runtime is not None:
            await self.runtime.stop()
        with contextlib.suppress(OSError):
            (self.state_root / "data" / "run" / ADMIN_TOKEN_FILE).unlink()
        log.info("Beendet.")


def run() -> int:
    """``moritz-agent run``."""
    return asyncio.run(Supervisor().run())

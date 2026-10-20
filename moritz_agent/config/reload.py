# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The running configuration: one immutable snapshot, replaced atomically on reload (CFG-05).

An invalid file never replaces the working one: the old snapshot stays active and the reason is
kept for the status page and the log. Subscribers learn which parts changed; a change of the SIP
account or the phone ports is reported as the event ``sip_changed`` (PHONE-08).
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from moritz_agent.config.secrets import Passwords
from moritz_agent.config.settings import REPO_ROOT, Settings
from moritz_agent.config.validate import ValidationReport, settings_path, validate_files
from moritz_agent.logging_setup import get_logger

log = get_logger("system")

# changes that only take effect after a restart of the service
RESTART_SECTIONS = ("server", "logging", "inference", "storage")
SIP_PHONE_KEYS = (
    "local_sip_port",
    "rtp_port_start",
    "rtp_port_count",
    "codecs",
    "allowed_source_ips",
    "register_retry_min_s",
    "register_retry_max_s",
)


class ConfigError(RuntimeError):
    """The first load failed: there is no valid configuration to run with."""

    def __init__(self, message: str, report: ValidationReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class RuntimeConfig:
    settings: Settings
    passwords: Passwords
    generation: int
    loaded_at: float


@dataclass
class ReloadResult:
    ok: bool
    changed: set[str] = field(default_factory=set)  # "settings.skills", "passwords.sip", …
    events: set[str] = field(default_factory=set)  # "sip_changed"
    restart_required: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)  # place + message, never values
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "changed": sorted(self.changed),
            "events": sorted(self.events),
            "restart_required": sorted(self.restart_required),
            "errors": self.errors,
            "warnings": self.warnings,
        }


Listener = Callable[[RuntimeConfig, RuntimeConfig, ReloadResult], Awaitable[None] | None]


def diff(old: RuntimeConfig, new: RuntimeConfig) -> ReloadResult:
    """Which sections differ between two snapshots."""
    result = ReloadResult(ok=True)
    before, after = old.settings.model_dump(), new.settings.model_dump()
    for section in after:
        if before.get(section) != after[section]:
            result.changed.add(f"settings.{section}")
            if section in RESTART_SECTIONS:
                result.restart_required.add(section)
    for name in ("sip", "web_login", "sandbox_ssh", "optional_services"):
        if getattr(old.passwords, name) != getattr(new.passwords, name):
            result.changed.add(f"passwords.{name}")
    if "passwords.web_login" in result.changed:
        result.restart_required.add("web_login")  # the login of a running server is fixed
    phone_before, phone_after = before.get("phone", {}), after.get("phone", {})
    if "passwords.sip" in result.changed or any(
        phone_before.get(key) != phone_after.get(key) for key in SIP_PHONE_KEYS
    ):
        result.events.add("sip_changed")
    return result


class ConfigManager:
    def __init__(
        self,
        settings_file: Path | None = None,
        passwords_file: Path | None = None,
        root: Path = REPO_ROOT,
    ) -> None:
        self.root = root
        self.settings_file = settings_file
        self.passwords_file = passwords_file
        self._current: RuntimeConfig | None = None
        self._listeners: list[Listener] = []
        self._pending: set[asyncio.Future[None]] = set()
        self._mtimes: tuple[float, float] = (0.0, 0.0)
        self.last_error: str | None = None
        self.last_reload: float | None = None

    # -- loading ---------------------------------------------------------------------------------
    @property
    def current(self) -> RuntimeConfig:
        if self._current is None:
            raise RuntimeError("configuration not loaded")
        return self._current

    @property
    def settings(self) -> Settings:
        return self.current.settings

    @property
    def passwords(self) -> Passwords:
        return self.current.passwords

    def load(self) -> RuntimeConfig:
        """First load; raises ``ConfigError`` (with the report) when the files are unusable."""
        report = validate_files(self.settings_file, self.passwords_file, self.root)
        if not report.ok or report.settings is None or report.passwords is None:
            raise ConfigError("; ".join(f"{i.where}: {i.message}" for i in report.errors), report)
        self._current = RuntimeConfig(report.settings, report.passwords, 1, time.time())
        self._mtimes = self._stat()
        return self._current

    def reload(self) -> ReloadResult:
        """Read both files again; only a valid pair replaces the running snapshot."""
        report = validate_files(self.settings_file, self.passwords_file, self.root)
        if not report.ok or report.settings is None or report.passwords is None:
            errors = [f"{i.where}: {i.message}" for i in report.errors]
            self.last_error = "; ".join(errors)
            log.error("Neu laden abgelehnt, der bisherige Stand bleibt aktiv: %s", self.last_error)
            self._mtimes = self._stat()
            return ReloadResult(ok=False, errors=errors)
        old = self.current
        new = RuntimeConfig(report.settings, report.passwords, old.generation + 1, time.time())
        result = diff(old, new)
        result.warnings = [f"{i.where}: {i.message}" for i in report.warnings]
        self._current = new  # one assignment: readers see the old or the new snapshot, never a mix
        self.last_error = None
        self.last_reload = new.loaded_at
        self._mtimes = self._stat()
        log.info(
            "Konfiguration neu geladen (Stand %d): %s",
            new.generation,
            ", ".join(sorted(result.changed)) or "keine Änderung",
        )
        for listener in list(self._listeners):
            outcome = listener(old, new, result)
            if inspect.isawaitable(outcome):
                task = asyncio.ensure_future(outcome)
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)
        return result

    # -- subscribers and polling -----------------------------------------------------------------
    def on_change(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _stat(self) -> tuple[float, float]:
        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        settings = self.settings_file or settings_path(self.root)
        passwords = self.passwords_file or self.root / (
            self._current.settings.general.passwords_file if self._current else "passwords.txt"
        )
        return mtime(settings), mtime(passwords)

    def poll(self) -> ReloadResult | None:
        """Reload if a file changed since the last look (optional, off by default)."""
        stamp = self._stat()
        if stamp == self._mtimes:
            return None
        return self.reload()

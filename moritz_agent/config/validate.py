# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Check config/moritz-agent.toml and passwords.txt – and say what is wrong without ever naming a
value (CFG-05, CFG-06, API-02). Used by ``moritz-agent check-config``, start-up and reload."""

from __future__ import annotations

import ipaddress
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from moritz_agent.config.secrets import Passwords, PasswordsFileError, load_passwords
from moritz_agent.config.settings import (
    EXAMPLE_CONFIG_NAME,
    LOCAL_CONFIG_NAME,
    REPO_ROOT,
    Settings,
    SettingsError,
    load_settings,
)

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning" | "info"
    where: str  # file or section, e.g. "passwords.txt", "server"
    message: str


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    settings: Settings | None = None
    passwords: Passwords | None = None

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, where: str, message: str) -> None:
        self.issues.append(Issue(level, where, message))


def effective_host(settings: Settings, passwords: Passwords) -> str:
    """The address the web interface really binds to: a network address only with a login (API-02)."""
    if settings.server.host in LOOPBACK or passwords.web_login.enabled:
        return settings.server.host
    return "127.0.0.1"


def settings_path(root: Path = REPO_ROOT) -> Path:
    local = root / "config" / LOCAL_CONFIG_NAME
    return local if local.is_file() else root / "config" / EXAMPLE_CONFIG_NAME


def ensure_private(path: Path, *, fix: bool = True) -> Issue | None:
    """passwords.txt must be readable by its owner only (CFG-06): warn and correct if possible."""
    try:
        info = path.stat()
    except OSError:
        return None
    problems = []
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        mode = stat.S_IMODE(info.st_mode)
        if fix:
            try:
                path.chmod(0o600)
                return Issue(
                    "warning",
                    path.name,
                    f"Dateirechte waren zu offen ({mode:04o}) und wurden auf 0600 gesetzt",
                )
            except OSError:
                pass
        problems.append(f"Dateirechte sind zu offen ({mode:04o}); erwartet wird 0600")
    if hasattr(os, "getuid") and os.getuid() != 0 and info.st_uid != os.getuid():
        problems.append("die Datei gehört einem anderen Benutzer als dem Dienstbenutzer")
    if problems:
        return Issue("warning", path.name, "; ".join(problems))
    return None


def validate_files(
    settings_file: Path | None = None,
    passwords_file: Path | None = None,
    root: Path = REPO_ROOT,
    *,
    fix_permissions: bool = True,
) -> ValidationReport:
    """Load and cross-check both files. Never raises, never contains a value."""
    report = ValidationReport()
    try:
        report.settings = load_settings(settings_file or settings_path(root), root)
    except SettingsError as exc:
        report.add("error", "config/moritz-agent.toml", str(exc))
    password_path = passwords_file or (
        root / (report.settings.general.passwords_file if report.settings else "passwords.txt")
    )
    note = ensure_private(password_path, fix=fix_permissions)
    if note is not None:
        report.issues.append(note)
    try:
        report.passwords = load_passwords(password_path)
    except PasswordsFileError as exc:
        report.add("error", "passwords.txt", str(exc))
    if report.settings is not None:
        _check_settings(report, report.settings, report.passwords, root)
    return report


def _check_settings(
    report: ValidationReport, settings: Settings, passwords: Passwords | None, root: Path
) -> None:
    try:
        ZoneInfo(settings.general.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        report.add("error", "general", "die Zeitzone ist unbekannt")
    for entry in settings.phone.allowed_source_ips:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            report.add("error", "phone", "allowed_source_ips enthält eine ungültige Adresse")
            break
    # API-02: without a login the web interface is not offered to the network (see effective_host)
    if passwords is not None and effective_host(settings, passwords) != settings.server.host:
        report.add(
            "warning",
            "server",
            "in passwords.txt ([web_login]) ist kein Login eingerichtet: die Weboberfläche bleibt "
            "deshalb nur lokal erreichbar (API-02)",
        )
    if settings.server.tls:
        for key in ("tls_cert", "tls_key"):
            if not settings.resolve(getattr(settings.server, key), root).is_file():
                report.add(
                    "info", "server", f"{key}: Datei fehlt noch, sie wird beim Start erzeugt"
                )
    prompt = settings.resolve(settings.agent.phone.system_prompt_file, root)
    if not prompt.is_file():
        report.add("error", "agent", "die Systemanweisung (system_prompt_file) fehlt")
    if not settings.resolve(settings.inference.model, root).is_file():
        report.add(
            "warning",
            "inference",
            "die Modelldatei fehlt – Sofortauskünfte laufen weiter, Fragen an die KI nicht",
        )
    if passwords is not None and passwords.sip.password.reveal() == "agent":
        report.add("warning", "passwords.txt", "das SIP-Passwort ist noch der Startwert")


def format_report(report: ValidationReport) -> list[str]:
    """Lines for the console: level, place, message – no values."""
    labels = {"error": "FEHLER ", "warning": "Hinweis", "info": "Info   "}
    return [f"{labels[i.level]} {i.where}: {i.message}" for i in report.issues]

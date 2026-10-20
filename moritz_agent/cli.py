# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Command line entry point: ``moritz-agent [run|check-config|phone|--version]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from moritz_agent import __version__


def _check_config(args: argparse.Namespace) -> int:
    """Validate config/moritz-agent.toml and passwords.txt – without printing any value (CFG-05)."""
    from moritz_agent.config.settings import REPO_ROOT
    from moritz_agent.config.validate import format_report, validate_files

    config = Path(args.config) if args.config else None
    report = validate_files(config, Path(args.passwords), REPO_ROOT, fix_permissions=False)
    for line in format_report(report):
        print(line, file=sys.stderr if report.errors else sys.stdout)
    if not report.ok:
        print("Konfiguration: FEHLER – bitte die Meldungen oben beheben.", file=sys.stderr)
        return 1
    settings, passwords = report.settings, report.passwords
    assert settings is not None and passwords is not None
    print("Konfiguration: OK")
    print(f"  SIP-Konto gesetzt, Registrar {passwords.sip.registrar}:{passwords.sip.port}")
    print(f"  Web-Login: {'aktiv' if passwords.web_login.enabled else 'nicht eingerichtet'}")
    print(f"  Sandbox-SSH: {'aktiv' if passwords.sandbox_ssh.enabled else 'deaktiviert'}")
    print(f"  Weboberfläche: {settings.server.host}:{settings.server.port}")
    return 0


def _run(_args: argparse.Namespace) -> int:
    """Start the service. Until the supervisor (P1-04) exists, that is the phone worker."""
    from moritz_agent.phone.__main__ import main as phone_main

    return phone_main(["run"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moritz-agent", description="Lokaler KI-Agent.")
    parser.add_argument("--version", action="version", version=f"moritz-agent {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Anwendung starten (Standard)")
    run.set_defaults(func=_run)

    check = sub.add_parser("check-config", help="Konfiguration prüfen, ohne Werte auszugeben")
    check.add_argument("--passwords", default="passwords.txt", help="Pfad zu passwords.txt")
    check.add_argument("--config", default=None, help="Pfad zu config/moritz-agent.toml")
    check.set_defaults(func=_check_config)

    # Handled in main() before parsing: everything after "phone" belongs to moritz_agent.phone.
    sub.add_parser(
        "phone",
        help="Telefon- und Stimmenteil: run, check, speak, prompts, bench (siehe ./test-1.sh)",
        add_help=False,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "phone":
        from moritz_agent.phone.__main__ import main as phone_main

        return phone_main(argv[1:])
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", _run)
    return func(args)

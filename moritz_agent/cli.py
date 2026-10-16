"""Command line entry point: ``moritz-agent [run|check-config|--version]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from moritz_agent import __version__
from moritz_agent.config.secrets import PasswordsFileError, load_passwords


def _check_config(args: argparse.Namespace) -> int:
    """Validate passwords.txt without printing any values (P1-03 extends this to TOML)."""
    try:
        passwords = load_passwords(Path(args.passwords))
    except PasswordsFileError as exc:
        print(f"passwords.txt: FEHLER – {exc}", file=sys.stderr)
        return 1
    print("passwords.txt: OK")
    print(f"  SIP-Konto gesetzt, Registrar {passwords.sip.registrar}:{passwords.sip.port}")
    print(f"  Web-Login: {'aktiv' if passwords.web_login.enabled else 'nicht eingerichtet'}")
    print(f"  Sandbox-SSH: {'aktiv' if passwords.sandbox_ssh.enabled else 'deaktiviert'}")
    if passwords.sip.password.reveal() == "agent":
        print("  WARNUNG: SIP-Passwort ist der Startwert – starkes Passwort empfohlen.")
    return 0


def _run(_args: argparse.Namespace) -> int:
    print("moritz-agent: Laufzeit noch nicht implementiert (Ticket P1-04).", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moritz-agent", description="Lokaler KI-Agent.")
    parser.add_argument("--version", action="version", version=f"moritz-agent {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Anwendung starten (Standard)")
    run.set_defaults(func=_run)

    check = sub.add_parser("check-config", help="Konfiguration prüfen, ohne Werte auszugeben")
    check.add_argument("--passwords", default="passwords.txt", help="Pfad zu passwords.txt")
    check.set_defaults(func=_check_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", _run)
    return func(args)

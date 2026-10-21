# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Helpers for the installer and updater:  python -m moritz_agent.setup <command>

migrate            add missing sections/keys to passwords.txt (appends only, nothing re-written)
discord-token      read the bot token from stdin, check it, store it, switch Discord on
discord-channel    set the home channel: ``--id N``, or pick from a list (the answer comes from stdin)
discord-pin        read a PIN for dangerous admin commands from stdin and store it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from moritz_agent.config.settings import REPO_ROOT
from moritz_agent.setup import discord as setup_discord
from moritz_agent.setup import files


def _paths(args: argparse.Namespace) -> tuple[Path, Path | None]:
    passwords = Path(args.passwords) if args.passwords else REPO_ROOT / "passwords.txt"
    config = Path(args.config) if args.config else REPO_ROOT / "config" / "moritz-agent.toml"
    return passwords, config if config.exists() else None


def _token_of(passwords: Path) -> str:
    return files.get_value(passwords.read_text(encoding="utf-8"), "discord", "bot_token") or ""


def _migrate(args: argparse.Namespace) -> int:
    passwords, _ = _paths(args)
    if not passwords.exists():
        print("passwords.txt fehlt.", file=sys.stderr)
        return 1
    added: list[str] = []

    def edit(text: str) -> str:
        new, added[:] = files.migrate_passwords(text)
        return new

    files.update_file(passwords, edit)
    print("Ergänzt: " + ", ".join(added) if added else "passwords.txt ist vollständig.")
    return 0


def _discord_token(args: argparse.Namespace) -> int:
    passwords, config = _paths(args)
    token = sys.stdin.readline().strip()
    return setup_discord.run(
        setup_discord.setup_token(passwords, config, token, check=not args.no_check)
    )


def _discord_channel(args: argparse.Namespace) -> int:
    passwords, _ = _paths(args)
    token = _token_of(passwords)
    if not token:
        print("Zuerst den Token eintragen (discord-token).", file=sys.stderr)
        return 2
    answer = args.id or (sys.stdin.readline().strip() if args.answer else "")
    return setup_discord.run(setup_discord.setup_channel(passwords, token, answer))


def _discord_pin(args: argparse.Namespace) -> int:
    passwords, _ = _paths(args)
    pin = sys.stdin.readline().strip()
    if len(pin) < 4 or any(c.isspace() for c in pin):
        print("Die PIN braucht mindestens 4 Zeichen ohne Leerzeichen.", file=sys.stderr)
        return 2
    files.update_file(
        passwords,
        lambda t: files.set_value(files.migrate_passwords(t)[0], "discord", "admin_pin", pin),
    )
    print("PIN gespeichert.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m moritz_agent.setup", description=__doc__)
    parser.add_argument("--passwords", default=None)
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate").set_defaults(func=_migrate)
    token = sub.add_parser("discord-token")
    token.add_argument("--no-check", action="store_true", help="Discord nicht fragen")
    token.set_defaults(func=_discord_token)
    channel = sub.add_parser("discord-channel")
    channel.add_argument("--id", default="", help="Kanal-ID")
    channel.add_argument("--answer", action="store_true", help="die Auswahl von stdin lesen")
    channel.set_defaults(func=_discord_channel)
    sub.add_parser("discord-pin").set_defaults(func=_discord_pin)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

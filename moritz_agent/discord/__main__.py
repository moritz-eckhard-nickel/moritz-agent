# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Command line of the Discord part:  python -m moritz_agent.discord <command>

run            start the bot (the supervisor does this; ``--standalone`` brings the main process along)
check          test token, application settings, server and home channel
invite         print the invite links (server and user installation)
channels       list the text channels of the servers Anton is on (to pick the home channel)
sync-commands  register the slash commands with Discord now
say TEXT       send a test message into the home channel
profile        set avatar and bio of the bot
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from moritz_agent.config.secrets import Passwords, PasswordsFileError, load_passwords
from moritz_agent.config.settings import REPO_ROOT, Settings, SettingsError, load_settings


def _files(args: argparse.Namespace) -> tuple[Settings, Passwords]:
    settings = load_settings(Path(args.config) if args.config else None)
    path = Path(args.passwords) if args.passwords else REPO_ROOT / settings.general.passwords_file
    return settings, load_passwords(path)


def _token(args: argparse.Namespace) -> tuple[Settings, Passwords] | None:
    try:
        settings, passwords = _files(args)
    except (SettingsError, PasswordsFileError) as exc:
        print(f"Konfiguration: {exc}", file=sys.stderr)
        return None
    if not passwords.discord.enabled:
        print("In passwords.txt fehlt [discord] bot_token.", file=sys.stderr)
        return None
    return settings, passwords


def _run(args: argparse.Namespace) -> int:
    from moritz_agent.discord.worker import WorkerOptions, nice_self, run

    if args.nice:
        nice_self()
    options = WorkerOptions(
        config=Path(args.config) if args.config else None,
        passwords=Path(args.passwords) if args.passwords else None,
        standalone=args.standalone,
        force_sync=args.force_sync,
        no_startup_message=args.quiet,
    )
    return run(options)


def _check(args: argparse.Namespace) -> int:
    from moritz_agent.discord.setup import check, invite_links

    loaded = _token(args)
    if loaded is None:
        return 2
    settings, passwords = loaded
    report = asyncio.run(
        check(
            passwords.discord.bot_token.reveal(),
            passwords.discord.channel_id,
            settings.discord.owner_user_ids,
        )
    )
    icons = {"ok": "✔", "warn": "!", "error": "✘"}
    for item in report.checks:
        print(f" {icons[item.level]} {item.text}")
    if report.application_id:
        print()
        for line in invite_links(report.application_id):
            print(" ", line)
    if report.owner_ids and not settings.discord.owner_user_ids:
        print("\n  In config/moritz-agent.toml unter [discord]:")
        print("  owner_user_ids = [" + ", ".join(f'"{o}"' for o in report.owner_ids) + "]")
    return 0 if report.ok else 1


def _invite(args: argparse.Namespace) -> int:
    from moritz_agent.discord.setup import DiscordApiError, DiscordRest, invite_links

    loaded = _token(args)
    if loaded is None:
        return 2

    async def application_id() -> str:
        async with DiscordRest(loaded[1].discord.bot_token.reveal()) as rest:
            return str((await rest.application()).get("id") or (await rest.me())["id"])

    try:
        ident = asyncio.run(application_id())
    except DiscordApiError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    for line in invite_links(ident):
        print(line)
    return 0


def _channels(args: argparse.Namespace) -> int:
    from moritz_agent.discord.setup import DiscordApiError, DiscordRest

    loaded = _token(args)
    if loaded is None:
        return 2

    async def listing() -> list[tuple[str, str, str]]:
        async with DiscordRest(loaded[1].discord.bot_token.reveal()) as rest:
            found = []
            for guild in await rest.guilds():
                for channel in await rest.text_channels(str(guild["id"])):
                    found.append((guild["name"], channel["name"], str(channel["id"])))
            return found

    try:
        found = asyncio.run(listing())
    except DiscordApiError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    if not found:
        print("Anton ist auf keinem Server oder darf keine Kanäle sehen.", file=sys.stderr)
        return 1
    for number, (guild, channel, ident) in enumerate(found, 1):
        print(f"{number:2d}  {guild} / #{channel}  ({ident})")
    return 0


def _say(args: argparse.Namespace) -> int:
    from moritz_agent.discord.setup import DiscordApiError, DiscordRest

    loaded = _token(args)
    if loaded is None:
        return 2
    channel = loaded[1].discord.channel_id
    if not channel:
        print("In passwords.txt fehlt [discord] channel_id.", file=sys.stderr)
        return 2

    async def send() -> None:
        async with DiscordRest(loaded[1].discord.bot_token.reveal()) as rest:
            await rest.say(channel, args.text)

    try:
        asyncio.run(send())
    except DiscordApiError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    print("Gesendet.")
    return 0


def _profile(args: argparse.Namespace) -> int:
    from moritz_agent.discord.setup import BIO, DiscordApiError, DiscordRest

    loaded = _token(args)
    if loaded is None:
        return 2
    avatar = REPO_ROOT / "assets" / "branding" / "discord-avatar.png"
    image = avatar.read_bytes() if avatar.is_file() else None

    async def apply() -> None:
        async with DiscordRest(loaded[1].discord.bot_token.reveal()) as rest:
            await rest.set_profile(image, BIO)

    try:
        asyncio.run(apply())
    except DiscordApiError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    print(
        "Profil gesetzt"
        + ("" if image else " (ohne Avatar: assets/branding/discord-avatar.png fehlt)")
    )
    return 0


def _sync(args: argparse.Namespace) -> int:
    from moritz_agent.discord.worker import WorkerOptions, sync_once

    options = WorkerOptions(
        config=Path(args.config) if args.config else None,
        passwords=Path(args.passwords) if args.passwords else None,
    )
    return asyncio.run(sync_once(options))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m moritz_agent.discord",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default=None, help="Pfad zu config/moritz-agent.toml")
    parser.add_argument("--passwords", default=None, help="Pfad zu passwords.txt")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Bot starten")
    run.add_argument("--standalone", action="store_true", help="Hauptprozess im Worker starten")
    run.add_argument("--force-sync", action="store_true", help="Befehle neu registrieren")
    run.add_argument("--quiet", action="store_true", help="keine Startnachricht")
    run.add_argument("--nice", action="store_true", help="niedrigere CPU-Priorität")
    run.set_defaults(func=_run)
    sub.add_parser("check", help="Token, Einstellungen und Kanal prüfen").set_defaults(func=_check)
    sub.add_parser("invite", help="Einladungslinks ausgeben").set_defaults(func=_invite)
    sub.add_parser("channels", help="Textkanäle auflisten").set_defaults(func=_channels)
    sub.add_parser("profile", help="Avatar und Bio setzen").set_defaults(func=_profile)
    sync = sub.add_parser("sync-commands", help="Befehle jetzt bei Discord registrieren")
    sync.set_defaults(func=_sync)
    say = sub.add_parser("say", help="Testnachricht in den Standardkanal")
    say.add_argument("text")
    say.set_defaults(func=_say)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

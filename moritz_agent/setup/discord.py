# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Discord setup steps for the installer and ``./test-1.sh discord`` (docs/plan/14 §14.2).

The token arrives on stdin only – never as an argument or an environment variable – and goes into
``passwords.txt`` as one replaced line. Nothing printed here contains it.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import TextIO

import httpx

from moritz_agent.discord import setup as api
from moritz_agent.setup import files

TOKEN_SHAPE = re.compile(r"^\S{20,200}$")
SNOWFLAKE = re.compile(r"^\d{5,25}$")  # real ids have 17–20 digits; the tests use short ones


def store_token(passwords: Path, token: str) -> None:
    files.update_file(
        passwords,
        lambda t: files.set_value(files.migrate_passwords(t)[0], "discord", "bot_token", token),
    )


def store_channel(passwords: Path, channel_id: str) -> None:
    files.update_file(
        passwords,
        lambda t: files.set_value(
            files.migrate_passwords(t)[0], "discord", "channel_id", channel_id
        ),
    )


def enable_discord(config: Path, owners: list[str]) -> bool:
    """``enabled = true`` and the owners in ``[discord]`` of the configuration (other lines untouched)."""

    def edit(text: str) -> str:
        text = files.set_value(text, "discord", "enabled", "true", keep_comment=True)
        current = files.get_value(text, "discord", "owner_user_ids", comments=True)
        if owners and (current is None or current.replace(" ", "") in {"[]", ""}):
            text = files.set_value(
                text, "discord", "owner_user_ids", files.toml_list(owners), keep_comment=True
            )
        return text

    return files.update_file(config, edit, default_mode=0o640)


async def setup_token(
    passwords: Path,
    config: Path | None,
    token: str,
    *,
    check: bool = True,
    out: TextIO = sys.stdout,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    token = token.strip()
    if not TOKEN_SHAPE.match(token):
        print(
            "Das sieht nicht wie ein Bot-Token aus (keine Leerzeichen, mindestens 20 Zeichen).",
            file=out,
        )
        return 2
    owners: list[str] = []
    if check:
        report = await api.check(token, transport=transport)
        for item in report.checks:
            print(f"  {item.text}", file=out)
        if not report.ok and any("Token" in c.text and c.level == "error" for c in report.checks):
            return 1
        owners = report.owner_ids
        for line in api.invite_links(report.application_id or "?"):
            print(f"  {line}", file=out)
    store_token(passwords, token)
    print("Der Token steht jetzt in passwords.txt (nur dort).", file=out)
    if config is not None:
        enable_discord(config, owners)
        print("Discord ist in der Konfiguration eingeschaltet.", file=out)
        if owners:
            print(f"Owner: {', '.join(owners)}", file=out)
    return 0


async def list_channels(
    token: str, transport: httpx.AsyncBaseTransport | None = None
) -> list[tuple[str, str, str]]:
    async with api.DiscordRest(token, transport=transport) as rest:
        found = []
        for guild in await rest.guilds():
            for channel in await rest.text_channels(str(guild["id"])):
                found.append((guild["name"], channel["name"], str(channel["id"])))
        return found


async def setup_channel(
    passwords: Path,
    token: str,
    answer: str,
    *,
    out: TextIO = sys.stdout,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """``answer``: a channel id, a number from the list, or empty (show the list)."""
    answer = answer.strip()
    try:
        channels = await list_channels(token, transport)
    except api.DiscordApiError as exc:
        print(f"Fehler: {exc}", file=out)
        return 1
    if answer.isdigit() and 1 <= int(answer) <= len(channels):
        chosen = channels[int(answer) - 1][2]  # a number from the list
    elif SNOWFLAKE.match(answer):
        chosen = answer
    else:
        if not channels:
            print(
                "Anton ist noch auf keinem Server oder darf keine Kanäle sehen. Einladungslink benutzen.",
                file=out,
            )
            return 1
        for number, (guild, channel, ident) in enumerate(channels, 1):
            print(f"{number:2d}  {guild} / #{channel}  ({ident})", file=out)
        return 3  # the caller asks for the number
    report = await api.check(token, chosen, transport=transport)
    problems = [c.text for c in report.checks if c.level == "error"]
    if problems:
        for text in problems:
            print(f"  {text}", file=out)
        return 1
    store_channel(passwords, chosen)
    print(f"Standardkanal gespeichert ({chosen}).", file=out)
    return 0


def store_voice_channel(config: Path, channel_id: str) -> bool:
    """``default_channel_id`` under ``[discord.voice]``: where ``/joinvc`` goes when Moritz is in none."""
    return files.update_file(
        config,
        lambda t: files.set_value(
            t, "discord.voice", "default_channel_id", f'"{channel_id}"', keep_comment=True
        ),
        default_mode=0o640,
    )


async def setup_voice_channel(
    config: Path,
    token: str,
    answer: str,
    *,
    out: TextIO = sys.stdout,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Like :func:`setup_channel` for the voice channel; stored in the configuration."""
    answer = answer.strip()
    try:
        async with api.DiscordRest(token, transport=transport) as rest:
            channels = [
                (guild["name"], channel["name"], str(channel["id"]))
                for guild in await rest.guilds()
                for channel in await rest.voice_channels(str(guild["id"]))
            ]
    except api.DiscordApiError as exc:
        print(f"Fehler: {exc}", file=out)
        return 1
    if answer.isdigit() and 1 <= int(answer) <= len(channels):
        chosen = channels[int(answer) - 1][2]
    elif SNOWFLAKE.match(answer):
        chosen = answer
    else:
        if not channels:
            print("Auf Antons Servern gibt es keinen Sprachkanal, den er sehen darf.", file=out)
            return 1
        for number, (guild, channel, ident) in enumerate(channels, 1):
            print(f"{number:2d}  {guild} / 🔊 {channel}  ({ident})", file=out)
        return 3  # the caller asks for the number
    store_voice_channel(config, chosen)
    print(f"Sprachkanal gespeichert ({chosen}).", file=out)
    return 0


def run(coro) -> int:
    return int(asyncio.run(coro))

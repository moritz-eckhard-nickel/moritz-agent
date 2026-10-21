# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A Discord side for the tests: a recording sender and a dispatcher wired to the real main process."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

import httpx

from moritz_agent.discord.access import AccessPolicy, MessageInfo, RateLimiter
from moritz_agent.discord.admin import AdminCommands
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.commands.handlers import LocalCommands
from moritz_agent.discord.core import CoreApi
from moritz_agent.discord.dispatch import Dispatcher
from moritz_agent.discord.render import OutMessage
from moritz_agent.discord.sender import Origin
from moritz_agent.discord.style import Styler

from .system_util import ADMIN_PIN, BOT_TOKEN, CHANNEL_ID, OWNER_ID, ROOT, System

GUILD_ID = "9000"
BOT_ID = "5000"
FOREIGN_GUILD_ID = "9999"


@dataclass
class Recorder:
    """Stands for a channel or a deferred interaction."""

    ephemeral: bool = False
    sent: list[OutMessage] = field(default_factory=list)
    edits: list[tuple[int, OutMessage]] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)
    began: int = 0
    typed: int = 0

    async def begin(self) -> None:
        self.began += 1

    async def send(self, message: OutMessage) -> int:
        self.sent.append(message)
        return len(self.sent) - 1

    async def edit(self, handle: object, message: OutMessage) -> None:
        assert isinstance(handle, int)
        self.edits.append((handle, message))
        self.sent[handle] = message

    @contextlib.asynccontextmanager
    async def typing(self):
        self.typed += 1
        yield

    async def react(self, emoji: str) -> None:
        self.reactions.append(emoji)

    @property
    def texts(self) -> list[str]:
        return [m.content for m in self.sent]

    @property
    def text(self) -> str:
        return "\n".join(m.content for m in self.sent)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Bench:
    dispatcher: Dispatcher
    core: CoreApi
    policy: AccessPolicy
    clock: Clock
    system: System
    draining: list[bool]

    def origin(
        self,
        user: str = OWNER_ID,
        *,
        where: str = "DM",
        channel: str = "",
        guild: str | None = None,
        thread: bool = False,
        seed: int = 3,
    ) -> Origin:
        if where != "DM" and guild is None:
            guild = GUILD_ID if where == "S" else FOREIGN_GUILD_ID
        return Origin(
            user_id=user,
            name="Moritz",
            where=where,
            guild_id=guild,
            channel_id=channel or (CHANNEL_ID if where == "S" else f"7{user}"),
            in_thread=thread,
            message_id=seed,
        )

    def info(self, text: str, origin: Origin, **flags: Any) -> MessageInfo:
        return MessageInfo(
            author_id=origin.user_id,
            author_is_bot=False,
            channel_id=origin.channel_id,
            content=text,
            guild_id=origin.guild_id,
            **flags,
        )

    async def say(
        self, text: str, user: str = OWNER_ID, *, sender: Recorder | None = None, **where: Any
    ) -> Recorder:
        sender = sender or Recorder()
        origin = self.origin(user, **where)
        await self.dispatcher.message(self.info(text, origin), origin, sender)
        return sender

    async def command(
        self,
        name: str,
        values: dict[str, Any] | None = None,
        *,
        group: str = "",
        user: str = OWNER_ID,
        sender: Recorder | None = None,
        **where: Any,
    ) -> Recorder:
        spec = commands.find(name, group)
        assert spec is not None, name
        origin = self.origin(user, **where)
        sender = sender or Recorder(ephemeral=commands_ephemeral(spec, origin, self))
        await self.dispatcher.command(spec, values or {}, origin, sender)
        return sender


def commands_ephemeral(spec: commands.Spec, origin: Origin, bench: Bench) -> bool:
    from moritz_agent.discord.dispatch import ephemeral_for

    return ephemeral_for(spec, origin, bench.system.config.settings.discord)


def bench(system: System, *, clock: Clock | None = None) -> Bench:
    settings = lambda: system.config.settings  # noqa: E731 - read the live settings every time
    transport = httpx.ASGITransport(app=system.internal_app, client=("127.0.0.1", 5001))
    core = CoreApi("http://testserver", system.ctx.internal_token, transport=transport)
    clock = clock or Clock()
    cfg = settings().discord
    policy = AccessPolicy(
        cfg, default_channel_id=CHANNEL_ID, default_guild_id=GUILD_ID, bot_id=BOT_ID
    )
    limiter = RateLimiter(lambda: settings().discord, clock)
    styler = Styler.from_root(ROOT, cfg.style)
    draining = [False]
    secrets = lambda: [BOT_TOKEN, ADMIN_PIN]  # noqa: E731
    dispatcher = Dispatcher(
        core,
        settings,
        policy,
        limiter,
        styler,
        secrets=secrets,
        draining=lambda: draining[0],
        clock=clock,
        today=lambda: "2026-10-18",
    )
    admin = AdminCommands(
        core,
        dispatcher.confirmations,
        secrets=secrets,
        admin_pin=lambda: ADMIN_PIN,
        local_status=lambda: {"latency_ms": 41, "guilds": 1, "voice": False},
        data_root=system.tree,
    )
    dispatcher.local = LocalCommands(
        core,
        settings,
        policy,
        styler,
        admin,
        lambda: commands.Features.from_settings(settings(), voice=True),
    )
    return Bench(dispatcher, core, policy, clock, system, draining)

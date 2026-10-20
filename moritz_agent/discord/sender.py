# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Where answers go: the small interface between the dispatcher and discord.py (docs/plan/14 §4).

A ``Sender`` stands for one place that can be answered – a message in a channel or a deferred
interaction. ``client.py`` implements it with discord.py objects, the tests with a recorder, so the
whole flow (filter, rate limit, core, rendering, streaming) runs without Discord.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from moritz_agent.discord import sessions
from moritz_agent.discord.render import OutMessage


class Sender(Protocol):
    ephemeral: bool  # the answer is only visible to the caller (interactions)

    async def begin(self) -> None:
        """Acknowledge at once (interactions must answer within three seconds)."""

    async def send(self, message: OutMessage) -> object:
        """Send a message; the handle can be given to ``edit``."""

    async def edit(self, handle: object, message: OutMessage) -> None: ...

    def typing(self) -> AbstractAsyncContextManager[None]: ...

    async def react(self, emoji: str) -> None: ...


@dataclass(frozen=True)
class Origin:
    """Who asks from where – the facts the core and the access rules need."""

    user_id: str
    name: str = ""
    where: str = "DM"  # "S" our server · "DM" direct message · "U" anywhere else (user app)
    guild_id: str | None = None
    channel_id: str = ""
    in_thread: bool = False
    message_id: int = 0  # the seed of the style (docs/plan/14 §8.2)

    @property
    def foreign(self) -> bool:
        return self.where == "U" and self.guild_id is not None

    @property
    def place(self) -> str:
        if self.guild_id is None or self.where == "DM":
            return "dm"
        return "thread" if self.in_thread else "guild"

    @property
    def conversation(self) -> str:
        if self.place == "dm":
            return sessions.dm(self.user_id)
        if self.place == "thread":
            return sessions.thread(self.channel_id)
        return sessions.channel(self.channel_id)

    def reply_target(self, default_channel_id: str) -> str:
        if self.foreign:
            return sessions.reply_target("dm", user_id=self.user_id)
        return sessions.reply_target(
            self.place,
            user_id=self.user_id,
            channel_id=self.channel_id,
            default_id=default_channel_id,
        )

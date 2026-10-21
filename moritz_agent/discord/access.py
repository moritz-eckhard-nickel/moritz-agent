# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Who may talk to Anton where, and when she answers (docs/plan/14 §5, ADR-035).

Default is *refuse*: Discord is the internet. Roles hang on the Discord user id only. This module
is pure logic (no Discord objects), so the whole matrix is tested without Discord.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from moritz_agent.config.settings import Discord
from moritz_agent.core.principal import Role, discord_role

_MENTION = re.compile(r"<@!?(\d+)>")
_TRIGGER = re.compile(r"^\s*(?:(?:hey|hi|hallo|moin|guude)\s+)?anton\s*[,:!]\s*", re.IGNORECASE)
NOTICE_STRANGER = "Psst, da ist jemand Neues auf dem Server 👀 – mit dem rede ich nicht."
NOTICE_ONCE_A_DAY = "Ich spreche nur mit freigegebenen Personen."


class Reaction(StrEnum):
    IGNORE = "ignore"
    ANSWER = "answer"
    NOTICE = "notice"  # tell the stranger once a day that Anton does not talk to them


@dataclass(frozen=True)
class MessageInfo:
    author_id: str
    author_is_bot: bool
    channel_id: str
    content: str
    guild_id: str | None = None  # None: a direct message
    mentions_bot: bool = False
    replies_to_bot: bool = False
    in_bot_thread: bool = False
    is_voice_message: bool = False


@dataclass(frozen=True)
class Decision:
    reaction: Reaction
    text: str = ""  # the question without mention and name
    role: Role = Role.UNKNOWN
    reason: str = ""


@dataclass(frozen=True)
class CommandRule:
    """Who may use a command and where (docs/plan/14 §7: S = server, DM, U = user app)."""

    roles: str = "OV"  # letters O (owner), V (trusted), G (guest)
    contexts: str = "S DM U"


_LETTER = {Role.OWNER: "O", Role.TRUSTED: "V", Role.GUEST: "G"}


def strip_address(text: str, bot_id: str | None = None) -> tuple[str, bool, bool]:
    """The text without the bot's mention or a leading "Anton, …", whether she was mentioned and
    whether she was called by name."""
    mentioned = named = False
    cleaned = text
    if bot_id is not None and bot_id in {m.group(1) for m in _MENTION.finditer(cleaned)}:
        mentioned = True
        cleaned = re.sub(rf"<@!?{re.escape(bot_id)}>", " ", cleaned)
    if _TRIGGER.match(cleaned):
        named = True
        cleaned = _TRIGGER.sub("", cleaned, count=1)
    return re.sub(r"\s+", " ", cleaned).strip(), mentioned, named


class AccessPolicy:
    def __init__(
        self,
        cfg: Discord,
        *,
        default_channel_id: str = "",
        default_guild_id: str = "",
        bot_id: str = "",
    ) -> None:
        self.cfg = cfg
        self.default_channel_id = default_channel_id
        self.default_guild_id = default_guild_id
        self.bot_id = bot_id
        self._noticed: dict[str, str] = {}  # stranger → day of the last notice
        self._announced: set[str] = set()  # strangers the default channel was told about
        self.extra_chat_channels: set[str] = set()  # e.g. the chat of the voice channel Anton is in

    def configure(self, cfg: Discord, default_channel_id: str) -> None:
        self.cfg = cfg
        self.default_channel_id = default_channel_id

    # -- roles and places ----------------------------------------------------------------------------
    def role(self, user_id: str) -> Role:
        return discord_role(self.cfg, user_id)

    def guild_allowed(self, guild_id: str | None) -> bool:
        if guild_id is None:
            return True
        return guild_id == self.default_guild_id or guild_id in self.cfg.allowed_guild_ids

    def in_chat_channel(self, channel_id: str) -> bool:
        return (
            channel_id == self.default_channel_id
            or channel_id in self.cfg.chat_channel_ids
            or channel_id in self.extra_chat_channels
        )

    # -- messages --------------------------------------------------------------------------------------------
    def message(self, msg: MessageInfo, *, today: str = "") -> Decision:
        """Answer, ignore, or send a short notice – the whole decision of docs/plan/14 §4.3 step 1."""
        if msg.author_is_bot or msg.author_id == self.bot_id:
            return Decision(Reaction.IGNORE, reason="bot")
        role = self.role(msg.author_id)
        text, mentioned, named = strip_address(msg.content, self.bot_id)
        addressed = msg.mentions_bot or mentioned or (named and self.cfg.name_trigger)
        if msg.guild_id is not None and not self.guild_allowed(msg.guild_id):
            return Decision(Reaction.IGNORE, role=role, reason="guild")
        if role is Role.UNKNOWN:
            if (
                self.cfg.unknown_users == "notice"
                and (addressed or msg.guild_id is None)
                and self._noticed.get(msg.author_id) != today
            ):
                self._noticed[msg.author_id] = today
                return Decision(
                    Reaction.NOTICE, text=NOTICE_ONCE_A_DAY, role=role, reason="unknown"
                )
            return Decision(Reaction.IGNORE, role=role, reason="unknown")
        if msg.guild_id is None:  # direct message: owner and trusted only
            if role is Role.GUEST:
                return Decision(Reaction.IGNORE, role=role, reason="guest in dm")
            return Decision(Reaction.ANSWER, text=text or msg.content, role=role, reason="dm")
        always = self.in_chat_channel(msg.channel_id) or msg.in_bot_thread or msg.replies_to_bot
        if role is Role.GUEST:
            if not (addressed or msg.replies_to_bot):
                return Decision(Reaction.IGNORE, role=role, reason="guest not addressed")
            return Decision(Reaction.ANSWER, text=text, role=role, reason="guest")
        if always or addressed:
            return Decision(
                Reaction.ANSWER, text=text or msg.content, role=role, reason="addressed"
            )
        return Decision(Reaction.IGNORE, role=role, reason="not addressed")

    def stranger_hint(self, msg: MessageInfo) -> str | None:
        """A stranger writes on our server: a note for the default channel – once per person."""
        if (
            msg.author_is_bot
            or msg.guild_id is None
            or not self.guild_allowed(msg.guild_id)
            or self.role(msg.author_id) is not Role.UNKNOWN
            or msg.author_id in self._announced
        ):
            return None
        self._announced.add(msg.author_id)
        return NOTICE_STRANGER

    # -- commands ------------------------------------------------------------------------------------------------
    def command_allowed(self, user_id: str, rule: CommandRule, context: str) -> bool:
        """``context`` is "S" (server we know), "DM" or "U" (user app elsewhere)."""
        role = self.role(user_id)
        letter = _LETTER.get(role)
        return letter is not None and letter in rule.roles and context in rule.contexts.split()


class RateLimiter:
    """At most N requests per minute and person (docs/plan/14 §5.4)."""

    def __init__(
        self, cfg: Callable[[], Discord], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._cfg = cfg
        self._clock = clock
        self._seen: dict[str, deque[float]] = defaultdict(deque)

    def limit(self, role: Role) -> int:
        limits = self._cfg().rate_limits
        return {
            Role.OWNER: limits.owner_per_minute,
            Role.TRUSTED: limits.trusted_per_minute,
        }.get(role, limits.guest_per_minute)

    def allow(self, user_id: str, role: Role) -> bool:
        now = self._clock()
        seen = self._seen[user_id]
        while seen and now - seen[0] > 60:
            seen.popleft()
        if len(seen) >= self.limit(role):
            return False
        seen.append(now)
        return True

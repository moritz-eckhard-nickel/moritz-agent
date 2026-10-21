# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The flow of an incoming message, command or button press (docs/plan/14 §4.3, §4.4).

filter → rate limit → core turn (streamed) → rendering in the style → send. Knows nothing about
discord.py: it works on ``MessageInfo``/``Origin`` and answers through a ``Sender``, so the complete
flow is tested against the real main process without Discord.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

from moritz_agent.config.settings import Discord, Settings
from moritz_agent.core.principal import Role, owner_ids
from moritz_agent.core.turn import TurnResult
from moritz_agent.discord import components
from moritz_agent.discord.access import AccessPolicy, MessageInfo, RateLimiter, Reaction
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.core import CoreApi, CoreForbidden, CoreUnavailable
from moritz_agent.discord.render import (
    MESSAGE_LIMIT,
    OutMessage,
    redact,
    render_result,
)
from moritz_agent.discord.sender import Origin, Sender
from moritz_agent.discord.style import Styler, StyleState
from moritz_agent.logging_setup import get_logger

if TYPE_CHECKING:
    from moritz_agent.discord.commands.handlers import LocalCommands

log = get_logger("discord")

STREAM_EVERY_S = 1.2
NOTICE_EVERY_S = 30.0
MAX_STYLE_STATES = 200
MAX_REMEMBERED = 500
_SENTENCE_END = re.compile(r"[.!?…](?:\s|$)|\n")
NEEDS_PIN = "pin"


def ephemeral_for(spec: commands.Spec | None, origin: Origin, cfg: Discord) -> bool:
    """Only the caller sees it: private commands, and everything in a server that is not ours."""
    if spec is not None and spec.ephemeral:
        return True
    return origin.foreign and cfg.ephemeral_in_foreign_guilds


class Dispatcher:
    def __init__(
        self,
        core: CoreApi,
        settings: Callable[[], Settings],
        policy: AccessPolicy,
        limiter: RateLimiter,
        styler: Styler,
        *,
        secrets: Callable[[], list[str]] = list,
        draining: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], str] = lambda: date.today().isoformat(),
    ) -> None:
        self.core = core
        self.settings = settings
        self.policy = policy
        self.limiter = limiter
        self.styler = styler
        self.secrets = secrets
        self.draining = draining
        self.clock = clock
        self.today = today
        self.confirmations = components.Confirmations(clock)
        self.local: LocalCommands | None = None
        self._states: dict[str, StyleState] = {}
        self._noticed_at: dict[str, float] = {}
        self.skill_of: dict[int, str] = {}  # message id → skill of the answer (for 👍/👎)

    # -- small things ----------------------------------------------------------------------------------
    @property
    def cfg(self) -> Discord:
        return self.settings().discord

    def _state(self, conversation: str) -> StyleState:
        if conversation not in self._states and len(self._states) >= MAX_STYLE_STATES:
            self._states.pop(next(iter(self._states)))
        return self._states.setdefault(conversation, StyleState())

    def say(self, kind: str) -> OutMessage:
        """A friendly error as a message."""
        self.styler.style = self.cfg.style
        return OutMessage(content=redact(self.styler.error(kind), self.secrets()))

    async def _refuse(self, sender: Sender, kind: str, *, once_for: str = "") -> None:
        """Say "not so fast" or "I am being updated" – but not again within 30 seconds."""
        if once_for:
            now = self.clock()
            if now - self._noticed_at.get(once_for, -NOTICE_EVERY_S) < NOTICE_EVERY_S:
                return
            self._noticed_at[once_for] = now
        await sender.send(self.say(kind))

    # -- messages --------------------------------------------------------------------------------------
    async def message(self, info: MessageInfo, origin: Origin, sender: Sender) -> TurnResult | None:
        """Answer a message if it is meant for Anton; returns the answer (``None``: not answered)."""
        decision = self.policy.message(info, today=self.today())
        if decision.reaction is Reaction.IGNORE:
            return None
        if decision.reaction is Reaction.NOTICE:
            await sender.send(OutMessage(content=decision.text))
            return None
        user = origin.user_id
        if self.draining():
            await self._refuse(sender, "maintenance", once_for=f"drain:{user}")
            return None
        if not self.limiter.allow(user, decision.role):
            await self._refuse(sender, "rate_limited", once_for=f"rate:{user}")
            return None
        text = decision.text
        if not text.strip():
            return None
        limit = self.cfg.max_message_chars
        if len(text) > limit:
            text = text[:limit]
            self.styler.style = self.cfg.style
            await sender.send(OutMessage(content=self.styler.phrase("input_cut", n=str(limit))))
        return await self.ask(text, origin, sender)

    # -- the core ----------------------------------------------------------------------------------------
    async def ask(
        self, text: str, origin: Origin, sender: Sender, *, surface: str = "chat"
    ) -> TurnResult | None:
        """One question to the core, streamed into the channel, rendered in the style."""
        cfg = self.cfg
        self.styler.style = cfg.style
        secrets = self.secrets()
        state = self._state(origin.conversation)
        streamed: dict[str, Any] = {"handle": None, "last": 0.0, "shown": ""}

        async def on_event(event: dict[str, Any]) -> None:
            if event.get("type") != "partial":
                return
            partial = redact(str(event.get("text", "")), secrets)
            if len(partial) > MESSAGE_LIMIT - 4:
                return  # the final answer is split into pieces; stop editing here
            now = self.clock()
            if streamed["handle"] is None:
                if _SENTENCE_END.search(partial):
                    streamed["handle"] = await sender.send(
                        OutMessage(content=partial + " ▌", ephemeral=sender.ephemeral)
                    )
                    streamed["last"], streamed["shown"] = now, partial
            elif partial != streamed["shown"] and now - streamed["last"] >= STREAM_EVERY_S:
                await sender.edit(streamed["handle"], OutMessage(content=partial + " ▌"))
                streamed["last"], streamed["shown"] = now, partial

        try:
            async with sender.typing():
                result = await self.core.turn(
                    on_event,
                    conversation_id=origin.conversation,
                    text=text,
                    user_id=origin.user_id,
                    name=origin.name[:80],
                    surface=surface,
                    place=origin.place,
                    foreign_guild=origin.foreign,
                    reply_target=origin.reply_target(self.policy.default_channel_id),
                )
        except CoreForbidden:
            log.info("Discord: %s darf nicht fragen", origin.user_id[-4:])
            await sender.send(self.say("forbidden"))
            return None
        except CoreUnavailable as exc:
            log.warning("Discord: Antwort nicht möglich (%s)", exc)
            kind = "starting" if "not started" in str(exc) else "unavailable"
            message = self.say(kind)
            if streamed["handle"] is not None:
                await sender.edit(streamed["handle"], message)
            else:
                await sender.send(message)
            return None
        messages = render_result(
            result,
            user_id=origin.user_id,
            styler=self.styler,
            state=state,
            seed=origin.message_id,
            secrets=secrets,
            limit=MESSAGE_LIMIT,
            ephemeral=sender.ephemeral,
        )
        rest = messages
        if streamed["handle"] is not None:
            await sender.edit(streamed["handle"], messages[0])
            rest = messages[1:]
        for message in rest:
            await sender.send(message)
        for message_id in getattr(sender, "ids", []):
            self.skill_of[message_id] = result.skill_id or "agent"
        while len(self.skill_of) > MAX_REMEMBERED:
            self.skill_of.pop(next(iter(self.skill_of)))
        if result.reminder is not None:
            await sender.react("✅")
        log.info(
            "Discord: %s, %s, %s, %d ms",
            origin.place,
            Role(self.policy.role(origin.user_id)).value,
            result.skill_id or "agent",
            result.ms,
        )
        return result

    # -- commands ----------------------------------------------------------------------------------------------
    def allowed(self, spec: commands.Spec, origin: Origin) -> bool:
        return self.policy.command_allowed(origin.user_id, spec.rule, origin.where)

    async def command(
        self, spec: commands.Spec, values: dict[str, Any], origin: Origin, sender: Sender
    ) -> None:
        """A slash command. ``spec`` is the final one (``/admin status`` is the sub command)."""
        await sender.begin()
        user = origin.user_id
        if not self.allowed(spec, origin):
            await sender.send(self.say("forbidden"))
            return
        role = self.policy.role(user)
        if not self.limiter.allow(user, role):
            await self._refuse(sender, "rate_limited", once_for=f"rate:{user}")
            return
        if self.draining() and spec.say is not None:
            await self._refuse(sender, "maintenance", once_for=f"drain:{user}")
            return
        if spec.say is not None:
            await self.ask(commands.sentence(spec, values), origin, sender)
            return
        assert self.local is not None, "local commands not wired"
        await self.local.run(spec, values, origin, sender)

    async def context_menu(self, name: str, text: str, origin: Origin, sender: Sender) -> None:
        """ "Anton fragen" on a message."""
        await sender.begin()
        if self.policy.role(origin.user_id) is Role.UNKNOWN:
            await sender.send(self.say("forbidden"))
            return
        if not self.limiter.allow(origin.user_id, self.policy.role(origin.user_id)):
            await self._refuse(sender, "rate_limited", once_for=f"rate:{origin.user_id}")
            return
        if self.draining():  # (an interaction always gets an answer, never a silent defer)
            await sender.send(self.say("maintenance"))
            return
        await self.ask(text[: self.cfg.max_message_chars], origin, sender)

    # -- buttons and menus ---------------------------------------------------------------------------------------
    async def component(
        self, custom_id: str, values: list[str], origin: Origin, sender: Sender
    ) -> str | None:
        """A press on a button or a choice in a menu. Returns ``"pin"`` when the PIN dialog must open."""
        decoded = components.decode(custom_id)
        if decoded is None:
            return None
        user = origin.user_id
        role = self.policy.role(user)
        if role is Role.UNKNOWN:
            await sender.begin()
            await sender.send(self.say("forbidden"))
            return None
        if decoded.kind == components.CONFIRM:
            return await self._confirm(decoded, origin, sender)
        if not components.may_press(user, decoded.user_id, owner_ids(self.cfg)):
            await sender.begin()
            await sender.send(OutMessage(content="Das ist nicht deine Frage 🙈", ephemeral=True))
            return None
        await sender.begin()
        if not self.limiter.allow(user, role):
            await self._refuse(sender, "rate_limited", once_for=f"rate:{user}")
            return None
        if self.draining() and decoded.kind in {components.ACTION, components.PICK}:
            await sender.send(self.say("maintenance"))
            return None
        if decoded.kind == components.ACTION:
            await self.ask(decoded.payload, origin, sender)
        elif decoded.kind == components.PICK and values:
            await self.ask(_pick_text(values[0]), origin, sender)
        return None

    async def _confirm(
        self, decoded: components.Decoded, origin: Origin, sender: Sender
    ) -> str | None:
        assert self.local is not None
        user = origin.user_id
        pending = self.confirmations.peek(decoded.nonce, user)
        if decoded.answer == "ok" and pending is not None and pending.needs_pin:
            return NEEDS_PIN  # the PIN dialog has to be the first answer to the press
        await sender.begin()
        if decoded.answer != "ok":
            self.confirmations.take(decoded.nonce, user)
            await sender.send(OutMessage(content="Okay, dann lasse ich es.", ephemeral=True))
            return None
        if pending is None:
            await sender.send(
                OutMessage(content="Das ist abgelaufen. Bitte noch einmal.", ephemeral=True)
            )
            return None
        self.confirmations.take(decoded.nonce, user)
        await self.local.admin.execute(pending.action, origin, sender)
        return None

    async def pin_submitted(self, nonce: str, pin: str, origin: Origin, sender: Sender) -> None:
        """The PIN dialog of a dangerous admin command was filled in."""
        assert self.local is not None
        await sender.begin()
        user = origin.user_id
        if self.confirmations.pin_blocked(user):
            await sender.send(
                OutMessage(
                    content="Zu viele falsche PINs. Bitte in zehn Minuten wieder.", ephemeral=True
                )
            )
            return
        if not self.local.admin.pin_ok(pin):
            self.confirmations.pin_failed(user)
            await sender.send(OutMessage(content="Die PIN stimmt nicht.", ephemeral=True))
            return
        pending = self.confirmations.take(nonce, user)
        if pending is None:
            await sender.send(
                OutMessage(content="Das ist abgelaufen. Bitte noch einmal.", ephemeral=True)
            )
            return
        await self.local.admin.execute(pending.action, origin, sender)

    # -- reactions -----------------------------------------------------------------------------------------------
    async def feedback(self, user_id: str, emoji: str, skill_id: str = "agent") -> bool:
        """👍/👎 on an answer of Anton goes to the statistics (docs/plan/14 §8.3)."""
        rating = {"👍": "up", "👎": "down"}.get(emoji)
        if rating is None or self.policy.role(user_id) is Role.UNKNOWN:
            return False
        try:
            await self.core.feedback(skill_id, rating)
        except (CoreUnavailable, CoreForbidden):
            return False
        return True


def _pick_text(value: str) -> str:
    """ "2:Neustadt in Hessen" → "2" (the router knows ordinals), further down the list the name."""
    index, _, label = value.partition(":")
    if index.isdigit() and 1 <= int(index) <= 4:
        return index
    return label or value

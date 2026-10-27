# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Conversations of the chat channels (Discord, web) with the core (P1-31).

One ``ChatService`` serves every conversation: a DM, a text channel, a thread, a voice session.
It keeps the skill context per conversation (follow-ups, open questions), applies the person's
role and home town, runs skills first and the language model behind them, keeps reminders and
returns a ``TurnResult`` – plain data the channel renders as it likes.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from moritz_agent.core.callback import phone_request
from moritz_agent.core.principal import Principal, Role
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn, TurnResult, from_skill
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import Reply, ResponderUnavailable, TurnContext
from moritz_agent.skills.geo.gazetteer import Place

if TYPE_CHECKING:
    from moritz_agent.runtime import Runtime

log = get_logger("system")

CONVERSATION_TTL_S = 3600
CONVERSATIONS_MAX = 200
HISTORY_TURNS = 100  # the context builder drops the oldest turns that do not fit (P2-03)
MEMORY_NOTICE = (
    "Ich hab mein Kurzzeitgedächtnis geleert – {minutes} Minuten war Ruhe. Wir fangen frisch an."
)


class AccessDenied(PermissionError):
    """The person has no right to talk to Anton (unknown role)."""


@dataclass
class _Conversation:
    context: TurnContext
    touched: float
    task: asyncio.Task[Reply] | None = None
    target: str = ""  # where a note about this conversation goes (Discord reply target)
    notify: bool = False  # a written chat: say so when the memory is emptied after a quiet time


class ChatService:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._conversations: dict[str, _Conversation] = {}

    # -- people -----------------------------------------------------------------------------------
    def principal(
        self, user_id: str, role: Role, name: str = "", channel: str = "discord"
    ) -> Principal:
        """The person with the settings saved for them (home town, quiet hours, voice reply)."""
        saved = (
            self.runtime.discord_store.principal(user_id) if self.runtime.discord_store else None
        )
        if saved is None:
            return Principal(f"{channel}:{user_id}", role, channel, name)
        return Principal(
            f"{channel}:{user_id}",
            role,
            channel,
            name,
            saved.get("home_postal_code"),
            saved.get("home_name"),
            saved.get("quiet_hours"),
            saved.get("voice_reply"),
        )

    def home_of(self, principal: Principal) -> Place | None:
        """Personal home town; ``None`` means the household's (``skills.home``)."""
        gazetteer = self.runtime.svc.gazetteer if self.runtime.svc else None
        if gazetteer is None:
            return None
        if principal.home_postal_code:
            place = gazetteer.by_postcode(principal.home_postal_code)
            if place is not None:
                return place
        if principal.home_name:
            found = gazetteer.find(principal.home_name, limit=1).best
            if found is not None:
                return found.place
        return None

    # -- conversations ---------------------------------------------------------------------------------
    def _conversation(self, turn: Turn) -> _Conversation:
        self._expire()
        conversation = self._conversations.get(turn.conversation_id)
        if conversation is None:
            context = TurnContext(
                call_id=turn.conversation_id,
                assistant_name=self.runtime.settings.phone.assistant_name,
                timezone=self.runtime.settings.general.timezone,
                started_at=time.monotonic(),
            )
            history = getattr(self.runtime, "history", None)
            if turn.principal.channel == "web" and history is not None:
                # a web conversation continued after a restart remembers what was said (P2-04)
                with contextlib.suppress(Exception):
                    context.history = history.pairs(turn.conversation_id, HISTORY_TURNS)
            conversation = self._conversations[turn.conversation_id] = _Conversation(
                context, time.monotonic()
            )
        conversation.touched = time.monotonic()
        conversation.target = turn.reply_target or conversation.target
        conversation.notify = (
            turn.surface is Surface.CHAT
            and turn.principal.channel == "discord"
            and turn.place != "voice"
        )
        return conversation

    def sweep_idle(self, minutes: int, now: float | None = None) -> list[str]:
        """Empty the short-term memory of chats that were quiet for ``minutes`` (Moritz, 24.10.2026:
        "wenn im Discord-Chat 30 Minuten keine Nachricht kam, sagt er, dass er sein Kurzzeitgedächtnis
        geleert hat"). Returns the places that get a note."""
        if minutes <= 0:
            return []
        now = time.monotonic() if now is None else now
        noted: list[str] = []
        for conversation in self._conversations.values():
            context = conversation.context
            if not context.history or now - conversation.touched < minutes * 60:
                continue
            forget(context)
            if conversation.notify and conversation.target:
                noted.append(conversation.target)
        return noted

    def flush(self, conversation_id: str) -> bool:
        conversation = self._conversations.get(conversation_id)
        if conversation is None or not conversation.context.history:
            return False
        forget(conversation.context)
        return True

    def _expire(self) -> None:
        now = time.monotonic()
        for key in [
            k for k, c in self._conversations.items() if now - c.touched > CONVERSATION_TTL_S
        ]:
            del self._conversations[key]
        while len(self._conversations) > CONVERSATIONS_MAX:
            oldest = min(self._conversations, key=lambda k: self._conversations[k].touched)
            del self._conversations[oldest]

    def end(self, conversation_id: str) -> None:
        conversation = self._conversations.pop(conversation_id, None)
        if conversation is not None and conversation.task is not None:
            conversation.task.cancel()

    def cancel(self, conversation_id: str) -> bool:
        conversation = self._conversations.get(conversation_id)
        if conversation is not None and conversation.task is not None:
            conversation.task.cancel()
            return True
        return False

    def forget_home(self, user_id: str) -> None:
        """A changed home town applies to the next question of every open conversation."""
        for conversation in self._conversations.values():
            skills = conversation.context.extras.get("skills")
            if skills is not None and skills.user_id == user_id:
                skills.home = None

    # -- one exchange --------------------------------------------------------------------------------------
    def _prepare(self, turn: Turn) -> _Conversation:
        if turn.principal.role is Role.UNKNOWN:
            raise AccessDenied(turn.principal.short())
        responder = self.runtime.skill_responder
        if responder is None:
            raise ResponderUnavailable("runtime not started")
        conversation = self._conversation(turn)
        context = conversation.context
        context.extras.update(
            surface=turn.surface.value, channel=turn.principal.channel, principal=turn.principal
        )
        skills = responder.context_for(context)
        skills.role = turn.principal.role.value
        skills.user_id = turn.principal.user_id
        skills.home = self.home_of(turn.principal)
        return conversation

    async def events(
        self, turn: Turn, *, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """``thinking`` / ``partial`` while the answer is made, then ``result``.

        ``on_event`` hears the tool calls of the language model as they happen (WebUI runs).
        """
        conversation = self._prepare(turn)
        context = conversation.context
        responder = self.runtime.skill_responder
        assert responder is not None
        question = self._callback_question(turn)
        if question is not None:
            yield {"type": "result", "result": await self._call_back(turn, question)}
            return
        chunks: list[str] = []
        context.extras["on_text"] = chunks.append if turn.surface is Surface.CHAT else None
        context.extras["on_event"] = on_event
        started = time.monotonic()
        task = asyncio.ensure_future(responder.respond(turn.text, context))
        conversation.task = task
        sent_thinking: str | None = None
        sent_len = 0
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.05)
                skills = context.extras.get("skills")
                prompt = getattr(skills, "thinking_prompt", None)
                if prompt and prompt != sent_thinking:
                    sent_thinking = prompt
                    yield {"type": "thinking", "prompt": prompt}
                text = "".join(chunks)
                if len(text) > sent_len and not task.done():
                    sent_len = len(text)
                    yield {"type": "partial", "text": text}
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            conversation.task = None
            context.extras.pop("on_text", None)
            context.extras.pop("on_event", None)
        if task.cancelled():
            yield {"type": "cancelled"}
            return
        reply = task.result()
        result = self._result(reply, turn, round((time.monotonic() - started) * 1000))
        self._remember(context, turn, reply)
        self._keep_reminder(turn, reply, result)
        self.runtime.record_chat_turn(turn, reply, result)
        yield {"type": "result", "result": result}

    async def run(self, turn: Turn) -> TurnResult:
        result: TurnResult | None = None
        async for event in self.events(turn):
            if event["type"] == "result":
                result = event["result"]
        if result is None:
            raise ResponderUnavailable("answer cancelled")
        return result

    # -- Anton calls back --------------------------------------------------------------------------------------
    def _callback_question(self, turn: Turn) -> str | None:
        """Only typed by the owner on Discord – never from a call or the voice channel."""
        cfg = self.runtime.settings.phone
        if (
            not cfg.enabled
            or not cfg.callback.enabled
            or turn.principal.channel != "discord"
            or turn.surface is not Surface.CHAT
            or turn.place == "voice"
            or turn.principal.role is not Role.OWNER
        ):
            return None
        return phone_request(turn.text)

    async def _call_back(self, turn: Turn, question: str) -> TurnResult:
        """Answer the question as on the phone (spoken form) and hand it to the phone worker."""
        responder = self.runtime.skill_responder
        assert responder is not None
        cfg = self.runtime.settings.phone
        context = TurnContext(
            f"callback-{turn.principal.user_id}",
            cfg.assistant_name,
            self.runtime.settings.general.timezone,
        )
        context.extras.update(
            surface=Surface.SPOKEN.value, channel="phone", principal=turn.principal
        )
        skills = responder.context_for(context)
        skills.role = turn.principal.role.value
        skills.user_id = turn.principal.user_id
        skills.home = self.home_of(turn.principal)
        started = time.monotonic()
        reply = await responder.respond(question, context)
        text = (reply.text or "").strip()
        if not text:
            return TurnResult(
                text="Darauf habe ich gerade keine Antwort, die ich dir am Telefon sagen könnte."
            )
        call = self.runtime.callbacks.add(
            text,
            cfg.callback.extension,
            (cfg.callback.ring_min_s, cfg.callback.ring_max_s),
            cfg.callback.speak_after_s,
        )
        if call is None:
            return TurnResult(text="Ich hab schon genug Anrufe vor mir – gleich noch mal, ja?")
        log.info(
            "Rückruf %d an %s angefordert (%s)", call.id, call.extension, turn.principal.short()
        )
        message = "Okay, ich rufe dich an."
        return TurnResult(
            text=message, markdown=message, ms=round((time.monotonic() - started) * 1000)
        )

    # -- details ------------------------------------------------------------------------------------------------
    @staticmethod
    def _result(reply: Reply, turn: Turn, ms: int) -> TurnResult:
        skill_result = reply.result
        if skill_result is not None:
            return from_skill(skill_result, reply.skill_id, ms=ms, surface=turn.surface)
        meta = reply.meta or {}
        return TurnResult(
            text=reply.text or "",
            markdown=reply.text or "",
            prompt=reply.prompt,
            hangup=reply.hangup,
            tools=list(meta.get("tools", [])),
            sources=list(meta.get("sources", [])),
            ms=ms,
        )

    @staticmethod
    def _remember(context: TurnContext, turn: Turn, reply: Reply) -> None:
        context.turn += 1
        context.last_reply = reply.text or context.last_reply
        if getattr(reply.result, "forget", False):
            forget(context)
            return
        remember(context, turn.text, reply)

    def _keep_reminder(self, turn: Turn, reply: Reply, result: TurnResult) -> None:
        """Reminders and timers of a chat live in the database and are delivered where asked."""
        skill_result = reply.result
        store = self.runtime.discord_store
        if skill_result is None or store is None or turn.principal.channel != "discord":
            return
        due: datetime | None = None
        text = ""
        if skill_result.reminder is not None:
            due, text = skill_result.reminder
        elif skill_result.start_timer is not None:
            seconds, label = skill_result.start_timer
            due = self.runtime.svc.now() + _seconds(seconds)
            text = f"Der Timer ({label}) ist abgelaufen."
        if due is None:
            return
        reminder_id = store.add_reminder(
            turn.principal.user_id, turn.reply_target, due.astimezone(UTC), text
        )
        result.reminder = {
            "id": reminder_id,
            "due": due.isoformat(timespec="seconds"),
            "text": text,
        }


def _seconds(value: float):
    from datetime import timedelta

    return timedelta(seconds=value)


def remember(context: TurnContext, heard: str, reply: Reply) -> None:
    """One exchange into the short-term memory – instant answers too, so the language model knows
    what was asked and said ("wie ist das Wetter?" … "und morgen?")."""
    context.history.append((heard, reply.text or reply.prompt or ""))
    del context.history[:-HISTORY_TURNS]


def forget(context: TurnContext) -> None:
    """The short-term memory starts fresh: no history, no follow-up state of the instant answers."""
    context.history.clear()
    skills = context.extras.get("skills")
    if skills is not None:
        skills.last = None
        skills.pending = None
        skills.last_text = ""

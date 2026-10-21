# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The answers of the voice channel: the same core as everywhere, spoken style (docs/plan/14 §9.1).

``CallSession`` asks a ``Responder`` for every utterance; this one forwards it to the main process
(``/internal/discord/turn``, ``surface = spoken``, conversation = the voice channel), so instant
answers, tools and the language model behave exactly as on the phone.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from moritz_agent.discord import sessions
from moritz_agent.discord.core import CoreApi, CoreForbidden, CoreUnavailable
from moritz_agent.phone.remote import RemoteSkillState
from moritz_agent.phone.responder import Reply, ResponderUnavailable, TurnContext


class VoiceResponder:
    def __init__(
        self, core: CoreApi, channel_id: str | int, speaker: Callable[[], tuple[str, str]]
    ) -> None:
        self.core = core
        self.conversation = sessions.voice(channel_id)
        self.speaker = speaker  # → (user id, display name) of whoever is talking to Nikita

    async def respond(self, text: str, context: TurnContext) -> Reply:
        state = context.extras.setdefault("skills", RemoteSkillState())
        state.thinking_prompt = None
        user_id, name = self.speaker()

        async def on_event(event: dict) -> None:
            if event.get("type") == "thinking":
                state.thinking_prompt = event.get("prompt")

        try:
            result = await self.core.turn(
                on_event,
                conversation_id=self.conversation,
                text=text,
                user_id=user_id,
                name=name[:80],
                surface="spoken",
                place="voice",
                reply_target="default",
            )
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await self.core.cancel(self.conversation)
            raise
        except (CoreUnavailable, CoreForbidden) as exc:
            raise ResponderUnavailable(str(exc)) from exc
        return Reply(
            text=result.text or None,
            prompt=result.prompt,
            hangup=result.hangup,
            skill_id=result.skill_id,
        )

    async def end(self) -> None:
        """The conversation is over: the core forgets its context (like hanging up)."""
        with contextlib.suppress(Exception):
            await self.core.end(self.conversation)

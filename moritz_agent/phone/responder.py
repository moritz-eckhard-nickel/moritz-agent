# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""What Anton answers: the interface between the phone and the agent (P1-09 plugs in here).

The phone part only needs ``Responder.respond(text, context) -> Reply``. The real agent (language
model, tools, web search) will implement it; until then :class:`TestResponder` answers the fast
paths (time, date, …) and otherwise repeats what it understood – enough to test the complete
chain telephone → speech recognition → answer → voice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from moritz_agent.agent import fastpath


@dataclass(frozen=True)
class Reply:
    text: str | None = None
    prompt: str | None = None  # id of a pre-recorded announcement
    hangup: bool = False
    result: Any = None  # the full SkillResult (card, buttons, sources …) for chat channels
    skill_id: str | None = None
    meta: dict[str, Any] | None = None  # model answers: {"tools": […], "sources": […]}


@dataclass
class TurnContext:
    call_id: str
    assistant_name: str = "Anton"
    timezone: str = "Europe/Berlin"
    turn: int = 0
    last_reply: str | None = None
    history: list[tuple[str, str]] = field(default_factory=list)  # (caller, assistant)
    started_at: float | None = None  # time.monotonic() when the call/chat started
    extras: dict[str, Any] = field(default_factory=dict)  # per-conversation state of responders


class ResponderUnavailable(RuntimeError):
    """The component behind the answers is not reachable (language model down, …)."""


class Responder(Protocol):
    async def respond(self, text: str, context: TurnContext) -> Reply: ...


class TestResponder:
    """Fast paths, otherwise an honest "I understood X" (test mode, no language model)."""

    __test__ = False  # not a pytest class

    async def respond(self, text: str, context: TurnContext) -> Reply:
        result = fastpath.answer(text, context.assistant_name, context.last_reply, context.timezone)
        if result is not None:
            return Reply(text=result.text, prompt=result.prompt, hangup=result.hangup)
        heard = text.strip().rstrip(".!?")
        return Reply(
            text=f"Ich habe verstanden: {heard}. Dazu kann ich im Testmodus noch nichts sagen."
        )

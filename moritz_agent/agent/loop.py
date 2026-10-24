# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The agent loop: question → (tool call → result) × n → answer (AGENT-01, AGENT-03, AGENT-04).

* at most ``max_tool_steps`` rounds of tool calls, then the model must answer without tools
* the whole turn has a deadline; when it runs out the generation is stopped and the answer is honest
* clock times and weather values the model states without the matching tool are replaced by what the
  tool says (AGENT-06, AGENT-11)
* cancelling the task (hang-up) stops the generation on the model server
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from moritz_agent.agent import guard
from moritz_agent.agent.context import ContextBuilder
from moritz_agent.agent.profiles import Profile
from moritz_agent.agent.speakable import clean, make_speakable, strip_reasoning
from moritz_agent.inference import Completion, InferenceQueue, Priority, ToolCall
from moritz_agent.logging_setup import get_logger
from moritz_agent.tools.base import ToolContext, ToolResult
from moritz_agent.tools.registry import ToolRegistry

log = get_logger("agent")

DEADLINE_TEXT = "Das dauert gerade zu lange. Versuch es bitte gleich noch einmal."
EMPTY_TEXT = "Dazu fällt mir gerade nichts Sinnvolles ein. Kannst du es anders sagen?"
UNSURE_TEXT = "Das kann ich dir gerade nicht sicher sagen."
MAX_CALLS_PER_STEP = 3
_DATE_WORDS = re.compile(r"\b(?:datum|wochentag|welcher tag|den wievielten|kalenderwoche)\b", re.I)

TextSink = Callable[[str], Awaitable[None] | None]


@dataclass
class AgentResult:
    text: str
    hangup: bool = False
    tools: list[str] = field(default_factory=list)  # tools that ran successfully
    sources: list[dict[str, str]] = field(default_factory=list)
    steps: int = 0
    guard: str | None = None  # "time" | "weather" when an answer had to be replaced
    failure: str | None = None  # "deadline" | "empty"
    ms: int = 0
    dropped_turns: int = 0


@dataclass
class _Turn:
    user_text: str
    ctx: ToolContext
    messages: list[dict[str, Any]]
    called: set[str] = field(default_factory=set)
    sources: list[dict[str, str]] = field(default_factory=list)
    invalid: int = 0
    steps: int = 0
    repaired: guard.Violation | None = None
    forced: ToolResult | None = None
    last_speakable: str = ""
    weather_values: set[tuple[str, str]] = field(default_factory=set)
    weather_text: str = ""


class AgentLoop:
    def __init__(
        self,
        queue: InferenceQueue,
        tools: ToolRegistry,
        profile: Profile,
        *,
        context_size: int = 4096,
        priority: Priority = Priority.PHONE,
        label: str = "phone",
    ) -> None:
        self.queue = queue
        self.tools = tools
        self.profile = profile
        self.context_size = context_size
        self.priority = priority
        self.label = label

    # -- public ---------------------------------------------------------------------------------
    async def run(
        self,
        user_text: str,
        history: list[tuple[str, str]],
        ctx: ToolContext,
        *,
        on_text: TextSink | None = None,
    ) -> AgentResult:
        started = time.monotonic()
        definitions = self.tools.definitions(self.profile.tools)
        builder = ContextBuilder(
            self.profile.system_prompt,
            context_size=self.context_size,
            answer_tokens=self.profile.max_answer_tokens,
            tools=definitions,
            counter=self.queue.client.token_count,
        )
        built = await builder.build(history, user_text)
        turn = _Turn(user_text, ctx, built.messages)
        try:
            async with asyncio.timeout(self.profile.deadline_s):
                result = await self._run(turn, definitions, on_text)
        except TimeoutError:
            log.warning("Antwort nach %.0f s abgebrochen (Deadline)", self.profile.deadline_s)
            result = AgentResult(DEADLINE_TEXT, failure="deadline")
        result.steps = turn.steps
        result.tools = sorted(turn.called)
        result.sources = turn.sources
        result.dropped_turns = built.dropped_turns
        result.hangup = guard.is_farewell(user_text) or "end_call" in turn.called
        result.ms = round((time.monotonic() - started) * 1000)
        log.info(
            "Agent: %d Schritte, Werkzeuge %s, %d ms%s",
            result.steps,
            ",".join(result.tools) or "keine",
            result.ms,
            f", Guard {result.guard}" if result.guard else "",
        )
        return result

    # -- the loop -------------------------------------------------------------------------------
    async def _run(
        self, turn: _Turn, definitions: list[dict[str, Any]], on_text: TextSink | None
    ) -> AgentResult:
        profile = self.profile
        # one extra round is allowed for a guard repair
        for _ in range(profile.max_tool_steps + 2):
            offer = (
                bool(definitions)
                and turn.steps < profile.max_tool_steps
                and turn.invalid <= profile.invalid_retries
                and turn.repaired is None
            )
            completion = await self.queue.chat(
                turn.messages,
                priority=self.priority,
                label=self.label,
                tools=definitions if offer else None,
                max_tokens=profile.max_answer_tokens,
                temperature=profile.temperature,
                on_text=on_text,
            )
            if completion.tool_calls and offer:
                await self._tools(turn, completion)
                continue
            answer = self._answer(turn, completion)
            violation = guard.check(
                turn.user_text, clean(answer), turn.called, supported=turn.weather_values
            )
            if violation is None:
                return self._finish(turn, answer)
            if (
                violation.kind != "weather_mismatch"
                and turn.repaired is None
                and await self._repair(turn, violation)
            ):
                forced = turn.forced
                if violation.kind == "time" and forced is not None and forced.ok:
                    # the clock needs no wording: the tool's sentence is the answer (AGENT-06)
                    return self._finish(turn, forced.speakable or "", guarded="time")
                if forced is not None and forced.error == "no_answer":
                    # no weather skill knows the question: it was no weather question after all
                    # ("Bei wie viel Grad schmilzt Eisen?"), so the model's answer stands
                    turn.repaired = None
                    return self._finish(turn, answer)
                continue  # the model words the answer again, now with the tool result at hand
            return self._finish(turn, self._deterministic(turn, violation), guarded=violation.kind)
        return self._finish(turn, turn.last_speakable or EMPTY_TEXT)

    def _answer(self, turn: _Turn, completion: Completion) -> str:
        return strip_reasoning(completion.text) if completion.text else ""

    async def _tools(self, turn: _Turn, completion: Completion) -> None:
        calls = completion.tool_calls[:MAX_CALLS_PER_STEP]
        turn.messages.append(
            {
                "role": "assistant",
                "content": completion.text or None,
                "tool_calls": [_wire(call) for call in calls],
            }
        )
        turn.steps += 1
        for call in calls:
            arguments: Any = call.arguments if call.valid_json else call.raw_arguments
            result = await self.tools.call(
                call.name, arguments, turn.ctx, allowed=self.profile.tools
            )
            self._note(turn, call.name, result)
            turn.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result.payload(), ensure_ascii=False, default=str),
                }
            )

    def _note(self, turn: _Turn, name: str, result: ToolResult) -> None:
        if result.ok:
            turn.called.add(name)
            turn.sources.extend(result.sources)
            if result.speakable:
                turn.last_speakable = result.speakable
            if name in guard.WEATHER_TOOLS:
                turn.weather_text = result.speakable or turn.weather_text
                data = result.data if isinstance(result.data, dict) else {}
                spoken = f"{result.speakable or ''} {data.get('detail') or ''}"
                turn.weather_values |= guard.weather_values(spoken)
        elif result.error == "invalid_arguments":
            turn.invalid += 1

    # -- guards ---------------------------------------------------------------------------------
    async def _repair(self, turn: _Turn, violation: guard.Violation) -> bool:
        """Run the tool the model skipped and show the result to it (as if it had asked)."""
        if violation.tool not in self.profile.tools:
            return False
        if violation.kind == "time":
            kind = "date" if _DATE_WORDS.search(turn.user_text) else "time"
            arguments: dict[str, Any] = {"kind": kind}
        else:
            arguments = {"question": turn.user_text}
        call_id = f"guard_{violation.kind}"
        turn.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": violation.tool,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                ],
            }
        )
        result = await self.tools.call(
            violation.tool, arguments, turn.ctx, allowed=self.profile.tools
        )
        self._note(turn, violation.tool, result)
        turn.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result.payload(), ensure_ascii=False, default=str),
            }
        )
        turn.repaired = violation
        turn.forced = result
        log.info("Guard %s: Antwort verworfen, %s ausgeführt", violation.kind, violation.tool)
        return True

    def _deterministic(self, turn: _Turn, violation: guard.Violation) -> str:
        """The tool's own sentence when the model still states a value it did not get from it."""
        if violation.kind == "weather_mismatch" and turn.weather_text:
            return turn.weather_text
        forced = turn.forced
        if forced is not None and forced.ok and forced.speakable:
            return forced.speakable
        if forced is not None and forced.message:
            return forced.message
        return UNSURE_TEXT

    def _finish(self, turn: _Turn, answer: str, *, guarded: str | None = None) -> AgentResult:
        profile = self.profile
        if profile.speak:
            text = make_speakable(
                answer, max_sentences=profile.max_sentences, max_chars=profile.max_chars
            )
        else:  # chat: markdown stays, only reasoning goes and the length is limited
            text = strip_reasoning(answer)
            if len(text) > profile.max_chars:
                text = text[: profile.max_chars].rsplit(" ", 1)[0].rstrip(",;:") + " …"
        if not text:
            return AgentResult(turn.last_speakable or EMPTY_TEXT, failure="empty", guard=guarded)
        return AgentResult(text, guard=guarded or (turn.repaired.kind if turn.repaired else None))


def _wire(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": call.raw_arguments or json.dumps(call.arguments, ensure_ascii=False),
        },
    }

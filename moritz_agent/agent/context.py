# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Context manager: what goes into the prompt and what is left out (AGENT-05).

The budget is the context window minus room for the answer, the tool schemas and the tool results
of this turn. The estimate is 3.5 characters per token plus 15 % reserve; only when a prompt comes
close to the limit the exact count of the model server is asked for.
"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

CHARS_PER_TOKEN = 3.5
RESERVE = 1.15
TOOL_RESULT_RESERVE = 400  # tokens for what the tools bring back in this turn
CLOSE_TO_LIMIT = 0.85  # above this share of the budget the exact count is asked for

Counter = Callable[[str], Awaitable[int | None]]


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN * RESERVE)


def message_tokens(message: dict[str, Any]) -> int:
    content = message.get("content") or ""
    extra = (
        json.dumps(message.get("tool_calls"), ensure_ascii=False)
        if message.get("tool_calls")
        else ""
    )
    return estimate_tokens(f"{content}{extra}") + 4  # role and separators


@dataclass
class BuiltContext:
    messages: list[dict[str, Any]]
    dropped_turns: int = 0
    estimated_tokens: int = 0


class ContextBuilder:
    def __init__(
        self,
        system_prompt: str,
        *,
        context_size: int,
        answer_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        counter: Counter | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.counter = counter
        schema_tokens = estimate_tokens(json.dumps(tools, ensure_ascii=False)) if tools else 0
        self.budget = max(256, context_size - answer_tokens - schema_tokens - TOOL_RESULT_RESERVE)

    def _assemble(self, turns: list[tuple[str, str]], user_text: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        for heard, said in turns:
            messages.append({"role": "user", "content": heard})
            if said:
                messages.append({"role": "assistant", "content": said})
        messages.append({"role": "user", "content": user_text})
        return messages

    async def build(self, history: list[tuple[str, str]], user_text: str) -> BuiltContext:
        """System prompt, as many of the latest turns as fit, then the new question."""
        fixed = message_tokens({"content": self.system_prompt}) + message_tokens(
            {"content": user_text}
        )
        kept: list[tuple[str, str]] = []
        used = fixed
        for heard, said in reversed(history):
            cost = message_tokens({"content": heard}) + (
                message_tokens({"content": said}) if said else 0
            )
            if used + cost > self.budget:
                break
            kept.append((heard, said))
            used += cost
        kept.reverse()
        dropped = len(history) - len(kept)
        messages = self._assemble(kept, user_text)
        # close to the limit: the exact count decides, one oldest turn at a time
        while kept and used > self.budget * CLOSE_TO_LIMIT and self.counter is not None:
            exact = await self.counter("\n".join(str(m["content"]) for m in messages))
            if exact is None or exact <= self.budget:
                break
            kept.pop(0)
            dropped += 1
            messages = self._assemble(kept, user_text)
            used = sum(message_tokens(m) for m in messages)
        return BuiltContext(messages, dropped, used)

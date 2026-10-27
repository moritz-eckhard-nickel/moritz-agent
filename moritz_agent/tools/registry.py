# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Tool registry: profile permissions, argument validation, time limit, size limit, logging (P1-07).

``ToolRegistry.call`` never raises: whatever goes wrong becomes a ``ToolResult`` the language model
can read and react to ("invalid_arguments" lets it retry, "search_unavailable" makes it say honestly
that it cannot look things up right now).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Collection, Iterable
from typing import Any

from moritz_agent.logging_setup import get_logger
from moritz_agent.tools.base import Tool, ToolContext, ToolResult
from moritz_agent.tools.schema import validate

log = get_logger("agent")

MAX_OUTPUT_CHARS = 3000
_STRING_STEPS = (600, 300, 150)
_LIST_STEPS = (8, 5, 3)


class ToolRegistry:
    def __init__(self, *, repo: Any = None, max_output_chars: int = MAX_OUTPUT_CHARS) -> None:
        self._tools: dict[str, Tool] = {}
        self.repo = repo
        self.max_output_chars = max_output_chars

    # -- registration ---------------------------------------------------------------------------
    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool

    def register_all(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self, allowed: Collection[str]) -> list[dict[str, Any]]:
        """Tool definitions for the model, restricted to the tools a profile may use."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for name, tool in self._tools.items()
            if name in allowed
        ]

    # -- calling --------------------------------------------------------------------------------
    async def call(
        self,
        name: str,
        arguments: str | dict[str, Any] | None,
        ctx: ToolContext,
        *,
        allowed: Collection[str],
    ) -> ToolResult:
        started = time.monotonic()
        _emit(ctx, {"type": "tool_call", "tool": name, "args": _summary(arguments)})
        tool = self._tools.get(name)
        if tool is None or name not in allowed:
            result = ToolResult.failure(
                "unknown_tool", f"Das Werkzeug '{name}' gibt es hier nicht. Antworte ohne Werkzeug."
            )
        else:
            result = await self._run(tool, arguments, ctx)
        result = self._limit(result)
        ms = round((time.monotonic() - started) * 1000)
        self._record(name, result, ctx, ms)
        _emit(
            ctx,
            {
                "type": "tool_result",
                "tool": name,
                "ok": result.ok,
                "ms": ms,
                "error": result.error,
                "sources": [
                    {"name": s.get("name", ""), "url": s.get("url", "")} for s in result.sources
                ],
            },
        )
        return result

    async def _run(self, tool: Tool, arguments: Any, ctx: ToolContext) -> ToolResult:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except ValueError:
                return ToolResult.failure(
                    "invalid_arguments",
                    "Die Argumente sind kein gültiges JSON. Versuche es nochmal.",
                )
        args, problems = validate(arguments, tool.parameters)
        if problems:
            return ToolResult.failure("invalid_arguments", " ".join(problems))
        try:
            async with asyncio.timeout(tool.timeout_s):
                result = await tool.run(args, ctx)
        except TimeoutError:
            result = ToolResult.failure(
                "timeout", "Das hat zu lange gedauert. Sag ehrlich, dass es gerade nicht klappt."
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Werkzeug %s ist fehlgeschlagen", tool.name)
            result = ToolResult.failure(
                "tool_failed",
                "Das Werkzeug ist ausgefallen. Sag ehrlich, dass es gerade nicht klappt.",
            )
        result.args = args
        return result

    # -- size limit -----------------------------------------------------------------------------
    def _limit(self, result: ToolResult) -> ToolResult:
        if not result.ok or _size(result.payload()) <= self.max_output_chars:
            return result
        for strings, items in zip(_STRING_STEPS, _LIST_STEPS, strict=True):
            result.data = _shrink(result.data, strings, items)
            result.truncated = True
            if _size(result.payload()) <= self.max_output_chars:
                return result
        # still too large: keep the sentence, drop the details
        result.data = None
        return result

    # -- statistics -----------------------------------------------------------------------------
    def _record(self, name: str, result: ToolResult, ctx: ToolContext, ms: int) -> None:
        if self.repo is None:
            return
        try:
            keep = bool(
                getattr(self.repo, "store_transcripts", False)
            )  # F-03: text only if allowed
            self.repo.add_tool_call(
                name,
                args=result.args if keep else {},
                ok=result.ok,
                error=result.error,
                summary=(result.speakable or result.message or "") if keep else "",
                sources=result.sources or None,
                duration_ms=ms,
                call_id=ctx.call_id,
                turn_id=ctx.turn_id,
                channel=ctx.channel,
            )
        except Exception:  # statistics must never get in the way of an answer
            log.debug("Werkzeugaufruf nicht protokolliert", exc_info=True)


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def _shrink(value: Any, max_string: int, max_items: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string].rstrip() + " …"
    if isinstance(value, list):
        return [_shrink(item, max_string, max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        return {key: _shrink(item, max_string, max_items) for key, item in value.items()}
    return value


def _emit(ctx: ToolContext, event: dict[str, Any]) -> None:
    if ctx.on_event is not None:
        try:
            ctx.on_event(event)
        except Exception:  # a listener never breaks the tool call
            log.exception("Werkzeug-Ereignis nicht zugestellt")


def _summary(arguments: Any, limit: int = 160) -> dict[str, str]:
    """The arguments for the timeline: short strings, nothing nested."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except ValueError:
            return {}
    if not isinstance(arguments, dict):
        return {}
    shown: dict[str, str] = {}
    for key, value in list(arguments.items())[:6]:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        shown[str(key)[:40]] = text if len(text) <= limit else text[: limit - 1] + "…"
    return shown

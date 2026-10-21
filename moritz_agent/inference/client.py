# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Async client for the OpenAI-compatible endpoint of KoboldCpp (streaming and tool calls)."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from moritz_agent.logging_setup import get_logger

log = get_logger("inference")


class InferenceError(RuntimeError):
    """Base class of everything that can go wrong when asking the model."""


class InferenceUnavailable(InferenceError):
    """The model server cannot be reached or answers with an error."""


class InferenceTimeout(InferenceError):
    """The model took longer than allowed."""


class InferenceAborted(InferenceError):
    """The generation was stopped on purpose (hang-up, a more important request)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    valid_json: bool = True


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    first_token_ms: int | None = None
    total_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def new_genkey() -> str:
    return "MA_" + secrets.token_hex(6)


class InferenceClient:
    def __init__(
        self,
        base_url: str,
        *,
        request_timeout_s: float = 60.0,
        model: str = "koboldcpp",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout_s = request_timeout_s
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=httpx.Timeout(request_timeout_s, connect=3.0),
        )
        self._aborted: set[str] = set()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- health ---------------------------------------------------------------------------------
    async def health(self) -> bool:
        """The model is loaded and the server answers (``/api/v1/model``)."""
        try:
            response = await self._client.get("/api/v1/model", timeout=3.0)
            return response.status_code == 200 and bool(response.json().get("result"))
        except (httpx.HTTPError, ValueError):
            return False

    async def perf(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/api/extra/perf", timeout=3.0)
            data = response.json()
            return data if isinstance(data, dict) else {}
        except (httpx.HTTPError, ValueError):
            return {}

    async def token_count(self, text: str) -> int | None:
        try:
            response = await self._client.post(
                "/api/extra/tokencount", json={"prompt": text}, timeout=3.0
            )
            return int(response.json()["value"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    async def websearch(self, query: str, timeout_s: float = 8.0) -> list[dict[str, Any]]:
        """``/api/extra/websearch`` (needs ``--websearch``): ``[{title, url, desc, content}]``."""
        try:
            response = await self._client.post(
                "/api/extra/websearch", json={"q": query}, timeout=timeout_s
            )
            rows = response.json()
        except httpx.TimeoutException as exc:
            raise InferenceTimeout("web search did not answer in time") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise InferenceUnavailable(f"web search unavailable ({type(exc).__name__})") from exc
        if response.status_code >= 400 or not isinstance(rows, list):
            raise InferenceUnavailable(f"web search answered {response.status_code}")
        return [row for row in rows if isinstance(row, dict)]

    # -- abort ----------------------------------------------------------------------------------
    async def abort(self, genkey: str) -> None:
        """Stop the generation with this key (and remember it, so ``chat`` raises)."""
        self._aborted.add(genkey)
        try:
            await self._client.post("/api/extra/abort", json={"genkey": genkey}, timeout=3.0)
        except httpx.HTTPError:
            log.warning("Abbruch der Generierung konnte nicht gemeldet werden")

    # -- chat -------------------------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 160,
        temperature: float = 0.3,
        genkey: str | None = None,
        on_text: Callable[[str], Awaitable[None] | None] | None = None,
        timeout_s: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Completion:
        genkey = genkey or new_genkey()
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "genkey": genkey,
            **(extra or {}),
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        started = time.monotonic()
        result = Completion()
        pending: dict[int, dict[str, Any]] = {}
        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=body,
                timeout=httpx.Timeout(timeout_s or self.request_timeout_s, connect=3.0),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise InferenceUnavailable(f"model server answered {response.status_code}")
                async for line in response.aiter_lines():
                    chunk = _parse_sse(line)
                    if chunk is None:
                        continue
                    if chunk == "[DONE]":
                        break
                    await self._apply(chunk, result, pending, started, on_text)
        except httpx.TimeoutException as exc:
            raise InferenceTimeout("the model did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise InferenceUnavailable(f"model server unreachable ({type(exc).__name__})") from exc
        finally:
            was_aborted = genkey in self._aborted
            self._aborted.discard(genkey)
        if was_aborted:
            raise InferenceAborted("generation aborted")
        result.total_ms = round((time.monotonic() - started) * 1000)
        result.tool_calls = [_tool_call(pending[i]) for i in sorted(pending)]
        if result.tool_calls and not result.finish_reason:
            result.finish_reason = "tool_calls"
        return result

    async def _apply(
        self,
        chunk: dict[str, Any],
        result: Completion,
        pending: dict[int, dict[str, Any]],
        started: float,
        on_text: Callable[[str], Awaitable[None] | None] | None,
    ) -> None:
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            result.prompt_tokens = usage.get("prompt_tokens", result.prompt_tokens)
            result.completion_tokens = usage.get("completion_tokens", result.completion_tokens)
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                if result.first_token_ms is None:
                    result.first_token_ms = round((time.monotonic() - started) * 1000)
                result.text += piece
                if on_text is not None:
                    outcome = on_text(piece)
                    if outcome is not None:
                        await outcome
            for call in delta.get("tool_calls") or []:
                entry = pending.setdefault(call.get("index", 0), {"id": "", "name": "", "args": ""})
                entry["id"] = call.get("id") or entry["id"]
                function = call.get("function") or {}
                entry["name"] = function.get("name") or entry["name"]
                entry["args"] += function.get("arguments") or ""
            if choice.get("finish_reason"):
                result.finish_reason = choice["finish_reason"]


def _parse_sse(line: str) -> dict[str, Any] | str | None:
    line = line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return "[DONE]"
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _tool_call(entry: dict[str, Any]) -> ToolCall:
    raw = entry["args"] or "{}"
    try:
        arguments = json.loads(raw)
        valid = isinstance(arguments, dict)
        if not valid:
            arguments = {}
    except ValueError:
        arguments, valid = {}, False
    return ToolCall(
        id=entry["id"] or "call_" + secrets.token_hex(4),
        name=entry["name"],
        arguments=arguments,
        raw_arguments=raw,
        valid_json=valid,
    )

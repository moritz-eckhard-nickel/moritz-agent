# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A fake KoboldCpp for the inference tests: OpenAI-style streaming, tool calls, abort, gates."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


def sse(data: dict[str, Any] | str) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"data: {payload}\n\n".encode()


def text_chunks(*pieces: str, finish: str = "stop") -> list[dict[str, Any]]:
    chunks = [{"choices": [{"index": 0, "delta": {"content": piece}}]} for piece in pieces]
    chunks.append(
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 20, "completion_tokens": len(pieces)},
        }
    )
    return chunks


def tool_chunks(name: str, arguments: str, call_id: str = "call_1") -> list[dict[str, Any]]:
    half = len(arguments) // 2
    return [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "function": {"name": name, "arguments": arguments[:half]},
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": arguments[half:]}}]
                    },
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


class _Stream(httpx.AsyncByteStream):
    def __init__(self, model: FakeModel, genkey: str, chunks: list[dict[str, Any]]) -> None:
        self.model, self.genkey, self.chunks = model, genkey, chunks

    async def __aiter__(self):
        model = self.model
        model.running.add(self.genkey)
        try:
            for chunk in self.chunks:
                if self.genkey in model.aborted:
                    return
                yield sse(chunk)
                await model.step(self.genkey)
            yield sse("[DONE]")
        finally:
            model.running.discard(self.genkey)


class FakeModel:
    """Answers ``/v1/chat/completions`` from a script; ``gate=True`` stops after every chunk."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.script: list[
            Any
        ] = []  # per request: list of chunks, an int (HTTP status) or an Exception
        self.default = text_chunks("Hallo", " Welt")
        self.gate = False
        self.aborted: set[str] = set()
        self.running: set[str] = set()
        self.abort_calls: list[str] = []
        self.model_loaded = True
        self._released: dict[str, asyncio.Event] = {}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    # -- control ---------------------------------------------------------------------------------
    async def step(self, genkey: str) -> None:
        if not self.gate:
            await asyncio.sleep(0)
            return
        event = self._released.setdefault(genkey, asyncio.Event())
        await event.wait()
        event.clear()

    def release(self, genkey: str | None = None) -> None:
        for key, event in list(self._released.items()):
            if genkey is None or key == genkey:
                event.set()

    def release_all(self) -> None:
        self.gate = False
        self.release()

    async def wait_for_running(self, count: int = 1, timeout: float = 2.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while len(self.running) < count:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("no generation started")
            await asyncio.sleep(0.01)

    # -- http ---------------------------------------------------------------------------------------
    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/model":
            return httpx.Response(
                200, json={"result": "koboldcpp/fake" if self.model_loaded else ""}
            )
        if path == "/api/extra/perf":
            return httpx.Response(200, json={"total_gens": 3, "queue": 0})
        if path == "/api/extra/tokencount":
            body = json.loads(request.content)
            return httpx.Response(200, json={"value": max(1, len(body["prompt"]) // 4), "ids": []})
        if path == "/api/extra/abort":
            key = json.loads(request.content).get("genkey", "")
            self.abort_calls.append(key)
            self.aborted.add(key)
            self.release(key)
            return httpx.Response(200, json={"success": "true", "done": "true"})
        if path == "/v1/chat/completions":
            body = json.loads(request.content)
            self.requests.append(body)
            step = self.script.pop(0) if self.script else self.default
            if isinstance(step, Exception):
                raise step
            if isinstance(step, int):
                return httpx.Response(step, json={"error": "nope"})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_Stream(self, body.get("genkey", ""), step),
            )
        return httpx.Response(404)

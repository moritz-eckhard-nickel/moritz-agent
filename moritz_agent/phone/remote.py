# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The phone worker's view of the main process: the same ``Responder`` interface over HTTP.

The worker (SIP, voice activity detection, speech recognition, voice) never thinks for itself when
the supervisor runs it: every utterance goes to ``/internal/phone/turn`` of the main process, where
instant answers, search and language model live (docs/plan/02 §3). The token is new on every start
of the service and is passed to the worker in its environment, never stored.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os

import httpx

from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import Reply, ResponderUnavailable, TurnContext

log = get_logger("phone")
ENV_URL = "MORITZ_INTERNAL_URL"
ENV_TOKEN = "MORITZ_INTERNAL_TOKEN"


class RemoteSkillState:
    """Stands in for the skill context of the main process: the dialogue reads the more specific
    "one moment" announcement ("thinking_weather") from here while an answer is still pending."""

    def __init__(self) -> None:
        self.thinking_prompt: str | None = None


def from_environment() -> RemoteResponder | None:
    url, token = os.environ.get(ENV_URL), os.environ.get(ENV_TOKEN)
    if url and token:
        return RemoteResponder(url, token)
    return None


class RemoteResponder:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Internal-Token": token},
            transport=transport,
            timeout=httpx.Timeout(None, connect=2.0),  # the turn deadline is the dialogue's job
        )
        self._background: set[asyncio.Task[None]] = set()

    async def aclose(self) -> None:
        for task in list(self._background):
            task.cancel()
        await self._client.aclose()

    # -- Responder -------------------------------------------------------------------------------
    async def respond(self, text: str, context: TurnContext) -> Reply:
        state = context.extras.setdefault("skills", RemoteSkillState())
        state.thinking_prompt = None
        try:
            async with self._client.stream(
                "POST", "/internal/phone/turn", json={"call_id": context.call_id, "text": text}
            ) as response:
                if response.status_code != 200:
                    raise ResponderUnavailable(f"main process answered {response.status_code}")
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    kind = event.get("type")
                    if kind == "thinking":
                        state.thinking_prompt = event.get("prompt")
                    elif kind == "reply":
                        return Reply(
                            text=event.get("text"),
                            prompt=event.get("prompt"),
                            hangup=bool(event.get("hangup")),
                            skill_id=event.get("skill_id"),
                            meta={"timer": event["timer"]} if event.get("timer") else None,
                        )
                    elif kind == "cancelled":
                        raise asyncio.CancelledError
                    elif kind == "error":
                        raise ResponderUnavailable(str(event.get("message") or event.get("kind")))
        except asyncio.CancelledError:
            self._spawn(self._post("/internal/phone/cancel", {"call_id": context.call_id}))
            raise
        except httpx.HTTPError as exc:
            raise ResponderUnavailable(f"main process unreachable ({type(exc).__name__})") from exc
        except ValueError as exc:
            raise ResponderUnavailable("main process sent an unreadable answer") from exc
        raise ResponderUnavailable("main process sent no answer")

    async def greeting_hint(self, context: TurnContext) -> str | None:
        try:
            response = await self._client.post(
                "/internal/phone/greeting_hint", json={"call_id": context.call_id}, timeout=0.4
            )
            text = response.json().get("text")
        except (httpx.HTTPError, ValueError):
            return None
        return str(text) if text else None

    # -- call life cycle (fire and forget: a lost message must never disturb a call) -----------------
    def call_started(self, call_id: str, remote: str = "", codec: str = "") -> None:
        self._spawn(
            self._post(
                "/internal/phone/event",
                {
                    "call_id": call_id,
                    "event": "call_started",
                    "remote": remote[:200],
                    "codec": codec,
                },
            )
        )

    def call_ended(self, call_id: str, reason: str = "") -> None:
        self._spawn(
            self._post(
                "/internal/phone/event",
                {"call_id": call_id, "event": "call_ended", "reason": reason[:100]},
            )
        )

    # -- Anton calls back ("Sag mir am Telefon …" on Discord) ----------------------------------------
    async def next_callback(self) -> dict | None:
        """A call to make, or ``None``. Never raises: the main process may be restarting."""
        try:
            response = await self._client.get("/internal/phone/callback", timeout=3.0)
            call = response.json().get("call") if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
        return call if isinstance(call, dict) else None

    def callback_done(self, callback_id: int, outcome: str) -> None:
        self._spawn(
            self._post(
                "/internal/phone/event",
                {"call_id": f"callback-{callback_id}", "event": "callback_done", "reason": outcome},
            )
        )

    # -- helpers --------------------------------------------------------------------------------------
    def _spawn(self, coroutine) -> None:
        task = asyncio.ensure_future(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _post(self, path: str, body: dict) -> None:
        with contextlib.suppress(httpx.HTTPError):
            await self._client.post(path, json=body, timeout=3.0)

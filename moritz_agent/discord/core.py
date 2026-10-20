# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The Discord worker's client for the internal API of the main process (docs/plan/14 §4.2)."""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

from moritz_agent.core.turn import TurnResult

ENV_URL = "MORITZ_INTERNAL_URL"
ENV_TOKEN = "MORITZ_INTERNAL_TOKEN"

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


class CoreUnavailable(RuntimeError):
    """The main process does not answer (restarting, model down) or refused the request."""

    def __init__(self, message: str, status: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class CoreForbidden(PermissionError):
    """The main process refuses this person (not on the lists, not the owner)."""


class CoreApi:
    def __init__(
        self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-Internal-Token": token},
            transport=transport,
            timeout=httpx.Timeout(30.0, connect=2.0),
        )

    @classmethod
    def from_environment(cls) -> CoreApi | None:
        url, token = os.environ.get(ENV_URL), os.environ.get(ENV_TOKEN)
        return cls(url, token) if url and token else None

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- plumbing ---------------------------------------------------------------------------------
    async def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CoreUnavailable(type(exc).__name__) from exc
        if response.status_code == 403:
            raise CoreForbidden(path)
        if response.status_code >= 400:
            detail: Any = None
            with contextlib.suppress(ValueError):
                detail = response.json().get("detail")
            raise CoreUnavailable(f"{path}: {response.status_code}", response.status_code, detail)
        return response.json()  # type: ignore[no-any-return]

    # -- turns --------------------------------------------------------------------------------------
    async def events(self, **body: Any) -> AsyncIterator[dict[str, Any]]:
        """``thinking`` / ``partial`` / ``result`` / ``error`` events of one question."""
        try:
            async with self._client.stream(
                "POST",
                "/internal/discord/turn",
                json=body,
                timeout=httpx.Timeout(None, connect=2.0),
            ) as response:
                if response.status_code == 403:
                    raise CoreForbidden("turn")
                if response.status_code != 200:
                    raise CoreUnavailable(f"turn: {response.status_code}")
                async for line in response.aiter_lines():
                    if line:
                        yield json.loads(line)
        except httpx.HTTPError as exc:
            raise CoreUnavailable(type(exc).__name__) from exc

    async def turn(self, on_event: EventSink | None = None, **body: Any) -> TurnResult:
        async for event in self.events(**body):
            kind = event.get("type")
            if kind == "result":
                return TurnResult.from_json(event["result"])
            if kind == "error":
                if event.get("kind") == "forbidden":
                    raise CoreForbidden("turn")
                raise CoreUnavailable(str(event.get("message") or event.get("kind")))
            if kind == "cancelled":
                raise CoreUnavailable("cancelled")
            if on_event is not None:
                await on_event(event)
        raise CoreUnavailable("no answer")

    async def cancel(self, conversation_id: str) -> None:
        await self._json(
            "POST", "/internal/discord/cancel", json={"conversation_id": conversation_id}
        )

    async def end(self, conversation_id: str) -> None:
        await self._json("POST", "/internal/discord/end", json={"conversation_id": conversation_id})

    # -- messages the main process wants to send -------------------------------------------------
    async def outbox(self, limit: int = 20) -> list[dict[str, Any]]:
        return (await self._json("GET", "/internal/discord/outbox", params={"limit": limit}))[
            "items"
        ]

    async def ack(self, item_id: int, delivered: bool) -> None:
        await self._json(
            "POST", "/internal/discord/outbox/ack", json={"id": item_id, "delivered": delivered}
        )

    # -- people ---------------------------------------------------------------------------------------------
    async def principal(self, user_id: str) -> dict[str, Any]:
        return await self._json("GET", f"/internal/discord/principal/{user_id}")

    async def set_principal(self, user_id: str, **changes: Any) -> dict[str, Any]:
        return await self._json("PUT", f"/internal/discord/principal/{user_id}", json=changes)

    async def subscribe(
        self, user_id: str, kind: str, *, enabled: bool = True, **params: Any
    ) -> dict[str, Any]:
        body = {"kind": kind, "enabled": enabled, "params": params}
        return await self._json("PUT", f"/internal/discord/subscriptions/{user_id}", json=body)

    async def reminders(self, user_id: str) -> list[dict[str, Any]]:
        return (await self._json("GET", f"/internal/discord/reminders/{user_id}"))["items"]

    async def cancel_reminder(self, user_id: str, reminder_id: int) -> bool:
        data = await self._json("DELETE", f"/internal/discord/reminders/{user_id}/{reminder_id}")
        return bool(data["cancelled"])

    async def feedback(self, skill_id: str, rating: str) -> None:
        await self._json(
            "POST", "/internal/discord/feedback", json={"skill_id": skill_id, "rating": rating}
        )

    # -- status and admin ------------------------------------------------------------------------------------
    async def overview(self) -> dict[str, Any]:
        return await self._json("GET", "/internal/discord/overview")

    async def admin_reload(self, user_id: str) -> dict[str, Any]:
        return await self._json(
            "POST", "/internal/discord/admin/reload", params={"user_id": user_id}
        )

    async def admin_drain(self, user_id: str, drain: bool) -> dict[str, Any]:
        return await self._json(
            "POST",
            "/internal/discord/admin/drain",
            params={"user_id": user_id},
            json={"drain": drain},
        )

    async def admin_restart(self, user_id: str) -> dict[str, Any]:
        return await self._json(
            "POST", "/internal/discord/admin/restart", params={"user_id": user_id}
        )

    async def admin_logs(self, user_id: str, category: str = "", lines: int = 100) -> list[str]:
        data = await self._json(
            "GET",
            "/internal/discord/admin/logs",
            params={"user_id": user_id, "category": category, "lines": lines},
        )
        return list(data["lines"])

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Runs: every answer of the WebUI as a numbered stream of events (ADR-041, docs/plan/15 P2-02).

A run lives in the server, not in the browser. The browser follows it (``follow(after=n)``) and can
come back after a reload or from another device; closing the tab does not stop it, only ``cancel``
does. A web answer is a run with a few events; a sandbox agent later is the same with hundreds.

Events (each with ``seq`` and ``ms`` since the start):

* ``run`` – id and conversation, always first
* ``status`` – Anton is busy (``prompt``: the id of the announcement, e.g. a search)
* ``token`` – more answer text (``text`` is appended); ``text`` – the whole text so far (replace)
* ``tool_call`` / ``tool_result`` – a tool of the language model starts / ends
* ``approval_request`` / ``approval_response`` – a risky tool asks Moritz first (``POST …/approval``)
* ``done`` – the final answer (``result``: the TurnResult as JSON)
* ``cancelled`` / ``error`` – the end without an answer (``error``: a machine-readable reason)
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from moritz_agent.core.chat import AccessDenied, ChatService
from moritz_agent.core.turn import Turn
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import ResponderUnavailable

log = get_logger("agent")

KEEP_S = 600.0  # a finished run can be followed for ten more minutes
APPROVAL_TIMEOUT_S = 90.0  # no answer from Moritz: no (below the chat's deadline of 120 s)
MAX_RUNS = 100
FINAL = frozenset({"done", "cancelled", "error"})


class RunBusy(RuntimeError):
    """The conversation already has a run that is not finished."""


@dataclass
class Run:
    id: str
    conversation_id: str
    started: float = field(default_factory=time.monotonic)
    started_wall: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    finished_at: float | None = None
    task: asyncio.Task[None] | None = None
    # replaced on every event: a follower waits on the one it saw, so no wake-up is lost
    _signal: asyncio.Event = field(default_factory=asyncio.Event)
    approvals: dict[str, asyncio.Future[bool]] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.finished_at is not None

    def add(self, event: dict[str, Any]) -> None:
        if self.finished:
            return
        event = {
            "seq": len(self.events) + 1,
            "ms": round((time.monotonic() - self.started) * 1000),
            **event,
        }
        self.events.append(event)
        if event["type"] in FINAL:
            self.finished_at = time.monotonic()
        signal, self._signal = self._signal, asyncio.Event()
        signal.set()


class RunManager:
    def __init__(
        self,
        chat: ChatService,
        *,
        keep_s: float = KEEP_S,
        on_finish: Callable[[Run], None] | None = None,
    ) -> None:
        self.chat = chat
        self.keep_s = keep_s
        self.on_finish = on_finish  # stores the steps with the answer (P2-04)
        self._runs: dict[str, Run] = {}

    def get(self, run_id: str) -> Run | None:
        self._expire()
        return self._runs.get(run_id)

    def active(self, conversation_id: str) -> Run | None:
        for run in self._runs.values():
            if run.conversation_id == conversation_id and not run.finished:
                return run
        return None

    def start(self, turn: Turn) -> Run:
        self._expire()
        if self.active(turn.conversation_id) is not None:
            raise RunBusy(turn.conversation_id)
        run = Run(id="r-" + secrets.token_hex(8), conversation_id=turn.conversation_id)
        run.add({"type": "run", "run_id": run.id, "conversation_id": turn.conversation_id})
        self._runs[run.id] = run
        run.task = asyncio.ensure_future(self._drive(run, turn))
        return run

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or run.finished:
            return False
        self.chat.cancel(run.conversation_id)  # stops the model, the queue gives the slot back
        if run.task is not None:
            run.task.cancel()
        run.add({"type": "cancelled"})
        return True

    def approve(self, run_id: str, request_id: str, allow: bool) -> bool:
        """Moritz answers a question of the run ("Anton möchte … – Erlauben / Ablehnen")."""
        run = self._runs.get(run_id)
        future = run.approvals.get(request_id) if run is not None else None
        if run is None or future is None or future.done():
            return False
        future.set_result(allow)
        run.add({"type": "approval_response", "id": request_id, "allow": allow, "by": "moritz"})
        return True

    async def _ask(self, run: Run, request: dict[str, Any]) -> bool:
        request_id = "a-" + secrets.token_hex(6)
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        run.approvals[request_id] = future
        run.add({"type": "approval_request", "id": request_id, **request})
        try:
            return await asyncio.wait_for(asyncio.shield(future), APPROVAL_TIMEOUT_S)
        except TimeoutError:
            run.add(
                {"type": "approval_response", "id": request_id, "allow": False, "by": "timeout"}
            )
            return False
        finally:
            run.approvals.pop(request_id, None)

    async def follow(self, run_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Every event after ``after``, then wait for more until the run has finished."""
        run = self._runs.get(run_id)
        if run is None:
            return
        sent = max(0, after)
        while True:
            signal = run._signal
            while sent < len(run.events):
                event = run.events[sent]
                sent += 1
                yield event
            if run.finished:
                return
            await signal.wait()

    # -- inside ----------------------------------------------------------------------------------
    async def _drive(self, run: Run, turn: Turn) -> None:
        text = ""
        try:
            async for event in self.chat.events(
                turn, on_event=run.add, approver=lambda request: self._ask(run, request)
            ):
                kind = event["type"]
                if kind == "thinking":
                    run.add({"type": "status", "prompt": event["prompt"]})
                elif kind == "partial":
                    new = event["text"]
                    if new.startswith(text):
                        run.add({"type": "token", "text": new[len(text) :]})
                    else:
                        run.add({"type": "text", "text": new})
                    text = new
                elif kind == "result":
                    run.add({"type": "done", "result": event["result"].to_json()})
                elif kind == "cancelled":
                    run.add({"type": "cancelled"})
        except asyncio.CancelledError:
            run.add({"type": "cancelled"})
            raise
        except ResponderUnavailable:
            run.add({"type": "error", "error": "model_unavailable"})
        except AccessDenied:
            run.add({"type": "error", "error": "forbidden"})
        except Exception:
            log.exception("Lauf %s abgebrochen", run.id)
            run.add({"type": "error", "error": "internal"})
        finally:
            if not run.finished:  # ended without a word: say so instead of hanging
                run.add({"type": "error", "error": "no_answer"})
            if self.on_finish is not None:
                try:
                    self.on_finish(run)
                except Exception:
                    log.exception("Lauf %s nicht gespeichert", run.id)

    def _expire(self) -> None:
        now = time.monotonic()
        for run_id, run in list(self._runs.items()):
            if run.finished_at is not None and now - run.finished_at > self.keep_s:
                del self._runs[run_id]
        while len(self._runs) > MAX_RUNS:
            oldest = next((k for k, r in self._runs.items() if r.finished), None)
            if oldest is None:
                break
            del self._runs[oldest]

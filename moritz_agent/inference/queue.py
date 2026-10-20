# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""One generation at a time, the phone first (docs/plan/02 §6, PHONE-41).

Priorities: PHONE 0, VOICE 1 (Discord voice channel), INTERACTIVE 2 (Discord text, web), BACKGROUND 3.
A more important request that arrives while a less important one runs stops that one – at once for
BACKGROUND, after ``preempt_wait_s`` for the others – and the stopped job goes back in line.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from moritz_agent.inference.client import (
    Completion,
    InferenceAborted,
    InferenceClient,
    InferenceError,
    new_genkey,
)
from moritz_agent.logging_setup import get_logger

log = get_logger("inference")


class Priority(IntEnum):
    PHONE = 0
    VOICE = 1
    INTERACTIVE = 2
    BACKGROUND = 3


@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    run: Callable[[str], Awaitable[Completion]] = field(compare=False)
    future: asyncio.Future[Completion] = field(compare=False)
    genkey: str = field(default="", compare=False)
    preempted: bool = field(default=False, compare=False)
    requeues: int = field(default=0, compare=False)
    label: str = field(default="", compare=False)


class InferenceQueue:
    def __init__(self, client: InferenceClient, *, preempt_wait_s: float = 3.0) -> None:
        self.client = client
        self.preempt_wait_s = preempt_wait_s
        self._heap: list[_Job] = []
        self._counter = itertools.count()
        self._wake = asyncio.Event()
        self._current: _Job | None = None
        self._worker: asyncio.Task[None] | None = None
        self._preempt: asyncio.Task[None] | None = None
        self.completed = 0
        self.preemptions = 0

    # -- public ----------------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._current is not None or bool(self._heap)

    def depth(self) -> int:
        return len(self._heap) + (1 if self._current else 0)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        priority: Priority = Priority.INTERACTIVE,
        label: str = "",
        **options: Any,
    ) -> Completion:
        async def run(genkey: str) -> Completion:
            return await self.client.chat(messages, genkey=genkey, **options)

        return await self.submit(run, priority=priority, label=label)

    async def submit(
        self, run: Callable[[str], Awaitable[Completion]], *, priority: Priority, label: str = ""
    ) -> Completion:
        loop = asyncio.get_running_loop()
        job = _Job(int(priority), next(self._counter), run, loop.create_future(), label=label)
        heapq.heappush(self._heap, job)
        self._ensure_worker()
        self._wake.set()
        self._maybe_preempt(job)
        try:
            return await job.future
        except asyncio.CancelledError:
            await self._cancel(job)
            raise

    async def aclose(self) -> None:
        for task in (self._preempt, self._worker):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        for job in self._heap:
            if not job.future.done():
                job.future.set_exception(InferenceAborted("queue closed"))
        self._heap.clear()

    # -- internals ---------------------------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._work())

    async def _work(self) -> None:
        while True:
            while not self._heap:
                self._wake.clear()
                await self._wake.wait()
            job = heapq.heappop(self._heap)
            if job.future.done():  # cancelled while waiting
                continue
            job.genkey = new_genkey()
            job.preempted = False
            self._current = job
            try:
                completion = await job.run(job.genkey)
            except InferenceAborted:
                if job.preempted and not job.future.done():
                    job.requeues += 1
                    log.info(
                        "Generierung '%s' wurde unterbrochen und neu eingereiht", job.label or "?"
                    )
                    heapq.heappush(self._heap, job)
                elif not job.future.done():
                    job.future.set_exception(InferenceAborted("generation aborted"))
            except InferenceError as exc:
                if not job.future.done():
                    job.future.set_exception(exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let one bad job stop the queue
                log.exception("Generierung fehlgeschlagen")
                if not job.future.done():
                    job.future.set_exception(exc)
            else:
                self.completed += 1
                if not job.future.done():
                    job.future.set_result(completion)
            finally:
                self._current = None

    def _maybe_preempt(self, new: _Job) -> None:
        current = self._current
        if current is None or new.priority >= current.priority:
            return
        if self._preempt is not None and not self._preempt.done():
            return
        wait = 0.0 if current.priority >= int(Priority.BACKGROUND) else self.preempt_wait_s
        self._preempt = asyncio.ensure_future(self._preempt_after(current, wait))

    async def _preempt_after(self, victim: _Job, wait: float) -> None:
        if wait > 0:
            await asyncio.sleep(wait)
        if self._current is victim and not victim.future.done() and victim.genkey:
            victim.preempted = True
            self.preemptions += 1
            log.info(
                "Generierung '%s' wird für eine wichtigere Anfrage abgebrochen", victim.label or "?"
            )
            await self.client.abort(victim.genkey)

    async def _cancel(self, job: _Job) -> None:
        """The caller gave up (hang-up): drop the job, stop its generation if it is running."""
        if job in self._heap:
            self._heap.remove(job)
            heapq.heapify(self._heap)
        elif self._current is job and job.genkey:
            await self.client.abort(job.genkey)

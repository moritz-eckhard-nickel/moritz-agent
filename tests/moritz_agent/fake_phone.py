# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A stand-in for the phone worker, started by the supervisor tests.

Asks the main process one question through the real ``RemoteResponder`` (token and address from the
environment, like the real worker), writes the answer and a live status file, and records signals.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path

from moritz_agent.phone.remote import from_environment
from moritz_agent.phone.responder import TurnContext

root = Path(sys.argv[1])
run_dir = root / "data" / "run"
run_dir.mkdir(parents=True, exist_ok=True)
log = run_dir / "fake-phone.log"


def note(line: str) -> None:
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


async def main() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, lambda: (note("SIGTERM"), stop.set()))
    loop.add_signal_handler(signal.SIGHUP, lambda: note("SIGHUP"))
    remote = from_environment()
    note("env " + ("ok" if remote else "missing"))
    if remote is not None and "--ask" in sys.argv:
        context = TurnContext(call_id="fake-call")
        remote.call_started("fake-call", "sip:test", "G722")
        reply = await remote.respond("Wie spät ist es?", context)
        note("reply " + json.dumps(reply.text, ensure_ascii=False))
        remote.call_ended("fake-call", "caller_hangup")
        await asyncio.sleep(0.2)
    while not stop.is_set():
        (run_dir / "phone-status.json").write_text(
            json.dumps(
                {
                    "state": "running",
                    "updated": time.time(),
                    "registration": "registered",
                    "in_call": False,
                    "pid": os.getpid(),
                }
            )
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 0.2)
    if remote is not None:
        await remote.aclose()


asyncio.run(main())

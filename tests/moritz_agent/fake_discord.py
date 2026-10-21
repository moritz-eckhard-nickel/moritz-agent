# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A stand-in for the Discord worker, started by the supervisor tests.

Asks the main process for its overview through the real ``CoreApi`` (token and address from the
environment, like the real worker), writes a live status file and records signals.
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

from moritz_agent.discord.core import CoreApi

root = Path(sys.argv[1])
run_dir = root / "data" / "run"
run_dir.mkdir(parents=True, exist_ok=True)
log = run_dir / "fake-discord.log"


def note(line: str) -> None:
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


async def main() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, lambda: (note("SIGTERM"), stop.set()))
    loop.add_signal_handler(signal.SIGHUP, lambda: note("SIGHUP"))
    core = CoreApi.from_environment()
    note("env " + ("ok" if core else "missing") + f" nice={os.nice(0)}")
    if core is not None:
        overview = await core.overview()
        note("overview " + json.dumps(sorted(overview)))
    while not stop.is_set():
        (run_dir / "discord-status.json").write_text(
            json.dumps(
                {
                    "state": "ready",
                    "updated": time.time(),
                    "pid": os.getpid(),
                    "guilds": 1,
                    "default_channel": "ok",
                }
            )
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), 0.2)
    if core is not None:
        await core.aclose()


asyncio.run(main())

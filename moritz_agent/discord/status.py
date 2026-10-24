# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""``data/run/discord-status.json``: what the worker tells the others (docs/plan/14 §4.2).

Written about once a second, atomically. Never contains the token, message contents or user names.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from moritz_agent.phone.control import run_dir

STATUS_FILE = "discord-status.json"
# written into runtime/discord-venv when the worker keeps losing the gateway with the DAVE fork: the
# supervisor then starts it with the pinned discord.py again (P1-32); setup-discord-voice.sh clears it
UNSTABLE_MARK = ".moritz-unstable"
STALE_AFTER_S = 15.0


def status_path(root: Path) -> Path:
    return run_dir(root) / STATUS_FILE


def write_status(root: Path, payload: dict[str, Any]) -> None:
    path = status_path(root)
    tmp = path.with_suffix(".tmp")
    data = {"pid": os.getpid(), "updated": time.time(), **payload}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def read_status(root: Path) -> dict[str, Any] | None:
    """The status of a live worker, or ``None`` (missing, stale or stopped)."""
    try:
        data = json.loads(status_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        data.get("state") == "stopped"
        or time.time() - float(data.get("updated", 0)) > STALE_AFTER_S
    ):
        return None
    return data  # type: ignore[no-any-return]

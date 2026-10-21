# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""File-based control channel between the running phone service and the update script.

The updater (moritz-update.sh, UPD-01) must not interrupt a call. Until the web API exists, the two
processes talk through two small files in ``data/run/``:

* ``phone-status.json`` – written by the phone about once a second (atomically): registration,
  whether a call is active, version, process id. A status that is older than a few seconds means
  "the service is not running".
* ``drain`` – created by the updater: the phone then answers new calls with "busy" (SIP 486), so
  the active call can finish and the update can start (drain, then timeout → postpone).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

STATUS_FILE = "phone-status.json"
DRAIN_FILE = "drain"
STALE_AFTER_S = 10.0  # a status file older than this does not describe a live service


def run_dir(root: Path) -> Path:
    return root / "data" / "run"


class PhoneControl:
    def __init__(self, root: Path, version: str) -> None:
        self.directory = run_dir(root)
        self.version = version
        self._announced_drain = False

    @property
    def status_path(self) -> Path:
        return self.directory / STATUS_FILE

    @property
    def drain_path(self) -> Path:
        return self.directory / DRAIN_FILE

    def draining(self) -> bool:
        return self.drain_path.exists()

    def write_status(self, sip_status: dict, *, state: str = "running") -> None:
        """Atomically replace the status file (readable by the updater, which runs as root)."""
        payload = {
            "state": state,
            "pid": os.getpid(),
            "version": self.version,
            "updated": time.time(),
            "draining": self.draining(),
            "registration": sip_status.get("registration"),
            "in_call": bool(sip_status.get("in_call")),
            "calls_total": sip_status.get("calls_total", 0),
        }
        if sip_status.get("skills"):
            payload["skills"] = sip_status["skills"]  # home place and data services (13 §13)
        tmp = self.status_path.with_suffix(".tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self.status_path)
        except OSError:
            # a read-only data directory must never take the phone down
            with contextlib.suppress(OSError):
                tmp.unlink()

    def write_stopped(self) -> None:
        self.write_status({}, state="stopped")


def read_status(root: Path) -> dict | None:
    """Status of the running phone, or None if there is no live service (missing/stale/stopped)."""
    path = run_dir(root) / STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        data.get("state") != "running"
        or time.time() - float(data.get("updated", 0)) > STALE_AFTER_S
    ):
        return None
    return data

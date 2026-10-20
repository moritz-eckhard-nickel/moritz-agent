# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""RAM + file cache for data services with fresh and stale lifetimes (docs/plan/13 §3.6).

Entries are JSON, written atomically (temp file + rename, UPD-06) and never contain anything
personal. ``data/cache/`` may be deleted at any time.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moritz_agent.logging_setup import get_logger
from moritz_agent.skills.clock import Clock

log = get_logger("skill")


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    stored_at: float  # unix time
    age_s: float
    fresh: bool


class Cache:
    def __init__(self, directory: Path | None, clock: Clock) -> None:
        self.directory = directory
        self.clock = clock
        self._ram: dict[tuple[str, str], tuple[float, Any]] = {}

    def _now(self) -> float:
        return self.clock.now("UTC").timestamp()

    def _path(self, namespace: str, key: str) -> Path | None:
        if self.directory is None:
            return None
        digest = hashlib.sha256(key.encode()).hexdigest()[:20]
        return self.directory / namespace / f"{digest}.json"

    def get(self, namespace: str, key: str, *, fresh_s: float, stale_s: float) -> CacheEntry | None:
        """The entry if it is younger than ``stale_s``; ``fresh`` tells whether < ``fresh_s``."""
        record = self._ram.get((namespace, key))
        if record is None:
            record = self._read(namespace, key)
            if record is not None:
                self._ram[(namespace, key)] = record
        if record is None:
            return None
        stored_at, value = record
        age = max(0.0, self._now() - stored_at)
        if age > max(stale_s, fresh_s):
            return None
        return CacheEntry(value, stored_at, age, age <= fresh_s)

    def put(self, namespace: str, key: str, value: Any) -> None:
        stored_at = self._now()
        self._ram[(namespace, key)] = (stored_at, value)
        path = self._path(namespace, key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"stored_at": stored_at, "value": value}, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError):
            log.debug("Cache konnte nicht geschrieben werden (%s)", namespace)

    def _read(self, namespace: str, key: str) -> tuple[float, Any] | None:
        path = self._path(namespace, key)
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return float(payload["stored_at"]), payload["value"]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def clear(self) -> None:
        self._ram.clear()

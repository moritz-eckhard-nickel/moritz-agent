# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The clock behind every time answer – swappable so tests can fix the time (docs/plan/13 §14)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self, timezone: str) -> datetime:
        """Current aware datetime in ``timezone``."""
        ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now(self, timezone: str) -> datetime:
        return datetime.now(ZoneInfo(timezone))

    def monotonic(self) -> float:
        import time

        return time.monotonic()


class FixedClock:
    """A clock that stands still (or moves when told to) – for tests and ``ask --at``."""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("Europe/Berlin"))
        self._moment = moment
        self._mono = 0.0

    def now(self, timezone: str) -> datetime:
        return self._moment.astimezone(ZoneInfo(timezone))

    def monotonic(self) -> float:
        return self._mono

    def advance(self, **kwargs: float) -> None:
        delta = timedelta(**kwargs)
        self._moment += delta
        self._mono += delta.total_seconds()

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""School holidays of Hessen from the maintained table (docs/plan/13 §8.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from moritz_agent.skills.data import load_toml

NAMES = {
    "ostern": "Osterferien", "sommer": "Sommerferien", "herbst": "Herbstferien",
    "weihnachten": "Weihnachtsferien",
}  # fmt: skip
ALIASES = {
    "osterferien": "ostern", "ostern": "ostern", "sommerferien": "sommer", "sommer": "sommer",
    "herbstferien": "herbst", "herbst": "herbst", "weihnachtsferien": "weihnachten",
    "weihnachten": "weihnachten", "winterferien": "weihnachten",
}  # fmt: skip


@dataclass(frozen=True)
class Vacation:
    kind: str
    first: date
    last: date

    @property
    def name(self) -> str:
        return NAMES[self.kind]

    def contains(self, day: date) -> bool:
        return self.first <= day <= self.last

    @property
    def school_resumes(self) -> date:
        """First school day after the holidays (next Monday–Friday)."""
        day = self.last + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        return day


@lru_cache(maxsize=1)
def all_vacations() -> tuple[Vacation, ...]:
    entries = load_toml("kalender/schulferien-he.toml")["ferien"]
    return tuple(
        sorted((Vacation(e["art"], e["von"], e["bis"]) for e in entries), key=lambda v: v.first)
    )


def current(day: date) -> Vacation | None:
    return next((v for v in all_vacations() if v.contains(day)), None)


def upcoming(day: date, kind: str | None = None) -> Vacation | None:
    return next(
        (v for v in all_vacations() if v.first > day and (kind is None or v.kind == kind)), None
    )


def last_covered_day() -> date:
    return max(v.last for v in all_vacations())


def table_is_stale(today: date, months: int = 12) -> bool:
    """True if the table reaches less than ``months`` into the future (self-test warning)."""
    return last_covered_day() < today + timedelta(days=30 * months)

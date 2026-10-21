# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Small helpers shared by the catalog modules."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.calendar.special import SPECIAL_DAYS, find_special, next_occurrence
from moritz_agent.skills.slots.when import When, find_dates, find_when

BriefingPart = Callable[[Request], Awaitable[str | None]]
_BRIEFING_PARTS: list[tuple[int, BriefingPart]] = []


def briefing_part(order: int) -> Callable[[BriefingPart], BriefingPart]:
    """Register a building block of the morning overview ("Guten Morgen") – lowest order first."""

    def register(func: BriefingPart) -> BriefingPart:
        _BRIEFING_PARTS.append((order, func))
        _BRIEFING_PARTS.sort(key=lambda item: item[0])
        return func

    return register


def briefing_parts() -> list[BriefingPart]:
    return [func for _, func in _BRIEFING_PARTS]


def say(text: str, **kwargs) -> SkillResult:
    return SkillResult(text=text, **kwargs)


def when_of(req: Request) -> When | None:
    return find_when(req.text, req.now)


def target_date(req: Request) -> date | None:
    """The single day the user names (word, date, weekday, special day) or None."""
    when = when_of(req)
    if when is not None and when.day is not None and when.granularity in {"day", "daypart", "hour"}:
        return when.day
    dates = find_dates(req.text, req.now)
    return dates[0] if dates else None


def dative_until(key: str) -> str:
    """ "bis" target in the dative: Heiligabend → "Heiligabend", erster Advent → "zum ersten Advent"."""
    name = SPECIAL_DAYS[key][0]
    if not name.startswith("der "):
        return name
    rest = name[4:]
    first, _, tail = rest.partition(" ")
    ordinals = {"erste": "ersten", "zweite": "zweiten", "dritte": "dritten", "vierte": "vierten"}
    if first in ordinals:
        return f"zum {ordinals[first]} {tail}"
    return f"zum {rest}"


def special_target(text: str, today: date) -> tuple[str, date] | None:
    found = find_special(text)
    if not found:
        return None
    key, _ = found
    return key, next_occurrence(key, today)


def days_between(first: date, last: date) -> int:
    return (last - first).days


def start_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def next_weekday(today: date, weekday: int, *, include_today: bool = True) -> date:
    offset = (weekday - today.weekday()) % 7
    if offset == 0 and not include_today:
        offset = 7
    return today + timedelta(days=offset)


WORD = r"[a-zäöüß]"


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None

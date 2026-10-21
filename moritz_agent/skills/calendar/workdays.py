# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Work days, bridge days and long weekends (docs/plan/13 §8.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from moritz_agent.skills.calendar.holidays import Holiday, holiday_on, holidays


def is_workday(day: date, state: str, workdays: tuple[int, ...] = (1, 2, 3, 4, 5)) -> bool:
    return (day.weekday() + 1) in workdays and holiday_on(day, state) is None


def count_workdays(
    first: date, last: date, state: str, workdays: tuple[int, ...] = (1, 2, 3, 4, 5)
) -> int:
    """Work days from ``first`` to ``last`` inclusive."""
    day, total = first, 0
    while day <= last:
        total += is_workday(day, state, workdays)
        day += timedelta(days=1)
    return total


@dataclass(frozen=True)
class LongWeekend:
    holiday: Holiday
    bridge: date | None  # a single day off that joins the holiday to the weekend
    first: date
    last: date

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


def _free_span(day: date, state: str, workdays: tuple[int, ...]) -> tuple[date, date]:
    """The run of consecutive days off (weekend days and holidays) around ``day``."""
    first = last = day
    while not is_workday(first - timedelta(days=1), state, workdays):
        first -= timedelta(days=1)
    while not is_workday(last + timedelta(days=1), state, workdays):
        last += timedelta(days=1)
    return first, last


def long_weekends(
    start: date,
    state: str,
    year_span: int = 2,
    workdays: tuple[int, ...] = (1, 2, 3, 4, 5),
) -> list[LongWeekend]:
    """Holidays that give 3+ days off in a row – as they fall, or with one bridge day.

    The free span grows over every weekend day and holiday next to it (Easter: Friday to Monday;
    Christmas 2028: Saturday 23 to Tuesday 26 December). A bridge day is a single work day between
    the holiday's span and another day off; a holiday itself is never one.
    """
    found: dict[tuple[date, date], LongWeekend] = {}
    for year in range(start.year, start.year + year_span):
        for holiday in holidays(year, state):
            if holiday.day < start or holiday.sunday:
                continue
            if (holiday.day.weekday() + 1) not in workdays:
                continue  # on a weekend day it frees nothing (a neighbour holiday counts itself)
            first, last = _free_span(holiday.day, state, workdays)
            if (last - first).days + 1 >= 3:
                found.setdefault((first, last), LongWeekend(holiday, None, first, last))
                continue
            best: LongWeekend | None = None
            one = timedelta(days=1)
            for bridge, beyond in ((first - one, first - 2 * one), (last + one, last + 2 * one)):
                if is_workday(beyond, state, workdays):
                    continue  # the bridge would not join another day off
                a, b = _free_span(beyond, state, workdays)
                lw = LongWeekend(holiday, bridge, min(a, first), max(b, last))
                if lw.days >= 4 and (best is None or lw.days > best.days):
                    best = lw
            if best is not None:
                found.setdefault((best.first, best.last), best)
    return sorted(found.values(), key=lambda lw: lw.first)

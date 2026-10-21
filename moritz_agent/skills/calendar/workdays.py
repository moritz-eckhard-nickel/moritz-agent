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


def long_weekends(start: date, state: str, year_span: int = 2) -> list[LongWeekend]:
    """Holidays near a weekend that give 3+ days off – with or without a bridge day."""
    found: list[LongWeekend] = []
    for year in range(start.year, start.year + year_span):
        for holiday in holidays(year, state):
            if holiday.day < start or holiday.sunday:
                continue
            weekday = holiday.day.weekday()
            if weekday == 4:  # Friday: Fri–Sun
                found.append(
                    LongWeekend(holiday, None, holiday.day, holiday.day + timedelta(days=2))
                )
            elif weekday == 0:  # Monday: Sat–Mon
                found.append(
                    LongWeekend(holiday, None, holiday.day - timedelta(days=2), holiday.day)
                )
            elif weekday == 1:  # Tuesday: bridge Monday → Sat–Tue
                found.append(
                    LongWeekend(
                        holiday,
                        holiday.day - timedelta(days=1),
                        holiday.day - timedelta(days=3),
                        holiday.day,
                    )
                )
            elif weekday == 3:  # Thursday: bridge Friday → Thu–Sun
                found.append(
                    LongWeekend(
                        holiday,
                        holiday.day + timedelta(days=1),
                        holiday.day,
                        holiday.day + timedelta(days=3),
                    )
                )
    return sorted(found, key=lambda lw: lw.first)

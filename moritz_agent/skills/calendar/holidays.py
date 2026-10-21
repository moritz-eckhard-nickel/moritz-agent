# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Public holidays of all German states, computed per year (Easter by the Gaussian formula)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

from moritz_agent.skills.data import load_toml

STATE_ALIASES = {
    "baden-württemberg": "BW", "baden württemberg": "BW", "bayern": "BY", "berlin": "BE",
    "brandenburg": "BB", "bremen": "HB", "hamburg": "HH", "hessen": "HE",
    "mecklenburg-vorpommern": "MV", "mecklenburg vorpommern": "MV", "niedersachsen": "NI",
    "nrw": "NW", "nordrhein-westfalen": "NW", "nordrhein westfalen": "NW",
    "rheinland-pfalz": "RP", "rheinland pfalz": "RP", "saarland": "SL", "sachsen": "SN",
    "sachsen-anhalt": "ST", "sachsen anhalt": "ST", "schleswig-holstein": "SH",
    "schleswig holstein": "SH", "thüringen": "TH",
}  # fmt: skip


@dataclass(frozen=True)
class Holiday:
    id: str
    name: str
    day: date
    states: tuple[str, ...]  # empty = whole country
    sunday: bool = False
    note: str = ""

    def applies(self, state: str) -> bool:
        return not self.states or state in self.states


def easter(year: int) -> date:
    """Easter Sunday of ``year`` (Gregorian calendar, anonymous Gaussian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def state_names() -> dict[str, str]:
    return dict(load_toml("kalender/feiertage-de.toml")["states"])


def state_code(text: str) -> str | None:
    """ "hessen" / "NRW" / "HE" → "HE" …, or None."""
    text = text.strip().lower()
    if text.upper() in state_names():
        return text.upper()
    return STATE_ALIASES.get(text)


def _resolve(rule: str, year: int) -> date:
    kind, _, arg = rule.partition(":")
    if kind == "fixed":
        month, day = arg.split("-")
        return date(year, int(month), int(day))
    if kind == "easter":
        return easter(year) + timedelta(days=int(arg))
    if kind == "buss":
        base = date(year, 11, 22)  # the Wednesday strictly before 23 November
        return base - timedelta(days=(base.weekday() - 2) % 7)
    raise ValueError(f"unknown holiday rule {rule!r}")


@lru_cache(maxsize=64)
def holidays_in_year(year: int) -> tuple[Holiday, ...]:
    """Every holiday of ``year`` for every state (filter with :meth:`Holiday.applies`)."""
    entries = load_toml("kalender/feiertage-de.toml")["holiday"]
    result = []
    for entry in entries:
        states = entry["states"]
        result.append(
            Holiday(
                id=entry["id"],
                name=entry["name"],
                day=_resolve(entry["rule"], year),
                states=() if states == "all" else tuple(states),
                sunday=bool(entry.get("sunday", False)),
                note=entry.get("note", ""),
            )
        )
    return tuple(sorted(result, key=lambda h: h.day))


def holidays(year: int, state: str) -> list[Holiday]:
    return [h for h in holidays_in_year(year) if h.applies(state)]


def holiday_on(day: date, state: str) -> Holiday | None:
    for holiday in holidays_in_year(day.year):
        if holiday.day == day and holiday.applies(state):
            return holiday
    return None


def holiday_states_on(day: date) -> list[str]:
    """States in which ``day`` is a public holiday."""
    codes = set(state_names())
    found: set[str] = set()
    for holiday in holidays_in_year(day.year):
        if holiday.day == day:
            found |= codes if not holiday.states else set(holiday.states)
    return sorted(found)


def next_holiday(start: date, state: str, *, include_start: bool = True) -> Holiday | None:
    """First holiday on or after ``start`` (looking up to two years ahead)."""
    for year in (start.year, start.year + 1, start.year + 2):
        for holiday in holidays(year, state):
            if holiday.day > start or (include_start and holiday.day == start):
                return holiday
    return None

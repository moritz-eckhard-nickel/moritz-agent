# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Special days that are not public holidays: Advent, carnival, Mother's Day, daylight saving …"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta

from moritz_agent.skills.calendar.holidays import easter


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) ``weekday`` (0 = Monday) of the month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def advent(year: int, number: int) -> date:
    """1st … 4th Advent (the 4th is the last Sunday before 25 December)."""
    fourth = date(year, 12, 24) - timedelta(days=(date(year, 12, 24).weekday() + 1) % 7)
    return fourth - timedelta(days=7 * (4 - number))


def dst_change(year: int, spring: bool) -> date:
    """Last Sunday of March (clocks forward) or October (clocks back)."""
    return last_weekday(year, 3 if spring else 10, 6)


def _fixed(month: int, day: int) -> Callable[[int], date]:
    return lambda year: date(year, month, day)


def _easter(offset: int) -> Callable[[int], date]:
    return lambda year: easter(year) + timedelta(days=offset)


def _buss(year: int) -> date:
    base = date(year, 11, 22)
    return base - timedelta(days=(base.weekday() - 2) % 7)


# key → (spoken name, resolver(year) -> date)
SPECIAL_DAYS: dict[str, tuple[str, Callable[[int], date]]] = {
    "neujahr": ("Neujahr", _fixed(1, 1)),
    "dreikoenige": ("Heilige Drei Könige", _fixed(1, 6)),
    "valentinstag": ("Valentinstag", _fixed(2, 14)),
    "weiberfastnacht": ("Weiberfastnacht", _easter(-52)),
    "rosenmontag": ("Rosenmontag", _easter(-48)),
    "fastnacht": ("Fastnachtsdienstag", _easter(-47)),
    "aschermittwoch": ("Aschermittwoch", _easter(-46)),
    "palmsonntag": ("Palmsonntag", _easter(-7)),
    "gruendonnerstag": ("Gründonnerstag", _easter(-3)),
    "karfreitag": ("Karfreitag", _easter(-2)),
    "karsamstag": ("Karsamstag", _easter(-1)),
    "ostern": ("Ostern", _easter(0)),
    "ostermontag": ("Ostermontag", _easter(1)),
    "tag_der_arbeit": ("der Tag der Arbeit", _fixed(5, 1)),
    "muttertag": ("Muttertag", lambda y: nth_weekday(y, 5, 6, 2)),
    "himmelfahrt": ("Christi Himmelfahrt", _easter(39)),
    "pfingsten": ("Pfingsten", _easter(49)),
    "pfingstmontag": ("Pfingstmontag", _easter(50)),
    "fronleichnam": ("Fronleichnam", _easter(60)),
    "mariae_himmelfahrt": ("Mariä Himmelfahrt", _fixed(8, 15)),
    "einheit": ("der Tag der Deutschen Einheit", _fixed(10, 3)),
    "erntedank": ("Erntedank", lambda y: nth_weekday(y, 10, 6, 1)),
    "halloween": ("Halloween", _fixed(10, 31)),
    "reformationstag": ("der Reformationstag", _fixed(10, 31)),
    "allerheiligen": ("Allerheiligen", _fixed(11, 1)),
    "martinstag": ("Martinstag", _fixed(11, 11)),
    "volkstrauertag": ("Volkstrauertag", lambda y: advent(y, 1) - timedelta(days=14)),
    "buss_und_bettag": ("Buß- und Bettag", _buss),
    "totensonntag": ("Totensonntag", lambda y: advent(y, 1) - timedelta(days=7)),
    "advent1": ("der erste Advent", lambda y: advent(y, 1)),
    "advent2": ("der zweite Advent", lambda y: advent(y, 2)),
    "advent3": ("der dritte Advent", lambda y: advent(y, 3)),
    "advent4": ("der vierte Advent", lambda y: advent(y, 4)),
    "nikolaus": ("Nikolaus", _fixed(12, 6)),
    "heiligabend": ("Heiligabend", _fixed(12, 24)),
    "weihnachten": ("Heiligabend", _fixed(12, 24)),
    "weihnachtstag1": ("der erste Weihnachtstag", _fixed(12, 25)),
    "weihnachtstag2": ("der zweite Weihnachtstag", _fixed(12, 26)),
    "silvester": ("Silvester", _fixed(12, 31)),
    "sommerzeit": ("der Beginn der Sommerzeit", lambda y: dst_change(y, True)),
    "winterzeit": ("der Beginn der Winterzeit", lambda y: dst_change(y, False)),
}

# phrases (prepared text) → key; longest phrases first
_ALIASES: list[tuple[str, str]] = sorted(
    [
        ("neujahr", "neujahr"),
        ("neujahrstag", "neujahr"),
        ("silvester", "silvester"),
        ("sylvester", "silvester"),
        ("jahreswechsel", "silvester"),
        ("heilige drei könige", "dreikoenige"),
        ("heilige 3 könige", "dreikoenige"),  # after number words became digits
        ("dreikönigstag", "dreikoenige"),
        ("valentinstag", "valentinstag"),
        ("weiberfastnacht", "weiberfastnacht"),
        ("altweiberfastnacht", "weiberfastnacht"),
        ("rosenmontag", "rosenmontag"),
        ("fastnachtsdienstag", "fastnacht"),
        ("faschingsdienstag", "fastnacht"),
        ("fastnacht", "fastnacht"),
        ("fasching", "fastnacht"),
        ("karneval", "fastnacht"),
        ("aschermittwoch", "aschermittwoch"),
        ("palmsonntag", "palmsonntag"),
        ("gründonnerstag", "gruendonnerstag"),
        ("karfreitag", "karfreitag"),
        ("karsamstag", "karsamstag"),
        ("ostersonntag", "ostern"),
        ("ostern", "ostern"),
        ("ostermontag", "ostermontag"),
        ("tag der arbeit", "tag_der_arbeit"),
        ("1. mai", "tag_der_arbeit"),
        ("erster mai", "tag_der_arbeit"),
        ("muttertag", "muttertag"),
        ("christi himmelfahrt", "himmelfahrt"),
        ("mariä himmelfahrt", "mariae_himmelfahrt"),
        ("mariae himmelfahrt", "mariae_himmelfahrt"),
        ("maria himmelfahrt", "mariae_himmelfahrt"),
        ("marie himmelfahrt", "mariae_himmelfahrt"),
        ("mariä aufnahme in den himmel", "mariae_himmelfahrt"),
        ("himmelfahrt", "himmelfahrt"),
        ("vatertag", "himmelfahrt"),
        ("herrentag", "himmelfahrt"),
        ("pfingstsonntag", "pfingsten"),
        ("pfingsten", "pfingsten"),
        ("pfingstmontag", "pfingstmontag"),
        ("fronleichnam", "fronleichnam"),
        ("tag der deutschen einheit", "einheit"),
        ("deutschen einheit", "einheit"),
        ("nationalfeiertag", "einheit"),
        ("erntedank", "erntedank"),
        ("erntedankfest", "erntedank"),
        ("halloween", "halloween"),
        ("reformationstag", "reformationstag"),
        ("allerheiligen", "allerheiligen"),
        ("martinstag", "martinstag"),
        ("sankt martin", "martinstag"),
        ("volkstrauertag", "volkstrauertag"),
        ("buß und bettag", "buss_und_bettag"),
        ("buß- und bettag", "buss_und_bettag"),
        ("buß - und bettag", "buss_und_bettag"),  # after punctuation cleaning
        ("bußtag", "buss_und_bettag"),
        ("totensonntag", "totensonntag"),
        ("ewigkeitssonntag", "totensonntag"),
        ("nikolaus", "nikolaus"),
        ("nikolaustag", "nikolaus"),
        ("heiligabend", "heiligabend"),
        ("heilig abend", "heiligabend"),
        ("weihnachten", "weihnachten"),
        ("weihnachtsfest", "weihnachten"),
        ("weihnachtsabend", "heiligabend"),
        ("1. weihnachtstag", "weihnachtstag1"),
        ("ersten weihnachtstag", "weihnachtstag1"),
        ("erster weihnachtstag", "weihnachtstag1"),
        ("2. weihnachtstag", "weihnachtstag2"),
        ("zweiten weihnachtstag", "weihnachtstag2"),
        ("zweiter weihnachtstag", "weihnachtstag2"),
    ],
    key=lambda pair: -len(pair[0]),
)
_ADVENT = re.compile(r"\b(?:([1-4])\.?|(erst|zweit|dritt|viert)\w*) advent\b")
_ADVENT_WORDS = {"erst": 1, "zweit": 2, "dritt": 3, "viert": 4}


def find_special(text: str) -> tuple[str, re.Match[str] | tuple[int, int]] | None:
    """Special day named in ``text`` → (key, span)."""
    match = _ADVENT.search(text)
    if match:
        number = int(match.group(1)) if match.group(1) else _ADVENT_WORDS[match.group(2)]
        return f"advent{number}", match
    for phrase, key in _ALIASES:
        found = re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", text)
        if found:
            return key, found
    return None


def special_date(key: str, year: int) -> date:
    return SPECIAL_DAYS[key][1](year)


def special_name(key: str) -> str:
    return SPECIAL_DAYS[key][0]


def next_occurrence(key: str, today: date) -> date:
    """Next date on or after ``today`` on which the special day falls."""
    for year in (today.year, today.year + 1):
        day = special_date(key, year)
        if day >= today:
            return day
    return special_date(key, today.year + 2)

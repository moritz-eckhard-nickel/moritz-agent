# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Spoken German for weather values (docs/plan/13 §7.4): degrees, rain, wind, sections, times."""

from __future__ import annotations

import math
from datetime import date, datetime

from moritz_agent.skills.geo.distance import wind_from_de
from moritz_agent.skills.render import german as g
from moritz_agent.skills.weather.analysis import BLOCKS, Section
from moritz_agent.tools.time_tool import WEEKDAYS_DE


def round_half_up(value: float) -> int:
    return math.floor(abs(value) + 0.5) * (1 if value >= 0 else -1)


# -- temperature ---------------------------------------------------------------------------
def deg_n(value: float) -> str:
    """ "11", "minus 2" – never "minus 0"."""
    n = round_half_up(value)
    return f"minus {abs(n)}" if n < 0 else str(n)


def deg(value: float) -> str:
    """ "11 Grad", "minus 2 Grad", "0 Grad"."""
    return f"{deg_n(value)} Grad"


def temp_range(low: float, high: float) -> str:
    """ "8 bis 14 Grad", "um 11 Grad", "minus 2 bis 5 Grad" (goes after "bei")."""
    a, b = round_half_up(low), round_half_up(high)
    if a == b:
        return f"um {deg(a)}"
    if a < 0 or b < 0:
        return f"{deg_n(a)} bis {deg(b)}"
    return f"{a} bis {b} Grad"


def temp_word(value: float) -> str:
    n = round_half_up(value)
    if n >= 30:
        return "heiß"
    if n >= 25:
        return "sommerlich warm"
    if n >= 15:
        return "mild"
    if n >= 5:
        return "kühl"
    if n >= 0:
        return "kalt"
    return "frostig"


def feels_like_note(temperature: float | None, apparent: float | None) -> str:
    """ "gefühlt 7 Grad" when it differs by 3 K or more."""
    if temperature is None or apparent is None:
        return ""
    if abs(apparent - temperature) >= 3 and round_half_up(apparent) != round_half_up(temperature):
        return f"gefühlt {deg(apparent)}"
    return ""


# -- rain ----------------------------------------------------------------------------------
def round_prob(value: float) -> int:
    return round(value / 10.0) * 10


def prob_phrase(prob: float | None) -> str:
    if prob is None:
        return ""
    if prob < 10:
        return "trocken"
    if prob < 30:
        return "kaum Regen"
    if prob < 60:
        return "Schauer möglich"
    if prob < 80:
        return "wahrscheinlich Regen"
    return "Regen"


def amount_phrase(mm: float) -> str:
    """ "ein paar Tropfen", "etwa 3 Liter pro Quadratmeter"."""
    if mm < 0.2:
        return "ein paar Tropfen"
    if mm < 1:
        return "etwas Regen, unter einem Liter pro Quadratmeter"
    return f"etwa {g.number(round(mm, 1) if mm < 10 else round(mm), 1)} Liter pro Quadratmeter"


def liters(mm: float) -> str:
    value = round(mm, 1) if mm < 10 else round(mm)
    return f"{g.number(value, 1)} Liter pro Quadratmeter"


# -- wind ----------------------------------------------------------------------------------
def beaufort_word(kmh: float) -> str:
    for limit, word in (
        (5, "windstill"),
        (19, "schwacher Wind"),
        (28, "mäßiger Wind"),
        (38, "frischer Wind"),
        (49, "starker Wind"),
        (61, "steifer Wind"),
        (74, "stürmischer Wind"),
        (88, "Sturm"),
        (102, "schwerer Sturm"),
        (117, "orkanartiger Sturm"),
    ):
        if kmh <= limit:
            return word
    return "Orkan"


def round5(value: float) -> int:
    return round(value / 5.0) * 5


def wind_phrase(speed: float | None, direction: float | None, gusts: float | None) -> str:
    """ "mäßiger Wind aus Südwest, Böen bis 50 Kilometer pro Stunde"."""
    if speed is None:
        return ""
    word = beaufort_word(speed)
    if word == "windstill":
        return word
    text = word
    if direction is not None:
        text += f" aus {wind_from_de(direction)}"
    if gusts is not None and (gusts >= 40 or gusts - speed >= 20):
        text += f", Böen bis {round5(gusts)} Kilometer pro Stunde"
    return text


# -- times ---------------------------------------------------------------------------------
def at_hour(moment: datetime) -> str:
    """ "gegen 15 Uhr" – hours only."""
    hour = (moment.hour + (1 if moment.minute >= 40 else 0)) % 24
    return "gegen Mitternacht" if hour == 0 else f"gegen {hour} Uhr"


def at_quarter(moment: datetime) -> str:
    """ "ab etwa 17 Uhr 15" – 15-minute grid."""
    minutes = round((moment.hour * 60 + moment.minute) / 15.0) * 15
    hour, minute = divmod(minutes % (24 * 60), 60)
    if hour == 0 and minute == 0:
        return "Mitternacht"
    return g.clock_digital(hour=hour, minute=minute)


def weekday(day: date) -> str:
    return WEEKDAYS_DE[day.weekday()]


# -- sections ------------------------------------------------------------------------------
_KIND_TEXT = {
    "schauer": "Schauer",
    "regen": "Regen",
    "schnee": "Schnee",
    "gewitter": "Gewitter",
    "glatt": "Glätte durch gefrierenden Regen",
    "nebel": "Nebel",
}
_UNTIL = ("bis zum Vormittag", "bis zum Nachmittag", "bis zum Abend")
_FROM = ("", "ab dem Nachmittag", "ab dem Abend")


def kind_text(kind: str, sky_word: str = "") -> str:
    if kind == "trocken":
        return sky_word or "trocken"
    return _KIND_TEXT[kind]


def sections_text(sections: list[Section], *, mention_dry: bool = True) -> str:
    """ "vormittags trocken, ab dem Nachmittag Schauer" / "den ganzen Tag trocken"."""
    if not sections:
        return ""
    if len(sections) == 1:
        only = sections[0]
        word = kind_text(
            only.kind, "trocken" if only.kind == "trocken" and mention_dry else only.sky
        )
        if only.first == 0 and only.last == len(BLOCKS) - 1:
            return f"den ganzen Tag {word}"
        if only.last == len(BLOCKS) - 1:
            return f"{word}"
        names = BLOCKS[only.first][0]
        return f"{names} {word}" if only.first == only.last else f"bis zum Abend {word}"
    if len(sections) == 2:
        first, second = sections
        dry_first = kind_text(first.kind, "trocken" if first.kind == "trocken" else "")
        dry_second = kind_text(second.kind, "trocken" if second.kind == "trocken" else "")
        head = (
            f"{_UNTIL[first.last]} {dry_first}"
            if first.first == 0
            else f"{BLOCKS[first.first][0]} {dry_first}"
        )
        if first.first == 0 and first.last == 0:
            head = f"vormittags {dry_first}"
        tail = f"{_FROM[second.first]} {dry_second}".strip()
        return f"{head}, {tail}"
    parts = []
    for section in sections:
        name = BLOCKS[section.first][0]
        word = kind_text(section.kind, "trocken" if section.kind == "trocken" else "")
        parts.append(f"{name} {word}")
    return ", ".join(parts)

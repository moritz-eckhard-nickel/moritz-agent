# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""German phrases for times, dates, durations, numbers and lists (docs/plan/13 §7.4, §9)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from moritz_agent.phone.audio.textnorm import cardinal
from moritz_agent.tools.time_tool import MONTHS_DE, WEEKDAYS_DE

WEEKDAY_ACCUSATIVE_STEM = WEEKDAYS_DE  # "am Montag"


def clock_digital(
    moment: datetime | None = None, *, hour: int | None = None, minute: int | None = None
) -> str:
    """ "19 Uhr 12" / "7 Uhr"."""
    h = moment.hour if moment is not None else hour
    m = moment.minute if moment is not None else minute
    assert h is not None and m is not None
    return f"{h} Uhr" if m == 0 else f"{h} Uhr {m}"


def clock_colloquial(moment: datetime) -> str:
    """ "Viertel nach sieben" for round quarters, else the digital form."""
    minute = moment.minute
    twelve = moment.hour % 12 or 12
    nxt = (moment.hour + 1) % 12 or 12
    word = lambda n: cardinal(n, eins=False)  # noqa: E731
    if minute == 0:
        return f"{word(twelve)} Uhr"
    if minute == 15:
        return f"Viertel nach {word(twelve)}"
    if minute == 30:
        return f"halb {word(nxt)}"
    if minute == 45:
        return f"Viertel vor {word(nxt)}"
    return clock_digital(moment)


def date_long(day: date, *, with_year: bool = True) -> str:
    """ "Sonntag, der 18. Oktober 2026"."""
    text = f"{WEEKDAYS_DE[day.weekday()]}, der {day.day}. {MONTHS_DE[day.month - 1]}"
    return f"{text} {day.year}" if with_year else text


def date_plain(day: date, *, with_year: bool = False) -> str:
    """ "18. Oktober" / "18. Oktober 2026"."""
    text = f"{day.day}. {MONTHS_DE[day.month - 1]}"
    return f"{text} {day.year}" if with_year else text


def day_label(day: date, today: date, *, capital: bool = False) -> str:
    """ "heute", "morgen", "am Samstag", "am Samstag, dem 24. Oktober" (relative to ``today``)."""
    delta = (day - today).days
    named = {0: "heute", 1: "morgen", 2: "übermorgen", -1: "gestern", -2: "vorgestern"}
    if delta in named:
        label = named[delta]
    elif 0 < delta < 7:
        label = f"am {WEEKDAYS_DE[day.weekday()]}"
    else:
        label = f"am {WEEKDAYS_DE[day.weekday()]}, dem {date_plain(day, with_year=day.year != today.year)}"
    return label[0].upper() + label[1:] if capital else label


def weekday_and_date(day: date, today: date) -> str:
    """ "Montag, der 19. Oktober" (year only if it differs)."""
    return date_long(day, with_year=day.year != today.year)


def plural(n: int, singular: str, plural_form: str) -> str:
    return f"{n} {singular if n == 1 else plural_form}"


def duration(delta: timedelta, *, seconds: bool = False) -> str:
    """ "2 Stunden und 48 Minuten", "3 Tage", "1 Minute"."""
    total = int(abs(delta.total_seconds()))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if days:
        parts.append(plural(days, "Tag", "Tage"))
    if hours:
        parts.append(plural(hours, "Stunde", "Stunden"))
    if minutes:
        parts.append(plural(minutes, "Minute", "Minuten"))
    if seconds and (secs or not parts):
        parts.append(plural(secs, "Sekunde", "Sekunden"))
    if not parts:
        parts.append("weniger als eine Minute")
    return join_and(parts)


def join_and(items: list[str] | tuple[str, ...]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " und " + items[-1]


def round_half_up(value: float, decimals: int = 0) -> Decimal:
    """Commercial rounding (2,5 → 3, 6,175 → 6,18) instead of Python's banker's rounding.

    The float is first cut to ten decimals so that binary noise (6,17499999…) does not decide.
    """
    exact = Decimal(repr(round(value, 10)))
    with localcontext() as ctx:
        ctx.prec = 80
        return exact.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def number(value: float, decimals: int = 2) -> str:
    """German number text: "3,5", "1.234", trailing zeros dropped (the voice reads "Komma")."""
    rounded = round_half_up(value, decimals)
    text = f"{rounded:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    # the format used "," for thousands and "." for decimals
    text = whole.replace(",", ".") + ("," + frac if frac else "")
    if text in {"-0", "-0,0"}:
        text = "0"
    return text.replace("-", "minus ") if text.startswith("-") else text


def euro(amount: float) -> str:
    """ "47 Euro 31" / "5 Euro" (speakable)."""
    cents = int(round_half_up(abs(amount) * 100))
    euros, rest = divmod(cents, 100)
    sign = "minus " if amount < 0 and cents else ""
    return f"{sign}{euros} Euro" + (f" {rest}" if rest else "")


def sentence(text: str) -> str:
    """Capitalize the first letter and make sure the sentence ends with a full stop."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."

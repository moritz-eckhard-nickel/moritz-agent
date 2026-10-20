# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Time expressions → a time span (docs/plan/13 §4.3).

"morgen früh", "am Samstag", "übers Wochenende", "in 3 Stunden", "um 15 Uhr", "am 24.12.",
"nächste Woche", "Heiligabend" … The parser works on the prepared utterance (lower case, digits,
dialect resolved) and returns the span as aware datetimes plus the German label for the answer.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from moritz_agent.skills.calendar.special import SPECIAL_DAYS, find_special, next_occurrence
from moritz_agent.skills.render.german import day_label
from moritz_agent.skills.text.numbers import MONTHS
from moritz_agent.tools.time_tool import WEEKDAYS_DE

WEEKDAY_INDEX = {name.lower(): i for i, name in enumerate(WEEKDAYS_DE)} | {"sonnabend": 5}
MONTH_INDEX = {name: i + 1 for i, name in enumerate(MONTHS)}
# daypart → (first hour, last hour exclusive); hours ≥ 24 belong to the next day
DAYPARTS = {
    "früh": (5, 9), "vormittag": (9, 12), "mittag": (12, 14), "nachmittag": (14, 18),
    "abend": (18, 22), "nacht": (22, 30),
}  # fmt: skip
DAYPART_WORDS = {
    "früh": "früh", "morgens": "früh", "morgen": "früh", "vormittag": "vormittag",
    "vormittags": "vormittag", "mittag": "mittag", "mittags": "mittag", "nachmittag": "nachmittag",
    "nachmittags": "nachmittag", "abend": "abend", "abends": "abend", "nacht": "nacht",
    "nachts": "nacht",
}  # fmt: skip
DAYPART_NOUN = {
    "früh": "früh", "vormittag": "Vormittag", "mittag": "Mittag", "nachmittag": "Nachmittag",
    "abend": "Abend", "nacht": "Nacht",
}  # fmt: skip
_DP = "|".join(sorted(DAYPART_WORDS, key=len, reverse=True))
_WD = "|".join(WEEKDAY_INDEX)
_MONTH_NAMES = "|".join(MONTHS)
_DAYWORDS = {"vorgestern": -2, "gestern": -1, "heute": 0, "morgen": 1, "übermorgen": 2}


@dataclass(frozen=True)
class When:
    start: datetime
    end: datetime
    granularity: str  # now | hour | daypart | day | weekend | week | days | month | year
    label: str
    day: date | None = None  # the single day, if the expression names one
    clock: time | None = None
    daypart: str | None = None
    spans: tuple[tuple[int, int], ...] = field(default=(), compare=False)
    explicit: bool = True  # False: derived from the default ("jetzt")

    @property
    def is_past(self) -> bool:
        return self.end <= self.start.__class__.now(self.start.tzinfo)

    def days(self) -> list[date]:
        """All calendar days touched by the span."""
        first, last = self.start.date(), (self.end - timedelta(seconds=1)).date()
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def _midnight(day: date, tz) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz)


def _at(day: date, hour: int, minute: int, tz) -> datetime:
    return _midnight(day, tz) + timedelta(hours=hour, minutes=minute)


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _daypart_span(day: date, part: str, tz) -> tuple[datetime, datetime]:
    first, last = DAYPARTS[part]
    return _at(day, first, 0, tz), _at(day, last, 0, tz)


def _label(day: date, today: date, part: str | None) -> str:
    base = day_label(day, today)
    if part is None:
        return base
    if base in {"heute", "morgen", "übermorgen", "gestern", "vorgestern"}:
        return f"{base} {DAYPART_NOUN[part]}"
    return f"{base} {DAYPART_NOUN[part]}"


@dataclass
class _Parts:
    day: date | None = None
    days_span: tuple[date, date] | None = None  # inclusive range for week / weekend / days
    kind: str = ""  # weekend | week | days | month | year
    part: str | None = None
    clock: time | None = None
    now: bool = False
    delta: timedelta | None = None
    spans: list[tuple[int, int]] = field(default_factory=list)
    label_override: str = ""


def _grab(pattern: str, text: str, taken: list[tuple[int, int]]) -> re.Match[str] | None:
    for match in re.finditer(pattern, text):
        if not any(match.start() < b and a < match.end() for a, b in taken):
            return match
    return None


def _clock_time(
    hour: int, minute: int, now: datetime | None, day_given: bool, part: str | None
) -> time:
    if hour == 24:
        hour = 0
    if part in {"nachmittag", "abend"} and hour < 12:
        hour += 12
    if part == "nacht" and 6 <= hour < 12:
        hour += 12
    return time(hour % 24, minute)


def find_when(text: str, now: datetime) -> When | None:
    """Parse the time expression in ``text`` (None if there is none)."""
    tz = now.tzinfo
    today = now.date()
    p = _Parts()
    taken = p.spans

    # --- relative durations: "in 3 stunden", "in einer halben stunde", "in anderthalb stunden"
    m = _grab(
        r"\bin (\d+|einer|einem|anderthalb|eineinhalb|einer halben|einer viertel|drei viertel|einer dreiviertel) "
        r"(minuten?|stunden?|tagen?|wochen?|monaten?|jahren?)\b",
        text,
        taken,
    )
    if m:
        amount_text, unit = m.group(1), m.group(2)
        amount = {"einer": 1, "einem": 1, "anderthalb": 1.5, "eineinhalb": 1.5, "einer halben": 0.5,
                  "einer viertel": 0.25, "drei viertel": 0.75, "einer dreiviertel": 0.75}.get(amount_text)  # fmt: skip
        amount = float(amount_text) if amount is None else amount
        base = unit.rstrip("n")
        if base.startswith("minute"):
            p.delta = timedelta(minutes=amount)
        elif base.startswith("stunde"):
            p.delta = timedelta(hours=amount)
        elif base.startswith("tag"):
            p.delta = timedelta(days=amount)
        elif base.startswith("woche"):
            p.delta = timedelta(weeks=amount)
        elif base.startswith("monat"):
            target = add_months(today, int(amount))
            p.delta = _midnight(target, tz) + (now - _midnight(today, tz)) - now
        else:
            target = add_months(today, int(amount * 12))
            p.delta = _midnight(target, tz) + (now - _midnight(today, tz)) - now
        taken.append(m.span())

    # --- numeric dates: 24.12. / 24.12.2026 / 24.12.26
    m = _grab(r"\b(\d{1,2})\.(\d{1,2})\.(?:(\d{4}|\d{2})\b)?", text, taken)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        p.day = _date_from(int(m.group(1)), int(m.group(2)), m.group(3), today)
        taken.append(m.span())
    if p.day is None:
        m = _grab(rf"\b(\d{{1,2}})\.? ({_MONTH_NAMES})(?: (\d{{4}}))?\b", text, taken)
        if m and 1 <= int(m.group(1)) <= 31:
            p.day = _date_from(int(m.group(1)), MONTH_INDEX[m.group(2)], m.group(3), today)
            taken.append(m.span())

    # --- special days (Heiligabend, Ostern, 1. Advent …)
    if p.day is None:
        found = find_special(text)
        if found:
            key, span = found
            if key in SPECIAL_DAYS:
                p.day = next_occurrence(key, today)
                a, b = span.span() if hasattr(span, "span") else span
                taken.append((a, b))
                p.label_override = ""

    # --- weekend / week / period words
    if p.day is None and p.delta is None:
        m = _grab(
            r"\b(?:(nächstes|kommendes|nächsten|kommenden|diesem|dieses|übernächstes) )?wochenende\b",
            text,
            taken,
        )
        if m:
            sat = today + timedelta(days=(5 - today.weekday()) % 7)
            if today.weekday() == 6:
                sat = today - timedelta(days=1)
            if m.group(1) in {"nächstes", "nächsten", "kommendes", "kommenden"}:
                sat = today + timedelta(days=6) if today.weekday() == 6 else sat + timedelta(days=7)
            elif m.group(1) == "übernächstes":
                sat += timedelta(days=14)
            p.days_span, p.kind = (sat, sat + timedelta(days=1)), "weekend"
            nxt = m.group(1) in {"nächstes", "nächsten", "kommendes", "kommenden"}
            p.label_override = "nächstes Wochenende" if nxt else "am Wochenende"
            taken.append(m.span())
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(
            r"\b(?:die )?(diese|dieser|nächste|nächsten|kommende|kommenden|letzte|letzten|vergangene|vergangenen) woche\b",
            text,
            taken,
        )
        if m:
            monday = today - timedelta(days=today.weekday())
            which = m.group(1)
            if which.startswith(("nächst", "kommend")):
                monday += timedelta(days=7)
            elif which.startswith(("letzt", "vergangen")):
                monday -= timedelta(days=7)
            first = today if which.startswith("dies") else monday
            p.days_span, p.kind = (first, monday + timedelta(days=6)), "week"
            p.label_override = (
                "nächste Woche"
                if which.startswith(("nächst", "kommend"))
                else "letzte Woche"
                if which.startswith(("letzt", "vergangen"))
                else "diese Woche"
            )
            taken.append(m.span())
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(
            r"\b(?:die |für die |in den )?(?:nächsten|kommenden|folgenden) (\d+ )?tage?n?\b",
            text,
            taken,
        )
        if m:
            count = int(m.group(1)) if m.group(1) else 5
            p.days_span, p.kind = (today, today + timedelta(days=count - 1)), "days"
            taken.append(m.span())
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(
            r"\b(?:wochenvorhersage|wochenvorschau|wochentrend|ganze woche|für die woche|diese tage)\b",
            text,
            taken,
        )
        if m:
            p.days_span, p.kind = (today, today + timedelta(days=6)), "days"
            taken.append(m.span())

    # --- months and years (calendar questions)
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(
            rf"\b(?:(im|in|für|der|dem|den monat|im monat) )?({_MONTH_NAMES})(?: (\d{{4}}))?\b",
            text,
            taken,
        )
        if m and (m.group(1) or m.group(3) or text.strip() == m.group(2)):
            month, year = MONTH_INDEX[m.group(2)], int(m.group(3)) if m.group(3) else today.year
            if not m.group(3) and month < today.month:
                year += 1
            last = calendar.monthrange(year, month)[1]
            p.days_span, p.kind = (date(year, month, 1), date(year, month, last)), "month"
            p.label_override = f"im {MONTHS[month - 1].capitalize()}" + (
                f" {year}" if year != today.year else ""
            )
            taken.append(m.span())
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(r"\b(diesen|nächsten|kommenden|letzten|vergangenen) monat\b", text, taken)
        if m:
            offset = {"diesen": 0, "nächsten": 1, "kommenden": 1, "letzten": -1, "vergangenen": -1}[
                m.group(1)
            ]
            first = add_months(date(today.year, today.month, 1), offset)
            p.days_span = (
                first,
                date(first.year, first.month, calendar.monthrange(first.year, first.month)[1]),
            )
            p.kind = "month"
            p.label_override = {
                0: "in diesem Monat",
                1: "im nächsten Monat",
                -1: "im letzten Monat",
            }[offset]
            taken.append(m.span())
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(
            r"\b(?:(dieses|nächstes|kommendes|letztes|vergangenes) jahr|im jahr (\d{4}))\b",
            text,
            taken,
        )
        if m:
            year = (
                int(m.group(2))
                if m.group(2)
                else today.year
                + {"dieses": 0, "nächstes": 1, "kommendes": 1, "letztes": -1, "vergangenes": -1}[
                    m.group(1)
                ]
            )
            p.days_span, p.kind = (date(year, 1, 1), date(year, 12, 31)), "year"
            p.label_override = "in diesem Jahr" if year == today.year else f"im Jahr {year}"
            taken.append(m.span())

    # --- day words with optional daypart: "heute abend", "morgen früh", "übermorgen"
    if p.day is None and p.delta is None and not p.kind:
        m = _grab(rf"\b(vorgestern|gestern|heute|übermorgen|morgen)(?: ({_DP}))?\b", text, taken)
        if m:
            word, part = m.group(1), m.group(2)
            p.day = today + timedelta(days=_DAYWORDS[word])
            if part:
                p.part = DAYPART_WORDS[part]
            taken.append(m.span())
        else:
            m = _grab(
                rf"\b(?:(am|diesen|diesem|dieser|kommenden|nächsten|letzten|vergangenen) )?({_WD})(?: ({_DP}))?\b",
                text,
                taken,
            )
            if m:
                target = WEEKDAY_INDEX[m.group(2)]
                offset = (target - today.weekday()) % 7
                prefix = m.group(1)
                if prefix in {"nächsten", "kommenden"}:
                    offset = offset or 7
                elif prefix in {"letzten", "vergangenen"}:
                    offset = (offset or 7) - 7 if offset else -7
                p.day = today + timedelta(days=offset)
                if m.group(3):
                    p.part = DAYPART_WORDS[m.group(3)]
                taken.append(m.span())

    # --- bare daypart: "abends", "heute nacht" was caught above; "nachmittags"
    if p.part is None:
        m = _grab(rf"\b({_DP})\b", text, taken)
        if m and m.group(1) not in {"morgen"}:  # bare "morgen" is "tomorrow", handled above
            p.part = DAYPART_WORDS[m.group(1)]
            taken.append(m.span())

    # --- clock time: "um 15 uhr", "um 15:30", "15:30 uhr", "um 3"
    m = _grab(
        r"\b(?:um|gegen|ab|bis|von|kurz nach|kurz vor)?\s*(\d{1,2}):(\d{2})(?: uhr)?\b", text, taken
    ) or _grab(r"\b(?:um |gegen |ab |bis |von )?(\d{1,2}) uhr(?: (\d{1,2}))?\b", text, taken)
    if not m:
        m = _grab(r"\bum (\d{1,2})\b(?! (?:prozent|euro|grad|mal|personen))", text, taken)
    if m:
        hour = int(m.group(1))
        minute = (
            int(m.group(2)) if len(m.groups()) > 1 and m.group(2) and m.group(2).isdigit() else 0
        )
        if 0 <= hour <= 24 and 0 <= minute < 60:
            p.clock = _clock_time(hour, minute, now, p.day is not None, p.part)
            taken.append(m.span())

    # --- "jetzt / gerade / aktuell …"
    m = _grab(
        r"\b(jetzt|gerade|im moment|momentan|aktuell|zur zeit|derzeit|draußen)\b", text, taken
    )
    if m:
        p.now = True
        taken.append(m.span())

    return _compose(p, now)


def _date_from(day: int, month: int, year_text: str | None, today: date) -> date | None:
    year = int(year_text) if year_text else today.year
    if year_text and len(year_text) == 2:
        year += 2000
    try:
        result = date(year, month, day)
    except ValueError:
        return None
    if not year_text and result < today:
        try:
            result = date(year + 1, month, day)
        except ValueError:
            return None
    return result


def _compose(p: _Parts, now: datetime) -> When | None:
    tz, today = now.tzinfo, now.date()
    spans = tuple(sorted(p.spans))
    if p.delta is not None and p.clock is None:
        target = now + p.delta
        gran = "hour" if p.delta <= timedelta(hours=48) else "day"
        label = f"in {_dur_label(p.delta)}"
        if gran == "day":
            return When(
                _midnight(target.date(), tz),
                _midnight(target.date() + timedelta(days=1), tz),
                "day",
                label,
                target.date(),
                spans=spans,
            )
        return When(
            target,
            target + timedelta(hours=1),
            "hour",
            label,
            target.date(),
            target.timetz().replace(tzinfo=None),
            spans=spans,
        )
    if p.kind and p.days_span:
        first, last = p.days_span
        label = (
            p.label_override
            or {
                "weekend": "am Wochenende",
                "week": "diese Woche",
                "days": "in den nächsten Tagen",
                "month": "in diesem Monat",
                "year": "in diesem Jahr",
            }[p.kind]
        )
        return When(
            _midnight(first, tz),
            _midnight(last + timedelta(days=1), tz),
            p.kind,
            label,
            spans=spans,
        )
    if p.day is None and p.clock is None and p.part is None and not p.now:
        return None
    if p.day is None and p.clock is None and p.part is None and p.now:
        return When(now, now + timedelta(hours=1), "now", "gerade", today, spans=spans)
    day = p.day
    if day is None:
        # no day given: the next time that fits
        if p.clock is not None:
            picked: datetime | None = None
            for add_days in (0, 1):
                for add_hours in (
                    (0, 12) if p.clock.hour < 12 and p.part is None and p.clock.hour >= 1 else (0,)
                ):
                    alt = datetime.combine(
                        today + timedelta(days=add_days),
                        time((p.clock.hour + add_hours) % 24, p.clock.minute),
                        tzinfo=tz,
                    )
                    ok_hours = (
                        6 <= alt.hour <= 23
                        if p.clock.hour < 12 and p.part is None and p.clock.hour >= 1
                        else True
                    )
                    if alt > now and ok_hours:
                        picked = alt
                        break
                if picked:
                    break
            candidate = picked or datetime.combine(today + timedelta(days=1), p.clock, tzinfo=tz)
            day, p.clock = candidate.date(), candidate.timetz().replace(tzinfo=None)
        else:
            day = today
            if p.part and p.part != "nacht":
                _, end = _daypart_span(day, p.part, tz)
                if end <= now:
                    pass  # stays today – the skill says "that is over" if it matters
    if p.clock is not None:
        start = datetime.combine(day, p.clock, tzinfo=tz)
        return When(
            start,
            start + timedelta(hours=1),
            "hour",
            f"{day_label(day, today)} um {p.clock.hour} Uhr"
            + (f" {p.clock.minute}" if p.clock.minute else ""),
            day,
            p.clock,
            p.part,
            spans,
        )
    if p.part:
        start, end = _daypart_span(day, p.part, tz)
        return When(start, end, "daypart", _label(day, today, p.part), day, None, p.part, spans)
    return When(
        _midnight(day, tz),
        _midnight(day + timedelta(days=1), tz),
        "day",
        day_label(day, today),
        day,
        spans=spans,
    )


def _dur_label(delta: timedelta) -> str:
    minutes = round(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes} Minuten"
    if minutes < 48 * 60:
        hours = minutes / 60
        return (
            f"{int(hours)} Stunden"
            if hours == int(hours)
            else f"{hours:g} Stunden".replace(".", ",")
        )
    return f"{round(minutes / 1440)} Tagen"


def remove_spans(text: str, when: When | None) -> str:
    """``text`` without the words the time parser consumed (for place detection)."""
    if when is None or not when.spans:
        return text
    pieces, last = [], 0
    for a, b in when.spans:
        pieces.append(text[last:a])
        last = max(last, b)
    pieces.append(text[last:])
    return re.sub(r"\s+", " ", " ".join(pieces)).strip()


def find_dates(text: str, now: datetime) -> list[date]:
    """Every single date named in ``text`` in spoken order ("vom 1. märz bis zum 15. april")."""
    today = now.date()
    found: list[tuple[int, date]] = []
    taken: list[tuple[int, int]] = []
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(?:(\d{4}|\d{2})\b)?", text):
        d = _date_from(int(m.group(1)), int(m.group(2)), m.group(3), today)
        if d:
            found.append((m.start(), d))
            taken.append(m.span())
    for m in re.finditer(rf"\b(\d{{1,2}})\.? ({_MONTH_NAMES})(?: (\d{{4}}))?\b", text):
        if any(m.start() < b and a < m.end() for a, b in taken):
            continue
        d = _date_from(int(m.group(1)), MONTH_INDEX[m.group(2)], m.group(3), today)
        if d:
            found.append((m.start(), d))
            taken.append(m.span())
    spec = find_special(text)
    if spec and not any(
        a <= (spec[1].start() if hasattr(spec[1], "start") else spec[1][0]) < b for a, b in taken
    ):
        key, span = spec
        start = span.start() if hasattr(span, "start") else span[0]
        found.append((start, next_occurrence(key, today)))
    for m in re.finditer(r"\b(vorgestern|gestern|heute|übermorgen|morgen)\b", text):
        found.append((m.start(), today + timedelta(days=_DAYWORDS[m.group(1)])))
    return [d for _, d in sorted(found)]

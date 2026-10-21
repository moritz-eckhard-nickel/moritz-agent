# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A small iCalendar reader for waste collection calendars (VEVENT with DTSTART, SUMMARY, EXDATE,
RECURRENCE-ID and the common RRULE forms; UTC/TZID times become local days) – docs/plan/13 §6.13."""

from __future__ import annotations

import calendar
import ipaddress
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from moritz_agent.skills.providers.http import HttpError

MAX_EVENTS = 5000
MAX_OCCURRENCES = 2000  # per event without COUNT (the window is at most about a year)
MAX_PERIODS = 5000  # rule periods (days, weeks, months) looked at per event
HOME_TZ = "Europe/Berlin"


@dataclass(frozen=True)
class Pickup:
    day: date
    summary: str


def check_url(url: str) -> str:
    """Return the host of a calendar link; only public https hosts are accepted (SSRF guard)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise HttpError("blocked", "waste calendar: only https links are allowed")
    if host in {"localhost"} or host.endswith(
        (".local", ".internal", ".lan", ".home", ".localdomain")
    ):
        raise HttpError("blocked", "waste calendar: local hosts are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if not address.is_global:
        raise HttpError("blocked", "waste calendar: private addresses are not allowed")
    return host


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in {" ", "\t"} and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    return value.replace("\\,", ",").replace(r"\;", ";").replace("\\n", " ").replace("\\\\", "\\")


def _parse_date(value: str) -> date | None:
    match = re.match(r"(\d{4})(\d{2})(\d{2})", value.strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


@dataclass(frozen=True)
class _Moment:
    """A DTSTART-like value: the wall-clock date/time in its own zone (``None`` = floating)."""

    day: date
    clock: time | None = None
    zone: tzinfo | None = None

    def local(self, home: tzinfo, day: date | None = None) -> date:
        """The calendar day in ``home`` of this moment (or of the same clock time on ``day``)."""
        day = day or self.day
        if self.clock is None or self.zone is None:
            return day
        return datetime.combine(day, self.clock, self.zone).astimezone(home).date()


def _zone(params: str) -> tzinfo | None:
    match = re.search(r"(?:^|;)TZID=\"?([^;:\"]+)\"?", params, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return ZoneInfo(match.group(1).strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None  # unknown zone: treat as local wall clock


def _parse_moment(value: str, params: str = "") -> _Moment | None:
    """ "20261021", "20261021T060000", "20261021T230000Z" (UTC) or with ``TZID=`` in ``params``."""
    day = _parse_date(value)
    if day is None:
        return None
    match = re.match(r"\d{8}T(\d{2})(\d{2})(\d{2})?(Z)?", value.strip(), flags=re.IGNORECASE)
    if not match:
        return _Moment(day)
    try:
        clock = time(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))
    except ValueError:
        return _Moment(day)
    zone = UTC if match.group(4) else _zone(params)
    return _Moment(day, clock, zone)


def _int(value: str | None, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


Event = dict[str, list[tuple[str, str]]]  # property → [(parameters, value), …]


def _first(event: Event, name: str) -> tuple[str, str]:
    values = event.get(name)
    return values[0] if values else ("", "")


def parse(text: str, first: date, last: date, tz: str = HOME_TZ) -> list[Pickup]:
    """All pick-ups between ``first`` and ``last`` (both included), sorted by day.

    Only the properties of the VEVENT itself count (not those of a nested VALARM); EXDATE,
    RECURRENCE-ID overrides, COUNT/UNTIL/INTERVAL and DAILY/WEEKLY (BYDAY), MONTHLY (BYMONTHDAY,
    BYDAY such as ``2TU``) and YEARLY rules are understood. Times with ``Z`` or ``TZID`` are
    converted to ``tz``.
    """
    home = ZoneInfo(tz)
    events: list[Event] = []
    event: Event | None = None
    depth = 0  # nesting below the VEVENT (VALARM …)
    for line in _unfold(text):
        upper = line.upper()
        if upper == "BEGIN:VEVENT" and event is None:
            event, depth = {}, 0
            continue
        if event is None:
            continue
        if upper.startswith("BEGIN:"):
            depth += 1
            continue
        if upper.startswith("END:"):
            if depth:
                depth -= 1
                continue
            if upper == "END:VEVENT":
                events.append(event)
                event = None
                if len(events) >= MAX_EVENTS:
                    break
            continue
        if depth or ":" not in line:
            continue
        head, _, value = line.partition(":")
        name, _, params = head.partition(";")
        event.setdefault(name.upper(), []).append((params, value))

    # RECURRENCE-ID: an override replaces the occurrence of the series with the same UID
    replaced: dict[str, set[date]] = {}
    for item in events:
        params, value = _first(item, "RECURRENCE-ID")
        moment = _parse_moment(value, params) if value else None
        if moment is not None:
            uid = _first(item, "UID")[1].strip()
            replaced.setdefault(uid, set()).add(moment.local(home))

    pickups: list[Pickup] = []
    for item in events:
        uid = _first(item, "UID")[1].strip()
        skip = set() if _first(item, "RECURRENCE-ID")[1] else replaced.get(uid, set())
        pickups.extend(_expand(item, first, last, home, skip))
    return sorted(pickups, key=lambda p: (p.day, p.summary))


def _exdates(event: Event, home: tzinfo) -> set[date]:
    found: set[date] = set()
    for params, value in event.get("EXDATE", []):
        for part in value.split(","):
            moment = _parse_moment(part, params)
            if moment is not None:
                found.add(moment.local(home))
    return found


def _expand(event: Event, first: date, last: date, home: tzinfo, skip: set[date]) -> list[Pickup]:
    params, value = _first(event, "DTSTART")
    start = _parse_moment(value, params)
    summary = _unescape(_first(event, "SUMMARY")[1]).strip()
    if start is None or not summary:
        return []
    if _first(event, "STATUS")[1].strip().upper() == "CANCELLED":
        return []
    excluded = skip | _exdates(event, home)
    rule = _first(event, "RRULE")[1]
    if not rule:
        day = start.local(home)
        return [Pickup(day, summary)] if first <= day <= last and day not in excluded else []
    options = {
        key.strip().upper(): val.strip()
        for key, _, val in (part.partition("=") for part in rule.split(";"))
        if key.strip()
    }
    interval = max(1, _int(options.get("INTERVAL"), 1) or 1)
    count = _int(options.get("COUNT"))
    if count is not None and count < 1:
        return []
    until_moment = _parse_moment(options.get("UNTIL", ""))
    until = until_moment.local(home) if until_moment else None
    out: list[Pickup] = []
    window = (first - timedelta(days=2), last + timedelta(days=2))
    for day in _occurrences(start.day, options, interval, count, window):
        local = start.local(home, day)
        if until is not None and local > until:
            break
        if local > last:
            break
        if local >= first and local not in excluded:
            out.append(Pickup(local, summary))
    return out


_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _byday(options: dict[str, str]) -> list[tuple[int | None, int]]:
    """ "TU,FR" → [(None, 1), (None, 4)]; "2TU" → [(2, 1)]; "-1FR" → [(-1, 4)]."""
    found = []
    for part in options.get("BYDAY", "").split(","):
        match = re.fullmatch(r"\s*([+-]?\d{1,2})?([A-Za-z]{2})\s*", part)
        if match and match.group(2).upper() in _WEEKDAYS:
            found.append((_int(match.group(1)), _WEEKDAYS[match.group(2).upper()]))
    return found


def _month_days(year: int, month: int, options: dict[str, str], start: date) -> list[date]:
    length = calendar.monthrange(year, month)[1]
    days: set[int] = set()
    for part in options.get("BYMONTHDAY", "").split(","):
        number = _int(part)
        if number:
            day = number if number > 0 else length + number + 1
            if 1 <= day <= length:
                days.add(day)
    for nth, weekday in _byday(options):
        matching = [d for d in range(1, length + 1) if date(year, month, d).weekday() == weekday]
        if nth is None:
            days.update(matching)
        elif 1 <= abs(nth) <= len(matching):
            days.add(matching[nth - 1] if nth > 0 else matching[nth])
    if not options.get("BYMONTHDAY") and not options.get("BYDAY") and start.day <= length:
        days.add(start.day)  # the same day of the month (skipped where the month is too short)
    return [date(year, month, d) for d in sorted(days)]


def _occurrences(
    start: date,
    options: dict[str, str],
    interval: int,
    count: int | None,
    window: tuple[date, date],
) -> Iterator[date]:
    """Recurrence days on the wall clock of DTSTART, from ``start`` up to the end of ``window``.

    Without COUNT nothing before the window matters, so DAILY/WEEKLY rules jump close to it.
    """
    freq = options.get("FREQ", "").upper()
    early, horizon = window
    produced = 0
    limit = count if count is not None else MAX_OCCURRENCES

    def emit(days: list[date]) -> Iterator[date]:
        nonlocal produced
        for day in days:
            if day < start:
                continue
            yield day
            produced += 1
            if produced >= limit:
                return

    if freq == "DAILY":
        period = 0
        if count is None and early > start:
            period = (early - start).days // interval
        for _ in range(MAX_PERIODS):
            day = start + timedelta(days=period * interval)
            if day > horizon or produced >= limit:
                return
            yield from emit([day])
            period += 1
    elif freq == "WEEKLY":
        weekdays = sorted({w for n, w in _byday(options) if n is None}) or [start.weekday()]
        week = start - timedelta(days=start.weekday())
        period = 0
        if count is None and early > week:
            period = max(0, (early - week).days // 7 - 1) // interval
        for _ in range(MAX_PERIODS):
            monday = week + timedelta(weeks=period * interval)
            if monday > horizon or produced >= limit:
                return
            yield from emit([monday + timedelta(days=w) for w in weekdays])
            period += 1
    elif freq in {"MONTHLY", "YEARLY"}:
        step = interval if freq == "MONTHLY" else 12 * interval
        index = start.year * 12 + start.month - 1
        for _ in range(MAX_PERIODS):
            year, month = divmod(index, 12)
            month += 1
            if date(year, month, 1) > horizon or produced >= limit:
                return
            if freq == "YEARLY" and not options.get("BYMONTHDAY") and not options.get("BYDAY"):
                days = (
                    [date(year, month, start.day)]
                    if start.day <= calendar.monthrange(year, month)[1]
                    else []
                )
            else:
                days = _month_days(year, month, options, start)
            yield from emit(days)
            index += step


KINDS = (
    ("Biotonne", ("bio", "biomüll", "grünschnitt")),
    ("Papiertonne", ("papier", "pappe", "blaue tonne", "altpapier")),
    ("gelbe Tonne", ("gelb", "wertstoff", "leichtverpackung", "verpackung")),
    ("Restmülltonne", ("restmüll", "rest", "schwarze tonne", "hausmüll", "graue tonne")),
    ("Sperrmüll", ("sperrmüll", "sperr")),
    ("Glascontainer", ("glas",)),
)


def kind_of(summary: str) -> str:
    low = summary.lower()
    for name, words in KINDS:
        if any(word in low for word in words):
            return name
    return summary.strip()


def when_parsed(text: str, today: date) -> list[Pickup]:
    return parse(text, today - timedelta(days=1), today + timedelta(days=400))

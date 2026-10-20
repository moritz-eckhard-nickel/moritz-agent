# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A small iCalendar reader for waste collection calendars (VEVENT with DTSTART, SUMMARY and a
simple RRULE; no time zones beyond the local one) – docs/plan/13 §6.13."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlsplit

from moritz_agent.skills.providers.http import HttpError

MAX_EVENTS = 5000


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


def parse(text: str, first: date, last: date) -> list[Pickup]:
    """All pick-ups between ``first`` and ``last`` (both included), sorted by day."""
    pickups: list[Pickup] = []
    event: dict[str, str] | None = None
    count = 0
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            event = {}
            continue
        if line == "END:VEVENT" and event is not None:
            count += 1
            if count > MAX_EVENTS:
                break
            pickups.extend(_expand(event, first, last))
            event = None
            continue
        if event is not None and ":" in line:
            name, _, value = line.partition(":")
            event[name.split(";", 1)[0].upper()] = value
    return sorted(pickups, key=lambda p: (p.day, p.summary))


def _expand(event: dict[str, str], first: date, last: date) -> list[Pickup]:
    start = _parse_date(event.get("DTSTART", ""))
    summary = _unescape(event.get("SUMMARY", "")).strip()
    if start is None or not summary:
        return []
    rule = event.get("RRULE")
    if not rule:
        return [Pickup(start, summary)] if first <= start <= last else []
    options = dict(part.split("=", 1) for part in rule.split(";") if "=" in part)
    freq = options.get("FREQ", "")
    step = {"DAILY": 1, "WEEKLY": 7}.get(freq)
    if step is None:
        return []
    step *= int(options.get("INTERVAL", "1") or 1)
    until = _parse_date(options.get("UNTIL", "")) or last
    limit = int(options["COUNT"]) if "COUNT" in options else 10**6
    out, current, produced = [], start, 0
    while current <= min(until, last) and produced < limit:
        if current >= first:
            out.append(Pickup(current, summary))
        current += timedelta(days=step)
        produced += 1
    return out


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

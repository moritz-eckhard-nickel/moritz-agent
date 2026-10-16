"""Clock tool: current time and date from the system clock (PHONE-23, PHONE-24, ADR-017).

The time is always read from the system clock in the configured zone (default
Europe/Berlin, daylight saving time handled by zoneinfo) at the moment of use – never
taken from the language model. Ticket P1-07 wraps this in the ``get_current_time`` tool.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Berlin"

WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS_DE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def now(timezone: str = DEFAULT_TIMEZONE) -> datetime:
    """Current aware datetime in ``timezone``."""
    return datetime.now(ZoneInfo(timezone))


def format_time_de(moment: datetime) -> str:
    """Speakable German time, e.g. 'Es ist 19 Uhr 12.' or 'Es ist 7 Uhr.'"""
    if moment.minute == 0:
        return f"Es ist {moment.hour} Uhr."
    return f"Es ist {moment.hour} Uhr {moment.minute}."


def format_date_de(moment: datetime) -> str:
    """Speakable German date, e.g. 'Heute ist Freitag, der 16. Oktober 2026.'"""
    weekday = WEEKDAYS_DE[moment.weekday()]
    month = MONTHS_DE[moment.month - 1]
    return f"Heute ist {weekday}, der {moment.day}. {month} {moment.year}."

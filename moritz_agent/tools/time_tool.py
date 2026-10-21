# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Clock tool: current time and date from the system clock (PHONE-23, PHONE-24, ADR-017).

The time is always read from the system clock in the configured zone (default
Europe/Berlin, daylight saving time handled by zoneinfo) at the moment of use – never
taken from the language model. :class:`GetCurrentTime` is the ``get_current_time`` tool (P1-07).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from moritz_agent.tools.base import BaseTool, ToolContext, ToolResult

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


def format_weekday_de(moment: datetime) -> str:
    """Speakable weekday, e.g. 'Heute ist Freitag.'"""
    return f"Heute ist {WEEKDAYS_DE[moment.weekday()]}."


def format_calendar_week_de(moment: datetime) -> str:
    """ISO 8601 calendar week, e.g. 'Wir haben Kalenderwoche 42.'"""
    return f"Wir haben Kalenderwoche {moment.isocalendar().week}."


class GetCurrentTime(BaseTool):
    name = "get_current_time"
    description = (
        "Liefert die aktuelle Uhrzeit, das Datum oder beides aus der Systemuhr. "
        "Nutze es bei jeder Frage nach Uhrzeit, Datum oder Wochentag; nenne nie eine Uhrzeit ohne dieses Werkzeug."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["time", "date", "datetime"],
                "description": "time = Uhrzeit, date = Datum und Wochentag, datetime = beides",
                "default": "datetime",
            }
        },
    }
    timeout_s = 2.0

    def __init__(
        self, timezone: str = DEFAULT_TIMEZONE, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.timezone = timezone
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else now(self.timezone)

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        moment = self._now()
        kind = args.get("kind", "datetime")
        data = {
            "iso": moment.isoformat(timespec="seconds"),
            "date": moment.date().isoformat(),
            "time": moment.strftime("%H:%M"),
            "weekday": WEEKDAYS_DE[moment.weekday()],
            "calendar_week": moment.isocalendar().week,
            "timezone": self.timezone,
        }
        parts = {
            "time": [format_time_de(moment)],
            "date": [format_date_de(moment)],
            "datetime": [format_time_de(moment), format_date_de(moment)],
        }[kind]
        return ToolResult.success(data, speakable=" ".join(parts))

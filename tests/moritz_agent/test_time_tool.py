# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from moritz_agent.tools.time_tool import (
    format_calendar_week_de,
    format_date_de,
    format_time_de,
    format_weekday_de,
    now,
)

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (19, 12, "Es ist 19 Uhr 12."),
        (7, 0, "Es ist 7 Uhr."),
        (0, 5, "Es ist 0 Uhr 5."),
        (23, 59, "Es ist 23 Uhr 59."),
    ],
)
def test_format_time_de(hour, minute, expected):
    assert format_time_de(datetime(2026, 10, 16, hour, minute, tzinfo=BERLIN)) == expected


def test_format_date_de():
    moment = datetime(2026, 10, 16, 12, 0, tzinfo=BERLIN)
    assert format_date_de(moment) == "Heute ist Freitag, der 16. Oktober 2026."


@pytest.mark.parametrize(
    ("utc", "expected_hour"),
    [
        (datetime(2026, 1, 15, 12, 0, tzinfo=UTC), 13),  # CET, UTC+1
        (datetime(2026, 7, 15, 12, 0, tzinfo=UTC), 14),  # CEST, UTC+2
        (datetime(2026, 3, 29, 1, 30, tzinfo=UTC), 3),  # right after the spring switch
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), 2),  # first 2 o'clock on switch-back day
        (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), 2),  # second 2 o'clock on switch-back day
    ],
)
def test_berlin_daylight_saving(utc, expected_hour):
    assert utc.astimezone(BERLIN).hour == expected_hour


def test_now_is_timezone_aware():
    current = now()
    assert current.tzinfo is not None
    assert current.utcoffset() is not None


def test_format_weekday_de():
    assert format_weekday_de(datetime(2026, 10, 18, 9, 0, tzinfo=BERLIN)) == "Heute ist Sonntag."


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (datetime(2026, 10, 16, tzinfo=BERLIN), "Wir haben Kalenderwoche 42."),
        (
            datetime(2027, 1, 1, tzinfo=BERLIN),
            "Wir haben Kalenderwoche 53.",
        ),  # ISO: belongs to 2026
        (datetime(2026, 12, 28, tzinfo=BERLIN), "Wir haben Kalenderwoche 53."),
    ],
)
def test_format_calendar_week_de(day, expected):
    assert format_calendar_week_de(day) == expected

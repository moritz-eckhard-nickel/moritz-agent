# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Time expressions → time spans (docs/plan/13 §4.3). "Now" is Sunday, 18 Oct 2026, 19:12."""

from __future__ import annotations

from datetime import datetime

import pytest

from moritz_agent.skills.slots.when import add_months, find_dates, find_when, remove_spans
from moritz_agent.skills.text.normalize import prepare

from .skills_util import BERLIN, SUNDAY_EVENING


def when(text: str, now: datetime = SUNDAY_EVENING):
    return find_when(prepare(text).text, now)


def stamp(moment: datetime) -> str:
    return moment.strftime("%a %d.%m. %H:%M")


@pytest.mark.parametrize(
    ("text", "granularity", "start", "label"),
    [
        ("wetter jetzt", "now", "Sun 18.10. 19:12", "gerade"),
        ("wetter heute", "day", "Sun 18.10. 00:00", "heute"),
        ("wetter heute abend", "daypart", "Sun 18.10. 18:00", "heute Abend"),
        ("wetter heute nacht", "daypart", "Sun 18.10. 22:00", "heute Nacht"),
        ("wetter heute morgen", "daypart", "Sun 18.10. 05:00", "heute früh"),
        ("wetter morgen", "day", "Mon 19.10. 00:00", "morgen"),
        ("wetter morgen früh", "daypart", "Mon 19.10. 05:00", "morgen früh"),
        ("wetter morgen mittag", "daypart", "Mon 19.10. 12:00", "morgen Mittag"),
        ("wetter übermorgen", "day", "Tue 20.10. 00:00", "übermorgen"),
        ("wetter gestern", "day", "Sat 17.10. 00:00", "gestern"),
        ("wetter am samstag", "day", "Sat 24.10. 00:00", "am Samstag"),
        ("wetter am freitag nachmittag", "daypart", "Fri 23.10. 14:00", "am Freitag Nachmittag"),
        ("wetter am montag", "day", "Mon 19.10. 00:00", "morgen"),
        ("wetter nächsten sonntag", "day", "Sun 25.10. 00:00", "am Sonntag, dem 25. Oktober"),
        ("wetter am sonntag", "day", "Sun 18.10. 00:00", "heute"),
        ("wetter nächstes wochenende", "weekend", "Sat 24.10. 00:00", "nächstes Wochenende"),
        ("wetter nächste woche", "week", "Mon 19.10. 00:00", "nächste Woche"),
        ("wetter diese woche", "week", "Sun 18.10. 00:00", "diese Woche"),
        ("wetter in den nächsten tagen", "days", "Sun 18.10. 00:00", "in den nächsten Tagen"),
        ("wetter um 15 uhr", "hour", "Mon 19.10. 15:00", "morgen um 15 Uhr"),
        ("wetter um 20:30", "hour", "Sun 18.10. 20:30", "heute um 20 Uhr 30"),
        ("wetter um drei", "hour", "Mon 19.10. 15:00", "morgen um 15 Uhr"),
        ("wetter um 8", "hour", "Sun 18.10. 20:00", "heute um 20 Uhr"),
        ("wetter morgen um 8 uhr", "hour", "Mon 19.10. 08:00", "morgen um 8 Uhr"),
        ("wetter in 3 stunden", "hour", "Sun 18.10. 22:12", "in 3 Stunden"),
        ("wetter in einer halben stunde", "hour", "Sun 18.10. 19:42", "in 30 Minuten"),
        ("wetter in 3 tagen", "day", "Wed 21.10. 00:00", "in 3 Tagen"),
        ("wetter am 24.12.", "day", "Thu 24.12. 00:00", "am Donnerstag, dem 24. Dezember"),
        ("wetter am 24. dezember", "day", "Thu 24.12. 00:00", "am Donnerstag, dem 24. Dezember"),
        ("wetter heiligabend", "day", "Thu 24.12. 00:00", "am Donnerstag, dem 24. Dezember"),
        ("wetter im november", "month", "Sun 01.11. 00:00", "im November"),
        ("wetter um halb vier", "hour", "Mon 19.10. 15:30", "morgen um 15 Uhr 30"),
        ("wetter um viertel nach 5", "hour", "Mon 19.10. 17:15", "morgen um 17 Uhr 15"),
        ("wetter um 3 uhr nachts", "hour", "Mon 19.10. 03:00", "morgen um 3 Uhr"),
    ],
)  # fmt: skip
def test_expressions(text, granularity, start, label):
    result = when(text)
    assert result is not None, text
    assert (result.granularity, stamp(result.start), result.label) == (granularity, start, label)


def test_nothing_to_find():
    assert when("wie wird das wetter") is None
    assert when("17 mal 23") is None


def test_a_day_covers_exactly_24_hours_even_when_the_clocks_change():
    # Sunday 25 October 2026 has 25 hours; the span is midnight to midnight local time
    result = find_when("am sonntag", datetime(2026, 10, 20, 10, 0, tzinfo=BERLIN))
    assert result is not None
    assert result.start.date().isoformat() == "2026-10-25"
    assert result.end.date().isoformat() == "2026-10-26"


def test_week_around_new_year():
    now = datetime(2026, 12, 30, 9, 0, tzinfo=BERLIN)
    result = find_when("nächste woche", now)
    assert result is not None and stamp(result.start) == "Mon 04.01. 00:00"


def test_date_without_year_rolls_over_to_next_year():
    now = datetime(2026, 12, 30, 9, 0, tzinfo=BERLIN)
    result = find_when("am 5. januar", now)
    assert result is not None and result.day is not None and result.day.year == 2027


def test_month_arithmetic_clamps_to_month_end():
    assert add_months(datetime(2026, 1, 31).date(), 1).isoformat() == "2026-02-28"
    assert add_months(datetime(2027, 1, 31).date(), 13).isoformat() == "2028-02-29"


def test_find_dates_in_spoken_order():
    dates = find_dates(prepare("vom 1. märz bis zum 15. april").text, SUNDAY_EVENING)
    assert [d.isoformat() for d in dates] == ["2027-03-01", "2027-04-15"]


def test_remove_spans_leaves_the_rest():
    text = prepare("wetter in limburg morgen früh").text
    result = find_when(text, SUNDAY_EVENING)
    assert remove_spans(text, result) == "wetter in limburg"

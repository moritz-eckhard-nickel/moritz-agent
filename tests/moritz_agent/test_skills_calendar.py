# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Holidays, special days, school holidays, work days (docs/plan/13 §8)."""

from __future__ import annotations

from datetime import date

import pytest

from moritz_agent.skills.calendar import holidays as hol
from moritz_agent.skills.calendar import school, special, workdays


@pytest.mark.parametrize(
    ("year", "expected"),
    [(1999, "1999-04-04"), (2000, "2000-04-23"), (2024, "2024-03-31"), (2025, "2025-04-20"),
     (2026, "2026-04-05"), (2027, "2027-03-28"), (2028, "2028-04-16"), (2038, "2038-04-25")],
)  # fmt: skip
def test_easter(year, expected):
    assert hol.easter(year).isoformat() == expected


def test_easter_is_always_a_sunday():
    assert all(hol.easter(year).weekday() == 6 for year in range(1900, 2101))


def test_hessen_holidays_2026():
    names = {h.day.isoformat(): h.name for h in hol.holidays(2026, "HE")}
    assert names == {
        "2026-01-01": "Neujahr", "2026-04-03": "Karfreitag", "2026-04-05": "Ostersonntag",
        "2026-04-06": "Ostermontag", "2026-05-01": "der Tag der Arbeit",
        "2026-05-14": "Christi Himmelfahrt", "2026-05-24": "Pfingstsonntag",
        "2026-05-25": "Pfingstmontag", "2026-06-04": "Fronleichnam",
        "2026-10-03": "der Tag der Deutschen Einheit", "2026-12-25": "der erste Weihnachtstag",
        "2026-12-26": "der zweite Weihnachtstag",
    }  # fmt: skip


@pytest.mark.parametrize(
    ("state", "count"),
    [("BW", 12), ("BY", 12), ("BE", 10), ("BB", 12), ("HB", 10), ("HH", 10), ("HE", 12), ("MV", 11),
     ("NI", 10), ("NW", 11), ("RP", 11), ("SL", 12), ("SN", 11), ("ST", 11), ("SH", 10), ("TH", 11)],
)  # fmt: skip
def test_number_of_holidays_per_state(state, count):
    """Nine holidays apply everywhere; the rest are state specific (checked against the lists)."""
    assert len(hol.holidays(2026, state)) == count


def test_reformationstag_is_not_a_holiday_in_hessen_but_in_others():
    assert hol.holiday_on(date(2026, 10, 31), "HE") is None
    assert hol.holiday_on(date(2026, 10, 31), "SN") is not None
    assert sorted(hol.holiday_states_on(date(2026, 10, 31))) == sorted(
        ["BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"]
    )


def test_fronleichnam_states():
    assert set(hol.holiday_states_on(date(2026, 6, 4))) == {"BW", "BY", "HE", "NW", "RP", "SL"}


def test_buss_und_bettag():
    assert hol.holiday_on(date(2026, 11, 18), "SN") is not None
    assert hol.holiday_on(date(2027, 11, 17), "SN") is not None
    assert hol.holiday_on(date(2026, 11, 18), "HE") is None


def test_next_holiday_looks_into_the_next_year():
    assert hol.next_holiday(date(2026, 12, 27), "HE").day == date(2027, 1, 1)
    assert hol.next_holiday(date(2026, 12, 25), "HE").day == date(2026, 12, 25)
    assert hol.next_holiday(date(2026, 12, 25), "HE", include_start=False).day == date(2026, 12, 26)


def test_state_names():
    assert hol.state_code("Hessen") == "HE"
    assert hol.state_code("nrw") == "NW"
    assert hol.state_code("Bayern") == "BY"
    assert hol.state_code("Atlantis") is None


@pytest.mark.parametrize(
    ("key", "year", "expected"),
    [
        ("muttertag", 2026, "2026-05-10"), ("erntedank", 2026, "2026-10-04"),
        ("advent1", 2026, "2026-11-29"), ("advent4", 2026, "2026-12-20"),
        ("advent1", 2027, "2027-11-28"), ("totensonntag", 2026, "2026-11-22"),
        ("volkstrauertag", 2026, "2026-11-15"), ("buss_und_bettag", 2026, "2026-11-18"),
        ("rosenmontag", 2027, "2027-02-08"), ("aschermittwoch", 2027, "2027-02-10"),
        ("weiberfastnacht", 2027, "2027-02-04"), ("gruendonnerstag", 2026, "2026-04-02"),
        ("himmelfahrt", 2026, "2026-05-14"), ("sommerzeit", 2027, "2027-03-28"),
        ("winterzeit", 2026, "2026-10-25"), ("heiligabend", 2026, "2026-12-24"),
    ],
)  # fmt: skip
def test_special_days(key, year, expected):
    assert special.special_date(key, year).isoformat() == expected


def test_find_special_names():
    assert special.find_special("wann ist der erste advent")[0] == "advent1"
    assert special.find_special("wann ist der 2. advent")[0] == "advent2"
    assert special.find_special("wann ist muttertag")[0] == "muttertag"
    assert special.find_special("wann ist vatertag")[0] == "himmelfahrt"
    assert special.find_special("wetter morgen") is None
    assert special.find_special("wann ist mariä himmelfahrt")[0] == "mariae_himmelfahrt"
    assert special.find_special("wann ist christi himmelfahrt")[0] == "himmelfahrt"
    assert special.special_date("mariae_himmelfahrt", 2027) == date(2027, 8, 15)


def test_school_holidays_hessen():
    assert school.current(date(2026, 10, 10)).kind == "herbst"
    assert school.current(date(2026, 10, 18)) is None
    assert school.upcoming(date(2026, 10, 18)).kind == "weihnachten"
    assert school.upcoming(date(2026, 10, 18), "sommer").first == date(2027, 6, 28)
    xmas = school.current(date(2027, 1, 5))
    assert xmas is not None and xmas.school_resumes == date(2027, 1, 13)


def test_school_table_reaches_far_enough():
    assert school.last_covered_day() >= date(2030, 8, 30)
    assert not school.table_is_stale(date(2026, 10, 20))
    assert school.table_is_stale(date(2029, 10, 20))


def test_workdays_exclude_weekends_and_holidays():
    assert workdays.count_workdays(date(2026, 12, 21), date(2026, 12, 27), "HE") == 4  # Mon–Thu
    assert workdays.count_workdays(date(2026, 11, 1), date(2026, 11, 30), "HE") == 21
    assert not workdays.is_workday(date(2026, 12, 25), "HE")
    assert workdays.is_workday(date(2026, 12, 24), "HE")


def test_long_weekends_with_bridge_days():
    found = {lw.holiday.id: lw for lw in workdays.long_weekends(date(2026, 1, 1), "HE", 1)}
    assert found["himmelfahrt"].bridge == date(2026, 5, 15)  # Thursday → bridge Friday
    assert found["himmelfahrt"].days == 4
    assert found["karfreitag"].bridge is None
    assert found["weihnachtstag1"].days == 3


def test_long_weekends_grow_over_neighbouring_holidays():
    found = workdays.long_weekends(date(2025, 12, 1), "HE", 4)
    spans = {(lw.first, lw.last): lw for lw in found}
    # 26.12.2025 is a holiday on Friday: never a bridge day, Thu–Sun are free anyway
    christmas = spans[(date(2025, 12, 25), date(2025, 12, 28))]
    assert christmas.bridge is None and christmas.days == 4
    assert all(lw.bridge is None or not hol.holiday_on(lw.bridge, "HE") for lw in found)
    # Easter 2027: Good Friday to Easter Monday, once
    easter = spans[(date(2027, 3, 26), date(2027, 3, 29))]
    assert easter.days == 4 and easter.bridge is None
    assert not any(lw.first == date(2027, 3, 27) for lw in found)
    # Christmas 2028: Saturday 23 to Tuesday 26 December
    assert spans[(date(2028, 12, 23), date(2028, 12, 26))].days == 4

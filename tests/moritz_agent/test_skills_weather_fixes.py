# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Regression tests for review findings in the weather, warning, money and region skills."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from moritz_agent.skills.catalog.geld import parse_amount
from moritz_agent.skills.geo.gazetteer import Place
from moritz_agent.skills.providers import brightsky, dwd, energy_charts, ics, open_meteo
from moritz_agent.skills.weather.health import event_dative

from . import weather_fixtures as wf
from .skills_util import BERLIN, SUNDAY_EVENING, weather_session
from .test_skills_region import full_session

POLLEN = "opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
FORECAST = "api.open-meteo.com/v1/forecast"
PEGEL = "www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json"
ALL_POLLEN = ("Hasel", "Erle", "Esche", "Birke", "Graeser", "Roggen", "Beifuss", "Ambrosia")


def _offline(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(503)


# -- 1 + 2: DWD pollen ---------------------------------------------------------------------------
def test_pollen_minus_one_means_no_forecast_not_an_error():
    raw = wf.pollen_answer({key: ("1", "1-2", "-1") for key in ALL_POLLEN})
    forecast = dwd.parse(raw["content"][0], raw["last_update"])
    assert "dayafter_to" not in forecast.days
    assert forecast.days["tomorrow"]["Birke"] == 1.5
    session = weather_session({POLLEN: raw})
    assert session.say("Wie ist der Pollenflug heute?").startswith("Heute fliegen")
    assert session.say("Wie wird der Pollenflug übermorgen?") == (
        "Für übermorgen hat der Deutsche Wetterdienst noch keine Pollenvorhersage."
    )


def test_pollen_empty_value_is_no_forecast_too():
    raw = wf.pollen_answer({"Birke": ("2", "", "-1")})
    forecast = dwd.parse(raw["content"][0], raw["last_update"])
    assert "Birke" not in forecast.days["tomorrow"]


def test_pollen_days_count_from_the_issue_date():
    raw = wf.pollen_answer({"Birke": ("0", "3", "2")})  # issued 2026-10-18 11:00
    monday = datetime(2026, 10, 19, 8, 0, tzinfo=BERLIN)
    assert weather_session({POLLEN: raw}, at=monday).say("Wie ist der Pollenflug heute?") == (
        "Heute fliegen Birkenpollen stark, alles andere kaum."
    )
    assert weather_session({POLLEN: raw}, at=monday).say("Wie wird der Pollenflug morgen?") == (
        "Morgen fliegen Birkenpollen mäßig, alles andere kaum."
    )
    wednesday = datetime(2026, 10, 21, 8, 0, tzinfo=BERLIN)
    assert weather_session({POLLEN: raw}, at=wednesday).say("Wie ist der Pollenflug?") == (
        "Für heute hat der Deutsche Wetterdienst noch keine Pollenvorhersage."
    )


def test_pollen_issue_date_parsing():
    assert dwd.issue_date("2026-10-18 11:00 Uhr") == date(2026, 10, 18)
    assert dwd.issue_date("") is None
    assert dwd.issue_date("kaputt") is None


# -- 3: amounts with German thousands separators ---------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("1.000", 1000.0),
        ("2.500", 2500.0),
        ("1.000.000", 1_000_000.0),
        ("1.000,50", 1000.5),
        ("2,5", 2.5),
        ("1.5", 1.5),
        ("100", 100.0),
    ],
)
def test_parse_amount(raw, value):
    assert parse_amount(raw) == value


def test_thousands_dollars_and_small_euro_amounts():
    answer = weather_session().say("Wie viel sind 1.000 Dollar in Euro?")
    assert answer.startswith("1.000 US-Dollar sind etwa 9")
    assert "Cent" in weather_session().say("Wie viel sind 0,5 Dollar in Euro?")
    assert "0 Euro" not in weather_session().say("Wie viel sind 0,5 Dollar in Euro?")


# -- 4: warning events after "vor" ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("SCHWERES GEWITTER mit ORKANBÖEN", "schwerem Gewitter mit Orkanböen"),
        ("GEWITTER mit STURMBÖEN", "Gewitter mit Sturmböen"),
        ("Unwetter durch HEFTIGEN STARKREGEN", "Unwetter durch heftigen Starkregen"),
        ("SCHWERES GEWITTER mit HAGEL", "schwerem Gewitter mit Hagel"),
        ("STRENGER FROST", "strengem Frost"),
        ("STURMBÖEN", "Sturmböen"),
    ],
)
def test_event_dative_only_declines_the_leading_adjectives(raw, spoken):
    assert event_dative(raw) == spoken


def test_warning_sentence_with_a_compound_event():
    alert = wf.storm_alert()
    alert["event_de"] = "SCHWERES GEWITTER mit ORKANBÖEN"
    answer = weather_session({"api.brightsky.dev/alerts": wf.alerts_answer([alert])}).say(
        "Gibt es Unwetterwarnungen?"
    )
    assert "vor schwerem Gewitter mit Orkanböen" in answer


# -- 5: Bright Sky sleet is no freezing rain ---------------------------------------------------------
@pytest.mark.parametrize(("temperature", "code"), [(2.0, 63), (0.5, 71), (None, 71)])
def test_sleet_is_rain_or_snow_never_freezing_rain(temperature, code):
    assert brightsky._code("sleet", 0.6, temperature) == code


def test_sleet_hours_do_not_warn_of_black_ice():
    raw = wf.bright_sky_weather()
    for row in raw["weather"]:
        if row["timestamp"].startswith("2026-10-18T2"):
            row.update(icon="sleet", condition="sleet", temperature=2.0, precipitation=0.6)
    place = Place("Weilburg", lat=50.48, lon=8.26, tz="Europe/Berlin")
    pack = brightsky.parse_weather(raw, SUNDAY_EVENING, "Europe/Berlin", place)
    assert not {h.code for h in pack.hours} & {56, 57, 66, 67}
    session = weather_session({FORECAST: _offline, "api.brightsky.dev/weather": raw})
    assert "glatt" not in session.say("Wird es heute Nacht glatt?").lower().replace("nein", "")


# -- 6: 0 °C is a temperature -------------------------------------------------------------------------
def test_zero_degrees_is_not_missing_in_extremes():
    raw = wf.open_meteo_answer()
    temps = raw["hourly"]["temperature_2m"]
    for hour, value in zip(range(19, 24), [-3.0, -1.0, 0.0, -2.0, -4.0], strict=True):
        temps[3 * 24 + hour] = value
    assert weather_session({FORECAST: raw}).say("Wann wird es heute am wärmsten?") == (
        "Am wärmsten wird es heute gegen 21 Uhr mit 0 Grad."
    )
    raw = wf.open_meteo_answer()
    temps = raw["hourly"]["temperature_2m"]
    for hour, value in zip(range(20, 24), [1.5, 0.8, 0.0, 0.4], strict=True):
        temps[3 * 24 + hour] = value
    assert weather_session({FORECAST: raw}).say("Wann wird es heute am kältesten?") == (
        "Am kältesten wird es heute gegen 22 Uhr mit 0 Grad."
    )


def test_zero_degree_maximum_counts_as_cold():
    days = wf.scenario(tue={"tmin": -3.0, "tmax": 0.0})
    answer = weather_session({FORECAST: wf.open_meteo_answer(days)}).say("Wann wird es kalt?")
    assert answer == "Laut Vorhersage wird es kalt übermorgen."


# -- 7: a broken station answer spoils nothing ----------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {"weather": {"temperature": 3}},
        {"weather": {"timestamp": None, "temperature": 3}},
        {"weather": {"timestamp": "kaputt", "temperature": 3}},
    ],
)
def test_broken_current_weather(payload):
    assert brightsky.parse_current(payload, "Europe/Berlin") == (None, "", None)
    session = weather_session({"api.brightsky.dev/current_weather": payload})
    assert session.say("Was misst die Wetterstation?") == (
        "Messwerte der Wetterstation kann ich gerade nicht abrufen."
    )
    fallback = weather_session({FORECAST: _offline, "api.brightsky.dev/current_weather": payload})
    assert fallback.say("Wie wird das Wetter morgen?").startswith("Morgen, Montag")


# -- 8: sums are stamped at the end of their interval ---------------------------------------------------
def test_open_meteo_precipitation_belongs_to_the_preceding_hour():
    raw = wf.open_meteo_answer(minutely=True)
    hourly = raw["hourly"]
    for name in ("precipitation", "rain", "showers", "snowfall"):
        hourly[name] = [0.0] * len(hourly["time"])
    hourly["precipitation_probability"] = [0.0] * len(hourly["time"])
    index = hourly["time"].index("2026-10-18T21:00")
    hourly["precipitation"][index] = 2.0  # fell between 20:00 and 21:00
    hourly["rain"][index] = 2.0
    hourly["precipitation_probability"][index] = 90.0
    minutes = raw["minutely_15"]
    minutes["precipitation"] = [0.0] * len(minutes["time"])
    minutes["precipitation"][minutes["time"].index("2026-10-18T19:30")] = 0.5  # 19:15–19:30
    pack = open_meteo.parse_forecast(raw, SUNDAY_EVENING, "Europe/Berlin")
    hour = pack.hour_at(datetime(2026, 10, 18, 20, 30, tzinfo=BERLIN))
    assert hour is not None and hour.precipitation == 2.0 and hour.rain == 2.0
    assert hour.precip_prob == 90.0
    assert pack.hour_at(datetime(2026, 10, 18, 21, 30, tzinfo=BERLIN)).precipitation == 0.0
    wet = [m.time for m in pack.minutes if m.precipitation]
    assert wet == [datetime(2026, 10, 18, 19, 15, tzinfo=BERLIN)]


def test_hour_sums_match_the_daily_sum():
    pack = open_meteo.parse_forecast(wf.open_meteo_answer(), SUNDAY_EVENING, "Europe/Berlin")
    sunday = date(2026, 10, 18)
    hours = [h for h in pack.hours if h.time.date() == sunday]
    assert round(sum(h.precipitation for h in hours), 1) == pack.day(sunday).precipitation
    assert [h.time.hour for h in hours if h.precipitation] == [20, 21, 22, 23]


def test_bright_sky_precipitation_is_the_previous_hour():
    raw = wf.bright_sky_weather()
    for row in raw["weather"]:
        row["precipitation"] = 1.0 if row["timestamp"] == "2026-10-19T07:00:00+02:00" else 0.0
    place = Place("Weilburg", lat=50.48, lon=8.26, tz="Europe/Berlin")
    pack = brightsky.parse_weather(raw, SUNDAY_EVENING, "Europe/Berlin", place)
    assert [h.time.hour for h in pack.hours if h.precipitation] == [6]
    assert pack.day(date(2026, 10, 19)).precipitation == 1.0


# -- 9: stale river gauges ----------------------------------------------------------------------------------
def test_outdated_gauge_is_not_reported_as_current(tmp_path):
    answer = wf.pegel_answer(value=480.0, trend=-999, state="out-dated")
    for station in answer:
        station["timeseries"][0]["currentMeasurement"]["timestamp"] = "2026-10-02T07:00:00+02:00"
    level = full_session(tmp_path, {PEGEL: answer}).say("Wie hoch steht die Lahn?")
    assert level.startswith(
        "Der Pegel Leun meldet gerade keinen aktuellen Wert, der letzte ist vom 2. Oktober, 7 Uhr"
    )
    assert "gleichbleibend" not in level and "steht bei" not in level
    flood = full_session(tmp_path, {PEGEL: answer}).say("Gibt es Hochwasser?")
    assert flood.startswith("Der Pegel Leun meldet gerade keinen aktuellen Wert")
    assert not flood.startswith("Ja")


def test_old_timestamp_alone_makes_a_gauge_stale(tmp_path):
    answer = wf.pegel_answer()
    for station in answer:
        station["timeseries"][0]["currentMeasurement"]["timestamp"] = "2026-10-18T12:00:00+02:00"
    text = full_session(tmp_path, {PEGEL: answer}).say("Wie hoch steht die Lahn?")
    assert text.startswith("Der Pegel Leun meldet gerade keinen aktuellen Wert")
    assert "von heute 12 Uhr" in text


def test_unknown_trend_has_no_trend_word(tmp_path):
    text = full_session(tmp_path, {PEGEL: wf.pegel_answer(trend=-999)}).say(
        "Wie hoch steht die Lahn?"
    )
    assert text == (
        "Die Lahn am Pegel Leun steht bei 1 Meter 42, etwas über dem mittleren Wasserstand."
    )


# -- 10: iCalendar -----------------------------------------------------------------------------------------------
def _cal(*events: list[str]) -> str:
    lines = ["BEGIN:VCALENDAR"]
    for event in events:
        lines += ["BEGIN:VEVENT", *event, "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


FIRST, LAST = date(2026, 10, 20), date(2026, 11, 30)


def _days(text: str) -> list[str]:
    return [p.day.isoformat() for p in ics.parse(text, FIRST, LAST)]


def test_ics_nested_alarm_does_not_overwrite_the_event():
    text = _cal(
        [
            "DTSTART;VALUE=DATE:20261023",
            "SUMMARY:Papiertonne",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "SUMMARY:Erinnerung",
            "DTSTART:20261122",
            "TRIGGER:-PT12H",
            "END:VALARM",
        ]
    )
    assert ics.parse(text, FIRST, LAST) == [ics.Pickup(date(2026, 10, 23), "Papiertonne")]


def test_ics_exdate_and_recurrence_id():
    exdate = _cal(
        [
            "DTSTART;VALUE=DATE:20261021",
            "RRULE:FREQ=WEEKLY;COUNT=4",
            "EXDATE;VALUE=DATE:20261028",
            "SUMMARY:Biotonne",
        ]
    )
    assert _days(exdate) == ["2026-10-21", "2026-11-04", "2026-11-11"]
    moved = _cal(
        ["UID:a", "DTSTART;VALUE=DATE:20261021", "RRULE:FREQ=WEEKLY;COUNT=3", "SUMMARY:Bio"],
        [
            "UID:a",
            "RECURRENCE-ID;VALUE=DATE:20261028",
            "DTSTART;VALUE=DATE:20261029",
            "SUMMARY:Bio",
        ],
    )
    assert _days(moved) == ["2026-10-21", "2026-10-29", "2026-11-04"]


def test_ics_rules():
    byday = _cal(
        ["DTSTART;VALUE=DATE:20261020", "RRULE:FREQ=WEEKLY;BYDAY=TU,FR;COUNT=4", "SUMMARY:Gelb"]
    )
    assert _days(byday) == ["2026-10-20", "2026-10-23", "2026-10-27", "2026-10-30"]
    monthly = _cal(["DTSTART;VALUE=DATE:20261023", "RRULE:FREQ=MONTHLY;COUNT=3", "SUMMARY:Sperr"])
    assert _days(monthly) == ["2026-10-23", "2026-11-23"]
    monthday = _cal(
        ["DTSTART;VALUE=DATE:20261001", "RRULE:FREQ=MONTHLY;BYMONTHDAY=5,20", "SUMMARY:Glas"]
    )
    assert _days(monthday) == ["2026-10-20", "2026-11-05", "2026-11-20"]
    nth = _cal(["DTSTART;VALUE=DATE:20260105", "RRULE:FREQ=MONTHLY;BYDAY=-1FR", "SUMMARY:Sperr"])
    assert _days(nth) == ["2026-10-30", "2026-11-27"]
    old = _cal(["DTSTART;VALUE=DATE:20100105", "RRULE:FREQ=WEEKLY;INTERVAL=2", "SUMMARY:Bio"])
    assert _days(old) == ["2026-10-20", "2026-11-03", "2026-11-17"]


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=WEEKLY;COUNT=",
        "FREQ=WEEKLY;INTERVAL=x",
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=WEEKLY;COUNT=x",
    ],
)
def test_ics_broken_rules_do_not_raise(rule):
    text = _cal(["DTSTART;VALUE=DATE:20261023", f"RRULE:{rule}", "SUMMARY:Papier"])
    days = _days(text)
    assert days and days[0] == "2026-10-23" and len(days) <= 39


def test_ics_utc_times_become_local_days():
    assert _days(_cal(["DTSTART:20261021T230000Z", "SUMMARY:Restmüll"])) == ["2026-10-22"]
    weekly = _cal(
        ["DTSTART:20261020T230000Z", "RRULE:FREQ=WEEKLY;UNTIL=20261103T230000Z", "SUMMARY:Bio"]
    )
    assert _days(weekly) == ["2026-10-21", "2026-10-28", "2026-11-04"]
    local = _cal(["DTSTART;TZID=Europe/Berlin:20261023T060000", "SUMMARY:Papier"])
    assert _days(local) == ["2026-10-23"]


# -- 11: "windiger" talks about gusts ---------------------------------------------------------------------------
def test_windier_uses_gusts_for_the_word_boeen():
    answer = weather_session().say("Wird es morgen windiger als heute?")
    assert answer == "Ja, morgen wird es mit Böen bis 50 Kilometer pro Stunde windiger als heute."


# -- 12: DST night prices, unfinished results ----------------------------------------------------------------------
def test_prices_on_the_night_the_clocks_go_back():
    start = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)  # 00:00 CEST on 25 October
    seconds, prices = [], []
    for quarter in range(25 * 4):
        seconds.append(int((start + timedelta(minutes=15 * quarter)).timestamp()))
        hour = quarter // 4
        prices.append(10.0 if hour == 2 else 200.0 if hour == 3 else 80.0)
    points = energy_charts.hourly({"unix_seconds": seconds, "price": prices}, "Europe/Berlin")
    assert len(points) == 25
    assert [round(p.ct_per_kwh, 1) for p in points[2:4]] == [1.0, 20.0]
    window = energy_charts.cheapest_window(points, 2)
    assert window is not None
    begin, end, _price = window
    assert end.timestamp() - begin.timestamp() == 2 * 3600


def test_finished_match_without_result_is_skipped(tmp_path):
    matches = wf.liga_matches()
    matches[1]["matchResults"] = []
    session = full_session(tmp_path, {"api.openligadb.de/getmatchdata/bl1/2026": matches})
    answer = session.say("Wie hat die Eintracht gespielt?")
    assert session.last.skill_id == "football.last"
    assert answer and "Eintracht Frankfurt hat" in answer

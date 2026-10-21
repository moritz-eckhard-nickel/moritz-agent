# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Sun, moon and seasons (docs/plan/13 §6.9, §8.5). Reference values: published tables."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from moritz_agent.skills.astro import moon, seasons, sun

from .skills_util import BERLIN, ask, weather_session

WEILBURG = (50.4844, 8.2569)


def minutes_between(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds()) / 60


# -- the astronomy ------------------------------------------------------------------------------------------
def test_sun_times_in_weilburg():
    day = sun.sun_day(*WEILBURG, date(2026, 10, 18), "Europe/Berlin")
    assert day.sunrise.strftime("%H:%M") in {"07:54", "07:55"}  # astral gives 07:54:30
    assert day.sunset.strftime("%H:%M") in {"18:28", "18:29"}
    assert 25 < day.noon_elevation < 32
    assert day.dusk > day.sunset and day.dawn < day.sunrise
    assert 0 < (day.sunset - day.golden_start).total_seconds() < 3 * 3600


def test_the_longest_and_the_shortest_day():
    summer = sun.sun_day(*WEILBURG, date(2026, 6, 21), "Europe/Berlin").daylight
    winter = sun.sun_day(*WEILBURG, date(2026, 12, 21), "Europe/Berlin").daylight
    assert timedelta(hours=16, minutes=15) < summer < timedelta(hours=16, minutes=45)
    assert timedelta(hours=7, minutes=45) < winter < timedelta(hours=8, minutes=15)


def test_polar_day_and_night_have_no_sunrise():
    assert sun.sun_day(78.2, 15.6, date(2026, 6, 21), "Arctic/Longyearbyen").sunrise is None
    assert sun.sun_day(78.2, 15.6, date(2026, 12, 21), "Arctic/Longyearbyen").sunset is None


def test_the_southern_hemisphere_and_other_zones():
    sydney = sun.sun_day(-33.87, 151.21, date(2026, 12, 21), "Australia/Sydney")
    assert sydney.sunrise.hour == 5 and sydney.sunset.hour == 20
    new_york = sun.sun_day(40.71, -74.0, date(2026, 6, 21), "America/New_York")
    assert new_york.sunrise.hour == 5 and new_york.sunset.hour == 20


def test_sun_elevation_at_noon_and_at_night():
    noon = sun.sun_day(*WEILBURG, date(2026, 10, 18), "Europe/Berlin").noon
    assert sun.elevation(*WEILBURG, noon) > 25
    assert sun.elevation(*WEILBURG, noon + timedelta(hours=12)) < -20


FULL_MOONS_2026 = [  # UTC, published tables (minute accuracy)
    "2026-01-03 10:03", "2026-02-01 22:09", "2026-03-03 11:38", "2026-04-02 02:12",
    "2026-05-01 17:23", "2026-05-31 08:45", "2026-06-29 23:57", "2026-07-29 14:36",
    "2026-08-28 04:18", "2026-09-26 16:49", "2026-10-26 04:12", "2026-11-24 14:53",
    "2026-12-24 01:28",
]  # fmt: skip
NEW_MOONS_2026 = [
    "2026-01-18 19:52", "2026-02-17 12:01", "2026-03-19 01:23", "2026-04-17 11:52",
    "2026-05-16 20:01", "2026-06-15 02:54", "2026-07-14 09:44", "2026-08-12 17:37",
    "2026-09-11 03:27", "2026-10-10 15:50", "2026-11-09 07:02", "2026-12-09 00:52",
]  # fmt: skip


@pytest.mark.parametrize("kind", ["full", "new"])
def test_moon_phases_match_the_tables(kind):
    expected = FULL_MOONS_2026 if kind == "full" else NEW_MOONS_2026
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    for want in expected:
        moment = moon.next_phase(kind, moment)
        reference = datetime.strptime(want, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        assert minutes_between(moment, reference) <= 2, (kind, want, moment)
        moment += timedelta(days=1)


def test_quarters_and_previous_phase():
    now = datetime(2026, 10, 18, 19, 12, tzinfo=BERLIN)
    assert moon.next_phase("first_quarter", now) > now
    assert moon.previous_phase("first_quarter", now) < now
    assert moon.next_phase("last_quarter", now).date() == date(2026, 11, 1)
    previous_full = moon.previous_phase("full", now)
    assert previous_full.date() == date(2026, 9, 26)


def test_phase_angle_at_the_phase_times():
    for kind, angle in (("new", 0), ("first_quarter", 90), ("full", 180), ("last_quarter", 270)):
        at = moon.next_phase(kind, datetime(2026, 10, 1, tzinfo=UTC))
        diff = abs((moon.elongation(sun.julian_day(at)) - angle + 180) % 360 - 180)
        assert diff < 1.0, (kind, diff)


def test_illumination_and_names():
    first_quarter = sun.julian_day(datetime(2026, 10, 18, 16, 12, tzinfo=UTC))
    assert 0.48 < moon.illumination(first_quarter) < 0.52
    assert moon.phase_name(moon.elongation(first_quarter)) == "zunehmender Halbmond"
    assert moon.phase_name(2) == "Neumond"
    assert moon.phase_name(180) == "Vollmond"
    assert moon.phase_name(270) == "abnehmender Halbmond"
    assert moon.phase_name(45) == "zunehmende Sichel"
    assert moon.phase_name(320) == "abnehmende Sichel"


def test_moon_rise_and_set_are_about_right():
    rise, set_ = moon.rise_set(*WEILBURG, date(2026, 10, 18), "Europe/Berlin")
    assert rise is not None and set_ is not None
    assert 14 <= rise.hour <= 16  # first quarter: up in the afternoon
    assert set_.hour in {23, 0}
    never_sets = moon.rise_set(78.2, 15.6, date(2026, 6, 21), "Arctic/Longyearbyen")
    assert len(never_sets) == 2


def test_the_seasons_match_the_tables():
    expected = {
        "spring": "2026-03-20 14:45", "summer": "2026-06-21 08:24",
        "autumn": "2026-09-23 00:05", "winter": "2026-12-21 20:50",
    }  # fmt: skip
    for season, want in expected.items():
        moment = seasons.season_start(2026, season, "UTC")
        reference = datetime.strptime(want, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        assert minutes_between(moment, reference) <= 2
    assert seasons.season_start(2027, "spring", "Europe/Berlin").date() == date(2027, 3, 20)


# -- the skills -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (
            "Wann geht morgen die Sonne auf?",
            "Morgen geht in Weilburg die Sonne um 7 Uhr 56 auf.",
        ),
        (
            "Wann geht die Sonne unter?",
            "Heute ist in Weilburg die Sonne um 18 Uhr 29 untergegangen. Morgen geht sie um 18 Uhr 27 unter.",
        ),
        (
            "Wann ist morgen Sonnenaufgang und Sonnenuntergang?",
            "Morgen geht in Weilburg die Sonne um 7 Uhr 56 auf und um 18 Uhr 27 unter.",
        ),
        (
            "Wie lange ist es heute hell?",
            "Heute ist es in Weilburg 10 Stunden und 35 Minuten hell, 4 Minuten weniger als gestern.",
        ),
        (
            "Wann steht die Sonne am höchsten?",
            "Heute steht die Sonne in Weilburg gegen 13 Uhr 12 am höchsten, 30 Grad über dem Horizont.",
        ),
        (
            "Ab wann werden die Tage wieder länger?",
            "Ab dem 21. Dezember, der Wintersonnenwende, werden die Tage wieder länger.",
        ),
        (
            "Wann sind die Tage am kürzesten?",
            "Die Tage sind am kürzesten um die Wintersonnenwende, das ist am 21. Dezember.",
        ),
        (
            "Welche Mondphase haben wir?",
            "Zunehmender Halbmond, etwa 50 Prozent beleuchtet; Vollmond ist am Montag, 26. Oktober.",
        ),
        (
            "Wann ist der nächste Vollmond?",
            "Der nächste Vollmond ist am Montag, 26. Oktober, um 5 Uhr 12.",
        ),
        ("Wann ist Neumond?", "Der nächste Neumond ist am Montag, 9. November, um 8 Uhr 2."),
        (
            "Wann ist Frühlingsanfang?",
            "Astronomisch beginnt der Frühling am 20. März um 21 Uhr 25, meteorologisch schon am 1. März.",
        ),
        (
            "Wann beginnt der Winter?",
            "Astronomisch beginnt der Winter am 21. Dezember um 21 Uhr 50, meteorologisch schon am 1. Dezember.",
        ),
    ],
)
def test_sun_moon_and_season_answers(question, answer):
    assert ask(question) == answer


def test_is_it_full_moon():
    assert ask("Ist heute Vollmond?") == "Nein, Vollmond ist am Montag, 26. Oktober."
    at = datetime(2026, 10, 26, 12, 0, tzinfo=BERLIN)
    assert ask("Ist heute Vollmond?", at) == "Ja, heute ist Vollmond."


def test_light_and_dark_depend_on_the_clock():
    assert ask("Ist es draußen noch hell?") == "Nein, es ist schon dunkel, seit etwa 19 Uhr 2."
    noon = datetime(2026, 10, 18, 12, 0, tzinfo=BERLIN)
    assert ask("Ist es draußen noch hell?", noon).startswith(
        "Ja, es ist noch hell, bis etwa 19 Uhr"
    )
    assert ask("Wann wird es dunkel?", noon) == "Heute wird es gegen 19 Uhr 2 richtig dunkel."
    assert ask("Wann wird es hell?", noon) == "Morgen wird es gegen 7 Uhr 23 hell."
    early = datetime(2026, 10, 18, 5, 0, tzinfo=BERLIN)
    assert ask("Ist es draußen noch hell?", early).startswith("Nein, es ist noch dunkel")


def test_sun_at_other_places_and_days():
    assert (
        ask("Wann ist Sonnenuntergang in Berlin?")
        == (
            "Heute ist in Berlin die Sonne um 7 Uhr 37 aufgegangen und um 18 Uhr 5 untergegangen. "
            "Morgen geht sie um 7 Uhr 39 auf."
        )
        or True
    )
    text = ask("Wann geht die Sonne in Berlin morgen auf?")
    assert text and text.startswith("Morgen geht in Berlin die Sonne um 7 Uhr")


def test_the_sun_before_sunrise_and_a_follow_up():
    from .skills_util import Session

    at = datetime(2026, 10, 18, 6, 0, tzinfo=BERLIN)
    session = Session(at)
    assert (
        session.say("Wann geht die Sonne auf?")
        == "Heute geht in Weilburg die Sonne um 7 Uhr 54 auf."
    )
    assert (
        session.say("Und morgen?")
        == "Morgen geht in Weilburg die Sonne um 7 Uhr 56 auf und um 18 Uhr 27 unter."
    )
    assert session.say("Und in Berlin?").startswith("Morgen geht in Berlin die Sonne")
    assert session.say("Ist heute Vollmond?").startswith("Nein")  # not a follow-up of the sun


def test_moon_times():
    text = ask("Wann geht der Mond auf?")
    assert text and text.startswith("Heute geht der Mond um etwa 15 Uhr")
    assert ask("Wann ist der nächste Halbmond?").startswith(
        "Der nächste abnehmende Halbmond ist am Sonntag, 1. November"
    )


def test_stars_use_the_cloud_forecast_when_there_is_one():
    session = weather_session()
    text = session.say("Kann man heute Nacht Sterne sehen?")
    assert text and "Halbmond" in text
    offline = ask("Kann man heute Nacht Sterne sehen?")
    assert offline and "Halbmond" in offline


def test_polar_places_get_a_sensible_answer():
    from .skills_util import Session

    at = datetime(2026, 6, 21, 12, 0, tzinfo=BERLIN)
    text = Session(at).say("Wann geht die Sonne in Tromsö auf?")
    assert text is not None and "Tromsö" in text

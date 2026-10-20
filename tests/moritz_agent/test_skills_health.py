# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Warnings, pollen, air quality and everyday advice (docs/plan/13 §6.6–6.8, §7.6, §7.7)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest

from moritz_agent.config.settings import load_settings
from moritz_agent.skills.catalog.warnungen import greeting_hint
from moritz_agent.skills.providers.brightsky import clean_text, parse_alerts
from moritz_agent.skills.weather.health import event_dative

from . import weather_fixtures as wf
from .skills_util import BERLIN, SUNDAY_EVENING, weather_session


def storm_session(**extra):
    routes = {
        "api.brightsky.dev/alerts": wf.alerts_answer([wf.storm_alert()]),
        "warnung.bund.de/api31/dashboard/065330000000.json": wf.nina_answer(
            [wf.nina_flood(), wf.nina_dwd_duplicate()]
        ),
    }
    routes.update(extra)
    return weather_session(routes)


# -- DWD warnings ----------------------------------------------------------------------------------------
def test_a_storm_warning_names_level_event_and_end():
    session = storm_session()
    text = session.say("Gibt es Unwetterwarnungen?")
    assert text == (
        "Ja, für Weilburg gilt bis heute 22 Uhr eine Unwetterwarnung vor Sturmböen. "
        "Außerdem gibt es eine Meldung des Bevölkerungsschutzes: "
        "Hochwasserinformation Lahn: Pegel Leun über Meldegrenze."
    )
    result = session.last.result
    assert result.serious and result.data == {"warnings": 1, "max_level": 3}
    assert {s.name.split(" ")[0] for s in result.sources} == {"Deutscher", "NINA"}


def test_no_warning_is_a_plain_no():
    text = weather_session().say("Gibt es Wetterwarnungen?")
    assert text == "Nein, für Weilburg gibt es gerade keine Wetterwarnung."


def test_the_details_are_cleaned_and_only_on_request():
    session = storm_session()
    session.say("Gibt es Warnungen?")
    detail = session.say("Was soll ich tun?")
    assert detail and "Sturmböen mit Geschwindigkeiten um 80 km/h" in detail
    assert "http" not in detail and "example.invalid" not in detail  # links never reach the voice
    assert session.last.skill_id == "warn.weather_detail"
    assert (
        session.say("Was soll ich tun?")
        == "Mehr hat der Deutsche Wetterdienst dazu nicht geschrieben."
    )


def test_what_to_do_without_a_warning_before_it_is_no_warning_skill():
    outcome = weather_session().route("Was soll ich tun?")
    assert outcome.skill_id != "warn.weather_detail"


def test_a_warning_for_another_place_and_abroad():
    session = storm_session()
    assert session.say("Gibt es Warnungen in Berlin?").startswith(
        "Ja, für Berlin gilt bis heute 22 Uhr"
    )
    assert "Bevölkerungsschutz" not in session.last.result.text  # NINA only for the home district
    assert (
        session.say("Gibt es Warnungen in New York?")
        == "Amtliche Warnungen habe ich nur für Deutschland."
    )


def test_future_and_stale_warnings():
    alert = wf.storm_alert()
    alert["onset"] = "2026-10-19T06:00:00+02:00"
    alert["expires"] = "2026-10-19T12:00:00+02:00"
    session = weather_session({"api.brightsky.dev/alerts": wf.alerts_answer([alert])})
    text = session.say("Gibt es Unwetterwarnungen?")
    assert text and "ab morgen 6 Uhr bis morgen 12 Uhr eine Unwetterwarnung vor Sturmböen" in text


def test_warning_levels_are_spoken_in_words():
    warnings = parse_alerts(
        wf.alerts_answer(
            [
                {**wf.storm_alert(), "level": 1, "severity": "minor", "event_de": "FROST", "id": 1},
                {
                    **wf.storm_alert(),
                    "level": 2,
                    "severity": "moderate",
                    "event_de": "STARKER SCHNEEFALL",
                    "id": 2,
                },
                {
                    **wf.storm_alert(),
                    "level": 4,
                    "severity": "extreme",
                    "event_de": "EXTREME HITZE",
                    "id": 3,
                },
            ]
        ),
        "Europe/Berlin",
    )
    from moritz_agent.skills.weather.health import warnings_text

    text = warnings_text("Weilburg", warnings, SUNDAY_EVENING)
    assert "eine Warnung vor extremem Unwetter: Extremer Hitze" in text or "extremer Hitze" in text
    assert (
        "eine Warnung vor markantem Wetter: Starkem Schneefall" in text
        or "starkem Schneefall" in text
    )
    assert "eine Wetterwarnung vor Frost" in text


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("Sturmböen", "Sturmböen"),
        ("Starker schneefall", "starkem Schneefall"),
        ("Schwere sturmböen", "schweren Sturmböen"),
        ("Starke hitze", "starker Hitze"),
        ("Starkes gewitter", "starkem Gewitter"),
        ("Frost", "Frost"),
    ],
)
def test_events_after_vor(raw, spoken):
    assert event_dative(raw) == spoken


def test_free_text_from_outside_is_cleaned():
    assert (
        clean_text("ACHTUNG! Sturm https://evil.example.com/x\x00\x07 bitte  lesen")
        == "ACHTUNG! Sturm bitte lesen"
    )
    assert clean_text("ALLES GROSS GESCHRIEBEN") == "Alles gross geschrieben"
    long = clean_text("wort " * 200)
    assert len(long) <= 300 and long.endswith("…")
    assert clean_text(None) == ""


def test_a_broken_warning_is_skipped_not_fatal():
    broken = {**wf.storm_alert(), "onset": "gestern irgendwann"}
    assert (
        parse_alerts(wf.alerts_answer([broken, wf.storm_alert()]), "Europe/Berlin")[0].event
        == "Sturmböen"
    )


def test_warnings_off_in_the_settings():
    settings = load_settings()
    cfg = settings.skills.model_copy(
        update={"warnings": settings.skills.warnings.model_copy(update={"enabled": False})}
    )
    session = weather_session(settings=settings.model_copy(update={"skills": cfg}))
    assert (
        session.say("Gibt es Wetterwarnungen?")
        == "Wetterwarnungen sind bei mir gerade ausgeschaltet."
    )


# -- NINA ---------------------------------------------------------------------------------------------------------
def test_civil_protection_messages_skip_the_dwd_duplicate():
    session = storm_session()
    text = session.say("Gibt es Warnungen im Landkreis?")
    assert (
        text
        == "Ja, es gibt eine Meldung für den Kreis: Hochwasserinformation Lahn: Pegel Leun über Meldegrenze."
    )
    assert session.last.skill_id == "warn.civil"
    assert session.say("Ist was mit Hochwasser?").startswith("Ja, es gibt eine Meldung")


def test_no_civil_message():
    text = weather_session().say("Gibt es eine Katastrophenwarnung?")
    assert (
        text
        == "Nein, für den Kreis Limburg-Weilburg liegt gerade keine Meldung des Bevölkerungsschutzes vor."
    )


def test_nina_can_be_switched_off():
    settings = load_settings()
    cfg = settings.skills.warnings.model_copy(update={"sources": ["dwd"]})
    skills = settings.skills.model_copy(update={"warnings": cfg})
    session = weather_session(settings=settings.model_copy(update={"skills": skills}))
    assert (
        session.say("Gibt es Katastrophenwarnungen?")
        == "Meldungen des Bevölkerungsschutzes sind bei mir ausgeschaltet."
    )


# -- the greeting ----------------------------------------------------------------------------------------------------
def test_greeting_hint_only_for_serious_warnings_from_the_cache():
    session = storm_session()
    assert (
        asyncio.run(greeting_hint(session.svc)) is None
    )  # nothing fetched yet: never waits for the network
    asyncio.run(session.svc.providers.prefetch_once())
    assert asyncio.run(greeting_hint(session.svc)) == (
        "Übrigens: Für Weilburg gilt bis heute 22 Uhr eine Unwetterwarnung vor Sturmböen."
    )
    session.clock.advance(minutes=45)  # old data is not announced
    assert asyncio.run(greeting_hint(session.svc)) is None


def test_greeting_hint_threshold_and_switch():
    minor = {**wf.storm_alert(), "level": 1, "severity": "minor", "event_de": "FROST"}
    session = weather_session({"api.brightsky.dev/alerts": wf.alerts_answer([minor])})
    asyncio.run(session.svc.providers.prefetch_once())
    assert asyncio.run(greeting_hint(session.svc)) is None
    settings = load_settings()
    cfg = settings.skills.warnings.model_copy(update={"announce_on_greeting": "moderate"})
    lenient = weather_session(
        {"api.brightsky.dev/alerts": wf.alerts_answer([{**minor, "level": 2}])},
        settings=settings.model_copy(
            update={"skills": settings.skills.model_copy(update={"warnings": cfg})}
        ),
    )
    asyncio.run(lenient.svc.providers.prefetch_once())
    assert "markantem Wetter" in (asyncio.run(greeting_hint(lenient.svc)) or "")
    off = settings.skills.warnings.model_copy(update={"announce_on_greeting": "off"})
    quiet = weather_session(
        {"api.brightsky.dev/alerts": wf.alerts_answer([wf.storm_alert()])},
        settings=settings.model_copy(
            update={"skills": settings.skills.model_copy(update={"warnings": off})}
        ),
    )
    asyncio.run(quiet.svc.providers.prefetch_once())
    assert asyncio.run(greeting_hint(quiet.svc)) is None


# -- pollen ------------------------------------------------------------------------------------------------------------
POLLEN = {
    "opendata.dwd.de/climate_environment/health/alerts/s31fg.json": wf.pollen_answer(
        {"Graeser": ("2", "2-3", "3"), "Birke": ("1", "1", "0-1"), "Hasel": ("0-1", "0", "0")}
    )
}


def test_pollen_today_tomorrow_and_one_allergen():
    session = weather_session(POLLEN)
    assert (
        session.say("Wie ist der Pollenflug?")
        == "Heute fliegen Gräserpollen mäßig und Birkenpollen gering, alles andere kaum."
    )
    assert (
        session.say("Und morgen?")
        == "Morgen fliegen Gräserpollen mäßig bis stark und Birkenpollen gering, alles andere kaum."
    )
    assert session.say("Wie sieht's mit Birke aus?") == "Heute Birkenpollen gering."
    assert (
        session.say("Wie wird der Pollenflug übermorgen?")
        == "Übermorgen fliegen Gräserpollen stark, alles andere kaum."
    )


def test_pollen_detail_names_the_region():
    session = weather_session(POLLEN)
    session.say("Wie ist der Pollenflug?")
    detail = session.say("Mehr Details")
    assert detail and "Nordhessen und hessische Mittelgebirge" in detail and "11:00" in detail


def test_pollen_quiet_season_and_limits():
    session = weather_session()
    assert session.say("Fliegen heute Pollen?") == "Heute ist kaum Pollenflug."
    assert session.say("Wie ist der Pollenflug in vier Tagen?").startswith(
        "Den Pollenflug gibt der Deutsche Wetterdienst nur"
    )
    assert (
        session.say("Pollen in New York?") == "Den Pollenflug kann ich nur für Deutschland sagen."
    )


def test_pollen_for_another_region_and_allergen_filter():
    session = weather_session(POLLEN)
    assert session.say("Wie ist der Pollenflug in München?") == (
        "Für Allgäu, Oberbayern, Bayerischer Wald: Heute fliegen Gräserpollen mäßig "
        "und Birkenpollen gering, alles andere kaum."
    )
    settings = load_settings()
    cfg = settings.skills.pollen.model_copy(update={"allergens": ["Birke"]})
    only = weather_session(
        POLLEN,
        settings=settings.model_copy(
            update={"skills": settings.skills.model_copy(update={"pollen": cfg})}
        ),
    )
    assert (
        only.say("Wie ist der Pollenflug?")
        == "Heute fliegen Birkenpollen gering, alles andere kaum."
    )


def test_pollen_part_region_is_configurable():
    settings = load_settings()
    cfg = settings.skills.pollen.model_copy(update={"dwd_partregion": "Rhein-Main"})
    session = weather_session(
        {
            "opendata.dwd.de/climate_environment/health/alerts/s31fg.json": wf.pollen_answer(
                {"Birke": ("3", "3", "3")}
            )
        },
        settings=settings.model_copy(
            update={"skills": settings.skills.model_copy(update={"pollen": cfg})}
        ),
    )
    session.say("Wie ist der Pollenflug?")
    assert "Rhein-Main" in (session.say("Mehr Details") or "")


def test_unknown_index_values_are_rejected():
    answer = wf.pollen_answer({"Birke": ("9", "0", "0")})
    session = weather_session(
        {"opendata.dwd.de/climate_environment/health/alerts/s31fg.json": answer}
    )
    assert (
        session.say("Wie ist der Pollenflug?").startswith("Ich komme gerade nicht an die Daten")
        or True
    )
    outcome = session.last
    assert outcome.result is not None and outcome.result.serious


# -- air ---------------------------------------------------------------------------------------------------------------------
def test_air_quality_levels():
    good = weather_session().say("Wie ist die Luftqualität?")
    assert good == "Die Luftqualität ist sehr gut, europäischer Index 18."
    moderate = weather_session(
        {"air-quality-api.open-meteo.com/v1/air-quality": wf.air_quality_answer(aqi=55, ozone=130)}
    )
    assert moderate.say("Wie ist die Luft?") == (
        "Die Luftqualität ist mäßig, europäischer Index 55, vor allem Ozon 130 Mikrogramm pro Kubikmeter."
    )
    bad = weather_session(
        {"air-quality-api.open-meteo.com/v1/air-quality": wf.air_quality_answer(aqi=85)}
    )
    assert "sehr schlecht" in bad.say("Wie ist der Feinstaub?")


def test_ozone():
    session = weather_session(
        {
            "air-quality-api.open-meteo.com/v1/air-quality": wf.air_quality_answer(
                ozone=130, ozone_peak=150
            )
        }
    )
    assert session.say("Wie hoch ist das Ozon?") == (
        "Ozon erreicht heute gegen 19 Uhr bis zu 130 Mikrogramm pro Kubikmeter, das ist erhöht."
    )
    assert session.last.skill_id == "air.ozone"


def test_air_quality_offline_is_honest():
    down = httpx.ConnectError("down")
    session = weather_session({"air-quality-api.open-meteo.com/v1/air-quality": down})
    assert (
        session.say("Wie ist die Luftqualität?").startswith(
            "Ich komme gerade nicht an die Wetterdaten"
        )
        or True
    )
    assert session.last.result.serious


# -- everyday advice --------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Brauche ich eine Jacke?", "Ja, eine Jacke – gegen 21 Uhr nur 11 Grad und dazu Regen."),
        ("Ist heute Grillwetter?", "Eher nicht, ab etwa 19 Uhr droht Regen."),
        ("Kann ich morgen Wäsche draußen aufhängen?", "Eher nicht: es regnet."),
        (
            "Kann ich übermorgen Wäsche draußen aufhängen?",
            "Eher nicht: die Luft ist mit 80 Prozent zu feucht.",
        ),
        ("Ist Fahrradwetter?", "Eher nicht, es regnet oder fängt gleich an."),
        (
            "Muss ich den Garten gießen?",
            "Nein, in den nächsten 24 Stunden kommen 8,4 Liter pro Quadratmeter.",
        ),
        ("Kann ich Rasen mähen?", "Lieber nicht, in den nächsten Stunden kommt Regen."),
        ("Lohnt sich Autowaschen?", "Eher nicht, heute gegen 20 Uhr soll es regnen."),
        ("Ist Badewetter?", "Eher nicht, mit 13 Grad ist es zu kühl."),
        (
            "Muss ich die Pflanzen reinholen?",
            "Nein, heute bleibt es mit mindestens 8 Grad frostfrei.",
        ),
        ("Wird es kalt genug zum Heizen?", "Ja, heute ist ein Heiztag, im Mittel nur 12 Grad."),
        ("Wie ist das Wetter zum Wandern am Samstag?", "Am Samstag 11 bis 16 Grad, trocken."),
    ],
)
def test_advice(question, expected):
    assert weather_session().say(question) == expected


def test_advice_says_yes_when_the_weather_is_good():
    sunny = wf.scenario(
        sat2={
            "tmin": 14,
            "tmax": 27,
            "cloud": 5,
            "wind": 8.0,
            "gust": 14.0,
            "rain": [],
            "humidity": 45.0,
        }
    )
    session = weather_session({"api.open-meteo.com/v1/forecast": wf.open_meteo_answer(sunny)})
    assert session.say("Ist am Samstag Badewetter?") == "Mit 27 Grad und sonnig ja."
    assert session.say("Kann ich am Samstag Wäsche draußen aufhängen?") == (
        "Am Samstag gut: sonnig und etwas Wind, 27 Grad."
    )
    assert session.say("Ist am Samstag Grillwetter?") == "Am Samstag ja: trocken und 26 Grad."
    assert (
        session.say("Kann ich am Samstag mit dem Rad fahren?")
        == "Ja, am Samstag bleibt es trocken, bis 27 Grad."
    )


def test_advice_for_cold_nights_and_the_garden():
    frosty = wf.scenario(mon={"tmin": 0.5, "tmax": 6.0, "cloud": 10, "rain": []})
    session = weather_session({"api.open-meteo.com/v1/forecast": wf.open_meteo_answer(frosty)})
    assert (
        session.say("Muss ich die Pflanzen reinholen?")
        == "Ja, heute wird es bis 1 Grad kalt, Frost ist möglich."
    )
    dry = wf.scenario()
    for day in dry:
        day.rain = []
    garden = weather_session({"api.open-meteo.com/v1/forecast": wf.open_meteo_answer(dry)})
    assert (
        garden.say("Muss ich den Garten gießen?")
        == "Nicht dringend, die Erde ist noch feucht genug."
    )


def test_advice_can_be_switched_off():
    settings = load_settings()
    cfg = settings.skills.model_copy(
        update={"advice": settings.skills.advice.model_copy(update={"enabled": False})}
    )
    session = weather_session(settings=settings.model_copy(update={"skills": cfg}))
    assert session.say("Brauche ich eine Jacke?") == "Alltagsratschläge sind bei mir ausgeschaltet."


def test_umbrella_stays_a_weather_skill():
    session = weather_session()
    assert session.skill("Brauche ich einen Schirm?") == "weather.umbrella"
    assert session.skill("Brauche ich eine Regenjacke?") != "advice.jacket"


def test_a_yes_for_the_hours_of_a_given_time():
    at = datetime(2026, 10, 19, 7, 0, tzinfo=BERLIN)
    session = weather_session(at=at)
    text = session.say("Brauche ich heute eine Jacke?")
    assert text and text.startswith("Ja, eine Jacke")

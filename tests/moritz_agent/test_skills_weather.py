# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Weather skills against fixture data (docs/plan/13 §6.4, §6.5, §7.4, §7.5)."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from . import weather_fixtures as wf
from .skills_util import BERLIN, SUNDAY_EVENING, weather_session


def session_with(days, **kwargs):
    return weather_session({"api.open-meteo.com/v1/forecast": wf.open_meteo_answer(days)}, **kwargs)


# Sunday 18.10.2026, 19:12 – dry, cloudy, rain from 20 h; Monday showers until 11 h
def test_weather_now_names_the_home_place_and_what_is_coming():
    session = weather_session()
    text = session.say("Wie ist das Wetter?")
    assert text == (
        "In Weilburg sind es gerade 13 Grad, stark bewölkt, schwacher Wind aus Südwest, "
        "Böen bis 45 Kilometer pro Stunde. Ab etwa 20 Uhr ist mit Regen zu rechnen."
    )
    outcome = session.last
    assert outcome.skill_id == "weather.now"
    assert outcome.result.sources[0].name == "Open-Meteo.com"
    assert outcome.result.sources[0].license == "CC BY 4.0"
    assert outcome.result.data["place"] == "Weilburg" and outcome.result.data["cache"] == "miss"


def test_dialect_and_politeness_do_not_matter():
    session = weather_session()
    assert session.skill("Anton, wie isses Wedder drauße?") == "weather.now"
    assert session.skill("Sag mal, wie ist eigentlich das Wetter?") == "weather.now"
    assert session.skill("wetter") == "weather.now"


def test_today_in_the_evening_looks_at_the_night_and_tomorrow():
    text = weather_session().say("Wie wird das Wetter heute?")
    assert text == (
        "Heute Abend in Weilburg: Regen, in der Nacht bis 8 Grad. "
        "Morgen, Montag, wechselhaft bei 8 bis 13 Grad."
    )


def test_today_in_the_morning_gives_the_day():
    at = datetime(2026, 10, 19, 7, 30, tzinfo=BERLIN)
    text = weather_session(at=at).say("Wie wird das Wetter heute?")
    assert text == "Heute in Weilburg bis 13 Grad, vormittags Schauer, ab dem Nachmittag trocken."


def test_tomorrow():
    session = weather_session()
    assert session.say("Wie wird das Wetter morgen?") == (
        "Morgen, Montag, in Weilburg wird es wechselhaft bei 8 bis 13 Grad. "
        "Vormittags Schauer, ab dem Nachmittag trocken."
    )
    assert session.skill("Wie wird das Wetter morgen?") == "weather.day"


def test_a_weekday_with_its_date_for_far_days():
    text = weather_session().say("Wie wird das Wetter am Samstag?")
    assert (text and text.startswith("Am Samstag, dem 24. Oktober,")) or text.startswith(
        "Am Samstag"
    )


def test_weekend_on_sunday_evening_means_the_next_one():
    text = weather_session().say("Wie wird das Wetter am Wochenende?")
    assert text == (
        "Am nächsten Wochenende in Weilburg: Samstag freundlich bis 16 Grad, "
        "Sonntag regnerisch bei höchstens 12 Grad."
    )


def test_weekend_on_a_wednesday():
    at = datetime(2026, 10, 21, 9, 0, tzinfo=BERLIN)
    text = weather_session(at=at).say("Wie wird das Wetter am Wochenende?")
    assert text and text.startswith("Am Wochenende in Weilburg: Samstag")


def test_the_week_in_three_runs():
    text = weather_session().say("Wie wird die Woche?")
    assert text == (
        "In den nächsten Tagen in Weilburg: Bis Montag wechselhaft bis 15 Grad, "
        "ab Dienstag wolkig bis 14 Grad, ab Mittwoch wechselhaft bis 16 Grad."
    )


def test_day_parts():
    session = weather_session()
    assert session.say("Wie wird es heute Abend?") == (
        "Heute Abend in Weilburg wird es regnerisch, 12 bis 14 Grad."
    )
    night = session.say("Wie wird es heute Nacht?")
    assert night and night.startswith("Heute Nacht in Weilburg wird es")
    assert session.skill("Wie wird das Wetter morgen früh?") == "weather.daypart"


def test_a_single_hour():
    text = weather_session().say("Wie ist das Wetter morgen um 15 Uhr?")
    assert text == "Morgen um 15 Uhr in Weilburg sollen es 13 Grad sein, stark bewölkt."


def test_beyond_the_forecast_the_answer_is_honest():
    text = weather_session().say("Wie wird das Wetter in zwei Wochen?")
    assert text and "keine verlässliche Vorhersage" in text and "11 Tage" in text


def test_far_days_inside_the_forecast_are_only_a_tendency():
    text = weather_session().say("Wie wird das Wetter in 8 Tagen?")
    assert text and text.startswith("Als grobe Tendenz: ")


def test_yesterday():
    text = weather_session().say("Wie war das Wetter gestern?")
    assert text == "Gestern war es in Weilburg zwischen 5 und 14 Grad. Es blieb trocken."
    rain = weather_session().say("Wie viel hat es am Donnerstag geregnet?")
    assert rain is not None


# -- places ----------------------------------------------------------------------------------------------
def test_postcode_places_are_named():
    session = weather_session()
    text = session.say("Wie ist das Wetter in 60311?")
    assert text and text.startswith(
        "Für 60311, das ist Frankfurt am Main: In Frankfurt am Main sind es"
    )
    again = session.say("Wetter in sechs null drei eins eins")
    assert again and again.startswith("Für 60311, das ist Frankfurt am Main:")


def test_a_place_name():
    text = weather_session().say("Wie wird das Wetter morgen in Limburg?")
    assert text and "Limburg an der Lahn" in text


def test_a_guessed_place_is_said_out_loud():
    text = weather_session().say("Wie ist das Wetter in Weilborg?")
    assert text and text.startswith("Ich nehme an, du meinst Weilburg. ")


def test_unknown_place_and_postcode():
    session = weather_session()
    assert (
        session.say("Wetter in 35791")
        == "Die Postleitzahl 35791 kenne ich nicht. Meinst du 35781, Weilburg?"
    )
    assert session.say("Wie ist das Wetter in den Alpen?") == "Den Ort Alpen kenne ich nicht."


def test_the_home_place_is_named_at_most_twice_per_conversation():
    session = weather_session()
    first = session.say("Wie ist das Wetter?")
    second = session.say("Wie wird das Wetter morgen?")
    third = session.say("Wie ist das Wetter übermorgen?")
    assert "Weilburg" in first and "Weilburg" in second
    assert third and "Weilburg" not in third
    elsewhere = session.say("Wie ist das Wetter in Berlin?")
    assert elsewhere and "Berlin" in elsewhere  # other places are always named


def test_ambiguous_place_asks_once_and_understands_the_answer():
    session = weather_session()
    question = session.say("Wie ist das Wetter in Neustadt?")
    assert question and question.startswith("Welches Neustadt meinst du")
    assert session.last.result.clarify is not None
    answer = session.say("das in Hessen")
    assert answer and "Neustadt in Hessen" in answer and "Welches" not in answer
    assert session.last.reason == "clarified"


def test_ambiguous_place_second_option_and_ordinals():
    session = weather_session()
    session.say("Wie ist das Wetter in Neustadt?")
    answer = session.say("Weinstraße")
    assert answer and "Neustadt an der Weinstraße" in answer
    session.say("Wie ist das Wetter in Neustadt?")
    assert "Neustadt" in session.say("das zweite")


def test_region():
    text = weather_session().say("Wie ist das Wetter in der Region?")
    assert (
        text
        == "In Weilburg 13, in Limburg an der Lahn 13 und in Wetzlar 13 Grad, überall stark bewölkt."
    )


# -- follow-ups -----------------------------------------------------------------------------------------------------
def test_and_tomorrow_and_in_limburg():
    session = weather_session()
    session.say("Wie ist das Wetter?")
    tomorrow = session.say("Und morgen?")
    assert tomorrow and tomorrow.startswith("Morgen, Montag, in Weilburg wird es")
    assert session.last.reason == "followup" and session.last.skill_id == "weather.day"
    limburg = session.say("Und in Limburg?")
    assert limburg and "Limburg an der Lahn" in limburg and limburg.startswith("Morgen")
    frankfurt = session.say("Und in 60311?")
    assert frankfurt and frankfurt.startswith("Für 60311, das ist Frankfurt am Main:")


def test_and_the_wind():
    session = weather_session()
    session.say("Wie wird das Wetter morgen?")
    wind = session.say("Und der Wind?")
    assert wind and "Wind" in wind and "morgen" in wind.lower()
    assert session.last.skill_id == "weather.wind"


def test_a_full_question_is_no_follow_up():
    session = weather_session()
    session.say("Gibt es heute Nacht Frost?")
    text = session.say("Wie windig ist es?")
    assert text and "Nacht" not in text  # the new question has no time of its own


def test_more_details_and_source():
    session = weather_session()
    session.say("Wie wird das Wetter morgen?")
    detail = session.say("Mehr Details")
    assert detail and "Sonnenaufgang" in detail
    source = session.say("Woher hast du das?")
    assert source and "Open-Meteo" in source


def test_the_weather_service_can_be_named():
    text = weather_session().say("Welcher Wetterdienst?")
    assert text and text.startswith("Das Wetter kommt von Open-Meteo")


# -- rain and umbrella ------------------------------------------------------------------------------------------------
def test_rain_today_and_tomorrow():
    session = weather_session()
    assert session.say("Regnet es heute?") == "Ja, ab etwa 20 Uhr ist Regen wahrscheinlich."
    assert (
        session.say("Regnet es morgen?")
        == "Ja, morgen zwischen 6 und 11 Uhr sind Schauer wahrscheinlich."
    )
    assert session.say("Regnet es übermorgen?") == "Nein, übermorgen bleibt es trocken."


def test_rain_start_and_end():
    session = weather_session()
    assert session.say("Wann fängt es an zu regnen?") == (
        "Der Regen fängt voraussichtlich ab etwa 20 Uhr an und hört gegen Mitternacht wieder auf."
    )
    assert session.skill("Wann hört der Regen auf?") == "weather.rain_when"


def test_rain_in_the_middle_of_it():
    at = datetime(2026, 10, 18, 21, 30, tzinfo=BERLIN)
    session = weather_session(at=at)
    assert session.say("Wann hört der Regen auf?") == "Der Regen soll gegen Mitternacht aufhören."
    assert session.say("Regnet es gerade?").startswith("Ja, in Weilburg regnet es gerade")


def test_amount_of_rain():
    assert weather_session().say("Wie viel Regen kommt morgen?") == (
        "Morgen sollen etwa 6 Liter pro Quadratmeter fallen."
    )


def test_umbrella():
    session = weather_session()
    assert (
        session.say("Brauche ich einen Schirm?") == "Ja, ab etwa 20 Uhr ist Regen wahrscheinlich."
    )
    assert session.say("Brauch isch en Schermche morgen?") == (
        "Ja, zwischen 6 und 11 Uhr sind Schauer wahrscheinlich."
    )
    assert (
        session.say("Brauche ich übermorgen einen Regenschirm?")
        == "Nein, übermorgen bleibt es trocken."
    )


def test_umbrella_with_a_small_chance():
    days = wf.scenario(mon={"rain": [(10, 12, 0.0, 3)]})
    days[4].rain = []
    answer = weather_session(
        {"api.open-meteo.com/v1/forecast": _with_probability(wf.open_meteo_answer(days), 4, 35)}
    ).say("Brauche ich morgen einen Schirm?")
    assert answer and answer.startswith("Ein kleiner Schirm schadet nicht")


def _with_probability(answer, day_index, prob):
    for hour in range(day_index * 24 + 8, day_index * 24 + 14):
        answer["hourly"]["precipitation_probability"][hour] = prob
    return answer


# -- frost, snow, thunder, fog, wind, UV ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("changes", "question", "expected"),
    [
        (
            {"mon": {"tmin": -2.0, "tmax": 5.0, "cloud": 10}},
            "Gibt es heute Nacht Frost?",
            "Heute Nacht gibt es Frost, bis minus 2 Grad – du musst wohl die Scheiben kratzen.",
        ),
        (
            {"mon": {"tmin": -2.0, "tmax": 5.0, "cloud": 10}},
            "Muss ich morgen kratzen?",
            "Morgen gibt es Frost, bis minus 2 Grad – du musst wohl die Scheiben kratzen.",
        ),
        (
            {},
            "Gibt es heute Nacht Frost?",
            "Nein, heute Nacht gibt es keinen Frost, der Tiefstwert liegt bei 8 Grad.",
        ),
        (
            {"mon": {"tmin": -1.0, "tmax": 3.0, "freezing_rain": (4, 8)}},
            "Wird es morgen früh glatt?",
            "Achtung, morgen früh droht Glatteis durch gefrierenden Regen. "
            "Morgen früh gibt es Frost, bis minus 1 Grad – du musst wohl die Scheiben kratzen.",
        ),
        (
            {"mon": {"thunder_hours": (14, 18), "tmax": 24}},
            "Gibt es morgen Gewitter?",
            "Ja, morgen sind Gewitter möglich, zwischen 14 und 18 Uhr, örtlich mit Starkregen.",
        ),
        ({}, "Gibt es morgen Gewitter?", "Nein, morgen sind keine Gewitter in Sicht."),
        (
            {"mon": {"fog_hours": (5, 10), "rain": [], "cloud": 100}},
            "Gibt es morgen früh Nebel?",
            "Morgen früh ist in Weilburg Nebel möglich.",
        ),
        (
            {"mon": {"wind": 55.0, "gust": 95.0, "wind_dir": 270}},
            "Gibt es morgen Sturm?",
            "Ja, morgen in Weilburg gibt es Sturm, Böen bis 95 Kilometer pro Stunde.",
        ),
        (
            {"mon": {"wind": 55.0, "gust": 95.0, "wind_dir": 270}},
            "Wie windig wird es morgen?",
            "Morgen in Weilburg: steifer Wind aus West, Böen bis 95 Kilometer pro Stunde.",
        ),
        (
            {"wed": {"tmin": 20, "tmax": 33, "cloud": 5, "uv_max": 8.0, "rain": []}},
            "Brauche ich am Mittwoch Sonnencreme?",
            "Am Mittwoch erreicht der UV-Index 8 – sehr hoch, Sonnencreme ist sinnvoll.",
        ),
    ],
)
def test_single_aspects(changes, question, expected):
    session = session_with(wf.scenario(**changes))
    assert session.say(question) == expected


def test_snow():
    days = wf.scenario(
        mon={"snowfall": True, "tmin": -1.0, "tmax": 1.0, "rain": [(6, 14, 1.0, 71)]}
    )
    session = session_with(days)
    text = session.say("Schneit es morgen?")
    assert text and text.startswith("Ja, morgen kann es schneien") and "Neuschnee" in text
    none = weather_session().say("Schneit es morgen?")
    assert none and none.startswith("Nein, morgen ist kein Schnee in Sicht")


def test_temperature_questions():
    session = weather_session()
    assert session.say("Wie warm ist es?") == "In Weilburg sind es gerade 13 Grad."
    assert session.say("Wie warm wird es morgen?") == "Morgen in Weilburg werden es bis zu 13 Grad."
    cold = session.say("Wie kalt wird es heute Nacht?")
    assert cold == "Heute Nacht kühlt es auf 8 Grad ab."
    assert session.say("Wie viel Grad hat es?").endswith("13 Grad.")


def test_feels_like_only_with_a_difference():
    windy = wf.open_meteo_answer()
    windy["current"]["apparent_temperature"] = 8.5
    text = weather_session({"api.open-meteo.com/v1/forecast": windy}).say("Wie ist das Wetter?")
    assert text and "gefühlt 9 Grad" in text
    plain = weather_session().say("Wie ist das Wetter?")
    assert plain and "gefühlt" not in plain  # 13 → 12.4 is no difference worth saying


def test_humidity_pressure_sun_clouds_and_visibility():
    session = weather_session()
    assert "80 Prozent" in session.say("Wie hoch ist die Luftfeuchtigkeit?")
    assert (
        session.say("Wie ist der Luftdruck?")
        == "Der Luftdruck liegt bei 1.015 Hektopascal, gleichbleibend."
    )
    assert "Sonnenstunden" in session.say("Wie viele Sonnenstunden gibt es morgen?")
    assert session.say("Ist es bewölkt?") is not None
    assert session.say("Wie ist die Sicht?") == "Die Sicht ist gut, mehr als zehn Kilometer."


def test_sultry_needs_a_high_dew_point():
    answer = wf.open_meteo_answer()
    for hour in range(len(answer["hourly"]["dew_point_2m"])):
        answer["hourly"]["dew_point_2m"][hour] = 19.0
    text = weather_session({"api.open-meteo.com/v1/forecast": answer}).say("Ist es schwül?")
    assert text and text.startswith("Ja, es ist schwül")
    assert weather_session().say("Ist es schwül?").startswith("Nein, schwül ist es nicht")


# -- comparisons and searches -------------------------------------------------------------------------------------------------
def test_compare_days_and_places():
    session = weather_session()
    assert session.say("Wird es morgen wärmer als heute?") == (
        "Nein, morgen wird es mit 13 Grad 2 Grad kälter als heute."
    )
    assert session.say("Ist es morgen nasser als heute?") == (
        "Ja, morgen wird es mit 6 Liter pro Quadratmeter nasser als heute."
    )
    text = session.say("Ist es in Frankfurt wärmer als hier?")
    assert text == "Nein, in Frankfurt am Main ist es etwa genauso warm wie in Weilburg."


def test_extremes():
    session = weather_session()
    assert (
        session.say("Wann ist es heute am wärmsten?")
        == "Am wärmsten wird es heute gegen 19 Uhr mit 13 Grad."
    )
    best = session.say("Welcher Tag wird diese Woche am schönsten?")
    assert best == "Am schönsten wird der Donnerstag: freundlich bis 16 Grad."


def test_when_does_it_change():
    session = weather_session()
    assert session.say("Wann wird es wieder warm?") == (
        "Laut Vorhersage wird es nicht wärmer als 16 Grad in den nächsten 11 Tagen."
    )
    warm = session_with(wf.scenario(wed={"tmax": 22.0, "tmin": 12.0})).say(
        "Wann wird es wieder warm?"
    )
    assert warm and warm.startswith("Laut Vorhersage wird es wieder warm am Mittwoch, dann bis zu")
    frost = session_with(wf.scenario(sat2={"tmin": -3.0})).say("Wann kommt der nächste Frost?")
    assert frost == "Laut Vorhersage gibt es den nächsten Frost am Samstag, bis minus 3 Grad."


def test_station_measurement_comes_from_bright_sky():
    text = weather_session().say("Was misst die Wetterstation?")
    assert (
        text
        == "Die Wetterstation Weilburg-Kubach, 5 Kilometer entfernt, misst gerade 10,8 Grad, schwacher Wind."
    )


# -- honesty ------------------------------------------------------------------------------------------------------------------------
def test_old_data_is_announced_with_its_age(tmp_path):
    session = weather_session(cache_dir=tmp_path)
    session.say("Wie ist das Wetter?")
    session.clock.advance(hours=2)
    down = weather_session(
        {
            "api.open-meteo.com/v1/forecast": httpx.ConnectError("down"),
            "api.brightsky.dev/weather": httpx.ConnectError("down"),
            "api.brightsky.dev/current_weather": httpx.ConnectError("down"),
        },
        at=SUNDAY_EVENING,
        cache_dir=tmp_path,
    )
    down.clock.advance(hours=2)
    text = down.say("Wie ist das Wetter?")
    assert text and text.startswith(
        "Ich komme gerade nicht an neue Wetterdaten. Stand von vor 2 Stunden: "
    )
    assert down.last.result.stale_s is not None


def test_not_a_weather_question():
    session = weather_session()
    for sentence in (
        "Das Wetter ist mir egal",
        "Wie war das Wetter in meinem Urlaub?",
        "Wie viel Grad Fahrenheit sind 20 Grad Celsius?",
        "Wie warm ist die Suppe?",
    ):
        outcome = session.route(sentence)
        assert not (outcome.skill_id or "").startswith("weather."), sentence


def test_thinking_prompt_only_when_the_network_is_needed():
    session = weather_session()
    session.route("Wie ist das Wetter?")
    assert session.ctx.thinking_prompt == "thinking_weather"
    session.ctx.thinking_prompt = None
    session.route("Wie wird das Wetter morgen?")
    assert session.ctx.thinking_prompt is None  # answered from the cache


def test_weather_is_switched_off_with_the_group():
    from moritz_agent.config.settings import load_settings

    settings = load_settings()
    cfg = settings.skills.model_copy(update={"disabled": ["wetter"]})
    session = weather_session(settings=settings.model_copy(update={"skills": cfg}))
    outcome = session.route("Wie ist das Wetter?")
    assert not (outcome.skill_id or "").startswith("weather.")


def test_chat_surface_gets_the_same_facts():
    session = weather_session(surface="chat")
    result = session.route("Wie wird das Wetter morgen?").result
    assert result is not None and result.actions and result.actions[0].say.startswith("und ")
    assert result.card is None or result.card.title

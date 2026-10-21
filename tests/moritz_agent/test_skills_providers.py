# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""HTTP client, cache and weather providers, answering from fixtures (docs/plan/13 §3.5–3.7, §12)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from moritz_agent.config.settings import load_settings
from moritz_agent.skills.providers import Providers, ProviderUnavailable
from moritz_agent.skills.providers.http import HttpClient, HttpError

from . import weather_fixtures as wf
from .skills_util import SUNDAY_EVENING, weather_session


def run(coro):
    return asyncio.run(coro)


def client(**kwargs):
    return HttpClient(load_settings().skills, **kwargs)


# -- the door to the internet ----------------------------------------------------------------------
def test_only_https_and_known_hosts():
    http = client()
    http.check("https://api.open-meteo.com/v1/forecast")
    for url in (
        "http://api.open-meteo.com/v1/forecast",  # no plain http
        "https://evil.example.com/steal",  # not on the list
        "https://api.open-meteo.com.evil.example/x",
        "file:///etc/passwd",
    ):
        with pytest.raises(HttpError) as excinfo:
            http.check(url)
        assert excinfo.value.kind == "blocked"


def test_a_self_hosted_instance_may_live_in_the_lan():
    settings = load_settings()
    weather = settings.skills.weather.model_copy(
        update={"open_meteo_url": "http://192.168.1.50:8080", "brightsky_url": "http://nas:8000"}
    )
    cfg = settings.skills.model_copy(update={"weather": weather})
    http = HttpClient(cfg)
    http.check("http://192.168.1.50:8080/v1/forecast")
    http.check("http://nas:8000/weather")
    with pytest.raises(HttpError):
        http.check("http://192.168.1.51:8080/v1/forecast")  # another host stays blocked


def test_redirects_are_not_followed():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "https://evil.example.com/"})
    )
    with pytest.raises(HttpError) as excinfo:
        run(client(transport=transport).get_json("https://api.open-meteo.com/v1/forecast"))
    assert excinfo.value.kind == "status"


def test_answers_over_two_megabytes_are_refused():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 2_200_000))
    with pytest.raises(HttpError) as excinfo:
        run(client(transport=transport).get_bytes("https://api.open-meteo.com/v1/forecast"))
    assert excinfo.value.kind == "too_large"


def test_errors_never_contain_the_query_string():
    def handler(request):
        return httpx.Response(500)

    with pytest.raises(HttpError) as excinfo:
        run(
            client(transport=httpx.MockTransport(handler)).get_json(
                "https://api.open-meteo.com/v1/forecast", {"latitude": "50.48", "longitude": "8.26"}
            )
        )
    assert "50.48" not in str(excinfo.value) and "latitude" not in str(excinfo.value)


def test_invalid_json_and_timeouts():
    bad = httpx.MockTransport(lambda request: httpx.Response(200, content=b"<html>"))
    with pytest.raises(HttpError) as excinfo:
        run(client(transport=bad).get_json("https://api.open-meteo.com/v1/forecast"))
    assert excinfo.value.kind == "bad_data"

    def slow(request):
        raise httpx.ConnectTimeout("too slow")

    with pytest.raises(HttpError) as excinfo:
        run(client(transport=httpx.MockTransport(slow)).get_json("https://api.open-meteo.com/x"))
    assert excinfo.value.kind == "timeout"


# -- parsing and checks ----------------------------------------------------------------------------
def pack_of(session):
    fetched = run(session.svc.providers.weather(session.svc.gazetteer.home))
    return fetched, fetched.data


def test_the_forecast_is_parsed():
    session = weather_session()
    fetched, pack = pack_of(session)
    assert fetched.source == "open-meteo" and fetched.cache == "miss"
    assert pack.tz == "Europe/Berlin" and pack.source == "open-meteo"
    assert len(pack.hours) == 14 * 24 and len(pack.days) == 14
    assert pack.hours[0].time.isoformat() == "2026-10-15T00:00:00+02:00"
    assert pack.current is not None and pack.current.temperature is not None
    assert len(pack.minutes) == 14 * 24 * 4
    assert pack.day(SUNDAY_EVENING.date()).tmax >= 14
    assert pack.hour_at(SUNDAY_EVENING).time.hour == 19


def test_the_second_question_comes_from_the_cache(tmp_path):
    calls: list = []
    session = weather_session(calls=calls, cache_dir=tmp_path)
    run(session.svc.providers.weather(session.svc.gazetteer.home))
    again = run(session.svc.providers.weather(session.svc.gazetteer.home))
    assert again.cache == "hit" and len(calls) == 1
    assert list((tmp_path / "weather").glob("*.json")), "the cache is also written to disk"
    # a new process (new Providers, same directory) still hits
    fresh = weather_session(calls=calls, cache_dir=tmp_path)
    third = run(fresh.svc.providers.weather(fresh.svc.gazetteer.home))
    assert third.cache == "hit" and len(calls) == 1


def test_the_cache_expires_after_the_forecast_lifetime(tmp_path):
    calls: list = []
    session = weather_session(calls=calls, cache_dir=tmp_path)
    home = session.svc.gazetteer.home
    run(session.svc.providers.weather(home))
    session.clock.advance(minutes=20)
    assert run(session.svc.providers.weather(home)).cache == "hit"
    session.clock.advance(minutes=15)
    assert run(session.svc.providers.weather(home)).cache == "miss"
    assert len(calls) == 2


def test_current_values_expire_sooner(tmp_path):
    calls: list = []
    session = weather_session(calls=calls, cache_dir=tmp_path)
    home = session.svc.gazetteer.home
    run(session.svc.providers.weather(home))
    session.clock.advance(minutes=12)
    assert run(session.svc.providers.weather(home, need="forecast")).cache == "hit"
    assert run(session.svc.providers.weather(home, need="current")).cache == "miss"


def test_old_data_is_used_when_the_network_is_gone(tmp_path):
    state = {"down": False}

    def forecast(request):
        if state["down"]:
            raise httpx.ConnectError("no route")
        return wf.open_meteo_answer()

    session = weather_session(
        {
            "api.open-meteo.com/v1/forecast": forecast,
            "api.brightsky.dev/weather": forecast,
            "api.brightsky.dev/current_weather": forecast,
        },
        cache_dir=tmp_path,
    )
    home = session.svc.gazetteer.home
    run(session.svc.providers.weather(home))
    state["down"] = True
    session.clock.advance(hours=2)
    stale = run(session.svc.providers.weather(home))
    assert stale.cache == "stale" and 7000 < stale.age_s < 7300
    session.clock.advance(hours=5)  # 7 hours: beyond max_stale_hours
    with pytest.raises(ProviderUnavailable):
        run(session.svc.providers.weather(home))
    assert session.svc.providers.snapshot()["open-meteo"]["state"] == "degraded"


def test_bright_sky_steps_in_when_open_meteo_fails():
    session = weather_session({"api.open-meteo.com/v1/forecast": httpx.ConnectError("down")})
    fetched, pack = pack_of(session)
    assert fetched.source == "brightsky" and fetched.fell_back
    assert pack.model == "MOSMIX" and pack.current is not None
    assert pack.station == "Weilburg-Kubach" and pack.station_km == 5.2
    assert pack.days and pack.day(SUNDAY_EVENING.date()).tmax is not None
    text = session.say("Wie ist das Wetter?")
    assert text and "Grad" in text


def test_implausible_data_is_rejected():
    hot = wf.open_meteo_answer()
    hot["hourly"]["temperature_2m"][10] = 70.0
    session = weather_session({"api.open-meteo.com/v1/forecast": hot})
    fetched, _ = pack_of(session)
    assert fetched.source == "brightsky"  # fell back
    broken = wf.open_meteo_answer()
    broken["hourly"]["wind_speed_10m"].pop()
    session = weather_session({"api.open-meteo.com/v1/forecast": broken})
    assert pack_of(session)[0].source == "brightsky"


def test_wrong_time_zone_is_rejected():
    answer = wf.open_meteo_answer()
    answer["timezone"] = "GMT"
    session = weather_session({"api.open-meteo.com/v1/forecast": answer})
    assert pack_of(session)[0].source == "brightsky"


def test_everything_down_is_an_honest_answer():
    down = httpx.ConnectError("down")
    session = weather_session(
        {
            "api.open-meteo.com/v1/forecast": down,
            "api.brightsky.dev/weather": down,
            "api.brightsky.dev/current_weather": down,
        }
    )
    outcome = session.route("Wie ist das Wetter?")
    assert outcome.result.text.startswith("Ich komme gerade nicht an die Wetterdaten")
    assert outcome.result.prompt == "skills_offline"
    assert outcome.result.serious


def test_a_missing_service_container_is_the_same_as_offline():
    from .skills_util import Session

    outcome = Session().route("Wie ist das Wetter?")
    assert outcome.result is not None and outcome.result.prompt == "skills_offline"


def test_online_false_switches_every_call_off():
    calls: list = []
    settings = load_settings()
    off = settings.model_copy(
        update={"skills": settings.skills.model_copy(update={"online": False})}
    )
    session = weather_session(calls=calls, settings=off)
    assert session.say("Wie ist das Wetter?") == "Wetterabfragen sind bei mir gerade ausgeschaltet."
    assert calls == []
    # time and calendar still work
    assert session.say("Wie viel Uhr ist es?")


def test_http_429_makes_the_client_wait(tmp_path):
    calls: list = []
    session = weather_session(
        {"api.open-meteo.com/v1/forecast": lambda r: httpx.Response(429, json={"reason": "limit"})},
        calls=calls,
        cache_dir=tmp_path,
    )
    home = session.svc.gazetteer.home
    fetched = run(session.svc.providers.weather(home))
    assert fetched.source == "brightsky"
    before = len([c for c in calls if "open-meteo" in c.url.host])
    session.clock.advance(minutes=11)  # "current" is stale again, the 15 minute pause is not over
    run(session.svc.providers.weather(home, need="current"))
    assert len([c for c in calls if "open-meteo" in c.url.host]) == before
    session.clock.advance(minutes=11)  # 22 minutes: the pause is over
    run(session.svc.providers.weather(home, need="current"))
    assert len([c for c in calls if "open-meteo" in c.url.host]) > before


def test_without_minutely_data_when_the_server_does_not_know_it():
    seen: list = []

    def forecast(request):
        seen.append(dict(request.url.params))
        if "minutely_15" in request.url.params:
            return httpx.Response(400, json={"error": True, "reason": "unknown variable"})
        return httpx.Response(200, json=wf.open_meteo_answer(minutely=False))

    session = weather_session({"api.open-meteo.com/v1/forecast": forecast})
    fetched, pack = pack_of(session)
    assert fetched.source == "open-meteo" and pack.minutes == []
    assert len(seen) == 2 and "minutely_15" not in seen[1]


def test_simultaneous_questions_share_one_request(tmp_path):
    calls: list = []
    session = weather_session(calls=calls, cache_dir=tmp_path)
    home = session.svc.gazetteer.home

    async def both():
        return await asyncio.gather(
            session.svc.providers.weather(home), session.svc.providers.weather(home)
        )

    first, second = run(both())
    assert first.data is second.data or first.data.fetched_at == second.data.fetched_at
    assert len([c for c in calls if c.url.path == "/v1/forecast"]) == 1


def test_only_rounded_coordinates_leave_the_house():
    calls: list = []
    session = weather_session(calls=calls)
    run(session.svc.providers.weather(session.svc.gazetteer.home))
    params = dict(calls[0].url.params)
    assert params["latitude"] == "50.48" and params["longitude"] == "8.26"
    assert set(params) >= {"timezone", "forecast_days", "past_days", "hourly", "daily", "current"}
    assert all("moritz" not in str(v).lower() for v in params.values())


# -- geocoding ---------------------------------------------------------------------------------------
GEOCODE = {
    "results": [
        {
            "name": "Tromsø",
            "latitude": 69.6496,
            "longitude": 18.957,
            "country": "Norwegen",
            "country_code": "NO",
            "timezone": "Europe/Oslo",
            "population": 77000,
        }
    ]
}


def test_unknown_places_are_looked_up_online_and_remembered(tmp_path):
    calls: list = []
    session = weather_session(
        {
            "geocoding-api.open-meteo.com/v1/search": GEOCODE,
            "api.open-meteo.com/v1/forecast": wf.open_meteo_answer(
                lat=69.65, lon=18.96, tz="Europe/Oslo"
            ),
        },
        calls=calls,
        cache_dir=tmp_path,
    )
    outcome = session.route("Wie ist das Wetter in Tromsö?")
    assert outcome.result is not None
    assert outcome.result.text.startswith("In Tromsø in Norwegen sind es gerade")
    session.route("Wie ist das Wetter in Tromsö?")
    assert len([c for c in calls if c.url.host.startswith("geocoding")]) == 1
    sent = next(c for c in calls if c.url.host.startswith("geocoding"))
    assert dict(sent.url.params)["name"] == "Tromsö"  # just the name, nothing else
    forecast = next(c for c in calls if c.url.path == "/v1/forecast")
    assert dict(forecast.url.params)["timezone"] == "Europe/Oslo"


def test_geocoding_failure_is_a_plain_unknown_place():
    session = weather_session({"geocoding-api.open-meteo.com/v1/search": {"results": []}})
    assert session.say("Wie ist das Wetter in Atlantis?") == "Den Ort Atlantis kenne ich nicht."


# -- status and prefetch ------------------------------------------------------------------------------
def test_status_has_no_urls():
    session = weather_session()
    run(session.svc.providers.prefetch_once())
    snapshot = session.svc.providers.snapshot()
    assert snapshot["open-meteo"]["state"] == "ready"
    assert "http" not in json.dumps(snapshot)


def test_prefetch_fills_the_cache_for_the_home_place(tmp_path):
    calls: list = []
    session = weather_session(calls=calls, cache_dir=tmp_path)
    done = run(session.svc.providers.prefetch_once())
    assert done["weather"].startswith("open-meteo") and "warnings" in done
    before = len(calls)
    assert session.say("Wie ist das Wetter?")
    assert len(calls) == before  # answered from the cache


def test_prefetch_is_off_without_internet_permission():
    settings = load_settings()
    off = settings.model_copy(
        update={"skills": settings.skills.model_copy(update={"online": False})}
    )
    session = weather_session(settings=off)
    assert run(session.svc.providers.prefetch_once()) == {"all": "skills.online ist aus"}


def test_provider_classes_are_importable_for_the_cli():
    assert Providers.__name__ == "Providers"

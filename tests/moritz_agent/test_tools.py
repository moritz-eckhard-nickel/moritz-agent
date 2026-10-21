# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Tool framework, get_current_time, web_search and the skill tools (P1-07)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

import pytest

from moritz_agent.research.search import SearchHit, SearchOutcome
from moritz_agent.skills.tools import skill_tools
from moritz_agent.storage import Database, Repo
from moritz_agent.tools.base import BaseTool, ToolContext, ToolResult
from moritz_agent.tools.registry import ToolRegistry
from moritz_agent.tools.schema import validate
from moritz_agent.tools.time_tool import GetCurrentTime
from moritz_agent.tools.web_search import WebSearch

from .skills_util import SUNDAY_EVENING, weather_session

BERLIN = ZoneInfo("Europe/Berlin")


def run(coro):
    return asyncio.run(coro)


# -- schema ---------------------------------------------------------------------------------------
SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "maxLength": 20},
        "count": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
        "kind": {"type": "string", "enum": ["a", "b"]},
        "exact": {"type": "boolean"},
        "ratio": {"type": "number"},
    },
    "required": ["query"],
}


def test_valid_arguments_get_defaults_and_unknown_ones_are_dropped():
    clean, problems = validate({"query": " Brot ", "extra": 1}, SCHEMA)
    assert problems == [] and clean == {"query": "Brot", "count": 3}


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"query": "x", "count": "4"}, 4),
        ({"query": "x", "count": 4.0}, 4),
        ({"query": "x", "count": "4,0"}, 4),
    ],
)
def test_numbers_are_coerced_from_text(given, expected):
    clean, problems = validate(given | {"query": "xy"}, SCHEMA)
    assert problems == [] and clean["count"] == expected


def test_booleans_and_numbers_from_text():
    clean, problems = validate({"query": "xy", "exact": "ja", "ratio": "0,5"}, SCHEMA)
    assert problems == [] and clean["exact"] is True and clean["ratio"] == 0.5


@pytest.mark.parametrize(
    ("given", "fragment"),
    [
        ({}, "'query' fehlt"),
        ({"query": "a"}, "nicht leer"),
        ({"query": "x" * 30}, "zu lang"),
        ({"query": "xy", "count": 9}, "höchstens 5"),
        ({"query": "xy", "count": 0}, "mindestens 1"),
        ({"query": "xy", "count": 1.5}, "ganze Zahl"),
        ({"query": "xy", "count": True}, "ganze Zahl"),
        ({"query": "xy", "kind": "c"}, "eines von diesen sein: a, b"),
        ({"query": "xy", "exact": "vielleicht"}, "wahr oder falsch"),
        ({"query": ["liste"]}, "muss ein Text sein"),
    ],
)
def test_problems_are_reported_in_german(given, fragment):
    _, problems = validate(given, SCHEMA)
    assert any(fragment in problem for problem in problems), problems


def test_arguments_must_be_an_object():
    assert validate([1], SCHEMA)[1] == ["Die Argumente müssen ein JSON-Objekt sein."]
    assert validate(None, {"type": "object", "properties": {}}) == ({}, [])


# -- registry ---------------------------------------------------------------------------------------
class Echo(BaseTool):
    name = "echo"
    description = "Gibt den Text zurück."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
    }
    timeout_s = 0.2

    async def run(self, args, ctx):
        return ToolResult.success({"text": args["text"]}, speakable=args["text"])


class Slow(BaseTool):
    name = "slow"
    timeout_s = 0.05

    async def run(self, args, ctx):
        await asyncio.sleep(1)
        return ToolResult.success()


class Broken(BaseTool):
    name = "broken"

    async def run(self, args, ctx):
        raise RuntimeError("geheim: passwort123")


class Big(BaseTool):
    name = "big"

    async def run(self, args, ctx):
        rows = [{"title": f"Treffer {i}", "snippet": "wort " * 120} for i in range(20)]
        return ToolResult.success({"results": rows})


def registry(**kwargs) -> ToolRegistry:
    reg = ToolRegistry(**kwargs)
    reg.register_all([Echo(), Slow(), Broken(), Big()])
    return reg


ALLOWED = {"echo", "slow", "broken", "big"}


def call(reg, name, arguments, allowed=ALLOWED, ctx=None):
    return run(reg.call(name, arguments, ctx or ToolContext(), allowed=allowed))


def test_definitions_are_limited_to_the_allowed_tools():
    reg = registry()
    names = [d["function"]["name"] for d in reg.definitions({"echo", "big"})]
    assert names == ["echo", "big"]
    definition = reg.definitions({"echo"})[0]
    assert definition["type"] == "function"
    assert definition["function"]["parameters"]["required"] == ["text"]


def test_duplicate_names_are_refused():
    reg = registry()
    with pytest.raises(ValueError):
        reg.register(Echo())


def test_a_call_with_json_text_arguments():
    result = call(registry(), "echo", '{"text": "Hallo"}')
    assert result.payload() == {"ok": True, "data": {"text": "Hallo"}, "speakable": "Hallo"}


def test_empty_argument_text_means_no_arguments():
    result = call(registry(), "big", "")
    assert result.ok


def test_invalid_json_and_invalid_arguments_let_the_model_retry():
    reg = registry()
    broken = call(reg, "echo", "{kein json")
    assert not broken.ok and broken.error == "invalid_arguments"
    missing = call(reg, "echo", {})
    assert missing.error == "invalid_arguments" and "'text' fehlt" in missing.message


def test_unknown_and_forbidden_tools():
    reg = registry()
    assert call(reg, "shell", {}).error == "unknown_tool"
    forbidden = call(reg, "echo", {"text": "x"}, allowed={"big"})
    assert forbidden.error == "unknown_tool"  # a profile must not learn that the tool exists


def test_timeout_and_crash_become_results_and_leak_nothing():
    reg = registry()
    assert call(reg, "slow", {}).error == "timeout"
    crashed = call(reg, "broken", {})
    assert crashed.error == "tool_failed"
    assert "passwort123" not in json.dumps(crashed.payload())


def test_large_results_are_shrunk_and_marked():
    reg = registry(max_output_chars=2000)
    result = call(reg, "big", {})
    assert result.ok and result.truncated
    payload = result.payload()
    assert len(json.dumps(payload, ensure_ascii=False)) <= 2000
    assert payload["truncated"] is True and payload["data"]["results"]


def test_small_results_stay_untouched():
    result = call(registry(), "echo", {"text": "kurz"})
    assert not result.truncated


def test_failure_payload_shape():
    assert ToolResult.failure("search_unavailable", "Nicht erreichbar").payload() == {
        "ok": False,
        "error": "search_unavailable",
        "message": "Nicht erreichbar",
    }


def database(tmp_path) -> Database:
    return Database(tmp_path / "t.sqlite3")


def test_every_call_is_logged_with_the_arguments_only_when_transcripts_are_kept(tmp_path):
    for keep in (True, False):
        db = Database(tmp_path / f"keep-{keep}.sqlite3")
        repo = Repo(db, store_transcripts=keep)
        reg = registry(repo=repo)
        call(reg, "echo", {"text": "geheime Frage"}, ctx=ToolContext(call_id="c1", channel="phone"))
        call(reg, "shell", {})
        rows = db.query(
            "SELECT tool, ok, error, args_json, result_summary, call_id FROM tool_calls"
        )
        assert sorted(r["tool"] for r in rows) == ["echo", "shell"]
        echo = next(r for r in rows if r["tool"] == "echo")
        assert echo["ok"] == 1 and echo["call_id"] == "c1"
        assert ("geheime Frage" in json.dumps(dict(echo), ensure_ascii=False)) is keep
        shell = next(r for r in rows if r["tool"] == "shell")
        assert shell["ok"] == 0 and shell["error"] == "unknown_tool"


# -- get_current_time -------------------------------------------------------------------------
def clock_tool(at=SUNDAY_EVENING):
    return GetCurrentTime("Europe/Berlin", clock=lambda: at)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("time", "Es ist 19 Uhr 12."),
        ("date", "Heute ist Sonntag, der 18. Oktober 2026."),
        ("datetime", "Es ist 19 Uhr 12. Heute ist Sonntag, der 18. Oktober 2026."),
    ],
)
def test_get_current_time(kind, expected):
    result = run(clock_tool().run({"kind": kind}, ToolContext()))
    assert result.speakable == expected
    assert result.data["time"] == "19:12" and result.data["weekday"] == "Sonntag"
    assert result.data["calendar_week"] == 42 and result.data["iso"].endswith("+02:00")


def test_get_current_time_defaults_to_both_and_follows_daylight_saving():
    reg = ToolRegistry()
    reg.register(clock_tool(datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN)))
    result = call(reg, "get_current_time", {}, allowed={"get_current_time"})
    assert result.ok and "Sonntag, der 25. Oktober" in result.speakable


def test_get_current_time_rejects_unknown_kinds():
    reg = ToolRegistry()
    reg.register(clock_tool())
    assert (
        call(reg, "get_current_time", {"kind": "sekunden"}, allowed={"get_current_time"}).error
        == "invalid_arguments"
    )


# -- web_search ------------------------------------------------------------------------------------
class FakeSearch:
    def __init__(self, outcome: SearchOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, int | None]] = []

    async def search(self, query, max_results=None):
        self.calls.append((query, max_results))
        return self.outcome


def hit(domain, backend="searxng", **kw):
    return SearchHit(f"Titel {domain}", f"https://{domain}/a", "Auszug", domain, backend, **kw)


def search_tool(outcome):
    fake = FakeSearch(outcome)
    return WebSearch(fake), fake


def test_web_search_returns_hits_and_sources():
    tool, fake = search_tool(
        SearchOutcome(
            "x", [hit("tagesschau.de", engines=("brave", "bing"))], "searxng", ["searxng"]
        )
    )
    result = run(tool.run({"query": "Nachrichten", "max_results": 3}, ToolContext()))
    assert fake.calls == [("Nachrichten", 3)]
    row = result.data["results"][0]
    assert row["domain"] == "tagesschau.de" and row["engines"] == ["brave", "bing"]
    assert result.data["backend"] == "searxng"
    assert result.sources == [
        {"name": "tagesschau.de", "url": "https://tagesschau.de/a", "backend": "searxng"}
    ]


def test_web_search_hands_over_page_text_of_the_fallback():
    tool, _ = search_tool(
        SearchOutcome("x", [hit("a.de", "koboldcpp", content="Langer Seitentext")], "koboldcpp")
    )
    assert (
        run(tool.run({"query": "xx"}, ToolContext())).data["results"][0]["content"]
        == "Langer Seitentext"
    )


def test_web_search_failure_is_search_unavailable():
    outcome = SearchOutcome("x", errors={"searxng": "timeout", "koboldcpp": "offline"})
    tool, _ = search_tool(outcome)
    reg = ToolRegistry()
    reg.register(tool)
    result = call(reg, "web_search", {"query": "Nachrichten"}, allowed={"web_search"})
    assert not result.ok and result.error == "search_unavailable"
    assert "ehrlich" in result.message


def test_web_search_without_hits_is_not_an_error():
    tool, _ = search_tool(SearchOutcome("x", errors={"searxng": "empty"}))
    result = run(tool.run({"query": "qwertz"}, ToolContext()))
    assert result.ok and result.data["results"] == []
    assert "keine Treffer" in result.data["note"]


def test_web_search_arguments_are_checked():
    tool, fake = search_tool(SearchOutcome("x"))
    reg = ToolRegistry()
    reg.register(tool)
    assert (
        call(reg, "web_search", {"query": "a"}, allowed={"web_search"}).error == "invalid_arguments"
    )
    assert (
        call(reg, "web_search", {"query": "xx", "max_results": 50}, allowed={"web_search"}).error
        == "invalid_arguments"
    )
    assert fake.calls == []


# -- skill tools -----------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    return weather_session()


@pytest.fixture(scope="module")
def tools(session):
    return {tool.name: tool for tool in skill_tools(session.router)}


def use(session, tools, name, **args):
    registry = ToolRegistry()
    registry.register_all(tools.values())
    return run(registry.call(name, args, ToolContext(skills=session.ctx), allowed=set(tools)))


CASES = [
    ("get_weather", {}, "weather.now"),
    ("get_weather", {"place": "Frankfurt", "when": "morgen"}, "weather.day"),
    ("get_weather", {"when": "heute Abend", "aspect": "rain"}, "weather.rain"),
    ("get_weather", {"place": "Berlin", "when": "2026-10-24"}, "weather.day"),
    ("get_weather", {"when": "Wochenende", "aspect": "temperature"}, "weather.temperature"),
    ("get_weather", {"aspect": "wind", "when": "morgen"}, "weather.wind"),
    ("get_weather", {"aspect": "snow", "when": "Samstag", "place": "Limburg"}, "weather.snow"),
    ("get_weather", {"aspect": "frost", "when": "heute Nacht"}, "weather.frost"),
    ("get_weather", {"aspect": "thunder"}, "weather.thunder"),
    ("get_weather", {"aspect": "humidity"}, "weather.humidity"),
    ("get_weather", {"aspect": "pressure"}, "weather.pressure"),
    ("get_weather", {"aspect": "fog", "when": "morgen früh"}, "weather.fog"),
    ("get_weather", {"aspect": "feels_like"}, "weather.feels_like"),
    ("get_weather", {"place": "35781", "when": "nächste Woche"}, "weather.week"),
    ("get_warnings", {}, "warn.weather"),
    ("get_warnings", {"kind": "civil", "place": "Weilburg"}, "warn.civil"),
    ("get_pollen", {}, "pollen.today"),
    ("get_pollen", {"when": "morgen", "pollen": "Birke"}, "pollen.forecast"),
    ("get_pollen", {"when": "morgen", "pollen": "Birke", "place": "Frankfurt"}, "pollen.forecast"),
    ("get_air_quality", {}, "air.quality"),
    ("get_air_quality", {"pollutant": "ozone"}, "air.ozone"),
    ("get_sun_moon", {"what": "sunrise"}, "sun.rise_set"),
    ("get_sun_moon", {"what": "sunset", "when": "morgen", "place": "Berlin"}, "sun.rise_set"),
    ("get_sun_moon", {"what": "dark"}, "sun.dark"),
    ("get_sun_moon", {"what": "daylength"}, "sun.daylength"),
    ("get_sun_moon", {"what": "moon_phase"}, "moon.phase"),
    ("get_sun_moon", {"what": "full_moon"}, "moon.next"),
    ("get_sun_moon", {"what": "new_moon"}, "moon.next"),
    ("get_sun_moon", {"what": "moonrise"}, "moon.rise_set"),
    ("get_sun_moon", {"what": "moonset", "when": "morgen"}, "moon.rise_set"),
    ("get_sun_moon", {"what": "season_start", "season": "Winter"}, "season.start"),
    ("calendar_info", {"question": "Welcher Wochentag ist der 3. Oktober 2027"}, "date.weekday_of"),
    ("calendar_info", {"question": "Wie viele Tage sind es bis Weihnachten"}, "date.days_until"),
    ("calendar_info", {"question": "Wann sind Herbstferien in Hessen"}, "school.next"),
    ("calculate", {"question": "Was sind 15 Prozent von 80"}, "calc.percent"),
    ("calculate", {"question": "Wie viel ist 12 mal 7"}, "calc.arith"),
    ("money_info", {"question": "Wie viel sind 100 Dollar in Euro"}, "money.fx"),
    ("regional_info", {"question": "Wie hoch steht die Lahn"}, "water.level"),
    ("place_info", {"question": "Welche Postleitzahl hat Limburg"}, "geo.place_to_plz"),
    ("place_info", {"question": "Wie weit ist es nach Frankfurt"}, "geo.distance"),
    ("everyday_advice", {"question": "Brauche ich eine Jacke"}, "advice.jacket"),
    (
        "everyday_advice",
        {"question": "Kann ich Wäsche draußen aufhängen", "place": "Wetzlar"},
        "advice.laundry",
    ),
]


@pytest.mark.parametrize(
    ("name", "args", "skill_id"), CASES, ids=[f"{n}-{i}" for i, (n, _, _) in enumerate(CASES)]
)
def test_each_skill_tool_reaches_the_intended_skill(session, tools, name, args, skill_id):
    result = use(session, tools, name, **args)
    assert result.ok, result.payload()
    assert result.data["skill"] == skill_id
    assert result.speakable and result.speakable == result.data["text"]


def test_the_place_and_time_arrive_in_the_answer(session, tools):
    result = use(session, tools, "get_weather", place="Frankfurt", when="morgen")
    assert "Frankfurt" in result.speakable and result.speakable.startswith("Morgen")
    assert result.sources and result.sources[0]["name"].startswith("Open-Meteo")
    assert result.data["facts"]["place"].startswith("Frankfurt")


def test_the_weather_tool_does_not_answer_from_the_web_search(session, tools):
    assert "web_search" not in tools
    result = use(session, tools, "get_weather", place="Berlin", when="2026-10-24")
    assert "Samstag" in result.speakable


def test_a_moon_day_without_moonset_names_the_day_it_happens(session, tools):
    result = use(session, tools, "get_sun_moon", what="moonset", when="morgen")
    assert "nicht unter" in result.speakable and "Dienstag" not in result.speakable
    assert "übermorgen" in result.speakable and "Uhr 47" in result.speakable


def test_a_season_start_needs_the_season(session, tools):
    result = use(session, tools, "get_sun_moon", what="season_start")
    assert result.error == "invalid_arguments" and "season" in result.message


def test_writing_skills_are_not_reachable(session, tools):
    for name in ("regional_info", "calendar_info", "calculate"):
        result = use(session, tools, name, question="Schreib Milch auf die Einkaufsliste")
        assert not result.ok and result.error == "no_answer"
    assert not any(
        skill.startswith("notes.") or skill.startswith("timer.")
        for skill in {
            s.id for s in session.router.skills.values() if any(t.only(s) for t in tools.values())
        }
    )


def test_a_question_outside_the_area_of_a_tool_has_no_answer(session, tools):
    result = use(session, tools, "calculate", question="Wie wird das Wetter morgen")
    assert result.error == "no_answer"


def test_follow_up_questions_continue_after_a_tool_call():
    s = weather_session()
    tool = {t.name: t for t in skill_tools(s.router)}["get_weather"]
    result = run(tool.run({"place": "Frankfurt"}, ToolContext(skills=s.ctx)))
    assert result.ok
    follow = s.say("und morgen?")
    assert follow is not None and "Frankfurt" in follow


def test_without_a_conversation_the_tool_still_answers(tools):
    s = weather_session()
    tool = {t.name: t for t in skill_tools(s.router)}["calculate"]
    result = run(tool.run({"question": "Wie viel ist 3 mal 4"}, ToolContext()))
    assert result.speakable == "3 mal 4 ist 12."


def test_offline_data_services_give_an_honest_sentence():
    from moritz_agent.config.settings import load_settings

    settings = load_settings()
    settings.skills.online = False
    s = weather_session(settings=settings)
    tool = {t.name: t for t in skill_tools(s.router)}["get_weather"]
    result = run(tool.run({}, ToolContext(skills=s.ctx)))
    assert result.ok and "ausgeschaltet" in result.speakable


def test_tool_definitions_are_valid_function_schemas(tools):
    for tool in tools.values():
        function = tool.definition()["function"]
        assert function["name"] == tool.name and len(function["description"]) > 30
        assert function["parameters"]["type"] == "object"
        for required in function["parameters"].get("required", []):
            assert required in function["parameters"]["properties"]

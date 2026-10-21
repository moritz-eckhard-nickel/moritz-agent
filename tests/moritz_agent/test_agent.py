# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Agent loop with a scripted model, guards, speakable text, context budget, profiles (P1-09)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from moritz_agent.agent import guard
from moritz_agent.agent.context import ContextBuilder, estimate_tokens
from moritz_agent.agent.loop import DEADLINE_TEXT, AgentLoop
from moritz_agent.agent.profiles import FORBIDDEN_TOOLS, Profile, phone_profile, render_prompt
from moritz_agent.agent.responder import AgentResponder
from moritz_agent.agent.speakable import clean, make_speakable, sentences
from moritz_agent.config.settings import Settings
from moritz_agent.inference import InferenceClient, InferenceQueue
from moritz_agent.phone.responder import ResponderUnavailable, TurnContext
from moritz_agent.research.search import SearchHit, SearchOutcome
from moritz_agent.tools.base import ToolContext
from moritz_agent.tools.registry import ToolRegistry
from moritz_agent.tools.time_tool import GetCurrentTime
from moritz_agent.tools.web_search import WebSearch

from .fake_model import FakeModel, text_chunks, tool_chunks
from .skills_util import SUNDAY_EVENING, weather_session

ROOT = Path(__file__).resolve().parents[2]


def run(coro):
    return asyncio.run(coro)


# -- speakable --------------------------------------------------------------------------------------
def test_clean_removes_reasoning_code_links_and_emoji():
    text = (
        "<think>erst überlegen</think>Das **Wetter** ist [hier](https://x.de/a?b=1) 😀 gut `code`."
    )
    assert clean(text) == "Das Wetter ist hier gut code."
    assert clean("Text ```python\nprint(1)\n``` Ende") == "Text Ende"
    assert clean("Siehe https://tagesschau.de/x und www.zdf.de gleich") == "Siehe und gleich"
    assert clean("<think>nie fertig") == ""


def test_lists_become_sentences():
    assert (
        clean("Das brauchst du:\n- Mehl\n- Eier\n1. Milch") == "Das brauchst du: Mehl. Eier. Milch"
    )


def test_clean_leaves_no_space_before_punctuation():
    assert clean("Hallo Moritz 😀 . Wie geht es dir ?") == "Hallo Moritz. Wie geht es dir?"


def test_sentences_do_not_break_at_dates_and_abbreviations():
    text = "Am 18. Oktober regnet es, z. B. in Weilburg. Dr. Müller sagt ja. Wirklich? Ja!"
    assert sentences(text) == [
        "Am 18. Oktober regnet es, z. B. in Weilburg.",
        "Dr. Müller sagt ja.",
        "Wirklich?",
        "Ja!",
    ]


def test_speakable_limits_sentences_and_length():
    text = "Eins ist gut. Zwei ist besser. Drei ist am besten. Vier kommt nie. Fünf auch nicht."
    assert make_speakable(text) == "Eins ist gut. Zwei ist besser. Drei ist am besten."
    assert make_speakable(text, max_sentences=1) == "Eins ist gut."
    long = "Wort " * 200
    assert len(make_speakable(long, max_chars=100)) <= 101
    assert make_speakable("   ") == ""


# -- guards ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "answer",
    [
        "Es ist 19:12.",
        "Es ist 19 Uhr 12.",
        "Kurz nach sieben.",
        "Es ist halb acht.",
        "Um 7.30 Uhr.",
    ],
)
def test_clock_times_without_a_tool_are_caught(answer):
    violation = guard.check("Sag mal was", answer, set())
    assert violation is not None and violation.kind == "time"


@pytest.mark.parametrize(
    "answer",
    ["Das kostet 3.50 Euro.", "Ich habe 5 Minuten gebraucht.", "Am 18. Oktober.", "Hallo."],
)
def test_other_numbers_are_no_clock_times(answer):
    assert guard.check("Was kostet das", answer, set()) is None


def test_a_time_question_needs_the_clock_tool_even_if_other_tools_ran():
    assert guard.check("Wie spät ist es", "Es ist 19 Uhr.", {"web_search"}).kind == "time"
    assert guard.check("Wie spät ist es", "Es ist 19 Uhr.", {"get_current_time"}) is None
    # a time from a search result is fine when the question is not about the time
    assert guard.check("Wann beginnt die Sendung", "Um 20 Uhr 15.", {"web_search"}) is None


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Wie wird das Wetter", "Morgen werden es 14 Grad."),
        ("Brauch ich einen Schirm", "Ja, bei 80 Prozent Regen."),
        ("Wie ist es draußen", "Es hat 12° und regnet."),
        ("Wie ist der Wind", "Der Wind weht mit 40 km/h."),
    ],
)
def test_weather_values_without_a_weather_tool_are_caught(question, answer):
    assert guard.check(question, answer, set()).kind == "weather"
    assert guard.check(question, answer, {"get_weather"}) is None


def test_degrees_outside_the_weather_are_not_weather_values():
    assert (
        guard.check("Bei wie viel Grad kocht Wasser", "Wasser kocht bei 100 Grad.", set()) is None
    )


def test_farewell_detection():
    assert guard.is_farewell("Okay, tschüss!")
    assert guard.is_farewell("Das war's, bis dann")
    assert not guard.is_farewell(
        "Erzähl mir etwas über den Abschied von Tschüss und Hallo in Hessen"
    )


# -- context budget ---------------------------------------------------------------------------
def builder(**kwargs):
    defaults = {"context_size": 1000, "answer_tokens": 100}
    return ContextBuilder("System", **(defaults | kwargs))


def test_the_context_keeps_the_latest_turns_that_fit():
    history = [(f"Frage {i} " + "wort " * 60, f"Antwort {i} " + "wort " * 60) for i in range(10)]
    built = run(builder().build(history, "Neue Frage"))
    assert built.messages[0] == {"role": "system", "content": "System"}
    assert built.messages[-1] == {"role": "user", "content": "Neue Frage"}
    assert 0 < built.dropped_turns < 10
    kept = [m["content"] for m in built.messages if m["role"] == "user"][:-1]
    assert kept[-1].startswith("Frage 9")  # newest stays, oldest goes
    assert built.estimated_tokens <= builder().budget


def test_the_question_always_survives_and_empty_answers_are_skipped():
    built = run(builder(context_size=300).build([("alt", "")], "x" * 2000))
    assert built.messages[-1]["content"] == "x" * 2000
    roles = [m["role"] for m in run(builder().build([("a", ""), ("b", "c")], "d")).messages]
    assert roles == ["system", "user", "user", "assistant", "user"]


def test_tool_schemas_shrink_the_budget():
    tools = [{"type": "function", "function": {"name": "t", "description": "x" * 800}}]
    assert builder(tools=tools).budget < builder().budget


def test_the_exact_count_trims_when_the_estimate_is_close_to_the_limit():
    history = [("a " * 150, "b " * 150) for _ in range(3)]
    counts = []

    async def counter(text):
        counts.append(len(text))
        return 10_000 if len(counts) == 1 else 10

    built = run(builder(context_size=1200, counter=counter).build(history, "Frage"))
    assert counts and built.dropped_turns >= 1


def test_estimate_has_a_reserve():
    assert estimate_tokens("x" * 350) == 115


# -- profile ------------------------------------------------------------------------------------------
def test_render_prompt_fills_the_variables():
    settings = Settings()
    text = render_prompt("Ich bin {assistant} in {home_name} ({home_postal_code}).", settings)
    assert text == "Ich bin Nikita in Weilburg (35781)."


def test_the_phone_profile_has_the_tools_of_phone_45_and_no_shell():
    settings = Settings()
    settings.agent.phone.tools = [*settings.agent.phone.tools, "shell", "ssh"]
    profile = phone_profile(settings, ROOT)
    assert {"get_current_time", "web_search", "get_weather", "calculate"} <= profile.tools
    assert not profile.tools & FORBIDDEN_TOOLS
    assert "Nikita" in profile.system_prompt and "{" not in profile.system_prompt
    assert "get_weather" in profile.system_prompt and "Weilburg (35781)" in profile.system_prompt
    assert profile.max_tool_steps == 3 and profile.deadline_s == 15


def test_the_prompt_names_every_tool_it_tells_the_model_to_use():
    prompt = phone_profile(Settings(), ROOT).system_prompt
    for name in ("get_current_time", "web_search", "get_weather", "get_warnings", "get_pollen",
                 "get_sun_moon", "calculate", "calendar_info"):  # fmt: skip
        assert name in prompt


# -- the loop ---------------------------------------------------------------------------------------
class Rig:
    """Scripted model + the real tool registry (clock, search stub, skill tools)."""

    def __init__(
        self, *, search: SearchOutcome | None = None, tools: set[str] | None = None, **profile
    ):
        self.model = FakeModel()
        self.client = InferenceClient("http://127.0.0.1:1", transport=self.model.transport())
        self.queue = InferenceQueue(self.client, preempt_wait_s=0.0)
        self.session = weather_session()
        from moritz_agent.skills.tools import skill_tools

        self.registry = ToolRegistry()
        self.registry.register(GetCurrentTime("Europe/Berlin", clock=lambda: SUNDAY_EVENING))
        self.registry.register(WebSearch(_Search(search or SearchOutcome("x"))))
        self.registry.register_all(skill_tools(self.session.router))
        base = {
            "name": "phone",
            "system_prompt": "Du bist Nikita.",
            "tools": frozenset(tools or self.registry.names()),
        }
        self.profile = Profile(**(base | profile))
        self.loop = AgentLoop(self.queue, self.registry, self.profile, context_size=4096)
        self.ctx = ToolContext(call_id="call-1", skills=self.session.ctx)

    def ask(self, text, history=()):
        return run(self.loop.run(text, list(history), self.ctx))

    def sent_roles(self, request=-1):
        return [m["role"] for m in self.model.requests[request]["messages"]]


class _Search:
    def __init__(self, outcome):
        self.outcome = outcome

    async def search(self, query, max_results=None):
        return self.outcome


def tools_offered(request):
    return [t["function"]["name"] for t in request.get("tools", [])]


def test_a_plain_answer_needs_one_request_and_is_made_speakable():
    rig = Rig()
    rig.model.script = [text_chunks("Hallo ", "**Moritz**! 😀 Wie ", "geht's?")]
    result = rig.ask("Hallo Nikita")
    assert result.text == "Hallo Moritz! Wie geht's?"
    assert result.steps == 0 and result.tools == [] and not result.hangup
    request = rig.model.requests[0]
    assert request["messages"][0] == {"role": "system", "content": "Du bist Nikita."}
    assert request["messages"][-1] == {"role": "user", "content": "Hallo Nikita"}
    assert "get_weather" in tools_offered(request) and request["max_tokens"] == 160


def test_history_goes_into_the_prompt_in_order():
    rig = Rig()
    rig.model.script = [text_chunks("Ok")]
    rig.ask("Und jetzt?", [("Hallo", "Hi"), ("Wie geht's", "Gut")])
    contents = [m["content"] for m in rig.model.requests[0]["messages"]]
    assert contents == ["Du bist Nikita.", "Hallo", "Hi", "Wie geht's", "Gut", "Und jetzt?"]


def test_a_tool_call_runs_and_its_result_goes_back_to_the_model():
    rig = Rig()
    rig.model.script = [
        tool_chunks("get_current_time", '{"kind": "time"}'),
        text_chunks("Es ist 19 Uhr 12."),
    ]
    result = rig.ask("Wie spät ist es?")
    assert result.text == "Es ist 19 Uhr 12." and result.tools == ["get_current_time"]
    assert result.steps == 1 and result.guard is None
    second = rig.model.requests[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "tool"]
    assistant, tool = second[2], second[3]
    assert assistant["tool_calls"][0]["function"]["name"] == "get_current_time"
    assert tool["tool_call_id"] == "call_1"
    payload = json.loads(tool["content"])
    assert payload["ok"] and payload["speakable"] == "Es ist 19 Uhr 12."


def test_a_skill_tool_brings_real_weather_data():
    rig = Rig()
    rig.model.script = [
        tool_chunks("get_weather", '{"place": "Frankfurt", "when": "morgen"}'),
        text_chunks("Morgen wird es wechselhaft bei 8 bis 13 Grad."),
    ]
    result = rig.ask("Wie wird das Wetter morgen in Frankfurt?")
    assert result.tools == ["get_weather"] and result.guard is None
    assert result.sources and result.sources[0]["name"].startswith("Open-Meteo")
    payload = json.loads(rig.model.requests[1]["messages"][-1]["content"])
    assert "Frankfurt" in payload["speakable"]


def test_web_search_results_and_sources_are_collected():
    hits = [
        SearchHit("Tagesschau", "https://tagesschau.de/a", "Meldung", "tagesschau.de", "searxng")
    ]
    rig = Rig(search=SearchOutcome("x", hits, "searxng", ["searxng"]))
    rig.model.script = [
        tool_chunks("web_search", '{"query": "Nachrichten"}'),
        text_chunks("Laut tagesschau.de gibt es eine Meldung."),
    ]
    result = rig.ask("Was gibt es Neues im Land?")
    assert result.tools == ["web_search"]
    assert result.sources == [
        {"name": "tagesschau.de", "url": "https://tagesschau.de/a", "backend": "searxng"}
    ]


def test_a_failing_search_is_reported_to_the_model_honestly():
    rig = Rig(search=SearchOutcome("x", errors={"searxng": "offline"}))
    rig.model.script = [
        tool_chunks("web_search", '{"query": "Nachrichten"}'),
        text_chunks("Ich kann gerade nichts nachschlagen."),
    ]
    result = rig.ask("Was gibt es Neues?")
    assert result.text == "Ich kann gerade nichts nachschlagen." and result.tools == []
    payload = json.loads(rig.model.requests[1]["messages"][-1]["content"])
    assert payload["ok"] is False and payload["error"] == "search_unavailable"


def test_invalid_arguments_let_the_model_try_again_but_only_twice():
    rig = Rig()
    bad = tool_chunks("web_search", "{}")
    rig.model.script = [bad, bad, bad, text_chunks("Ich weiß es nicht.")]
    result = rig.ask("Suche etwas")
    assert result.text == "Ich weiß es nicht."
    # after the second invalid call no tools are offered any more
    assert [bool(r.get("tools")) for r in rig.model.requests] == [True, True, True, False]


def test_at_most_three_tool_steps_then_the_model_must_answer():
    rig = Rig()
    call = tool_chunks("get_current_time", "{}")
    rig.model.script = [call, call, call, text_chunks("Es ist spät.")]
    result = rig.ask("Wie spät ist es wohl?")
    assert result.steps == 3 and result.text == "Es ist spät."
    assert [bool(r.get("tools")) for r in rig.model.requests] == [True, True, True, False]


def test_unknown_and_forbidden_tools_are_refused_without_running():
    rig = Rig(tools={"get_current_time"})
    rig.model.script = [tool_chunks("get_weather", "{}"), text_chunks("Das weiß ich nicht.")]
    result = rig.ask("Wetter?")
    assert result.tools == []
    payload = json.loads(rig.model.requests[1]["messages"][-1]["content"])
    assert payload["error"] == "unknown_tool"
    assert tools_offered(rig.model.requests[0]) == ["get_current_time"]


def test_a_stated_time_is_replaced_by_the_clock_tool():
    rig = Rig()
    rig.model.script = [text_chunks("Es ist 15 Uhr 30, glaube ich.")]
    result = rig.ask("Wie spät ist es?")
    assert result.text == "Es ist 19 Uhr 12." and result.guard == "time"
    assert result.tools == ["get_current_time"]
    assert len(rig.model.requests) == 1  # the clock needs no second model round


def test_a_date_question_gets_the_date_from_the_tool():
    rig = Rig()
    rig.model.script = [text_chunks("Heute ist der 3. März, um 12:00 Uhr.")]
    result = rig.ask("Welches Datum haben wir heute? Wie spät ist es?")
    assert "Sonntag, der 18. Oktober 2026" in result.text and result.guard == "time"


def test_invented_weather_is_repaired_with_the_weather_tool():
    rig = Rig()
    rig.model.script = [
        text_chunks("Morgen werden es 25 Grad und sonnig."),
        text_chunks("Morgen wird es wechselhaft bei 8 bis 13 Grad."),
    ]
    result = rig.ask("Wie wird das Wetter morgen?")
    assert result.guard == "weather" and result.tools == ["get_weather"]
    assert result.text == "Morgen wird es wechselhaft bei 8 bis 13 Grad."
    repair = rig.model.requests[1]["messages"]
    assert repair[-2]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert json.loads(repair[-2]["tool_calls"][0]["function"]["arguments"]) == {
        "question": "Wie wird das Wetter morgen?"
    }
    assert "tools" not in rig.model.requests[1]  # reword only, no more tool calls


def test_if_the_model_ignores_the_weather_result_the_tool_sentence_wins():
    rig = Rig()
    rig.model.script = [
        text_chunks("Morgen werden es 25 Grad."),
        text_chunks("Es bleibt dabei: 25 Grad Wetter."),
    ]
    result = rig.ask("Wie wird das Wetter morgen?")
    assert result.tools == ["get_weather"] and result.guard == "weather_mismatch"
    assert "25" not in result.text and "Grad" in result.text  # the sentence of the weather skill


def test_a_wrong_number_after_a_correct_tool_call_is_replaced_too():
    rig = Rig()
    rig.model.script = [
        tool_chunks("get_weather", '{"place": "Frankfurt", "when": "morgen"}'),
        text_chunks("Morgen werden es 21 Grad in Frankfurt."),
    ]
    result = rig.ask("Wie wird das Wetter morgen in Frankfurt?")
    assert result.guard == "weather_mismatch" and "21" not in result.text
    assert "Frankfurt" in result.text


def test_numbers_that_the_tool_delivered_pass_in_any_notation():
    rig = Rig()
    rig.model.script = [
        tool_chunks("get_weather", '{"place": "Frankfurt", "when": "morgen"}'),
        text_chunks("Morgen gibt es 8 bis 13 Grad, am Vormittag Schauer."),
    ]
    result = rig.ask("Wie wird das Wetter morgen in Frankfurt?")
    assert result.guard is None and result.text.startswith("Morgen gibt es 8 bis 13 Grad")


def test_a_question_that_is_no_weather_question_keeps_the_models_answer():
    rig = Rig()
    rig.model.script = [text_chunks("Lava ist heiß, etwa 1200 Grad.")]
    result = rig.ask("Wie heiß ist Lava?")
    assert result.text == "Lava ist heiß, etwa 1200 Grad." and result.guard is None
    assert result.tools == []


def test_when_the_weather_data_is_missing_the_answer_is_honest_not_invented():
    rig = Rig()
    rig.session.svc.providers = None  # no data service at all
    rig.model.script = [text_chunks("Es hat 25 Grad."), text_chunks("Es hat 25 Grad.")]
    result = rig.ask("Wie warm ist es draußen?")
    assert "25" not in result.text and "Wetterdaten" in result.text
    assert result.guard == "weather_mismatch"


def test_a_profile_without_the_tool_cannot_repair_and_says_so():
    rig = Rig(tools={"web_search"})
    rig.model.script = [text_chunks("Es ist 15 Uhr 30.")]
    result = rig.ask("Wie spät ist es?")
    assert "nicht sicher" in result.text and result.guard == "time"


def test_the_deadline_stops_the_generation_and_answers_honestly():
    rig = Rig(deadline_s=0.2)
    rig.model.gate = True

    async def scenario():
        task = asyncio.create_task(rig.loop.run("Frage", [], rig.ctx))
        result = await task
        return result

    result = run(scenario())
    assert result.text == DEADLINE_TEXT and result.failure == "deadline"
    assert rig.model.abort_calls  # the model server was told to stop


def test_cancelling_the_turn_stops_the_generation():
    rig = Rig()
    rig.model.gate = True

    async def scenario():
        task = asyncio.create_task(rig.loop.run("Frage", [], rig.ctx))
        await rig.model.wait_for_running()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)

    run(scenario())
    assert len(rig.model.abort_calls) == 1


def test_an_empty_answer_falls_back_to_the_last_tool_sentence():
    rig = Rig()
    rig.model.script = [tool_chunks("get_current_time", '{"kind": "time"}'), text_chunks("")]
    result = rig.ask("Uhrzeit bitte")
    assert result.text == "Es ist 19 Uhr 12."
    rig2 = Rig()
    rig2.model.script = [text_chunks("   ")]
    assert rig2.ask("Hmm").failure == "empty"


def test_farewells_hang_up():
    rig = Rig()
    rig.model.script = [text_chunks("Tschüss, Moritz!")]
    assert rig.ask("Danke, tschüss!").hangup is True


# -- the responder ----------------------------------------------------------------------------------
def test_the_responder_hands_the_conversation_to_the_loop():
    rig = Rig()
    rig.model.script = [text_chunks("Gerne.")]
    responder = AgentResponder(rig.loop)
    context = TurnContext(call_id="c9", history=[("Hallo", "Hi")])
    context.extras["skills"] = rig.session.ctx
    reply = run(responder.respond("Danke", context))
    assert reply.text == "Gerne."
    assert [m["content"] for m in rig.model.requests[0]["messages"]][1:] == ["Hallo", "Hi", "Danke"]


def test_the_responder_reports_an_unreachable_model():
    rig = Rig()
    rig.model.script = [503]
    with pytest.raises(ResponderUnavailable):
        run(AgentResponder(rig.loop).respond("Hallo", TurnContext(call_id="c")))


def test_a_date_at_the_start_of_a_line_is_not_a_list_marker():
    from moritz_agent.agent.speakable import clean

    assert clean("3. Oktober ist der Tag der Deutschen Einheit.").startswith("3. Oktober")
    assert clean("1. Erst das\n2. Dann das") == "Erst das. Dann das"

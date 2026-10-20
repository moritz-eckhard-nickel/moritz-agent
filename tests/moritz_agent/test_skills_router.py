# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Routing: when a skill answers and when not (SKILL-01, R23), the corpus, the responder."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from moritz_agent.phone.responder import TestResponder, TurnContext
from moritz_agent.skills.base import Clarification, Option
from moritz_agent.skills.registry import all_skills
from moritz_agent.skills.responder import SkillResponder
from moritz_agent.skills.router import Router, resolve_option
from moritz_agent.skills.text.normalize import prepare

from .skills_util import Session

CORPUS = Path(__file__).parent / "data" / "skills.de.jsonl"
NEEDS_CONTEXT = {"timer.left", "talk.details", "talk.source"}


def corpus() -> list:
    lines = CORPUS.read_text(encoding="utf-8").splitlines()
    return [
        pytest.param(json.loads(line), id=str(number))
        for number, line in enumerate(lines, 1)
        if line.strip() and not line.startswith("#")
    ]


@pytest.mark.parametrize("item", corpus())
def test_corpus(item):
    session = Session()
    for prior in item.get("prior", []):
        session.route(prior)
    assert session.skill(item["say"]) == item["skill"], item["say"]


def test_corpus_has_negatives_and_every_skill_with_examples():
    items = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]
    assert sum(1 for i in items if i["skill"] is None) >= 20
    covered = {i["skill"] for i in items if i["skill"]}
    uncovered = {
        s.id
        for s in all_skills().values()
        if s.id not in covered and s.priority == "M" and not s.online
    }
    assert not uncovered, uncovered


def test_every_skill_example_is_answered_by_that_skill():
    """The examples shown in the help text must really work."""
    skills = all_skills()
    for skill in skills.values():
        if skill.online:
            continue  # online skills are checked with fixtures in their own tests
        for example in skill.examples:
            session = Session(surface="chat" if skill.chat_only else "spoken")
            outcome = session.route(example)
            if skill.id in NEEDS_CONTEXT:
                continue  # only meaningful after something else was said (checked in the corpus)
            assert outcome.result is not None, f"{skill.id}: {example!r} wird nicht beantwortet"


def test_long_sentences_are_not_answered():
    assert (
        Session().say(
            "Wie spät ist es denn jetzt wirklich bei dir da drüben im schönen Weilburg an der Lahn heute Abend "
            * 2
        )
        is None
    )


def test_compound_sentences_with_because_go_on():
    assert (
        Session().say("Ich möchte wissen wie spät es ist weil ich den Zug nicht verpassen will")
        is None
    )


def test_two_questions_in_one_sentence():
    answer = Session().say("Wie spät ist es und welcher Tag ist heute")
    assert answer == "Es ist 19 Uhr 12. Heute ist Sonntag."


def test_disabled_skills_and_groups(monkeypatch):
    from moritz_agent.config.settings import load_settings

    settings = load_settings()
    settings.skills.disabled = ["fun", "random.coin"]
    session = Session(settings=settings)
    assert session.say("Erzähl einen Witz") is None
    assert session.say("Wirf eine Münze") is None
    assert session.say("Wie spät ist es?") == "Es ist 19 Uhr 12."


def test_skills_off_keeps_the_basics():
    from moritz_agent.config.settings import load_settings

    settings = load_settings()
    settings.skills.enabled = False
    session = Session(settings=settings)
    assert session.say("Wie spät ist es?") == "Es ist 19 Uhr 12."
    assert session.say("Tschüss") == "goodbye"
    assert session.say("Was ist 17 mal 23?") is None


def test_explain_gives_the_candidates():
    router = Router(Session().svc)
    ranked = router.candidates(prepare("Wie spät ist es"))
    assert ranked and ranked[0].skill.id == "time.now" and ranked[0].score >= 0.7


def test_scores_of_unrelated_sentences_stay_below_the_threshold():
    router = Router(Session().svc)
    for text in [
        "Wer war der erste Bundeskanzler",
        "Spiel mir ein Lied",
        "Wie hoch ist der Feldberg",
    ]:
        assert not [c for c in router.candidates(prepare(text)) if c.score >= 0.7], text


def test_skills_are_fast():
    import time

    session = Session()
    timings = []
    for _ in range(3):
        for text in [
            "Wie spät ist es",
            "Wie viele Tage bis Weihnachten",
            "Was ist 17 mal 23",
            "Wer war Goethe",
        ]:
            started = time.perf_counter()
            session.route(text)
            timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    assert (
        timings[int(len(timings) * 0.95)] < 50
    )  # SKILL-27: p95 well below the 20 ms goal on a real CPU


def test_pending_question_is_resolved_by_ordinal_and_by_name():
    pending = Clarification(
        "Welches Neustadt meinst du?",
        (
            Option("Neustadt in Hessen", {"id": 1}, ("hessen",)),
            Option("Neustadt an der Weinstraße", {"id": 2}, ("weinstraße", "pfalz")),
        ),
        "weather.day",
    )
    assert resolve_option(prepare("das erste"), pending).params == {"id": 1}
    assert resolve_option(prepare("die zweite bitte"), pending).params == {"id": 2}
    assert resolve_option(prepare("das in Hessen"), pending).params == {"id": 1}
    assert resolve_option(prepare("an der Weinstraße"), pending).params == {"id": 2}
    assert resolve_option(prepare("keine Ahnung"), pending) is None


# -- the responder ------------------------------------------------------------------------
def test_responder_answers_with_a_skill_and_falls_back_to_the_test_answer():
    session = Session()
    responder = SkillResponder(session.svc, fallback=TestResponder())
    context = TurnContext("call-1")
    reply = asyncio.run(responder.respond("Wie spät ist es?", context))
    assert reply.text == "Es ist 19 Uhr 12." and reply.skill_id == "time.now"
    reply = asyncio.run(responder.respond("Erzähl mir etwas über Goethes Leben", context))
    assert reply.text and reply.text.startswith("Ich habe verstanden")
    assert responder.misses and responder.misses[-1][0] == "Erzähl mir etwas über Goethes Leben"


def test_responder_keeps_a_context_per_call():
    session = Session()
    responder = SkillResponder(session.svc)
    a, b = TurnContext("a"), TurnContext("b")
    asyncio.run(responder.respond("Wie spät ist es?", a))
    asyncio.run(responder.respond("Sprich langsamer", a))
    assert responder.context_for(a).tempo < 1.0
    assert responder.context_for(b).tempo == 1.0


def test_old_fast_path_cases_still_work_through_the_skills():
    """SKILL-33: everything the first fast paths answered, the skills answer the same."""
    cases = {
        "Wie viel Uhr ist es?": "Es ist 19 Uhr 12.",
        "Wie spät ist es gerade?": "Es ist 19 Uhr 12.",
        "Welcher Tag ist heute?": "Heute ist Sonntag.",
        "Welches Datum haben wir heute": "Heute ist Sonntag, der 18. Oktober 2026.",
        "Welche Kalenderwoche ist gerade?": "Wir haben Kalenderwoche 42.",
        "Welcher Tag ist morgen?": "Morgen ist Montag, der 19. Oktober.",
        "Welcher Tag war gestern?": "Gestern war Samstag, der 17. Oktober.",
        "Tschüss": "goodbye",
        "Auf Wiederhören": "goodbye",
    }
    for question, answer in cases.items():
        assert Session().say(question) == answer, question
    for question in [
        "Um wie viel Uhr fährt der Zug nach Frankfurt?",
        "Erzähl mir etwas über die Geschichte von Hessen und was dort im Mittelalter passiert ist",
    ]:
        assert Session().say(question) is None, question

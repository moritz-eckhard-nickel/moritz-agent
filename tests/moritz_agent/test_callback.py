# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Anton calls back: "Sag mir am Telefon, wie viel Uhr es ist" on Discord (Moritz, 21.10.2026)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from moritz_agent.core.callback import CallbackQueue, phone_request
from moritz_agent.core.principal import Role
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn
from moritz_agent.phone.callback import GOODBYE, CallbackSession
from moritz_agent.phone.sip import dial_uri

from .skills_util import Session
from .system_util import OWNER_ID, TRUSTED_ID, running_system


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    ("text", "question"),
    [
        ("Sag mir am Telefon wie viel Uhr es ist", "wie viel uhr es ist"),
        ("sag mir bitte übers Telefon, wie das Wetter morgen wird", "wie das wetter morgen wird"),
        ("Ruf mich an und sag mir, was 19 Prozent von 250 sind", "was 19 prozent von 250 sind"),
        ("Wie spät ist es? Sag es mir am Telefon", "wie spät ist es"),
        ("Anton, erzähl mir am Telefon einen Witz", "einen witz"),
        ("Wie spät ist es?", None),
        ("Was hast du am Telefon gesagt?", None),
        ("Ruf mich an", None),  # nothing to say
    ],
)
def test_a_call_back_is_only_asked_for_with_something_to_say(text, question):
    assert phone_request(text) == question


def test_the_queue_hands_out_each_call_once_and_keeps_it_small():
    queue = CallbackQueue()
    first = queue.add("Es ist 19 Uhr 12.", "201", (10, 15), 1.0)
    assert first is not None and 10 <= first.ring_s <= 15
    assert all(queue.add("x", "201", (10, 15), 1.0) for _ in range(2))
    assert queue.add("zu viel", "201", (10, 15), 1.0) is None  # at most three waiting
    taken = queue.take()
    assert taken is first and queue.done(first.id) is first and queue.done(first.id) is None


def test_the_number_to_dial_lives_at_the_registrar():
    assert dial_uri("201", "192.168.1.176") == "sip:201@192.168.1.176"
    assert dial_uri("201", "pbx.local", 5070, "tcp") == "sip:201@pbx.local:5070;transport=tcp"


# -- main process: Discord text → call order → outcome ----------------------------------------------------------
def _turn(system, user, text, *, role, surface=Surface.CHAT, place="dm"):
    person = system.runtime.chat.principal(user, role, "Test")
    return Turn(
        text, person, surface, f"discord:{place}:{user}", place=place, reply_target=f"dm:{user}"
    )


def test_written_on_discord_the_answer_goes_to_the_phone_worker_and_nowhere_else(tmp_path):
    async def body(system):
        runtime = system.runtime
        answer = await runtime.chat.run(
            _turn(system, OWNER_ID, "Sag mir am Telefon wie viel Uhr es ist", role=Role.OWNER)
        )
        async with system.client(internal=True) as client:
            headers = system.internal_headers()
            order = (await client.get("/internal/phone/callback", headers=headers)).json()["call"]
            empty = (await client.get("/internal/phone/callback", headers=headers)).json()["call"]
            await client.post(
                "/internal/phone/event",
                json={
                    "call_id": f"callback-{order['id']}",
                    "event": "callback_done",
                    "reason": "no_answer",
                },
                headers=headers,
            )
        pending = runtime.discord_store.pending(runtime.svc.now() + timedelta(days=1), limit=10)
        return answer, order, empty, pending

    answer, order, empty, pending = run(_in(tmp_path, body))
    assert answer.text == "Okay, ich rufe dich an."
    assert order["extension"] == "201" and "19 Uhr 12" in order["text"]
    assert 10 <= order["ring_s"] <= 15 and order["speak_after_s"] == 1.0
    assert empty is None
    assert not [p for p in pending if p["kind"] == "forward"]  # nobody picked up: nothing else


@pytest.mark.parametrize(
    ("user", "role", "surface", "place"),
    [
        (TRUSTED_ID, Role.TRUSTED, Surface.CHAT, "dm"),  # only the owner
        (OWNER_ID, Role.OWNER, Surface.SPOKEN, "voice"),  # said in the voice channel: no call
        (OWNER_ID, Role.OWNER, Surface.CHAT, "voice"),  # the voice channel's text chat
    ],
)
def test_no_call_back_from_others_or_from_talking(tmp_path, user, role, surface, place):
    async def body(system):
        result = await system.runtime.chat.run(
            _turn(
                system,
                user,
                "Sag mir am Telefon wie viel Uhr es ist",
                role=role,
                surface=surface,
                place=place,
            )
        )
        return result, system.runtime.callbacks.take()

    result, order = run(_in(tmp_path, body))
    assert order is None and "rufe dich" not in result.text


async def _in(tmp_path, body):
    async with running_system(tmp_path, discord=True) as system:
        return await body(system)


# -- phone worker: the call itself -----------------------------------------------------------------------------
class FakeMedia:
    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.hung_up: str | None = None

    def play(self, pcm: bytes) -> None:
        self.played.append(pcm)

    def clear_playback(self) -> None:
        pass

    def pending_ms(self) -> int:
        return 0

    def hangup(self, reason: str) -> None:
        self.hung_up = reason

    def rx_packets(self) -> int | None:
        return None


class FakeTts:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def stream(self, text: str, **_):
        self.said.append(text)
        yield b"\x00\x00" * 160

    def cancel(self) -> None:
        pass


def test_picked_up_anton_waits_says_it_says_goodbye_and_hangs_up_without_listening():
    async def scenario():
        media, tts = FakeMedia(), FakeTts()
        session = CallbackSession(
            media, tts, "Es ist 19 Uhr 12.", speak_after_s=0.2, tail_guard_ms=0
        )
        loop = asyncio.get_running_loop()
        started = loop.time()
        session.rx_audio(b"\x01\x02" * 400)  # "Hallo?" – dropped, nothing listens
        outcome = await session.run()
        return outcome, loop.time() - started, media, tts

    outcome, took, media, tts = run(scenario())
    assert outcome == "done" and took >= 0.2
    assert tts.said == [f"Es ist 19 Uhr 12. {GOODBYE}"] and media.played
    assert media.hung_up == "callback_done"


def test_hanging_up_before_anton_speaks_ends_it_quietly():
    async def scenario():
        media, tts = FakeMedia(), FakeTts()
        session = CallbackSession(media, tts, "Es ist 19 Uhr 12.", speak_after_s=1.0)
        asyncio.get_running_loop().call_later(0.05, session.remote_hangup)
        return await session.run(), media, tts

    outcome, media, tts = run(scenario())
    assert outcome == "caller_hangup" and not tts.said and media.hung_up is None


# -- "Leg auf" in a call ---------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Leg auf",
        "Leg bitte auf",
        "Anton, leg auf",
        "Okay, du kannst jetzt auflegen",
        "Kannst du auflegen?",
        "Häng jetzt auf, danke",
    ],
)
def test_leg_auf_meant_as_such_hangs_up_politely(text):
    outcome = Session().route(text)
    assert outcome.skill_id == "talk.goodbye" and outcome.result is not None
    assert outcome.result.hangup and "lege auf" in outcome.result.text


@pytest.mark.parametrize(
    "text",
    [
        "Wie leg ich den Hörer auf?",
        "Leg nicht auf",
        "Soll ich auflegen?",
        "Leg das Handy auf den Tisch",
        "Wann legst du auf?",
    ],
)
def test_leg_auf_only_mentioned_does_not_hang_up(text):
    outcome = Session().route(text)
    assert outcome.result is None or not outcome.result.hangup

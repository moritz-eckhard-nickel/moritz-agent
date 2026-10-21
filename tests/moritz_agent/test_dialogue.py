# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Whole calls through the real CallSession with fake media, VAD, STT and voice."""

from __future__ import annotations

import asyncio
from pathlib import Path

from moritz_agent.config.settings import Phone
from moritz_agent.phone.audio.announcements import AnnouncementStore, Prompt
from moritz_agent.phone.audio.tts import TtsService
from moritz_agent.phone.dialogue import CallSession, SessionDeps
from moritz_agent.phone.responder import Reply, ResponderUnavailable, TestResponder, TurnContext
from moritz_agent.phone.state_machine import State

from .fakes import FakeEngine, FakeMedia, FakeStt, FakeVad, silence_frames, speech_frames

PROMPTS = {
    pid: Prompt(pid, text, True)
    for pid, text in {
        "greeting": "Hallo Moritz, hier ist Nikita.",
        "not_understood": "Das habe ich nicht verstanden.",
        "not_understood_again": "Ich verstehe dich schlecht.",
        "still_there": "Bist du noch da?",
        "goodbye": "Alles klar, bis bald!",
        "thinking": "Moment, ich schaue nach.",
        "error_generic": "Ich habe eine Störung.",
        "timeout": "Das dauert zu lange.",
    }.items()
}


class SlowResponder:
    def __init__(self, delay: float, text: str = "Fertig.") -> None:
        self.delay, self.text, self.started, self.cancelled = delay, text, 0, 0

    async def respond(self, text: str, context: TurnContext) -> Reply:
        self.started += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return Reply(text=self.text)


class BrokenResponder:
    async def respond(self, text: str, context: TurnContext) -> Reply:
        raise ResponderUnavailable("Sprachmodell nicht erreichbar")


class Harness:
    """A call plus a caller who feeds 20 ms frames in real time."""

    def __init__(self, tmp_path: Path, stt: FakeStt, responder, **phone_overrides) -> None:
        settings = {
            "silence_prompt_s": 0.6,
            "silence_hangup_s": 0.6,
            "thinking_prompt_after_s": 0.3,
            "turn_deadline_s": 2.0,
            "playback_tail_guard_ms": 20,
            "media_dead_timeout_s": 5.0,
            "max_unclear_hangup": 3,
        }
        settings.update(phone_overrides)
        phone = Phone(**settings)
        self.engine = FakeEngine()
        self.tts = TtsService({"fake": self.engine}, "fake", [], tmp_path / "cache")
        self.store = AnnouncementStore(self.tts, PROMPTS)
        assert self.store.ensure() == []
        self.baseline = len(self.engine.calls)  # announcements rendered before the call
        self.media = FakeMedia()
        self.stt, self.responder = stt, responder
        self.deps = SessionDeps(phone, stt, FakeVad(), self.tts, self.store, responder)
        self.session: CallSession | None = None
        self._script: asyncio.Queue[list[bytes]] = asyncio.Queue()
        self._feeder: asyncio.Task | None = None
        self.send_noise_while_speaking = False

    async def start(self) -> asyncio.Task:
        self.session = CallSession("test-call", self.media, self.deps, "sip:20@test")
        self._feeder = asyncio.ensure_future(self._feed())
        return asyncio.ensure_future(self.session.run())

    async def _feed(self) -> None:
        while True:
            try:
                frames = self._script.get_nowait()
            except asyncio.QueueEmpty:
                frames = silence_frames(1)
            for frame in frames:
                self.session.rx_audio(frame)
                await asyncio.sleep(0.004)  # faster than real time keeps the tests quick

    async def say(self, frames: int = 14) -> None:
        await self.wait_for(lambda: self.session._listening, "Zuhören")
        self._script.put_nowait(speech_frames(frames) + silence_frames(10))

    async def wait_for(self, condition, what: str, timeout: float = 6.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not condition():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"Zeitüberschreitung beim Warten auf: {what}")
            await asyncio.sleep(0.01)

    def played(self, prompt_id: str) -> bool:
        return self.store.get(prompt_id) in self.media.played

    async def finish(self, task: asyncio.Task) -> str:
        reason = await asyncio.wait_for(task, 8)
        assert self._feeder is not None
        self._feeder.cancel()
        return reason


def run(coroutine):
    return asyncio.run(coroutine)


def test_complete_call_with_three_turns_and_goodbye(tmp_path):
    async def scenario():
        h = Harness(
            tmp_path,
            FakeStt(
                "Wie viel Uhr haben wir?",
                "Welches Datum ist heute?",
                "Wie wird das Wetter?",
                "Tschüss",
            ),
            TestResponder(),
        )
        task = await h.start()
        await h.wait_for(lambda: h.played("greeting"), "Begrüßung")
        assert h.session.state is State.GREETING or h.session.state is State.LISTENING
        for _ in range(3):
            before = len(h.media.played)
            await h.say()
            await h.wait_for(lambda b=before: len(h.media.played) > b, "Antwort")
            await h.wait_for(lambda: h.session.state is State.LISTENING, "wieder zuhören")
        await h.say()
        reason = await h.finish(task)
        return h, reason

    h, reason = run(scenario())
    assert reason == "goodbye" and h.media.hung_up == "goodbye"
    assert h.played("goodbye")
    assert h.session.machine.turns == 4
    spoken = " ".join(h.engine.calls)
    assert "Uhr" in spoken and "Ich habe verstanden: Wie wird das Wetter" in spoken
    assert h.media.cleared >= 1


def test_time_answer_comes_from_the_clock_not_the_model(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt("Wie viel Uhr haben wir?"), TestResponder())
        task = await h.start()
        await h.say()
        await h.wait_for(lambda: any("Uhr" in c for c in h.engine.calls), "Uhrzeit")
        h.session.remote_hangup()
        await h.finish(task)
        return h

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from moritz_agent.phone.audio.textnorm import normalize_for_tts
    from moritz_agent.tools.time_tool import format_time_de

    before = normalize_for_tts(format_time_de(datetime.now(ZoneInfo("Europe/Berlin"))))
    h = run(scenario())
    after = normalize_for_tts(format_time_de(datetime.now(ZoneInfo("Europe/Berlin"))))
    spoken = next(c for c in h.engine.calls if "Uhr" in c)
    assert spoken in (before, after)


def test_silence_leads_to_one_question_then_hangup(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt("x"), TestResponder())
        task = await h.start()
        return h, await h.finish(task)

    h, reason = run(scenario())
    assert reason == "silence_timeout" and h.media.hung_up == "silence_timeout"
    order = [h.store.get("still_there"), h.store.get("goodbye")]
    positions = [h.media.played.index(p) for p in order]
    assert positions == sorted(positions)


def test_unintelligible_speech_triggers_reprompts_then_goodbye(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt(""), TestResponder())
        task = await h.start()
        for _ in range(3):
            await h.say()
            await h.wait_for(lambda: h.session.state in (State.SPEAKING, State.ENDING), "Rückfrage")
            await h.wait_for(
                lambda: h.session.state in (State.LISTENING, State.ENDED, State.ENDING), "danach"
            )
        return h, await h.finish(task)

    h, reason = run(scenario())
    assert reason == "unintelligible"
    assert h.played("not_understood") and h.played("goodbye")


def test_slow_answer_gets_a_thinking_prompt_first(tmp_path):
    async def scenario():
        h = Harness(
            tmp_path,
            FakeStt("Erzähl mir etwas Langes"),
            SlowResponder(0.8, "Hier ist die Antwort."),
        )
        task = await h.start()
        await h.say()
        await h.wait_for(lambda: h.played("thinking"), "Zwischenansage")
        await h.wait_for(
            lambda: any("Hier ist die Antwort" in c for c in h.engine.calls), "Antwort"
        )
        h.session.remote_hangup()
        await h.finish(task)
        return h

    h = run(scenario())
    assert h.played("thinking")


def test_answer_after_the_deadline_is_replaced_by_an_apology(tmp_path):
    async def scenario():
        responder = SlowResponder(30)
        h = Harness(tmp_path, FakeStt("Sehr schwere Frage"), responder)
        task = await h.start()
        await h.say()
        await h.wait_for(lambda: h.played("timeout"), "Entschuldigung")
        h.session.remote_hangup()
        await h.finish(task)
        return h, responder

    _h, responder = run(scenario())
    assert responder.cancelled == 1


def test_unreachable_responder_speaks_an_error_and_the_call_goes_on(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt("Frag irgendwas"), BrokenResponder())
        task = await h.start()
        await h.say()
        await h.wait_for(lambda: h.played("error_generic"), "Fehleransage")
        await h.wait_for(lambda: h.session.state is State.LISTENING, "weiter zuhören")
        h.session.remote_hangup()
        return await h.finish(task)

    assert run(scenario()) == "caller_hangup"


def test_hangup_during_the_answer_cancels_everything(tmp_path):
    async def scenario():
        responder = SlowResponder(30)
        h = Harness(tmp_path, FakeStt("Lange Frage"), responder)
        task = await h.start()
        await h.say()
        await h.wait_for(lambda: responder.started == 1, "Antwort läuft")
        h.session.remote_hangup()
        reason = await h.finish(task)
        return h, responder, reason

    h, responder, reason = run(scenario())
    assert reason == "caller_hangup"
    assert responder.cancelled == 1
    assert h.media.cleared >= 1 and h.media.hung_up is None  # the caller hung up, no BYE from us
    assert not h.session._tasks


def test_hangup_while_speaking_stops_the_synthesis(tmp_path):
    async def scenario():
        h = Harness(
            tmp_path,
            FakeStt("Erzähl was"),
            SlowResponder(0.0, "Satz eins. Satz zwei. Satz drei. Satz vier."),
        )
        h.engine.delay = 0.4  # every sentence takes a while
        task = await h.start()
        await h.say()
        await h.wait_for(lambda: len(h.engine.calls) >= 1, "Synthese läuft")
        h.session.remote_hangup()
        await h.finish(task)
        return h

    h = run(scenario())
    assert len(h.engine.calls) - h.baseline < 4  # the remaining sentences were never synthesized


def test_speech_during_our_own_playback_is_ignored(tmp_path):
    async def scenario():
        stt = FakeStt("Hallo")
        h = Harness(tmp_path, stt, SlowResponder(0.0, "Antwort."))
        h.media.speedup = 0.5  # slow playback: the greeting lasts several seconds
        task = await h.start()
        await h.wait_for(lambda: h.played("greeting"), "Begrüßung")
        h._script.put_nowait(
            speech_frames(14) + silence_frames(10)
        )  # caller talks over the greeting
        await asyncio.sleep(0.5)
        h.session.remote_hangup()
        await h.finish(task)
        return stt

    assert run(scenario()).calls == 0


def test_media_timeout_ends_a_dead_call(tmp_path):
    async def scenario():
        h = Harness(
            tmp_path, FakeStt("x"), TestResponder(), silence_prompt_s=30, silence_hangup_s=30
        )
        h.deps.phone.media_dead_timeout_s = 1.2
        task = await h.start()
        assert h._feeder is not None
        h._feeder.cancel()  # no more audio arrives
        return await asyncio.wait_for(task, 8)

    assert run(scenario()) == "media_timeout"


def test_packet_counter_detects_dead_media_even_though_frames_keep_coming(tmp_path):
    async def scenario():
        h = Harness(
            tmp_path, FakeStt("x"), TestResponder(), silence_prompt_s=30, silence_hangup_s=30
        )
        h.deps.phone.media_dead_timeout_s = 1.2
        h.media.packets = 100  # the RTP packet counter never moves; silence frames keep ticking
        task = await h.start()
        reason = await asyncio.wait_for(task, 8)
        assert h._feeder is not None
        h._feeder.cancel()
        return reason

    assert run(scenario()) == "media_timeout"


def test_without_speech_recognition_the_call_gets_a_fault_announcement(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt("x"), TestResponder())
        h.deps.stt = None
        task = await h.start()
        reason = await h.finish(task)
        return h, reason

    h, reason = run(scenario())
    assert reason == "out_of_service" and h.media.hung_up == "out_of_service"
    assert h.played("error_generic") and not h.played("greeting")


class RecordingResponder:
    """Remembers the call life cycle messages the dialogue sends to a remote responder."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    async def respond(self, text: str, context: TurnContext) -> Reply:
        return Reply(text="Alles klar.", hangup=True)

    def call_started(self, call_id: str, remote: str = "") -> None:
        self.events.append(("started", call_id, remote))

    def call_ended(self, call_id: str, reason: str = "") -> None:
        self.events.append(("ended", call_id, reason))


def test_the_responder_is_told_when_a_call_begins_and_ends(tmp_path):
    async def scenario():
        responder = RecordingResponder()
        h = Harness(tmp_path, FakeStt("Danke, tschüss"), responder)
        task = await h.start()
        await h.wait_for(lambda: h.played("greeting"), "Begrüßung")
        await h.say()
        reason = await h.finish(task)
        return responder.events, reason

    events, reason = run(scenario())
    assert events == [("started", "test-call", "sip:20@test"), ("ended", "test-call", reason)]


# -- Discord voice (docs/plan/14 §9) ---------------------------------------------------------------------------------
def test_a_session_woken_from_rest_says_yes_instead_of_the_greeting(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt("x"), TestResponder())
        h.store.catalog["yes"] = Prompt("yes", "Ja?", False)
        h.store.ensure()
        h.session = CallSession("c", h.media, h.deps, first_prompt="yes")
        h._feeder = asyncio.ensure_future(h._feed())
        task = asyncio.ensure_future(h.session.run())
        await h.wait_for(lambda: h.played("yes"), "Ja?")
        h.session.remote_hangup()
        await h.finish(task)
        return h

    h = run(scenario())
    assert not h.played("greeting")


def test_falling_silent_says_the_going_quiet_line(tmp_path):
    async def scenario():
        h = Harness(tmp_path, FakeStt("x"), TestResponder())
        h.store.catalog["going_quiet"] = Prompt("going_quiet", "Ich bin dann mal still.", False)
        h.store.ensure()
        h.session = CallSession("c", h.media, h.deps, silence_goodbye="going_quiet")
        h._feeder = asyncio.ensure_future(h._feed())
        task = asyncio.ensure_future(h.session.run())
        return h, await h.finish(task)

    h, reason = run(scenario())
    assert reason == "silence_timeout" and h.played("going_quiet") and not h.played("goodbye")


def test_talking_over_the_answer_stops_it_and_the_first_words_are_not_lost(tmp_path):
    async def scenario():
        stt = FakeStt("Wie spät ist es?", "Und wie ist das Datum?")
        h = Harness(tmp_path, stt, SlowResponder(0.0, "Das ist eine lange Antwort. " * 3))
        h.media.speedup = 0.5  # slow playback: the answer lasts a while
        task = await h.start()
        await h.wait_for(lambda: h.played("greeting"), "Begrüßung")
        await h.wait_for(lambda: h.session.state is State.LISTENING, "zuhören")
        await h.say()
        await h.wait_for(lambda: h.session.state is State.SPEAKING, "Antwort läuft")
        cleared = h.media.cleared
        h.session.barge_in(speech_frames(10)[0] * 10 + silence_frames(1)[0] * 10)
        # the replayed first words are enough for a complete utterance: it is recognised at once
        await h.wait_for(lambda: stt.calls >= 2, "die Unterbrechung wird erkannt")
        h.session.remote_hangup()
        await h.finish(task)
        return h, cleared, stt

    h, cleared, stt = run(scenario())
    assert h.media.cleared > cleared and stt.calls >= 2

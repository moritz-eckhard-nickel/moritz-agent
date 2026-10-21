# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The voice channel without Discord: audio plumbing, playback, listener, conversation (P1-36, docs/plan/14 §9)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import numpy as np

from moritz_agent.discord.sender import Origin
from moritz_agent.discord.speech import SpeechService
from moritz_agent.discord.voice import receive
from moritz_agent.discord.voice import session as voice_session
from moritz_agent.discord.voice.pipeline import (
    FRAME_BYTES,
    BargeInDetector,
    Downmix,
    frames_of,
    is_wake_word,
    to_48k_stereo,
)
from moritz_agent.discord.voice.playback import IDLE_FRAMES, DiscordMedia
from moritz_agent.discord.voice.responder import VoiceResponder
from moritz_agent.discord.voice.session import VoiceMode, VoiceSession
from moritz_agent.phone.audio.announcements import AnnouncementStore, Prompt
from moritz_agent.phone.audio.tts import TtsService
from moritz_agent.phone.responder import ResponderUnavailable, TurnContext

from .fakes import FakeEngine, FakeSegmenter, FakeStt, FakeVad, silence_frames, speech_frames
from .system_util import CHANNEL_ID, OWNER_ID, STRANGER_ID, TRUSTED_ID
from .test_discord_client import stub_client, wired

PROMPTS = {
    pid: Prompt(pid, text, False)
    for pid, text in {
        "greeting": "Hallo Moritz, hier ist Nikita.",
        "yes": "Ja?",
        "going_quiet": "Ich bin dann mal still.",
        "still_there": "Bist du noch da?",
        "goodbye": "Alles klar, bis bald!",
        "not_understood": "Das habe ich nicht verstanden.",
        "not_understood_again": "Ich verstehe dich schlecht.",
        "thinking": "Moment, ich schaue nach.",
        "error_generic": "Ich habe eine Störung.",
        "timeout": "Das dauert zu lange.",
    }.items()
}
CHANNEL = 8100


# -- pipeline -----------------------------------------------------------------------------------------------
def test_16k_mono_becomes_48k_stereo_in_20_ms_frames():
    pcm = (np.sin(np.arange(16000) / 20) * 8000).astype("<i2").tobytes()  # one second
    stereo = to_48k_stereo(pcm)
    assert len(stereo) == 48000 * 2 * 2
    samples = np.frombuffer(stereo, dtype="<i2").reshape(-1, 2)
    assert (samples[:, 0] == samples[:, 1]).all()
    frames = frames_of(stereo[: FRAME_BYTES * 3 + 100])
    assert [len(f) for f in frames] == [FRAME_BYTES] * 4 and frames[-1][100:] == bytes(
        FRAME_BYTES - 100
    )
    assert to_48k_stereo(b"") == b"" and frames_of(b"") == []


def test_incoming_stereo_48k_becomes_mono_16k_as_a_stream():
    t = np.arange(48000) / 48000
    tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype("<i2")
    stereo = np.repeat(tone, 2).tobytes()
    mixer = Downmix()
    out = b"".join(
        mixer.feed(stereo[i : i + FRAME_BYTES]) for i in range(0, len(stereo), FRAME_BYTES)
    )
    mono = np.frombuffer(out, dtype="<i2")
    assert 15000 <= len(mono) <= 16100
    assert 6000 < np.abs(mono[2000:]).max() < 12000  # same loudness
    body = mono[2000:].astype(float)
    spectrum = np.abs(np.fft.rfft(body * np.hanning(len(body))))
    assert abs(np.argmax(spectrum) * 16000 / len(body) - 440) < 5  # still 440 Hz
    assert mixer.feed(b"123") == b""  # less than one stereo sample


def segmenter_with(frames: list[bytes]) -> BargeInDetector:
    return BargeInDetector(FakeSegmenter(min_speech_frames=3, end_silence_frames=50), min_ms=300)


def test_talking_over_nikita_is_noticed_after_300_ms_and_only_once():
    detector = segmenter_with([])
    quiet, loud = silence_frames(1)[0], speech_frames(1)[0]
    assert all(detector.feed(quiet, True) is None for _ in range(10))
    fired = [detector.feed(loud, True) for _ in range(30)]
    first = next(i for i, heard in enumerate(fired) if heard)
    assert 14 <= first <= 16 and sum(1 for heard in fired if heard) == 1  # 300 ms of 20 ms frames
    heard = fired[first]
    assert len(heard) >= 15 * 640  # the first words are handed over
    detector.feed(loud, False)  # Nikita stopped: the next time counts again
    again = [detector.feed(loud, True) for _ in range(20)]
    assert any(again)


def test_coughs_and_other_nikita_free_moments_do_not_interrupt():
    detector = BargeInDetector(FakeSegmenter(min_speech_frames=3, end_silence_frames=1), min_ms=300)
    loud, quiet = speech_frames(1)[0], silence_frames(1)[0]
    for _ in range(5):  # short noises, each below 300 ms
        assert all(detector.feed(loud, True) is None for _ in range(8))
        assert detector.feed(quiet, True) is None
    assert all(
        detector.feed(loud, False) is None for _ in range(40)
    )  # Nikita is silent: no interruption


def test_the_wake_word_is_found_also_as_whisper_mishears_it():
    for text in (
        "Nikita, bist du da?",
        "Hey Nikita",
        "Nikida hörst du mich",
        "nikitta",
        "Ähm Nikita wie spät",
    ):
        assert is_wake_word(text), text
    for text in (
        "Wie spät ist es",
        "Nikolaus kommt bald",
        "",
        "Ich habe gestern mit Nikita gesprochen und es war schön",
    ):
        assert not is_wake_word(text), text


# -- playback ---------------------------------------------------------------------------------------------------
class FakeVoiceClient:
    """A voice connection; with ``auto`` a player "plays" what it is given, much faster than real time."""

    def __init__(self, auto: bool = False) -> None:
        self.auto = auto
        self.pumps: list[asyncio.Future] = []
        self.connected, self.playing = True, False
        self.sources: list[object] = []
        self.afters: list[object] = []
        self.stopped = 0
        self.disconnected = False
        self.sink = None
        self.loop = MagicMock()
        self.loop.call_soon_threadsafe = lambda fn, *a: fn(*a)

    def is_connected(self) -> bool:
        return self.connected

    def is_playing(self) -> bool:
        return self.playing

    def play(self, source, after=None) -> None:
        self.playing = True
        self.sources.append(source)
        self.afters.append(after)
        if self.auto:
            self.pumps.append(asyncio.ensure_future(self._pump(source, after)))

    async def _pump(self, source, after) -> None:
        while self.connected and source.read():
            await asyncio.sleep(0.0005)
        self.playing = False
        if after is not None:
            after(None)

    def stop(self) -> None:
        self.stopped += 1
        self.playing = False

    def listen(self, sink) -> None:
        self.sink = sink

    async def disconnect(self, force: bool = False) -> None:
        self.disconnected, self.connected = True, False


def test_playback_turns_sentences_into_frames_and_ends_the_player_after_a_pause():
    vc = FakeVoiceClient()
    media = DiscordMedia(vc)
    media.play(
        (np.sin(np.arange(3200) / 10) * 5000).astype("<i2").tobytes()
    )  # 3200 samples = 200 ms
    assert media.pending_ms() == 200 and len(vc.sources) == 1
    media.play(bytes(6400))  # more audio while the player runs: no second player
    assert len(vc.sources) == 1 and media.pending_ms() == 400
    source = vc.sources[0]
    assert not source.is_opus()
    frames = [source.read() for _ in range(20)]
    assert all(len(f) == FRAME_BYTES for f in frames) and media.pending_ms() == 0
    pause = [source.read() for _ in range(IDLE_FRAMES - 1)]
    assert all(f == bytes(FRAME_BYTES) for f in pause)  # a short pause is bridged with silence
    assert source.read() == b""  # then the player ends


def test_playback_restarts_when_audio_arrives_while_the_player_is_stopping():
    vc = FakeVoiceClient()
    media = DiscordMedia(vc)
    media.play(bytes(640))
    vc.playing = False  # the player thread just ended …
    media.play(bytes(640))  # … and the next sentence is there
    assert len(vc.sources) == 2
    vc.playing = False
    media._frames.append(bytes(FRAME_BYTES))
    vc.afters[-1](None)  # the end of the player notices leftover audio and starts again
    assert len(vc.sources) == 3


def test_clearing_stops_the_player_and_drops_the_queue():
    vc = FakeVoiceClient()
    media = DiscordMedia(vc)
    media.play(bytes(32000))
    media.clear_playback()
    assert media.pending_ms() == 0 and vc.stopped == 1


def test_the_packet_counter_runs_while_connected_and_stands_still_afterwards():
    now = [0.0]
    vc = FakeVoiceClient()
    media = DiscordMedia(vc, clock=lambda: now[0])
    now[0] = 2.0
    running = media.rx_packets()
    assert running == 100
    vc.connected = False
    now[0] = 10.0
    assert media.rx_packets() == running and media.rx_packets() == running


def test_hangup_is_reported_to_the_session():
    reasons: list[str] = []
    DiscordMedia(FakeVoiceClient(), on_hangup=reasons.append).hangup("goodbye")
    assert reasons == ["goodbye"]


# -- receiving ----------------------------------------------------------------------------------------------------------
def test_only_allowed_speakers_are_converted_and_everybody_else_is_dropped_before_decoding():
    got: list[tuple[int, bytes]] = []
    listener = receive.Listener(lambda uid: uid == 1001, lambda uid, pcm: got.append((uid, pcm)))
    frame = np.repeat((np.sin(np.arange(960) / 5) * 8000).astype("<i2"), 2).tobytes()
    for _ in range(5):
        listener.on_audio(1001, frame)
        listener.on_audio(1999, frame)
        listener.on_audio(None, frame)
    assert {uid for uid, _ in got} == {1001} and sum(len(p) for _, p in got) > 4 * 600
    assert listener.dropped == 10
    listener.forget(1001)


def test_without_the_extension_the_voice_channel_only_speaks(monkeypatch):
    monkeypatch.setattr(receive, "extension", lambda: None)
    assert not receive.available() and receive.client_class() is discord.VoiceClient


def test_the_sink_of_the_extension_hands_decoded_audio_to_the_listener(monkeypatch):
    class AudioSink:  # the extension's base class
        pass

    fake = SimpleNamespace(AudioSink=AudioSink, VoiceRecvClient=object)
    monkeypatch.setattr(receive, "extension", lambda: fake)
    got: list[tuple[int, bytes]] = []
    sink = receive.make_sink(
        receive.Listener(lambda uid: True, lambda uid, pcm: got.append((uid, pcm)))
    )
    assert sink.wants_opus() is False and receive.client_class() is object
    for _ in range(6):  # the resampler needs a few frames before the first audio comes out
        sink.write(SimpleNamespace(id=1001), SimpleNamespace(pcm=bytes(FRAME_BYTES)))
    sink.write(SimpleNamespace(id=1001), SimpleNamespace(pcm=b""))  # nothing to hear
    sink.write(None, SimpleNamespace(pcm=bytes(FRAME_BYTES)))  # unknown speaker
    sink.cleanup()
    assert got and {uid for uid, _ in got} == {1001}


# -- the answers ------------------------------------------------------------------------------------------------------------
def test_the_voice_responder_asks_the_core_in_spoken_style(tmp_path):
    async def body(system, worker, client):
        responder = VoiceResponder(worker.core, CHANNEL, lambda: (OWNER_ID, "Moritz"))
        context = TurnContext("c")
        reply = await responder.respond("Wie spät ist es?", context)
        week = await responder.respond("Welcher Tag ist heute?", context)
        await responder.end()
        broken = VoiceResponder(
            type(worker.core)("http://127.0.0.1:1", "x"), CHANNEL, lambda: (OWNER_ID, "")
        )
        try:
            await broken.respond("Hallo", TurnContext("c"))
        except ResponderUnavailable:
            failed = True
        else:
            failed = False
        return reply, week, failed

    reply, week, failed = wired(tmp_path, body)
    assert (
        reply.text == "Es ist 19 Uhr 12."
        and reply.skill_id == "time.now"
        and "Sonntag" in week.text
    )
    assert failed


# -- the session ---------------------------------------------------------------------------------------------------------------
class Room:
    """A voice channel with people in it, a voice client, and a worker around the real main process."""

    def __init__(self, system, worker, client) -> None:
        self.system, self.worker, self.client = system, worker, client
        self.vc = FakeVoiceClient(auto=True)
        self.engine = FakeEngine()
        tts = TtsService({"fake": self.engine}, "fake", [], system.tree / "tts-cache")
        self.stt = FakeStt("Wie spät ist es?")
        self.store = AnnouncementStore(tts, PROMPTS)
        worker.speech_service = SpeechService(
            worker.settings,
            system.tree,
            stt_factory=lambda: self.stt,
            tts_factory=lambda: tts,
            vad_factory=FakeVad,
            announcements_factory=lambda _tts: self.store,
        )
        phone = worker.config.settings.phone
        phone.silence_prompt_s, phone.silence_hangup_s = 0.5, 0.5
        phone.playback_tail_guard_ms, phone.media_dead_timeout_s = 20, 30.0
        phone.thinking_prompt_after_s = 5.0
        self.channel = MagicMock(spec=discord.VoiceChannel)
        self.channel.id, self.channel.name = CHANNEL, "Quatschecke"
        self.channel.guild = SimpleNamespace(id=9000, me=SimpleNamespace(), name="Zuhause")
        self.channel.voice_states = {}
        self.channel.permissions_for = lambda me: SimpleNamespace(connect=True, speak=True)
        self.channel.connect = AsyncMock(return_value=self.vc)
        self.stub = stub_client(None)
        self.stub.guilds = [
            SimpleNamespace(voice_channels=[self.channel], stage_channels=[], id=9000)
        ]
        self.stub.get_channel = lambda cid: self.channel if int(cid) == CHANNEL else None
        worker.client = self.stub
        worker.policy.bot_id = "5000"
        worker.default_channel = MagicMock(spec=discord.TextChannel)
        worker.default_channel.send = AsyncMock()
        worker.policy.default_guild_id = "9000"
        self.manager = voice_session.VoiceManager(worker)
        worker.voice = self.manager
        voice_session.START_DELAY_S = 0.01
        voice_session.CHECK_EVERY_S = 0.05

    def enter(self, user_id: str) -> None:
        self.channel.voice_states[int(user_id)] = SimpleNamespace(
            member=SimpleNamespace(display_name="Moritz")
        )
        if self.manager.session:
            self.manager.session.update()

    def leave(self, user_id: str) -> None:
        self.channel.voice_states.pop(int(user_id), None)
        if self.manager.session:
            self.manager.session.update()

    async def join(self, user: str = OWNER_ID, channel: str | None = str(CHANNEL)) -> str:
        origin = Origin(user_id=user, where="S", guild_id="9000", channel_id=CHANNEL_ID)
        return await self.manager.join(origin, channel)

    @property
    def session(self) -> VoiceSession:
        assert self.manager.session is not None
        return self.manager.session

    async def until(self, condition, what: str, timeout: float = 6.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not condition():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"Zeitüberschreitung beim Warten auf: {what}")
            await asyncio.sleep(0.01)

    async def talk(self, user: str = OWNER_ID, frames: int = 14) -> None:
        await self.until(
            lambda: self.session.call is not None and self.session.call._listening, "Zuhören"
        )
        for frame in speech_frames(frames) + silence_frames(10):
            self.session.on_audio(int(user), frame)
            await asyncio.sleep(0.003)

    def played(self, prompt_id: str) -> bool:
        data = self.store.get(prompt_id)
        return (
            any(data[i : i + 640] in self.heard for i in range(0, len(data), 640))
            if data
            else False
        )

    heard = ""


def room_test(tmp_path, body, *, receiving: bool = True):
    async def go(system, worker, client):
        room = Room(system, worker, client)
        voice_session.receive.available = lambda: receiving  # type: ignore[assignment]
        original = receive.available, receive.make_sink
        receive.available = lambda: receiving
        receive.make_sink = lambda listener: SimpleNamespace(listener=listener)
        receive.client_class = lambda: discord.VoiceClient
        try:
            return await body(room)
        finally:
            if room.manager.session:
                await room.manager.close(room.session, "Test")
            receive.available, receive.make_sink = original

    return wired(tmp_path, go)


def test_joining_waits_quietly_and_starts_the_conversation_when_the_owner_is_there(tmp_path):
    async def body(room: Room):
        text = await room.join()
        waiting = room.session.mode
        room.enter(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch")
        await room.until(
            lambda: room.session.media.pending_ms() > 0 or room.vc.sources, "Begrüßung"
        )
        return text, waiting, room.manager.active, room.vc.sink is not None

    text, waiting, active, listening = room_test(tmp_path, body)
    assert "Quatschecke" in text and "nur sprechen" not in text
    assert waiting is VoiceMode.WAITING and active and listening


def test_a_question_in_the_voice_channel_is_answered_by_voice(tmp_path):
    async def body(room: Room):
        await room.join()
        room.enter(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch")
        await room.talk()
        await room.until(lambda: any("Uhr" in c for c in room.engine.calls), "Antwort gesprochen")
        return room.stt.calls, [c for c in room.engine.calls if "Uhr" in c]

    calls, spoken = room_test(tmp_path, body)
    assert (calls == 1 and spoken and "19" in spoken[0]) or "neunzehn" in spoken[0].lower()


def test_a_stranger_in_the_channel_is_neither_heard_nor_a_reason_to_start(tmp_path):
    async def body(room: Room):
        await room.join()
        room.enter(STRANGER_ID)
        await asyncio.sleep(0.3)
        mode_with_stranger = room.session.mode
        humans = room.session.humans()
        room.enter(TRUSTED_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch mit Vertrautem")
        return mode_with_stranger, humans, room.session.humans()

    mode, humans, later = room_test(tmp_path, body)
    assert mode is VoiceMode.WAITING and humans == [] and later == [int(TRUSTED_ID)]


def test_leaving_the_channel_ends_the_conversation_like_hanging_up(tmp_path):
    async def body(room: Room):
        await room.join()
        room.enter(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch")
        room.leave(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.WAITING, "wieder wartend")
        room.enter(OWNER_ID)  # and back: a new conversation with a new greeting
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "neues Gespräch")
        return room.session._conversations

    assert room_test(tmp_path, body) == 2


def test_silence_makes_nikita_go_quiet_and_his_name_wakes_him(tmp_path):
    async def body(room: Room):
        room.stt.texts = ["Nikita, hörst du mich?"]
        await room.join()
        room.enter(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch")
        await room.until(lambda: room.session.mode is VoiceMode.RESTING, "Ruhemodus", 10)
        quiet = [c for c in room.engine.calls]
        # a sentence without his name changes nothing …
        room.stt.texts = ["Wie spät ist es?"]
        for frame in speech_frames(14) + silence_frames(12):
            room.session.on_audio(int(OWNER_ID), frame)
            await asyncio.sleep(0.003)
        await asyncio.sleep(0.3)
        still_resting = room.session.mode is VoiceMode.RESTING
        # … his name does, and he answers with "Ja?" instead of the greeting
        room.stt.texts = ["Nikita, hörst du mich?"]
        for frame in speech_frames(14) + silence_frames(12):
            room.session.on_audio(int(OWNER_ID), frame)
            await asyncio.sleep(0.003)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "geweckt")
        return still_resting, quiet

    still_resting, _ = room_test(tmp_path, body)
    assert still_resting


def test_saying_goodbye_ends_the_visit(tmp_path):
    async def body(room: Room):
        room.stt.texts = ["Tschüss"]
        await room.join()
        room.enter(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch")
        await room.talk()
        await room.until(lambda: not room.manager.active, "Nikita ist gegangen")
        # the manager forgets the session first (no re-entry), then stop() disconnects
        await room.until(lambda: room.vc.disconnected, "Verbindung getrennt")
        return room.vc.disconnected, room.worker.policy.extra_chat_channels

    disconnected, extra = room_test(tmp_path, body)
    assert disconnected and extra == set()


def test_after_goodbye_nikita_can_stay_and_rest(tmp_path):
    async def body(room: Room):
        room.worker.config.settings.discord.voice.after_goodbye = "stay"
        room.stt.texts = ["Tschüss"]
        await room.join()
        room.enter(OWNER_ID)
        await room.until(lambda: room.session.mode is VoiceMode.TALKING, "Gespräch")
        await room.talk()
        await room.until(lambda: room.session.mode is VoiceMode.RESTING, "Ruhemodus nach Tschüss")
        return room.manager.active

    assert room_test(tmp_path, body)


def test_without_the_listening_extension_only_the_voice_works(tmp_path):
    async def body(room: Room):
        text = await room.join()
        room.enter(OWNER_ID)
        await room.until(
            lambda: room.session.media.pending_ms() > 0 or room.vc.sources, "Begrüßung"
        )
        before = room.session.mode
        # the chat of the voice channel is answered … and spoken
        await room.manager.speak_answer(CHANNEL, "Das Wetter ist schön.")
        return (
            text,
            before,
            any("Wetter" in c for c in room.engine.calls),
            room.worker.policy.extra_chat_channels,
        )

    text, mode, spoken, extra = room_test(tmp_path, body, receiving=False)
    assert "nur sprechen" in text and mode is VoiceMode.WAITING and spoken
    assert extra == {str(CHANNEL)}


def test_the_chat_of_the_voice_channel_is_answered_without_a_mention(tmp_path):
    async def body(room: Room):
        await room.join()
        from .test_discord_client import fake_message

        message = fake_message(content="Wie spät ist es?", channel_id=CHANNEL)
        room.worker.client = room.client  # the real client knows how to read a message
        room.client.worker = room.worker
        room.client._connection.user = SimpleNamespace(id=5000)
        await room.client._on_message(message)
        return message

    message = room_test(tmp_path, body, receiving=False)
    assert "19 Uhr 12" in message.reply.await_args.kwargs["content"]


def test_joining_is_checked_before_connecting(tmp_path):
    async def body(room: Room):
        results = {}
        room.worker.drain_path.parent.mkdir(parents=True, exist_ok=True)
        room.worker.drain_path.touch()
        results["drain"] = await room.join()
        room.worker.drain_path.unlink()
        results["nowhere"] = await room.join(channel="424242")
        room.channel.permissions_for = lambda me: SimpleNamespace(connect=False, speak=True)
        results["rights"] = await room.join()
        room.channel.permissions_for = lambda me: SimpleNamespace(connect=True, speak=True)
        room.enter(OWNER_ID)
        results["ok"] = await room.join(
            channel=None
        )  # no explicit channel: the one the owner is in
        results["again"] = await room.join()
        other = MagicMock(spec=discord.VoiceChannel)
        other.id, other.name, other.guild = 8200, "Anderswo", room.channel.guild
        other.voice_states, other.permissions_for = {}, room.channel.permissions_for
        room.stub.get_channel = lambda cid: other if int(cid) == 8200 else room.channel
        results["other"] = await room.join(channel="8200")
        results["leave"] = await room.manager.leave(Origin(user_id=OWNER_ID))
        results["nothing"] = await room.manager.leave(Origin(user_id=OWNER_ID))
        return results

    results = room_test(tmp_path, body)
    assert "aktualisiert" in results["drain"]
    assert "welchen Sprachkanal" in results["nowhere"]
    assert "Rechte" in results["rights"]
    assert "Quatschecke" in results["ok"] and "schon da" in results["again"]
    assert "schon in" in results["other"] and "Quatschecke" in results["other"]
    assert "raus aus" in results["leave"] and "keinem Sprachkanal" in results["nothing"]


def test_nobody_there_for_long_makes_nikita_leave_and_say_so(tmp_path):
    async def body(room: Room):
        room.worker.config.settings.discord.voice.idle_leave_minutes = 1
        await room.join()
        room.session._empty_since -= 61
        await room.until(lambda: not room.manager.active, "Nikita geht")
        await room.until(lambda: room.worker.default_channel.send.await_args, "Hinweis im Kanal")
        return room.worker.default_channel.send.await_args.kwargs["content"]

    note = room_test(tmp_path, body)
    assert "Quatschecke" in note and "niemand mehr da" in note


def test_a_lost_connection_ends_the_session(tmp_path):
    async def body(room: Room):
        await room.join()
        room.vc.connected = False
        await room.until(lambda: not room.manager.active, "Sitzung beendet")
        await room.until(lambda: room.worker.default_channel.send.await_args, "Hinweis im Kanal")
        return room.worker.default_channel.send.await_args.kwargs["content"]

    assert "Verbindung verloren" in room_test(tmp_path, body)


def test_the_owner_arriving_can_bring_nikita_along_if_switched_on(tmp_path):
    async def body(room: Room):
        room.worker.config.settings.discord.voice.auto_join = True
        member = SimpleNamespace(id=int(OWNER_ID))
        room.enter(OWNER_ID)
        stranger = SimpleNamespace(id=int(STRANGER_ID))
        await room.manager.on_voice_state(
            stranger, SimpleNamespace(channel=None), SimpleNamespace(channel=room.channel)
        )
        none_for_stranger = not room.manager.active
        await room.manager.on_voice_state(
            member, SimpleNamespace(channel=None), SimpleNamespace(channel=room.channel)
        )
        return none_for_stranger, room.manager.active

    assert room_test(tmp_path, body) == (True, True)


def test_being_thrown_out_of_the_channel_closes_the_session(tmp_path):
    async def body(room: Room):
        await room.join()
        bot = SimpleNamespace(id=5000)
        await room.manager.on_voice_state(
            bot, SimpleNamespace(channel=room.channel), SimpleNamespace(channel=None)
        )
        return room.manager.active

    assert not room_test(tmp_path, body)


def test_the_models_are_held_only_while_a_session_runs(tmp_path):
    async def body(room: Room):
        speech = room.worker.speech_service
        await room.join()
        during = speech.active
        unloaded_while_active = speech.unload_if_idle(0)
        await room.manager.close(room.session, "Test")
        return during, unloaded_while_active, speech.active

    assert room_test(tmp_path, body) == (1, False, 0)

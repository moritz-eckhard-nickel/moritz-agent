# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Audio in and out, voice messages and "Vorlesen" (docs/plan/14 §10) – with fake models."""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from moritz_agent.discord.speech import (
    AudioError,
    SpeechService,
    decode_to_pcm16k,
    encode_ogg_opus,
    waveform,
)
from moritz_agent.discord.voice_messages import VoiceMessages, from_cdn, is_audio
from moritz_agent.phone.audio.stt import Transcript

from .discord_util import Recorder
from .system_util import CHANNEL_ID, OWNER_ID, STRANGER_ID
from .test_discord_client import fake_message, wired


def tone(seconds: float = 1.0, rate: int = 16000, freq: float = 440.0) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * freq * t) * 8000).astype("<i2").tobytes()


# -- the audio helpers ----------------------------------------------------------------------------------------
def test_opus_roundtrip_keeps_the_length():
    data = encode_ogg_opus(tone(1.5))
    assert data[:4] == b"OggS"
    pcm = decode_to_pcm16k(data, 60)
    assert abs(len(pcm) / 2 / 16000 - 1.5) < 0.15


def test_too_long_empty_and_broken_audio_is_refused_in_plain_words():
    data = encode_ogg_opus(tone(3.0))
    with pytest.raises(AudioError, match="länger"):
        decode_to_pcm16k(data, 1.0)
    with pytest.raises(AudioError):
        decode_to_pcm16k(b"das ist kein Audio" * 10, 60)
    with pytest.raises(AudioError):
        decode_to_pcm16k(b"", 60)


def test_the_waveform_is_a_fixed_size_loudness_curve():
    curve = base64.b64decode(waveform(tone(2.0)))
    assert len(curve) == 256 and max(curve) > 50
    assert set(base64.b64decode(waveform(b""))) == {0}


def test_only_discords_cdn_is_downloaded_from():
    assert from_cdn("https://cdn.discordapp.com/attachments/1/2/voice-message.ogg")
    assert from_cdn("https://media.discordapp.net/attachments/1/2/a.ogg")
    assert not from_cdn("http://cdn.discordapp.com/a.ogg")  # no plain http
    assert not from_cdn("https://cdn.discordapp.com.evil.example/a.ogg")
    assert not from_cdn("https://evil.example/cdn.discordapp.com/a.ogg")
    assert is_audio(SimpleNamespace(content_type="audio/ogg", filename="voice-message.ogg"))
    assert is_audio(SimpleNamespace(content_type=None, filename="memo.M4A"))
    assert not is_audio(SimpleNamespace(content_type="image/png", filename="bild.png"))


# -- the models on demand --------------------------------------------------------------------------------------------
class ScriptedStt:
    def __init__(self, text="Wie spät ist es", **kw):
        self.text, self.kw, self.calls = text, kw, 0

    def transcribe(self, pcm):
        self.calls += 1
        return Transcript(text=self.text, avg_logprob=-0.1, no_speech_prob=0.0, **self.kw)


class ScriptedTts:
    def __init__(self):
        self.texts: list[str] = []
        self.closed = False

    def best_available(self):
        return "fake"

    def render_blocking(self, text):
        self.texts.append(text)
        return tone(1.0)

    def close(self):
        self.closed = True


def service(stt=None, tts=None, clock=None):
    from moritz_agent.config.settings import Settings

    settings = Settings()
    return SpeechService(
        lambda: settings,
        settings.resolve("."),
        stt_factory=lambda: stt or ScriptedStt(),
        tts_factory=lambda: tts or ScriptedTts(),
        clock=clock or (lambda: 0.0),
    )


def test_models_load_on_first_use_and_go_after_a_quiet_time():
    now = [0.0]
    tts = ScriptedTts()
    speech = service(tts=tts, clock=lambda: now[0])

    async def go():
        assert not speech.unload_if_idle(10)  # nothing loaded yet
        text = (await speech.transcribe(tone())).text
        pcm = await speech.synthesize("Hallo")
        now[0] = 5 * 60
        early = speech.unload_if_idle(10)
        speech.active = 1
        now[0] = 60 * 60
        in_use = speech.unload_if_idle(10)
        speech.active = 0
        late = speech.unload_if_idle(10)
        return text, len(pcm), early, in_use, late

    assert asyncio.run(go()) == ("Wie spät ist es", 32000, False, False, True)
    assert tts.closed and speech._stt is None and speech._tts is None


# -- voice messages end to end -------------------------------------------------------------------------------------------
def attachment(url="https://cdn.discordapp.com/attachments/1/2/voice-message.ogg", **extra):
    return SimpleNamespace(
        url=url,
        content_type="audio/ogg",
        filename="voice-message.ogg",
        duration=extra.pop("duration", 2.0),
        **extra,
    )


def voice_handler(worker, speech, audio=None):
    audio = audio if audio is not None else encode_ogg_opus(tone(2.0))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=audio))
    return VoiceMessages(
        worker.dispatcher, speech, lambda m: worker.client.info_of(m), transport=transport
    )


def test_a_voice_message_is_recognised_answered_and_answered_as_audio(tmp_path):
    async def body(system, worker, client):
        stt, tts = ScriptedStt(), ScriptedTts()
        handler = voice_handler(worker, service(stt, tts))
        message = fake_message(channel_id=int(CHANNEL_ID), attachments=[attachment()], content="")
        sender = Recorder()
        origin = client.origin_of(message)
        handled = await handler.handle(message, origin, sender)
        return handled, sender, tts

    handled, sender, tts = wired(tmp_path, body)
    assert handled
    texts = [m.content for m in sender.sent]
    assert texts[0] == "🎤 *Wie spät ist es*" and "19 Uhr 12" in texts[1]
    assert sender.sent[-1].file and sender.sent[-1].file[0] == "antwort.ogg"
    assert sender.sent[-1].file[1][:4] == b"OggS" and tts.texts == ["Es ist 19 Uhr 12."]


def test_the_voice_reply_follows_the_setting_of_the_person(tmp_path):
    async def body(system, worker, client):
        handler = voice_handler(worker, service())
        results = {}
        for mode in ("never", "mirror", "always"):
            await worker.core.set_principal(OWNER_ID, voice_reply=mode)
            message = fake_message(
                channel_id=int(CHANNEL_ID), attachments=[attachment()], content=""
            )
            sender = Recorder()
            await handler.handle(message, client.origin_of(message), sender)
            results[mode] = any(m.file for m in sender.sent)
        return results

    assert wired(tmp_path, body) == {"never": False, "mirror": True, "always": True}


def test_unclear_speech_and_missing_models_get_a_friendly_answer(tmp_path):
    async def body(system, worker, client):
        mumble = voice_handler(worker, service(ScriptedStt(text="")))
        message = fake_message(channel_id=int(CHANNEL_ID), attachments=[attachment()], content="")
        first = Recorder()
        await mumble.handle(message, client.origin_of(message), first)
        no_model = voice_handler(worker, service())
        no_model.speech._stt_factory = None
        no_model.speech.settings().phone.stt.model = "models/gibt-es-nicht"
        second = Recorder()
        await no_model.handle(message, client.origin_of(message), second)
        return first, second

    first, second = wired(tmp_path, body)
    assert "nicht verstanden" in first.text
    assert "Spracherkennung" in second.text


def test_bad_attachments_are_not_downloaded_or_decoded(tmp_path):
    async def body(system, worker, client):
        handler = voice_handler(worker, service())
        out = {}
        for name, att, audio in (
            ("elsewhere", attachment(url="https://evil.example/a.ogg"), None),
            ("long", attachment(duration=999.0), None),
            ("garbage", attachment(), b"kein Audio" * 100),
        ):
            handler = voice_handler(worker, service(), audio)
            message = fake_message(channel_id=int(CHANNEL_ID), attachments=[att], content="")
            sender = Recorder()
            await handler.handle(message, client.origin_of(message), sender)
            out[name] = sender.text
        return out

    out = wired(tmp_path, body)
    assert "anderen Adressen" in out["elsewhere"]
    assert "länger" in out["long"]
    assert "Audio" in out["garbage"] or "beschädigt" in out["garbage"]


def test_voice_messages_of_strangers_or_in_other_channels_are_left_alone(tmp_path):
    async def body(system, worker, client):
        handler = voice_handler(worker, service())
        stranger = fake_message(
            author=int(STRANGER_ID),
            channel_id=int(CHANNEL_ID),
            attachments=[attachment()],
            content="",
        )
        elsewhere = fake_message(channel_id=777, attachments=[attachment()], content="")
        text_only = fake_message(channel_id=int(CHANNEL_ID), attachments=[], content="Hallo")
        out = []
        for message in (stranger, elsewhere, text_only):
            sender = Recorder()
            out.append(
                (await handler.handle(message, client.origin_of(message), sender), sender.sent)
            )
        return out

    assert wired(tmp_path, body) == [(False, []), (False, []), (False, [])]


def test_read_aloud_makes_an_audio_file_and_never_reads_secrets(tmp_path):
    async def body(system, worker, client):
        from .system_util import BOT_TOKEN

        tts = ScriptedTts()
        handler = voice_handler(worker, service(tts=tts))
        message = fake_message(content=f"Guude, der Token ist {BOT_TOKEN}!")
        sender = Recorder(ephemeral=True)
        await handler.read_aloud(message, client.origin_of(message), sender)
        empty = Recorder(ephemeral=True)
        await handler.read_aloud(fake_message(content="  "), client.origin_of(message), empty)
        return sender, tts, empty

    sender, tts, empty = wired(tmp_path, body)
    assert sender.sent[-1].file[0] == "vorlesen.ogg"
    assert "***" in tts.texts[0] and "0123456789abcdef" not in tts.texts[0]
    assert "kein Text" in empty.text and not empty.sent[0].file

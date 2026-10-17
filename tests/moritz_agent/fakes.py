# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Test doubles for the phone audio path."""

from __future__ import annotations

import math
import threading
import time

import numpy as np

from moritz_agent.phone.audio.stt import Transcript
from moritz_agent.phone.audio.tts import TtsCancelled, TtsError


def tone(seconds: float, rate: int = 22050, freq: float = 330.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.4 * np.sin(2 * math.pi * freq * t)).astype(np.float32)


class FakeEngine:
    """Synthesizes a tone whose length follows the text; counts calls."""

    def __init__(
        self, name: str = "fake", voice_id: str = "v1", delay: float = 0.0, ready: bool = True
    ) -> None:
        self.name = name
        self.voice_id = voice_id
        self.delay = delay
        self.ready = ready
        self.fail_on: str | None = None
        self.calls: list[str] = []
        self._cancel = threading.Event()

    def available(self) -> bool:
        return self.ready

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise TtsError("boom")
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                self._cancel.clear()
                raise TtsCancelled()
            time.sleep(0.01)
        return tone(0.3 + 0.03 * len(text)), 22050

    def cancel(self) -> None:
        self._cancel.set()

    def close(self) -> None:
        return None


class FakeStt:
    """Returns scripted transcripts in order (the last one repeats)."""

    def __init__(self, *texts: str, delay: float = 0.0) -> None:
        self.texts = list(texts) or [""]
        self.delay = delay
        self.calls = 0

    def transcribe(self, pcm: bytes) -> Transcript:
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return Transcript(
            text=text, avg_logprob=-0.2, no_speech_prob=0.01, audio_s=len(pcm) / 32000
        )


# -- phone call doubles ----------------------------------------------------------------------
class FakeMedia:
    """Call media that "plays" audio ``speedup`` times faster than real time."""

    def __init__(self, speedup: float = 50.0) -> None:
        self.speedup = speedup
        self.played: list[bytes] = []
        self.hung_up: str | None = None
        self.cleared = 0
        self._free_at = 0.0

    def play(self, pcm: bytes) -> None:
        self.played.append(pcm)
        now = time.monotonic()
        self._free_at = max(now, self._free_at) + len(pcm) / 32000 / self.speedup

    def clear_playback(self) -> None:
        self.cleared += 1
        self._free_at = 0.0

    def pending_ms(self) -> int:
        return max(0, int((self._free_at - time.monotonic()) * 1000 * self.speedup))

    def hangup(self, reason: str) -> None:
        self.hung_up = reason

    def rx_packets(self) -> int | None:
        return self.packets

    packets: int | None = None


class FakeSegmenter:
    """Energy based stand-in for the Silero segmenter: loud frames are speech."""

    def __init__(self, min_speech_frames: int = 10, end_silence_frames: int = 6) -> None:
        self.min_speech_frames = min_speech_frames
        self.end_silence_frames = end_silence_frames
        self.reset()

    def reset(self) -> None:
        self._frames: list[bytes] = []
        self._silent = 0
        self._speech = 0
        self.in_speech = False

    def feed(self, pcm: bytes):
        from moritz_agent.phone.audio.vad import SpeechStart, UtteranceEnd

        loud = bool(np.abs(np.frombuffer(pcm, dtype="<i2")).max() > 3000)
        events = []
        if loud:
            if not self.in_speech:
                self.in_speech = True
                events.append(SpeechStart())
            self._speech += 1
            self._silent = 0
        elif self.in_speech:
            self._silent += 1
        if self.in_speech:
            self._frames.append(pcm)
            if self._silent >= self.end_silence_frames:
                if self._speech >= self.min_speech_frames:
                    events.append(UtteranceEnd(pcm=b"".join(self._frames), reason="silence"))
                self.reset()
        return events


class FakeVad:
    def new_segmenter(self, **_kwargs) -> FakeSegmenter:
        return FakeSegmenter()


def speech_frames(count: int = 14) -> list[bytes]:
    loud = (tone(0.02, 16000, 300) * 32767).astype("<i2").tobytes()
    return [loud] * count


def silence_frames(count: int) -> list[bytes]:
    return [bytes(640)] * count

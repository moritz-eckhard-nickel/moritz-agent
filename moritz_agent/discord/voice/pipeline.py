# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Audio plumbing of the voice channel (docs/plan/14 §9.3): formats, interruption, wake word.

Discord speaks 48 kHz stereo in 20 ms frames, the conversation (``CallSession``) 16 kHz mono. These
are the converters, the detector that notices somebody talking over Anton, and the matcher for
"Anton …" in rest mode. No Discord objects here – everything is tested with plain bytes.
"""

from __future__ import annotations

import difflib
import re
from collections import deque
from typing import Protocol

import numpy as np

from moritz_agent.phone.audio import pcm as pcm_tools

RATE = 16_000
DISCORD_RATE = 48_000
FRAME_MS = 20
FRAME_BYTES = DISCORD_RATE * FRAME_MS // 1000 * 2 * 2  # 20 ms of 48 kHz, stereo, 16 bit = 3840
SILENCE_FRAME = bytes(FRAME_BYTES)
BYTES_PER_MS = RATE * 2 // 1000  # mono 16 kHz, 16 bit


def to_48k_stereo(pcm: bytes) -> bytes:
    """Mono PCM16 16 kHz → interleaved stereo PCM16 48 kHz (what Discord plays)."""
    if not pcm:
        return b""
    samples = pcm_tools.resample(pcm_tools.pcm16_to_float(pcm), RATE, DISCORD_RATE)
    mono = pcm_tools.float_to_pcm16(samples)
    return np.repeat(mono, 2).astype("<i2").tobytes()


def frames_of(pcm48: bytes) -> list[bytes]:
    """20 ms frames of 48 kHz stereo audio; the last one is padded with silence."""
    frames = [pcm48[i : i + FRAME_BYTES] for i in range(0, len(pcm48), FRAME_BYTES)]
    if frames and len(frames[-1]) < FRAME_BYTES:
        frames[-1] = frames[-1] + bytes(FRAME_BYTES - len(frames[-1]))
    return frames


class Downmix:
    """Stereo 48 kHz → mono 16 kHz for one speaker, as a stream (the filter keeps its state)."""

    def __init__(self) -> None:
        import soxr

        self._stream = soxr.ResampleStream(DISCORD_RATE, RATE, 1, dtype="float32", quality="HQ")

    def feed(self, pcm48_stereo: bytes) -> bytes:
        usable = len(pcm48_stereo) - len(pcm48_stereo) % 4
        if not usable:
            return b""
        stereo = np.frombuffer(pcm48_stereo[:usable], dtype="<i2").reshape(-1, 2)
        mono = stereo.astype(np.float32).mean(axis=1) / 32768.0
        out = self._stream.resample_chunk(mono, last=False)
        return pcm_tools.float_to_pcm16(out).tobytes()


class Segmenter(Protocol):
    @property
    def in_speech(self) -> bool: ...

    def feed(self, pcm: bytes) -> list[object]: ...


class BargeInDetector:
    """Notices that somebody keeps talking while Anton speaks (docs/plan/14 §9.3).

    Watches the speech detector of the incoming audio; after ``min_ms`` of continuous speech while
    Anton is talking it hands back what was said so far (so the interruption loses no word), once
    per episode. Short noises and coughs stay below the threshold.
    """

    def __init__(self, segmenter: Segmenter, min_ms: int = 300, keep_ms: int = 2000) -> None:
        self.segmenter = segmenter
        self.min_ms = min_ms
        self._recent: deque[bytes] = deque()
        self._recent_bytes = 0
        self._keep = keep_ms * BYTES_PER_MS
        self._speech_ms = 0.0
        self._fired = False

    def feed(self, pcm: bytes, speaking: bool) -> bytes | None:
        self._recent.append(pcm)
        self._recent_bytes += len(pcm)
        while self._recent_bytes > self._keep and len(self._recent) > 1:
            self._recent_bytes -= len(self._recent.popleft())
        self.segmenter.feed(pcm)
        if not speaking:
            self._fired = False
            self._speech_ms = 0.0
            return None
        if self.segmenter.in_speech:
            self._speech_ms += len(pcm) / BYTES_PER_MS
        else:
            self._speech_ms = 0.0
        if self._speech_ms >= self.min_ms and not self._fired:
            self._fired = True
            heard = b"".join(self._recent)
            keep = int((self._speech_ms + 300) * BYTES_PER_MS)  # a little before the first word
            return heard[-keep:] if keep < len(heard) else heard
        return None


_NAME = "anton"
_WORD = re.compile(r"[a-zäöüß]+")


# real words that sound too much like the name ("das kann ich dir nicht antun")
_NOT_THE_NAME = frozenset({"antun"})


def is_wake_word(text: str, name: str = _NAME) -> bool:
    """ "Anton …" in the first words of an utterance, also as Whisper mishears it ("Antonn",
    "Andon", "Anthon"). The start of the word must match: "Kanton" or "Santo" do not wake him."""
    words = _WORD.findall(text.lower())[:4]
    return any(
        len(word) >= 4
        and word[:2] == name[:2]
        and word not in _NOT_THE_NAME
        and difflib.SequenceMatcher(None, word, name).ratio() >= 0.75
        for word in words
    )

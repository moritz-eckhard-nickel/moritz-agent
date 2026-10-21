# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Speech for Discord: audio files in and out, and the models behind them (docs/plan/14 §9.3, §10).

* ``decode_to_pcm16k`` – any audio file Discord offers (Ogg/Opus voice message, m4a, mp3 …) →
  mono 16 kHz PCM, with a length limit (PyAV, already part of the phone group)
* ``encode_ogg_opus`` – PCM → Ogg/Opus 48 kHz for a reply or "Vorlesen"
* ``SpeechService`` – Whisper and Piper, loaded when first needed and let go after a quiet time
  (the Discord worker must not hold on to the memory the phone needs, docs/plan/14 §9.4)
"""

from __future__ import annotations

import asyncio
import base64
import io
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from moritz_agent.config.settings import Settings
from moritz_agent.logging_setup import get_logger

if TYPE_CHECKING:
    from moritz_agent.phone.audio.stt import SpeechToText, Transcript
    from moritz_agent.phone.audio.tts import TtsService

log = get_logger("discord")
RATE = 16_000
OPUS_RATE = 48_000
WAVEFORM_POINTS = 256


class AudioError(ValueError):
    """The file is no usable audio (message in German, safe to show)."""


def decode_to_pcm16k(data: bytes, max_seconds: float) -> bytes:
    """Mono PCM16 at 16 kHz from the bytes of an audio file; raises ``AudioError``."""
    import av

    try:
        container = av.open(io.BytesIO(data))
    except Exception as exc:
        raise AudioError("Die Datei kann ich nicht als Audio öffnen.") from exc
    try:
        streams = container.streams.audio
        if not streams:
            raise AudioError("In der Datei ist keine Tonspur.")
        if container.duration and container.duration / 1_000_000 > max_seconds + 1:
            raise AudioError(f"Das ist länger als {int(max_seconds // 60)} Minuten.")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        chunks: list[bytes] = []
        total = 0
        for frame in container.decode(streams[0]):
            for out in resampler.resample(frame):
                chunk = out.to_ndarray().tobytes()
                chunks.append(chunk)
                total += len(chunk)
            if total > max_seconds * RATE * 2:
                raise AudioError(f"Das ist länger als {int(max_seconds // 60)} Minuten.")
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().tobytes())
    except AudioError:
        raise
    except Exception as exc:
        raise AudioError(
            "Das Audio ist beschädigt oder in einem Format, das ich nicht kenne."
        ) from exc
    finally:
        container.close()
    pcm = b"".join(chunks)
    if not pcm:
        raise AudioError("Die Aufnahme ist leer.")
    return pcm


def encode_ogg_opus(pcm: bytes, rate: int = RATE) -> bytes:
    """Ogg/Opus (48 kHz, mono) from PCM16 – what Discord plays as an audio message."""
    import av

    from moritz_agent.phone.audio import pcm as pcm_tools

    samples = pcm_tools.resample(pcm_tools.pcm16_to_float(pcm), rate, OPUS_RATE)
    wave = pcm_tools.float_to_pcm16(samples).reshape(1, -1)
    buffer = io.BytesIO()
    container = av.open(buffer, mode="w", format="ogg")
    stream = container.add_stream("libopus", rate=OPUS_RATE, layout="mono")
    frame = av.AudioFrame.from_ndarray(wave, format="s16", layout="mono")
    frame.sample_rate = OPUS_RATE
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def waveform(pcm: bytes, points: int = WAVEFORM_POINTS) -> str:
    """The loudness curve of a voice message (base64, one byte per point) – for native voice messages."""
    samples = np.abs(np.frombuffer(pcm, dtype="<i2").astype(np.float32))
    if samples.size == 0:
        return base64.b64encode(bytes(points)).decode("ascii")
    parts = np.array_split(samples, points)
    peaks = np.array([part.max() if part.size else 0.0 for part in parts])
    scaled = np.clip(peaks / 32768.0 * 255 * 1.5, 0, 255).astype(np.uint8)
    return base64.b64encode(scaled.tobytes()).decode("ascii")


class SpeechService:
    """Whisper and Piper for the Discord worker, loaded on first use and unloaded when idle."""

    def __init__(
        self,
        settings: Callable[[], Settings],
        root: Path,
        *,
        stt_factory: Callable[[], SpeechToText] | None = None,
        tts_factory: Callable[[], TtsService] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.root = root
        self._stt_factory = stt_factory
        self._tts_factory = tts_factory
        self._clock = clock
        self._stt: SpeechToText | None = None
        self._tts: TtsService | None = None
        self._lock = threading.Lock()
        self._last_used = clock()
        self.active = 0  # >0: a voice session needs the models, never unload

    # -- availability --------------------------------------------------------------------------------
    def stt_available(self) -> bool:
        if self._stt_factory is not None or self._stt is not None:
            return True
        return (
            self.settings().resolve(self.settings().phone.stt.model, self.root) / "model.bin"
        ).is_file()

    def tts_available(self) -> bool:
        if self._tts_factory is not None or self._tts is not None:
            return True
        try:
            return bool(self._load_tts().best_available())
        except Exception:
            return False

    # -- loading -----------------------------------------------------------------------------------------
    def _load_stt(self) -> SpeechToText:
        with self._lock:
            if self._stt is None:
                if self._stt_factory is not None:
                    self._stt = self._stt_factory()
                else:
                    from moritz_agent.phone.audio.factory import build_stt

                    self._stt = build_stt(self.settings(), self.root)
            return self._stt

    def _load_tts(self) -> TtsService:
        with self._lock:
            if self._tts is None:
                if self._tts_factory is not None:
                    self._tts = self._tts_factory()
                else:
                    from moritz_agent.phone.audio.factory import build_tts

                    self._tts = build_tts(self.settings(), self.root)
            return self._tts

    # -- use ---------------------------------------------------------------------------------------------------
    async def transcribe(self, pcm: bytes) -> Transcript:
        self._last_used = self._clock()
        stt = await asyncio.to_thread(self._load_stt)
        result = await asyncio.to_thread(stt.transcribe, pcm)
        self._last_used = self._clock()
        return result

    async def synthesize(self, text: str) -> bytes:
        """PCM16 16 kHz of the whole text in Nikita's voice."""
        self._last_used = self._clock()
        tts = await asyncio.to_thread(self._load_tts)
        pcm = await asyncio.to_thread(tts.render_blocking, text)
        self._last_used = self._clock()
        return pcm

    def unload_if_idle(self, minutes: float) -> bool:
        """Let the models go after a quiet time (``discord.voice.unload_after_minutes``)."""
        if self.active or (self._stt is None and self._tts is None):
            return False
        if self._clock() - self._last_used < minutes * 60:
            return False
        with self._lock:
            tts, self._stt, self._tts = self._tts, None, None
        if tts is not None:
            _close(tts)
        log.info("Sprachmodelle entladen (lange nicht gebraucht)")
        return True


def _close(service: Any) -> None:
    close = getattr(service, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            log.debug("Schließen fehlgeschlagen", exc_info=True)

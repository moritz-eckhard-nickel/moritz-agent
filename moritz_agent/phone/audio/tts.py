# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Text-to-speech service: engine choice, sentence streaming and caching (ADR-027).

Nikita's voice is Thorsten-Voice "Hessisch" as a Piper model on the CPU (espeak-ng is the
last-resort voice). Pre-recorded announcements and fixed phrases are rendered once and cached on
disk, so they play instantly; live answers are spoken sentence by sentence, so the first sentence
is audible while the rest is still being synthesized.

All audio leaving this module is normalized 16 kHz mono PCM16, ready for the phone line.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio import pcm
from moritz_agent.phone.audio.textnorm import normalize_for_tts, split_sentences

log = get_logger("tts")
CACHE_VERSION = "1"


class TtsError(RuntimeError):
    """Synthesis failed."""


class TtsUnavailable(TtsError):
    """No voice is ready."""


class TtsCancelled(TtsError):
    """Synthesis was cancelled (caller hung up)."""


class TtsEngine(Protocol):
    name: str
    voice_id: str  # identifies voice + model version; part of the cache key

    def available(self) -> bool: ...

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Blocking synthesis of one normalized sentence → (float32 mono samples, sample rate)."""
        ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


@dataclass
class EngineStats:
    """Moving average of synthesis speed (seconds of work per second of audio)."""

    rtf: float | None = None
    samples: int = 0

    def update(self, synth_s: float, audio_s: float) -> None:
        if audio_s <= 0.2:  # tiny clips distort the ratio
            return
        value = synth_s / audio_s
        self.rtf = value if self.rtf is None else 0.7 * self.rtf + 0.3 * value
        self.samples += 1


class _Lru:
    def __init__(self, size: int) -> None:
        self.size = size
        self._data: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            value = self._data.get(key)
            if value is not None:
                self._data.move_to_end(key)
            return value

    def put(self, key: str, value: bytes) -> None:
        if self.size <= 0:
            return
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)


class TtsService:
    def __init__(
        self,
        engines: dict[str, TtsEngine],
        primary: str,
        fallbacks: list[str],
        cache_dir: Path,
        target_dbfs: float = -20.0,
        live_cache_entries: int = 64,
    ) -> None:
        self.engines = engines
        self.primary = primary
        self.order = [primary, *[name for name in fallbacks if name != primary]]
        self.cache_dir = cache_dir
        self.target_dbfs = target_dbfs
        self.stats = {name: EngineStats() for name in engines}
        self._lru = _Lru(live_cache_entries)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")
        self._cancelled = threading.Event()

    # -- engine choice -----------------------------------------------------------------
    def ready_engines(self) -> list[str]:
        return [
            name for name in self.order if name in self.engines and self.engines[name].available()
        ]

    def best_available(self) -> str | None:
        ready = self.ready_engines()
        return ready[0] if ready else None

    # -- cache -------------------------------------------------------------------------
    def _key(self, engine: TtsEngine, sentence: str, speed: float = 1.0) -> str:
        tempo = "" if abs(speed - 1.0) < 1e-6 else f"|x{speed:.2f}"
        raw = (
            f"{CACHE_VERSION}|{engine.name}|{engine.voice_id}|{self.target_dbfs}{tempo}|{sentence}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _disk_path(self, engine: TtsEngine, key: str) -> Path:
        return self.cache_dir / engine.name / f"{key}.wav"

    def cached(self, text: str, engine_name: str) -> bytes | None:
        """Persistent cache lookup for a whole text (all sentences must be cached)."""
        engine = self.engines.get(engine_name)
        if engine is None:
            return None
        chunks = []
        for sentence in split_sentences(normalize_for_tts(text)):
            path = self._disk_path(engine, self._key(engine, sentence))
            if not path.is_file():
                return None
            audio, rate = pcm.read_wav(path)
            chunks.append(pcm.float_to_pcm16(audio).tobytes())
            assert rate == pcm.SAMPLE_RATE
        return b"".join(chunks) if chunks else None

    # -- synthesis ---------------------------------------------------------------------
    def _render_sentence(
        self,
        engine: TtsEngine,
        sentence: str,
        persist: bool,
        cancellable: bool = False,
        speed: float = 1.0,
    ) -> bytes:
        if not getattr(engine, "supports_speed", False):
            speed = 1.0  # fake and simple engines speak at their own pace
        key = self._key(engine, sentence, speed)
        hit = self._lru.get(key)
        if hit is not None:
            return hit
        path = self._disk_path(engine, key)
        if path.is_file():
            audio, _rate = pcm.read_wav(path)
            data = pcm.float_to_pcm16(audio).tobytes()
            self._lru.put(key, data)
            return data
        if cancellable and self._cancelled.is_set():
            raise TtsCancelled()
        started = time.monotonic()
        try:
            samples, rate = (
                engine.synthesize(sentence, speed)  # type: ignore[call-arg]
                if speed != 1.0
                else engine.synthesize(sentence)
            )
        except TtsError:
            raise
        except Exception as exc:
            raise TtsError(f"{engine.name}: {type(exc).__name__}: {exc}") from exc
        synth_s = time.monotonic() - started
        data = pcm.to_telephony(samples, rate, self.target_dbfs)
        audio_s = pcm.duration_s(data)
        self.stats[engine.name].update(synth_s, audio_s)
        log.info(
            "%s: %.1f s Audio in %.1f s (RTF %.2f)",
            engine.name,
            audio_s,
            synth_s,
            synth_s / max(audio_s, 0.01),
        )
        self._lru.put(key, data)
        if persist and data:
            pcm.write_wav(path, data)
        return data

    def render_blocking(
        self, text: str, *, engine_name: str | None = None, persist: bool = False
    ) -> bytes:
        """Synthesize a whole text synchronously (announcement rendering, benchmarks)."""
        name = engine_name or self.best_available()
        engine = self.engines.get(name or "")
        if engine is None or not engine.available():
            raise TtsUnavailable("keine Stimme bereit")
        sentences = split_sentences(normalize_for_tts(text))
        if not sentences:
            return b""
        return b"".join(self._render_sentence(engine, s, persist) for s in sentences)

    async def stream(
        self, text: str, *, persist: bool = False, speed: float = 1.0, gain_db: float = 0.0
    ) -> AsyncIterator[bytes]:
        """Yield normalized PCM16 16 kHz audio sentence by sentence (first audio as early as possible).

        ``speed`` (> 1 faster) and ``gain_db`` change the speaking speed and volume for this call
        only (SKILL "Sprich langsamer" / "Lauter bitte"); announcements keep their cached form.
        """
        sentences = split_sentences(normalize_for_tts(text))
        if not sentences:
            return
        engine = self.engines.get(self.best_available() or "")
        if engine is None:
            raise TtsUnavailable("keine Stimme bereit")
        self._cancelled.clear()
        loop = asyncio.get_running_loop()
        for sentence in sentences:
            try:
                data = await loop.run_in_executor(
                    self._pool, self._render_sentence, engine, sentence, persist, True, speed
                )
            except TtsError:
                # try the next voice once if the chosen one failed mid-way
                fallback = next((n for n in self.ready_engines() if n != engine.name), None)
                if fallback is None or self._cancelled.is_set():
                    raise
                log.warning("%s fehlgeschlagen – wechsle zu %s", engine.name, fallback)
                engine = self.engines[fallback]
                data = await loop.run_in_executor(
                    self._pool, self._render_sentence, engine, sentence, persist, True, speed
                )
            if data:
                yield pcm.apply_gain(data, gain_db) if gain_db else data

    def cancel(self) -> None:
        """Abort running and pending syntheses (caller hung up)."""
        self._cancelled.set()
        for engine in self.engines.values():
            try:
                engine.cancel()
            except Exception:
                log.debug("cancel() von %s fehlgeschlagen", engine.name, exc_info=True)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        for engine in self.engines.values():
            try:
                engine.close()
            except Exception:
                log.debug("close() von %s fehlgeschlagen", engine.name, exc_info=True)

    def describe(self) -> dict:
        return {
            "primary": self.primary,
            "ready": self.ready_engines(),
            "rtf": {
                name: (round(s.rtf, 2) if s.rtf is not None else None)
                for name, s in self.stats.items()
            },
        }

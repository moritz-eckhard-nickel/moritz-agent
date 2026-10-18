# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Speech-to-text: faster-whisper small on the CPU (ADR-006, PHONE-22).

Whisper tends to invent text for noise and silence ("Untertitel der Amara.org-Community …").
:meth:`Transcript.usable` therefore rejects empty, very short, low-confidence and known
hallucinated results, which makes the dialogue ask again instead of answering nonsense
(PHONE-30).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from moritz_agent.logging_setup import get_logger

log = get_logger("stt")
SAMPLE_RATE = 16_000

_HALLUCINATIONS = (
    "untertitel",
    "amara.org",
    "vielen dank fürs zuschauen",
    "vielen dank für's zuschauen",
    "danke fürs zuschauen",
    "copyright wdr",
    "swr 2020",
    "zdf, 2020",
    "bis zum nächsten mal",
)


@dataclass(frozen=True)
class Transcript:
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    audio_s: float = 0.0
    elapsed_s: float = 0.0

    def usable(self, no_speech_threshold: float = 0.6, min_avg_logprob: float = -1.0) -> bool:
        """True if the transcript is worth answering."""
        words = re.sub(r"[^\w\s]", "", self.text, flags=re.UNICODE).strip()
        if len(words) < 2:
            return False
        lowered = self.text.lower()
        if any(marker in lowered for marker in _HALLUCINATIONS):
            return False
        # Whisper is sure it was not speech – unless the decoder was very confident anyway.
        if (
            self.no_speech_prob is not None
            and self.no_speech_prob > no_speech_threshold
            and (self.avg_logprob is None or self.avg_logprob < -0.4)
        ):
            return False
        return not (self.avg_logprob is not None and self.avg_logprob < min_avg_logprob)


class SpeechToText(Protocol):
    def transcribe(self, pcm: bytes) -> Transcript:
        """Blocking transcription of mono PCM16 16 kHz audio."""
        ...


class FasterWhisperStt:
    """CTranslate2 Whisper model, loaded once and shared by all calls."""

    def __init__(
        self,
        model_dir: Path,
        compute_type: str = "int8",
        cpu_threads: int = 8,
        beam_size: int = 1,
        initial_prompt: str = "",
        language: str = "de",
    ) -> None:
        from faster_whisper import WhisperModel

        if not (model_dir / "model.bin").is_file():
            raise FileNotFoundError(
                f"Whisper-Modell fehlt: {model_dir} (laden: python -m moritz_agent.phone.audio.models fetch)"
            )
        started = time.monotonic()
        self._model = WhisperModel(
            str(model_dir),
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            local_files_only=True,
        )
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt or None
        self.language = language
        log.info(
            "Whisper geladen in %.1f s (%s, %d Threads)",
            time.monotonic() - started,
            compute_type,
            cpu_threads,
        )

    def transcribe(self, pcm: bytes) -> Transcript:
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        started = time.monotonic()
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt,
            without_timestamps=True,
        )
        parts: list[str] = []
        logprobs: list[float] = []
        no_speech: list[float] = []
        for segment in segments:
            parts.append(segment.text.strip())
            logprobs.append(segment.avg_logprob)
            no_speech.append(segment.no_speech_prob)
        elapsed = time.monotonic() - started
        result = Transcript(
            text=" ".join(p for p in parts if p).strip(),
            avg_logprob=float(np.mean(logprobs)) if logprobs else None,
            no_speech_prob=float(np.max(no_speech)) if no_speech else None,
            audio_s=audio.size / SAMPLE_RATE,
            elapsed_s=elapsed,
        )
        log.info("STT %.1f s Audio in %.2f s", result.audio_s, elapsed)
        log.debug("STT-Text: %r", result.text)  # Gesprächsinhalt nur im Debug-Log (F-03)
        return result

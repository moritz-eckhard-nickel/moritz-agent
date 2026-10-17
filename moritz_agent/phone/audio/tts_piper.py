# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Piper "Thorsten" – fast local fallback voice (same speaker as Nikita, standard German).

Piper runs in-process on the CPU and is many times faster than real time, so it keeps live
answers snappy when CosyVoice would take too long (ADR-027).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from moritz_agent.config.settings import PiperSettings
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.tts import TtsError

log = get_logger("tts")


class PiperEngine:
    name = "piper"

    def __init__(self, settings: PiperSettings, repo_root: Path) -> None:
        path = Path(settings.voice)
        self.model_path = path if path.is_absolute() else repo_root / path
        self.length_scale = settings.length_scale
        self.voice_id = f"{self.model_path.stem}/{settings.length_scale}"
        self._voice = None
        self._error = ""
        self.load()

    def load(self) -> None:
        if not self.model_path.is_file():
            self._error = f"Piper-Stimme fehlt: {self.model_path}"
            return
        try:
            from piper import PiperVoice

            self._voice = PiperVoice.load(self.model_path)
        except Exception as exc:  # broken download, missing espeak data, …
            self._error = f"{type(exc).__name__}: {exc}"
            log.warning("Piper nicht ladbar: %s", self._error)

    def available(self) -> bool:
        return self._voice is not None

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        if self._voice is None:
            raise TtsError(self._error or "Piper nicht geladen")
        from piper import SynthesisConfig

        chunks, rate = [], 22050
        for chunk in self._voice.synthesize(
            text, syn_config=SynthesisConfig(length_scale=self.length_scale)
        ):
            chunks.append(chunk.audio_int16_array)
            rate = chunk.sample_rate
        if not chunks:
            raise TtsError("Piper lieferte kein Audio")
        return np.concatenate(chunks).astype(np.float32) / 32768.0, rate

    def cancel(self) -> None:
        return None

    def close(self) -> None:
        self._voice = None

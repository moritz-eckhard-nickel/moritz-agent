# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Piper – Nikitas Stimme: Thorsten-Voice "Hessisch" (ADR-027).

Piper runs in-process on the CPU, much faster than real time, with a model of ~110 MB and
well under 1 GB of RAM. Any Piper voice can be used (``phone.tts.piper.voice``).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from moritz_agent.config.settings import PiperSettings
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.tts import TtsError

log = get_logger("tts")


class PiperEngine:
    name = "piper"

    def __init__(self, settings: PiperSettings, repo_root: Path, threads: int = 4) -> None:
        path = Path(settings.voice)
        self.model_path = path if path.is_absolute() else repo_root / path
        self.length_scale = settings.length_scale
        self.threads = threads
        # model size in the id: a replaced model file must not reuse old cached announcements
        size = self.model_path.stat().st_size if self.model_path.is_file() else 0
        self.voice_id = f"{self.model_path.stem}/{size}/{settings.length_scale}"
        self._voice = None
        self._error = ""
        self.load()

    def load(self) -> None:
        if not self.model_path.is_file():
            self._error = f"Piper-Stimme fehlt: {self.model_path}"
            log.warning("%s", self._error)
            return
        try:
            self._voice = self._load_voice()
        except Exception as exc:  # broken download, missing config, espeak data, …
            self._error = f"{type(exc).__name__}: {exc}"
            log.warning("Piper nicht ladbar: %s", self._error)

    def _load_voice(self):
        import onnxruntime
        from piper import PiperVoice
        from piper.config import PiperConfig

        config_path = Path(f"{self.model_path}.json")
        config = PiperConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = self.threads  # leave CPU for speech recognition and the rest
        session = onnxruntime.InferenceSession(
            str(self.model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        # espeak-ng data: the copy bundled with the piper-tts wheel (the constructor's default)
        return PiperVoice(config=config, session=session, download_dir=self.model_path.parent)

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

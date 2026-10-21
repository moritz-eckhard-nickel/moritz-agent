# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""espeak-ng – last-resort voice that is always available (apt install espeak-ng).

Robotic, but instant and dependency-free: the phone can still speak when no neural voice is
installed or loadable. It also makes the SIP part testable without any model download.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave

import numpy as np

from moritz_agent.config.settings import EspeakSettings
from moritz_agent.phone.audio.tts import TtsError


class EspeakEngine:
    name = "espeak"
    supports_speed = True

    def __init__(self, settings: EspeakSettings) -> None:
        self.settings = settings
        self.binary = shutil.which("espeak-ng") or shutil.which("espeak")
        self.voice_id = f"espeak/{settings.voice}/{settings.speed_wpm}"

    def available(self) -> bool:
        return self.binary is not None

    def synthesize(self, text: str, speed: float = 1.0) -> tuple[np.ndarray, int]:
        if self.binary is None:
            raise TtsError("espeak-ng ist nicht installiert (apt install espeak-ng)")
        try:
            result = subprocess.run(
                [
                    self.binary,
                    "-v",
                    self.settings.voice,
                    "-s",
                    str(round(self.settings.speed_wpm * speed)),
                    "--stdout",
                    text,
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise TtsError(f"espeak-ng fehlgeschlagen: {exc}") from exc
        with wave.open(io.BytesIO(result.stdout), "rb") as handle:
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0, rate

    def cancel(self) -> None:
        return None

    def close(self) -> None:
        return None

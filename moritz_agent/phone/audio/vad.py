# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Voice activity detection with Silero VAD (ONNX, CPU) – ADR-009, PHONE-22.

The segmenter consumes 16 kHz mono PCM16 in arbitrary chunk sizes (PJSIP delivers 20 ms
frames) and reports where an utterance starts and ends. End of speech is declared after
``min_silence_ms`` of silence; a short pre-roll and trailing pad keep the first and last
phonemes intact for the speech recognizer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 512  # Silero v5/v6 expect 512 samples at 16 kHz
WINDOW_BYTES = WINDOW_SAMPLES * 2
WINDOW_MS = WINDOW_SAMPLES * 1000 / SAMPLE_RATE  # 32 ms
CONTEXT_SAMPLES = 64
HYSTERESIS = 0.15


@dataclass(frozen=True)
class SpeechStart:
    """Speech began (emitted once per utterance)."""


@dataclass(frozen=True)
class UtteranceEnd:
    """An utterance finished; ``pcm`` is mono PCM16 at 16 kHz including pre-roll and pad."""

    pcm: bytes
    reason: str  # "silence" | "max_length"

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) // 2 * 1000 // SAMPLE_RATE


VadEvent = SpeechStart | UtteranceEnd


class SileroVad:
    """Shared ONNX session; every call creates its own :class:`VadSegmenter`."""

    def __init__(self, model_path: Path, threads: int = 1) -> None:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = threads
        self.session = onnxruntime.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )

    def new_segmenter(self, **kwargs) -> VadSegmenter:
        return VadSegmenter(self, **kwargs)


class VadSegmenter:
    """Per-call state machine on top of the Silero speech probability."""

    def __init__(
        self,
        vad: SileroVad,
        threshold: float = 0.5,
        min_silence_ms: int = 700,
        speech_pad_ms: int = 300,
        min_speech_ms: int = 250,
        max_utterance_s: float = 20.0,
    ) -> None:
        self._session = vad.session
        self.threshold = threshold
        self.neg_threshold = max(threshold - HYSTERESIS, 0.01)
        self._min_silence_windows = max(1, round(min_silence_ms / WINDOW_MS))
        self._pad_windows = max(0, round(speech_pad_ms / WINDOW_MS))
        self._min_speech_windows = max(1, round(min_speech_ms / WINDOW_MS))
        self._max_windows = max(1, round(max_utterance_s * 1000 / WINDOW_MS))
        self.reset()

    # -- public ------------------------------------------------------------------------
    def reset(self) -> None:
        """Forget everything (call before every listening phase)."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)
        self._pending = bytearray()
        self._preroll: deque[bytes] = deque(maxlen=max(1, self._pad_windows))
        self._windows: list[bytes] = []
        self._triggered = False
        self._speech_windows = 0
        self._silence_run = 0
        self._last_speech_index = -1

    @property
    def in_speech(self) -> bool:
        return self._triggered

    def feed(self, pcm: bytes) -> list[VadEvent]:
        """Feed PCM16 mono 16 kHz bytes; returns the events that happened."""
        self._pending += pcm
        events: list[VadEvent] = []
        while len(self._pending) >= WINDOW_BYTES:
            window = bytes(self._pending[:WINDOW_BYTES])
            del self._pending[:WINDOW_BYTES]
            events.extend(self._process(window, self._probability(window)))
        return events

    # -- internals ---------------------------------------------------------------------
    def _probability(self, window: bytes) -> float:
        samples = np.frombuffer(window, dtype="<i2").astype(np.float32) / 32768.0
        x = np.concatenate([self._context, samples[None, :]], axis=1)
        out, self._state = self._session.run(
            None,
            {"input": x, "state": self._state, "sr": np.array(SAMPLE_RATE, dtype=np.int64)},
        )
        self._context = x[:, -CONTEXT_SAMPLES:]
        return float(out[0][0])

    def _process(self, window: bytes, prob: float) -> list[VadEvent]:
        events: list[VadEvent] = []
        if not self._triggered:
            if prob >= self.threshold:
                self._triggered = True
                self._windows = [*self._preroll, window]
                self._last_speech_index = len(self._windows) - 1
                self._speech_windows = 1
                self._silence_run = 0
                events.append(SpeechStart())
            else:
                self._preroll.append(window)
            return events

        self._windows.append(window)
        if prob >= self.threshold:
            self._speech_windows += 1
            self._silence_run = 0
            self._last_speech_index = len(self._windows) - 1
        elif prob < self.neg_threshold:
            self._silence_run += 1

        if self._silence_run >= self._min_silence_windows:
            events.extend(self._finish("silence"))
        elif len(self._windows) >= self._max_windows:
            events.extend(self._finish("max_length"))
        return events

    def _finish(self, reason: str) -> list[VadEvent]:
        keep = self._windows[: self._last_speech_index + 1 + self._pad_windows]
        enough = self._speech_windows >= self._min_speech_windows
        self._triggered = False
        self._windows = []
        self._preroll.clear()
        self._speech_windows = 0
        self._silence_run = 0
        if not enough:
            return []  # too short: a click or cough, not speech
        return [UtteranceEnd(pcm=b"".join(keep), reason=reason)]

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import numpy as np

from moritz_agent.phone.audio import pcm


def sine(seconds: float, rate: int = pcm.SAMPLE_RATE, amplitude: float = 0.1) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_pcm16_roundtrip():
    samples = sine(0.1)
    back = pcm.pcm16_to_float(pcm.float_to_pcm16(samples).tobytes())
    assert np.max(np.abs(back - samples)) < 1e-3


def test_resample_changes_length():
    out = pcm.resample(sine(1.0, 22050), 22050, pcm.SAMPLE_RATE)
    assert abs(len(out) - pcm.SAMPLE_RATE) <= 2


def test_loudness_is_normalized_and_peaks_are_limited():
    quiet = pcm.normalize_loudness(sine(1.0, amplitude=0.01), -20.0)
    assert abs(pcm.rms_dbfs(quiet) + 20.0) < 0.5
    loud = pcm.normalize_loudness(sine(1.0, amplitude=0.9), -6.0)
    assert float(np.abs(loud).max()) <= 10 ** (-1.5 / 20) + 1e-3


def test_trim_silence_keeps_the_speech():
    padded = np.concatenate([np.zeros(16000, np.float32), sine(0.5), np.zeros(16000, np.float32)])
    trimmed = pcm.trim_silence(padded)
    assert 0.5 <= len(trimmed) / pcm.SAMPLE_RATE < 0.8


def test_frames_are_20ms_and_complete():
    data = bytes(range(256)) * 10
    frames = list(pcm.chunk_frames(data))
    assert all(len(f) == pcm.FRAME_BYTES for f in frames)
    assert b"".join(frames).startswith(data[: pcm.FRAME_BYTES])


def test_wav_roundtrip(tmp_path):
    data = pcm.float_to_pcm16(sine(0.2)).tobytes()
    pcm.write_wav(tmp_path / "a.wav", data)
    samples, rate = pcm.read_wav(tmp_path / "a.wav")
    assert rate == pcm.SAMPLE_RATE and len(samples) == len(data) // 2
    assert pcm.wav_bytes(data).startswith(b"RIFF")

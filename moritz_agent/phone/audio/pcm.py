# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""PCM helpers for the phone audio path (PHONE-05).

Everything inside the phone worker is mono, 16-bit, 16 kHz (the wideband rate of G.722; the
PJSIP conference bridge resamples to and from 8 kHz codecs). Audio is only ever held in
memory or in the announcement cache – never as call recordings (PHONE-43).
"""

from __future__ import annotations

import wave
from collections.abc import Iterator
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2
PEAK_LIMIT_DBFS = -1.5


def pcm16_to_float(pcm: np.ndarray | bytes) -> np.ndarray:
    """int16 samples (array or little-endian bytes) → float32 in [-1, 1)."""
    if isinstance(pcm, bytes | bytearray | memoryview):
        pcm = np.frombuffer(pcm, dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def float_to_pcm16(samples: np.ndarray) -> np.ndarray:
    """float samples → int16 with clipping."""
    return np.clip(np.rint(samples * 32768.0), -32768, 32767).astype("<i2")


def resample(samples: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """Resample float32 mono audio with libsoxr (high quality)."""
    if rate_in == rate_out or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    import soxr

    return soxr.resample(samples.astype(np.float32, copy=False), rate_in, rate_out, quality="HQ")


def rms_dbfs(samples: np.ndarray) -> float:
    """RMS level in dBFS of float audio; -120 for silence."""
    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20.0 * np.log10(rms) if rms > 1e-6 else -120.0


def normalize_loudness(
    samples: np.ndarray, target_dbfs: float = -20.0, peak_dbfs: float = PEAK_LIMIT_DBFS
) -> np.ndarray:
    """Scale to a target RMS level and keep peaks below ``peak_dbfs`` (telephone loudness)."""
    level = rms_dbfs(samples)
    if level <= -100.0:
        return samples
    out = samples * (10.0 ** ((target_dbfs - level) / 20.0))
    peak = float(np.max(np.abs(out)))
    limit = 10.0 ** (peak_dbfs / 20.0)
    if peak > limit:
        out = out * (limit / peak)
    return out.astype(np.float32, copy=False)


def trim_silence(
    samples: np.ndarray, rate: int = SAMPLE_RATE, threshold_dbfs: float = -45.0, keep_ms: int = 80
) -> np.ndarray:
    """Cut leading/trailing near-silence, keeping a short margin."""
    if samples.size == 0:
        return samples
    window = max(1, rate // 100)  # 10 ms
    usable = samples.size - samples.size % window
    if usable == 0:
        return samples
    levels = np.sqrt(np.mean(np.square(samples[:usable].reshape(-1, window)), axis=1))
    loud = np.where(levels > 10.0 ** (threshold_dbfs / 20.0))[0]
    if loud.size == 0:
        return samples[:0]
    keep = rate * keep_ms // 1000
    start = max(0, int(loud[0]) * window - keep)
    end = min(samples.size, (int(loud[-1]) + 1) * window + keep)
    return samples[start:end]


def to_telephony(samples: np.ndarray, rate_in: int, target_dbfs: float = -20.0) -> bytes:
    """Float audio at any rate → normalized 16 kHz mono PCM16 bytes for playback."""
    mono = resample(samples, rate_in, SAMPLE_RATE)
    mono = normalize_loudness(trim_silence(mono), target_dbfs)
    return float_to_pcm16(mono).tobytes()


def apply_gain(pcm: bytes, gain_db: float) -> bytes:
    """Scale PCM16 by ``gain_db`` (with clipping protection)."""
    samples = pcm16_to_float(pcm) * (10 ** (gain_db / 20))
    return float_to_pcm16(np.clip(samples, -1.0, 1.0)).tobytes()


def duration_s(pcm: bytes | np.ndarray, rate: int = SAMPLE_RATE) -> float:
    n = len(pcm) // 2 if isinstance(pcm, bytes | bytearray) else int(pcm.size)
    return n / rate


def silence(ms: int, rate: int = SAMPLE_RATE) -> bytes:
    return bytes(2 * rate * ms // 1000)


def beep(ms: int = 220, freq: float = 880.0, count: int = 2, rate: int = SAMPLE_RATE) -> bytes:
    """A short double beep (the sound before "Die Zeit ist um.")."""
    n = rate * ms // 1000
    t = np.arange(n) / rate
    envelope = np.minimum(1.0, np.minimum(t, t[::-1] + 1 / rate) * 200)  # no clicks
    tone = (0.35 * np.sin(2 * np.pi * freq * t) * envelope).astype(np.float32)
    gap = np.zeros(rate * 90 // 1000, dtype=np.float32)
    parts: list[np.ndarray] = []
    for _ in range(count):
        parts += [tone, gap]
    return float_to_pcm16(np.concatenate(parts)).tobytes()


def chunk_frames(pcm: bytes, frame_bytes: int = FRAME_BYTES) -> Iterator[bytes]:
    """Split PCM into fixed-size frames (last one zero padded)."""
    for offset in range(0, len(pcm), frame_bytes):
        frame = pcm[offset : offset + frame_bytes]
        if len(frame) < frame_bytes:
            frame += bytes(frame_bytes - len(frame))
        yield frame


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a mono/stereo 16-bit WAV file → (float32 mono, sample rate)."""
    with wave.open(str(path), "rb") as handle:
        channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"{path}: only 16-bit WAV is supported")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def write_wav(path: Path, pcm: bytes, rate: int = SAMPLE_RATE) -> None:
    """Write mono PCM16 bytes to a WAV file atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(tmp), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    tmp.replace(path)


def wav_bytes(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """PCM16 mono → WAV container bytes (in memory)."""
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()

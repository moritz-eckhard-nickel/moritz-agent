# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Build the speech components from the settings."""

from __future__ import annotations

from pathlib import Path

from moritz_agent.config.settings import REPO_ROOT, Settings
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.stt import FasterWhisperStt, SpeechToText
from moritz_agent.phone.audio.tts import TtsEngine, TtsService
from moritz_agent.phone.audio.vad import SileroVad

log = get_logger("phone")


def build_tts(settings: Settings, root: Path = REPO_ROOT) -> TtsService:
    """Create the TTS service with the configured voice chain (Piper, then espeak-ng)."""
    tts = settings.phone.tts
    wanted = [tts.engine, *tts.fallback_engines]
    engines: dict[str, TtsEngine] = {}
    for name in dict.fromkeys(wanted):  # unique, ordered
        if name == "piper":
            from moritz_agent.phone.audio.tts_piper import PiperEngine

            engines[name] = PiperEngine(tts.piper, root, tts.cpu_threads)
        elif name == "espeak":
            from moritz_agent.phone.audio.tts_espeak import EspeakEngine

            engines[name] = EspeakEngine(tts.espeak)
    return TtsService(
        engines=engines,
        primary=tts.engine,
        fallbacks=list(tts.fallback_engines),
        cache_dir=settings.resolve(tts.cache_dir, root),
        target_dbfs=tts.loudness_target_dbfs,
        live_cache_entries=tts.live_cache_entries,
    )


def build_stt(settings: Settings, root: Path = REPO_ROOT) -> SpeechToText:
    cfg = settings.phone.stt
    return FasterWhisperStt(
        settings.resolve(cfg.model, root),
        compute_type=cfg.compute_type,
        cpu_threads=cfg.cpu_threads,
        beam_size=cfg.beam_size,
        initial_prompt=cfg.initial_prompt,
    )


def build_vad(settings: Settings, root: Path = REPO_ROOT) -> SileroVad:
    return SileroVad(settings.resolve(settings.phone.vad.model, root))

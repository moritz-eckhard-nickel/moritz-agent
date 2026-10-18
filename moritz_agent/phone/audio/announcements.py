# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Pre-recorded announcements (greeting, "didn't understand", goodbye, …) – ADR-011, ADR-027.

The catalog lives in assets/audio/prompts.de.toml. Every entry is rendered once and cached on
disk (16 kHz WAV), so a call starts with the greeting instantly, without waiting for any model.

:meth:`AnnouncementStore.ensure` makes sure every required announcement exists – taken from the
cache, else rendered with the best voice that is ready (Piper "Hessisch"; espeak-ng if the Piper
model is missing). The cache key contains the voice, so installing the real voice later renders
everything again with it instead of reusing the emergency-voice recordings.
"""

from __future__ import annotations

import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path

from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.tts import TtsError, TtsService

log = get_logger("tts")


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    required: bool


def load_catalog(path: Path, values: dict[str, str]) -> dict[str, Prompt]:
    """Read the TOML catalog; ``{placeholders}`` are filled from ``values``."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    catalog: dict[str, Prompt] = {}
    for prompt_id, entry in raw.items():
        text = str(entry["text"]).format(**values)
        catalog[prompt_id] = Prompt(prompt_id, text, bool(entry.get("required", True)))
    return catalog


class AnnouncementStore:
    def __init__(self, tts: TtsService, catalog: dict[str, Prompt]) -> None:
        self.tts = tts
        self.catalog = catalog
        self._audio: dict[str, tuple[str, bytes]] = {}  # id -> (engine name, pcm16 16 kHz)
        self._lock = threading.Lock()

    # -- lookup ------------------------------------------------------------------------
    def get(self, prompt_id: str) -> bytes | None:
        with self._lock:
            entry = self._audio.get(prompt_id)
        return entry[1] if entry else None

    def missing_required(self) -> list[str]:
        return [p.id for p in self.catalog.values() if p.required and self.get(p.id) is None]

    def voice(self) -> str | None:
        """Voice the loaded announcements were rendered with (None while nothing is loaded)."""
        with self._lock:
            engines = {engine for engine, _ in self._audio.values()}
        return ", ".join(sorted(engines)) or None

    def status(self) -> dict:
        return {
            "total": len(self.catalog),
            "loaded": len(self._audio),
            "missing_required": self.missing_required(),
            "voice": self.voice(),
        }

    # -- rendering ---------------------------------------------------------------------
    def _set(self, prompt_id: str, engine: str, data: bytes) -> None:
        with self._lock:
            self._audio[prompt_id] = (engine, data)

    def ensure(self) -> list[str]:
        """Load or render all announcements; returns the ids of required ones still missing."""
        engine = self.tts.best_available()
        if engine is None:
            log.warning("Ansagen können nicht erzeugt werden: keine Stimme bereit")
            return self.missing_required()
        for prompt in self.catalog.values():
            data = self.tts.cached(prompt.text, engine)
            if data is None:
                try:
                    data = self.tts.render_blocking(prompt.text, engine_name=engine, persist=True)
                except TtsError as exc:
                    log.warning("Ansage '%s' fehlgeschlagen: %s", prompt.id, exc)
                    continue
            self._set(prompt.id, engine, data)
        return self.missing_required()


def quarter_hour_phrases() -> list[str]:
    """Phrases of the time fast path for every quarter hour – optional cache warm-up."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from moritz_agent.tools.time_tool import format_time_de

    zone = ZoneInfo("Europe/Berlin")
    return [
        format_time_de(datetime(2026, 1, 15, hour, minute, tzinfo=zone))
        for hour in range(24)
        for minute in (0, 15, 30, 45)
    ]

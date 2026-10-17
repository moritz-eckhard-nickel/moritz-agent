# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Pre-recorded announcements (greeting, "didn't understand", goodbye, …) – ADR-011, ADR-027.

The catalog lives in assets/audio/prompts.de.toml. Every entry is rendered once and cached on
disk (16 kHz WAV), so a call starts with the greeting instantly, without waiting for any model.

* :meth:`AnnouncementStore.ensure` makes sure every required announcement exists – rendered
  with the best voice that is ready *now*. If the main voice (CosyVoice, ~minute load time)
  is not ready yet, a faster voice is used so that the phone can register immediately.
* :meth:`AnnouncementStore.upgrade_once` later re-renders those announcements with the main
  voice, one at a time and only while no call is running.
"""

from __future__ import annotations

import threading
import tomllib
from collections.abc import Callable
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

    def provisional(self) -> list[str]:
        """Announcements currently spoken by a fallback voice instead of the main voice."""
        with self._lock:
            return [pid for pid, (engine, _) in self._audio.items() if engine != self.tts.primary]

    def status(self) -> dict:
        return {
            "total": len(self.catalog),
            "loaded": len(self._audio),
            "missing_required": self.missing_required(),
            "provisional": self.provisional(),
        }

    # -- rendering ---------------------------------------------------------------------
    def _set(self, prompt_id: str, engine: str, data: bytes) -> None:
        with self._lock:
            self._audio[prompt_id] = (engine, data)

    def ensure(self) -> list[str]:
        """Load or render all announcements with what is ready now; returns missing required ids."""
        for prompt in self.catalog.values():
            # 1. a cached rendering by the main voice, else by any other voice
            found = False
            for engine in self.tts.order:
                data = self.tts.cached(prompt.text, engine)
                if data:
                    self._set(prompt.id, engine, data)
                    found = True
                    break
            if found:
                continue
            # 2. render with the best voice that is ready right now
            engine = self.tts.best_available()
            if engine is None:
                log.warning("Ansage '%s' kann nicht erzeugt werden: keine Stimme bereit", prompt.id)
                continue
            try:
                data = self.tts.render_blocking(prompt.text, engine_name=engine, persist=True)
            except TtsError as exc:
                log.warning("Ansage '%s' fehlgeschlagen: %s", prompt.id, exc)
                continue
            self._set(prompt.id, engine, data)
        return self.missing_required()

    def upgrade_once(self, idle: Callable[[], bool] = lambda: True) -> bool:
        """Re-render one provisional announcement with the main voice. True if work was done."""
        if self.tts.primary not in self.tts.ready_engines():
            return False
        for prompt_id in self.provisional():
            if not idle():
                return False
            prompt = self.catalog[prompt_id]
            try:
                data = self.tts.render_blocking(
                    prompt.text, engine_name=self.tts.primary, persist=True
                )
            except TtsError as exc:
                log.warning("Upgrade der Ansage '%s' fehlgeschlagen: %s", prompt_id, exc)
                return False
            self._set(prompt_id, self.tts.primary, data)
            log.info("Ansage '%s' mit der Hauptstimme erneuert", prompt_id)
            return True
        return False


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

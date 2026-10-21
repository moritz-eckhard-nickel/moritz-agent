# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Rotating mischievous activities and what the worker knows about the situation (docs/plan/14 §8.5)."""

from __future__ import annotations

import time
import tomllib
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.config.settings import Discord
from moritz_agent.discord import activities
from moritz_agent.discord.activities import Activity, ActivityPicker
from moritz_agent.logging_setup import get_logger

log = get_logger("discord")
LOCAL_FILE = "data/discord/aktivitaeten.local.toml"
SITUATION_EVERY_S = 60.0
MAX_OWN = 50

SetPresence = Callable[[Activity | None], Awaitable[None]]
GetSituation = Callable[[], Awaitable[dict[str, Any]]]


class ActivityManager:
    """Decides what Nikita shows, when it changes, and keeps the owner's own sayings."""

    def __init__(
        self,
        root: Path,
        state_root: Path,
        cfg: Callable[[], Discord],
        timezone: Callable[[], str],
        set_presence: SetPresence,
        situation: GetSituation,
        *,
        clock: Callable[[], datetime] | None = None,
        seed: int | None = None,
    ) -> None:
        self.root = root
        self.local = state_root / LOCAL_FILE
        self.cfg = cfg
        self.timezone = timezone
        self.set_presence = set_presence
        self.situation = situation
        self.clock = clock or (lambda: datetime.now(ZoneInfo(self.timezone())))
        self.flags: dict[str, bool] = {"startup": True}  # voice, maintenance … set from outside
        self.enabled = True
        self._seed = seed
        self._picker: ActivityPicker | None = None
        self._last_picker: ActivityPicker | None = None
        self._cached: tuple[float, dict[str, Any]] = (0.0, {})
        self._shown: Activity | None = None

    # -- picker --------------------------------------------------------------------------------------
    def picker(self) -> ActivityPicker:
        if self._picker is None:
            try:
                data = activities.load(self.root, self.local)
            except (tomllib.TOMLDecodeError, OSError) as exc:
                # the shipped list is broken (or unreadable): keep what is shown, try again later
                log.warning("Aktivitäten: Liste nicht lesbar (%s)", type(exc).__name__)
                if self._last_picker is not None:
                    return self._last_picker
                raise
            self._last_picker = None
            problems = activities.validate(data)
            if problems:
                log.warning("Aktivitäten: %s", "; ".join(problems[:3]))
            self._picker = ActivityPicker(data, self.cfg().activities, seed=self._seed)
            self._last_picker = self._picker
        return self._picker

    def reload(self) -> None:
        """New settings or a new own saying: read everything again at the next change."""
        self._picker = None

    # -- situation -----------------------------------------------------------------------------------
    async def current_situation(self) -> dict[str, Any]:
        stamp, cached = self._cached
        if time.monotonic() - stamp > SITUATION_EVERY_S:
            try:
                cached = dict(await self.situation())
            except Exception:
                log.debug("Lage nicht abrufbar", exc_info=True)
                cached = {**cached, "services_down": True}
            self._cached = (time.monotonic(), cached)
        return {**cached, **{k: v for k, v in self.flags.items() if v}}

    # -- the loop calls this every few seconds -------------------------------------------------------
    async def tick(self) -> Activity | None:
        if not self.enabled or not self.cfg().activities.enabled:
            if self._shown is not None:
                self._shown = None
                await self.set_presence(None)
            return None
        situation = await self.current_situation()
        picker = self.picker()
        now = self.clock()
        if not picker.due(situation, now):
            return None
        return await self._show(picker.pick(situation, now))

    async def _show(self, activity: Activity) -> Activity:
        self._shown = activity
        await self.set_presence(activity)
        return activity

    # -- ActivityControl (for /aktivitaet) -----------------------------------------------------------
    async def change(self) -> Activity | None:
        if not self.enabled:
            await self.enable(True)
        situation = await self.current_situation()
        return await self._show(self.picker().pick(situation, self.clock()))

    async def enable(self, on: bool) -> None:
        self.enabled = on
        self._cached = (0.0, self._cached[1])
        if not on:
            self._shown = None
            await self.set_presence(None)

    def suggest(self, kind: str, text: str) -> str | None:
        """Keep an own saying of the owner (``data/discord/aktivitaeten.local.toml``)."""
        if kind not in activities.KINDS:
            return "Die Art kenne ich nicht."
        if any(unicodedata.category(c) in {"Cc", "Cs"} for c in text):  # incl. U+007F
            return "Der Spruch darf keine Steuerzeichen enthalten."
        if not text or len(text) > activities.MAX_TEXT:
            return f"Der Spruch darf höchstens {activities.MAX_TEXT} Zeichen haben."
        existing: list[dict[str, str]] = []
        if self.local.is_file():
            try:
                with self.local.open("rb") as handle:
                    existing = list(tomllib.load(handle).get("base", []))
            except (tomllib.TOMLDecodeError, OSError) as exc:
                log.warning("Aktivitäten: eigene Sprüche nicht lesbar (%s)", type(exc).__name__)
                return "Die Datei mit den eigenen Sprüchen ist kaputt – bitte von Hand prüfen."
        if len(existing) >= MAX_OWN:
            return "Das sind schon ziemlich viele eigene Sprüche."
        if any(e["text"] == text for e in existing):
            return "Den Spruch habe ich schon."
        existing.append({"kind": kind, "text": text})
        self.local.parent.mkdir(parents=True, exist_ok=True)
        body = "# SPDX-License-Identifier: LicenseRef-MSOL-1.1\n# Eigene Sprüche (/aktivitaet vorschlag)\n"
        for entry in existing:
            body += f'\n[[base]]\nkind = "{entry["kind"]}"\ntext = {_toml_string(entry["text"])}\n'
        tmp = self.local.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self.local)
        self.reload()
        return None


def _toml_string(text: str) -> str:
    """A TOML basic string; control characters are escaped (TOML forbids them raw)."""
    out = []
    for char in text:
        if char in {"\\", '"'}:
            out.append("\\" + char)
        elif unicodedata.category(char) == "Cc":
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'

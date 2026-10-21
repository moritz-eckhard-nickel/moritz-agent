# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Mischievous activities in the member list (docs/plan/14 §8.5, ADR-037).

Every 7–15 minutes another one (never before five – Discord limits presence updates), none of the
last ten again; the situation (call, voice channel, night, weather, warning, special day) comes
first. A serious warning gets a serious status, no joke.
"""

from __future__ import annotations

import random
import tomllib
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from moritz_agent.config.settings import DiscordActivities
from moritz_agent.logging_setup import get_logger
from moritz_agent.skills.calendar.holidays import easter

log = get_logger("discord")

ACTIVITY_FILE = "assets/data/discord/aktivitaeten.de.toml"
MIN_CHANGE = timedelta(minutes=5)
REMEMBER = 10
KINDS = {"playing", "listening", "watching", "competing", "custom"}
MAX_TEXT = 128
WARNING_LEVEL = 3


@dataclass(frozen=True)
class Activity:
    kind: str
    text: str
    serious: bool = False


def load(root: Path, local: Path | None = None) -> dict[str, Any]:
    with (root / ACTIVITY_FILE).open("rb") as handle:
        data = tomllib.load(handle)
    if local is not None and local.is_file():  # /aktivitaet vorschlag: the owner's own sayings
        try:
            with local.open("rb") as handle:
                own = list(tomllib.load(handle).get("base", []))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            # a broken own file must not stop the rotation: the shipped list alone
            log.warning("Aktivitäten: eigene Sprüche nicht lesbar (%s)", type(exc).__name__)
            own = []
        data["base"] = [*data.get("base", []), *own]
    return data


def validate(data: dict[str, Any]) -> list[str]:
    """Problems of the activity file (kinds, lengths, empty lists) – an empty list means fine."""
    problems = []
    entries = list(data.get("base", [])) + list(data.get("special", []))
    for entry in entries:
        if entry.get("kind") not in KINDS:
            problems.append(f"unbekannte Art: {entry}")
        if not entry.get("text") or len(entry["text"]) > MAX_TEXT:
            problems.append(f"Text fehlt oder ist zu lang: {entry}")
    for name, entry in data.get("situation", {}).items():
        if entry.get("kind") not in KINDS or not entry.get("text"):
            problems.append(f"Lage {name}: Art oder Texte fehlen")
        problems += [f"Lage {name}: zu lang" for t in entry.get("text", []) if len(t) > MAX_TEXT]
    if len(data.get("base", [])) < 12:
        problems.append("zu wenige Aktivitäten in der Grundliste (mindestens 12)")
    return problems


def _in_season(entry: dict[str, Any], today: date) -> bool:
    if "easter" in entry:
        first, last = entry["easter"]
        base = easter(today.year)
        return base + timedelta(days=first) <= today <= base + timedelta(days=last)
    start, end = entry["from"], entry["to"]
    key = f"{today.month:02d}-{today.day:02d}"
    return start <= key <= end if start <= end else key >= start or key <= end


class ActivityPicker:
    def __init__(
        self,
        data: dict[str, Any],
        cfg: DiscordActivities,
        *,
        seed: int | None = None,
        night: tuple[str, str] | None = None,
    ) -> None:
        self.data = data
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.recent: deque[str] = deque(maxlen=REMEMBER)
        self.current: Activity | None = None
        self.changed_at: datetime | None = None
        self.next_change: datetime | None = None
        start, end = cfg.night.split("-")
        self.night = night or (start, end)

    # -- situation -----------------------------------------------------------------------------------
    def _is_night(self, now: datetime) -> bool:
        key = now.strftime("%H:%M")
        start, end = self.night
        return start <= key or key < end if start > end else start <= key < end

    def situation_name(self, situation: dict[str, Any], now: datetime) -> str | None:
        """The situation that applies right now, the most important first (None = nothing special)."""
        if not self.cfg.situational:
            return None
        if situation.get("startup"):
            return "startup"
        if situation.get("maintenance"):
            return "maintenance"
        if situation.get("warning_level", 0) >= WARNING_LEVEL:
            return "warning"
        if situation.get("call"):
            return "call"
        if situation.get("voice"):
            return "voice"
        if situation.get("services_down"):
            return "offline"
        if self._is_night(now):
            return "night"
        if situation.get("weather") in {"rain", "snow", "hot", "thunder"}:
            return str(situation["weather"])
        return None

    def _special(self, today: date) -> Activity | None:
        for entry in self.data.get("special", []):
            if _in_season(entry, today):
                return Activity(entry["kind"], entry["text"])
        return None

    # -- choosing ----------------------------------------------------------------------------------------
    def _base(self) -> Activity:
        entries = self.data["base"]
        fresh = [e for e in entries if e["text"] not in self.recent] or entries
        entry = fresh[self.rng.randrange(len(fresh))]
        return Activity(entry["kind"], entry["text"])

    def pick(self, situation: dict[str, Any], now: datetime) -> Activity:
        """The next activity: situation first, then a special day, then the base list."""
        name = self.situation_name(situation, now)
        chosen: Activity | None = None
        entry = self.data.get("situation", {}).get(name) if name else None
        if entry:
            texts = entry["text"]
            chosen = Activity(
                entry["kind"], texts[self.rng.randrange(len(texts))], name == "warning"
            )
        if chosen is None and self.cfg.situational:
            chosen = self._special(now.date())
            if chosen is not None and self.rng.random() < 0.5:
                chosen = None  # not always the same one on a special day
        if chosen is None:
            chosen = self._base()
        self.recent.append(chosen.text)
        self.current = chosen
        self.current_situation = name
        self.changed_at = now
        low, high = self.cfg.rotate_minutes
        self.next_change = now + timedelta(minutes=self.rng.uniform(low, high))
        return chosen

    def due(self, situation: dict[str, Any], now: datetime) -> bool:
        """Time for another one? A new situation (a call begins) counts at once; the random
        rotation never changes sooner than ``rotate_minutes`` (at least five, Discord's limit)."""
        if not self.cfg.enabled:
            return False
        if self.current is None or self.next_change is None:
            return True
        if self.situation_name(situation, now) != self.current_situation:
            return True
        return now >= self.next_change

    current_situation: str | None = None

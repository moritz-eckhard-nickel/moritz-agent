# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The planner: reminders, warning subscriptions, morning briefing, waste hint, system messages.

It runs in the main process and only fills the *outbox* of the database; the Discord worker fetches
and sends from there. So everything here works – and is tested – without Discord (P1-38).

* reminders survive a restart; one that came due while the service was off is delivered "verspätet"
  if it is at most 12 hours old
* warnings are announced once per change; a warning below level 3 waits for the end of the quiet
  hours, an update or an end ("Entwarnung") is announced as well
* every kind of message has a ``dedupe_key`` so nothing is sent twice
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from moritz_agent.config.settings import Discord
from moritz_agent.logging_setup import get_logger
from moritz_agent.storage.discord import DiscordStore, parse_iso

log = get_logger("system")

CATCH_UP_H = 12
LATE_AFTER_MIN = 5
WARNING_CHECK_S = 600
BRIEFING_WINDOW_H = 3
WASTE_TIME = time(19, 0)
LEVELS = {"moderate": 2, "severe": 3, "extreme": 4}
DEFAULT_TARGET = "default"  # the default text channel

Ask = Callable[[str, str], Awaitable[Any]]  # (user_id, text) → Outcome of the skills
Alerts = Callable[[str], Awaitable[list[Any]]]  # user_id → warnings of the user's home


def parse_range(text: str) -> tuple[time, time]:
    match = re.fullmatch(r"(\d\d):(\d\d)-(\d\d):(\d\d)", text)
    if match is None:
        raise ValueError(text)
    a, b, c, d = (int(x) for x in match.groups())
    return time(a, b), time(c, d)


def in_range(moment: datetime, span: str) -> bool:
    """Inside ``HH:MM-HH:MM`` (also across midnight: 22:00-07:00)."""
    start, end = parse_range(span)
    now = moment.time().replace(second=0, microsecond=0)
    return start <= now < end if start <= end else now >= start or now < end


def quiet_end(moment: datetime, span: str) -> datetime:
    """The next moment the quiet hours are over."""
    _, end = parse_range(span)
    candidate = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    return candidate if candidate > moment else candidate + timedelta(days=1)


@dataclass
class Tick:
    reminders: int = 0
    warnings: int = 0
    briefings: int = 0
    other: int = 0


class Scheduler:
    def __init__(
        self,
        store: DiscordStore,
        cfg: Callable[[], Discord],
        now: Callable[[], datetime],
        *,
        ask: Ask,
        alerts: Alerts,
        timezone: Callable[[], str] = lambda: "Europe/Berlin",
    ) -> None:
        self.store = store
        self.cfg = cfg
        self.now = now
        self.ask = ask
        self.alerts = alerts
        self.timezone = timezone

    # -- targets ----------------------------------------------------------------------------------------
    def _target(self, user_id: str) -> str:
        return DEFAULT_TARGET if self.cfg().notify.target == "channel" else f"dm:{user_id}"

    def _quiet(self, user_id: str, moment: datetime) -> str | None:
        """The quiet hours that apply at ``moment`` for this person (None = not quiet)."""
        principal = self.store.principal(user_id)
        span = (principal or {}).get("quiet_hours") or self.cfg().quiet_hours
        return span if span and in_range(moment, span) else None

    def ensure_defaults(self, user_id: str) -> None:
        """First contact of the owner: warnings from level 3 and system notes are on (F-32)."""
        if self.store.state(f"defaults:{user_id}"):
            return
        cfg = self.cfg()
        self.store.set_subscription(
            user_id, "warnings", {"level": LEVELS[cfg.notify.warnings_default_level]}
        )
        if cfg.notify.system_alerts:
            self.store.set_subscription(user_id, "system", {})
        self.store.set_state(f"defaults:{user_id}", "1")

    # -- main loop ----------------------------------------------------------------------------------------
    async def tick(self) -> Tick:
        """Call about every ten seconds."""
        now = self.now()
        result = Tick()
        result.reminders = self._reminders(now)
        if self._due(now, "warnings", WARNING_CHECK_S):
            result.warnings = await self._warnings(now)
        result.briefings = await self._briefings(now)
        result.other = await self._waste(now)
        if self._due(now, "purge", 86400):
            self.store.purge_outbox(now)
        return result

    def _due(self, now: datetime, name: str, every_s: int) -> bool:
        """True at most every ``every_s`` seconds (remembered in the database)."""
        key = f"last:{name}"
        last = self.store.state(key)
        if last is not None and (now - parse_iso(last)).total_seconds() < every_s:
            return False
        self.store.set_state(key, now.isoformat(timespec="seconds"))
        return True

    # -- reminders ----------------------------------------------------------------------------------------
    def _reminders(self, now: datetime) -> int:
        sent = 0
        for item in self.store.due_reminders(now):
            due = parse_iso(item["due_at"])
            age = now - due
            self.store.mark_reminder_delivered(item["id"], now)
            if age > timedelta(hours=CATCH_UP_H):
                log.info("Erinnerung %d war zu alt (%s), verworfen", item["id"], age)
                continue
            late = " (verspätet)" if age > timedelta(minutes=LATE_AFTER_MIN) else ""
            self.store.enqueue(
                "reminder",
                item["target"],
                {"title": f"⏰ Erinnerung{late}", "text": item["text"], "mention": item["user_id"]},
                user_id=item["user_id"],
                dedupe_key=f"reminder:{item['id']}",
            )
            sent += 1
        return sent

    # -- warnings ------------------------------------------------------------------------------------------
    async def _warnings(self, now: datetime) -> int:
        sent = 0
        for sub in self.store.subscriptions("warnings"):
            user = sub["user_id"]
            threshold = int(sub["params"].get("level", 3))
            try:
                warnings = await self.alerts(user)
            except Exception:
                log.debug("Warnungen für %s nicht abrufbar", user, exc_info=True)
                continue
            known = self.store.states(f"warn:{user}:")
            current: dict[str, Any] = {}
            for w in warnings:
                if w.level >= threshold and (w.end is None or w.end > now):
                    current[f"warn:{user}:{w.uid or w.event + w.start.isoformat()}"] = w
            quiet = self._quiet(user, now)
            for key, w in current.items():
                if known.get(key) == str(w.level):
                    continue
                if quiet and w.level < 3:
                    continue  # waits for the end of the quiet hours; stays "unknown" until then
                payload = {
                    "title": f"⚠️ {w.headline or w.event}",
                    "text": w.description or w.event,
                    "level": w.level,
                    "instruction": w.instruction,
                    "until": w.end.isoformat(timespec="minutes") if w.end else "",
                    "source": w.source,
                }
                self.store.enqueue(
                    "warning",
                    self._target(user),
                    payload,
                    user_id=user,
                    serious=True,
                    dedupe_key=f"{key}:{w.level}",
                )
                self.store.set_state(key, str(w.level))
                sent += 1
            for key in set(known) - set(current):
                self.store.enqueue(
                    "all_clear",
                    self._target(user),
                    {"title": "Entwarnung", "text": "Die Warnung ist beendet."},
                    user_id=user,
                    serious=True,
                    dedupe_key=f"clear:{key}",
                )
                self.store.drop_state(key)
                sent += 1
        return sent

    # -- briefing and waste -----------------------------------------------------------------------------------
    async def _briefings(self, now: datetime) -> int:
        sent = 0
        for sub in self.store.subscriptions("briefing"):
            user, at = sub["user_id"], sub["params"].get("time", "06:45")
            hour, minute = (int(x) for x in at.split(":"))
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if not start <= now < start + timedelta(hours=BRIEFING_WINDOW_H):
                continue
            if sub["params"].get("weekdays") and now.weekday() >= 5:
                continue
            marker = f"briefing:{user}"
            if self.store.state(marker) == now.date().isoformat():
                continue
            self.store.set_state(marker, now.date().isoformat())
            outcome = await self.ask(user, "Morgenbriefing")
            if outcome is None or outcome.result is None or not outcome.result.text:
                continue
            self.store.enqueue(
                "briefing",
                self._target(user),
                {"title": "☀️ Guten Morgen", "text": outcome.result.text, "mention": user},
                user_id=user,
                dedupe_key=f"briefing:{user}:{now.date().isoformat()}",
            )
            sent += 1
        return sent

    async def _waste(self, now: datetime) -> int:
        sent = 0
        for sub in self.store.subscriptions("waste"):
            user = sub["user_id"]
            if now.time() < WASTE_TIME or now.time() >= time(21, 0):
                continue
            marker = f"waste:{user}"
            if self.store.state(marker) == now.date().isoformat():
                continue
            self.store.set_state(marker, now.date().isoformat())
            outcome = await self.ask(user, "Welche Tonne kommt morgen?")
            result = getattr(outcome, "result", None)
            if result is None or not (result.data or {}).get("pickups"):
                continue
            self.store.enqueue(
                "waste",
                self._target(user),
                {"title": "🗑️ Müllabfuhr", "text": result.text, "mention": user},
                user_id=user,
                dedupe_key=f"waste:{user}:{now.date().isoformat()}",
            )
            sent += 1
        return sent

    # -- events from elsewhere ----------------------------------------------------------------------------------
    def system_event(self, kind: str, text: str) -> int:
        """A note for the owners ("Telefon seit 5 Minuten nicht registriert"): once per kind and hour."""
        now = self.now()
        sent = 0
        for sub in self.store.subscriptions("system"):
            user = sub["user_id"]
            quiet = self._quiet(user, now)
            queued = self.store.enqueue(
                "system",
                self._target(user),
                {"title": "🔧 Hinweis", "text": text},
                user_id=user,
                dedupe_key=f"system:{kind}:{now.strftime('%Y%m%d%H')}",
                not_before=quiet_end(now, quiet) if quiet else None,
            )
            sent += 1 if queued else 0
        return sent

    def call_event(self, summary: str) -> int:
        """After a call: "📞 Anruf von Nebenstelle 20, 3 Minuten" for everybody who subscribed."""
        sent = 0
        for sub in self.store.subscriptions("calls"):
            user = sub["user_id"]
            queued = self.store.enqueue(
                "call",
                self._target(user),
                {"title": "📞 Anruf", "text": summary},
                user_id=user,
            )
            sent += 1 if queued else 0
        return sent

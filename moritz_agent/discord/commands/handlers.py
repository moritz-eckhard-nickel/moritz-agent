# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The commands the Discord worker answers itself (docs/plan/14 §7): subscriptions, settings,
reminders, activities, calls, help and the voice channel. Everything that is a question goes to the
core instead (``dispatch.py``)."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from moritz_agent.config.settings import Settings
from moritz_agent.core.principal import Role
from moritz_agent.discord.access import AccessPolicy
from moritz_agent.discord.activities import KINDS, Activity
from moritz_agent.discord.admin import AdminCommands
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.core import CoreApi, CoreForbidden, CoreUnavailable
from moritz_agent.discord.render import MESSAGE_LIMIT, OutMessage, build_embed
from moritz_agent.discord.sender import Origin, Sender
from moritz_agent.discord.style import Styler

LEVELS = {
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "mäßig": 2,
    "maessig": 2,
    "markant": 2,
    "stark": 3,
    "schwer": 3,
    "extrem": 4,
}
LEVEL_NAMES = {1: "Hinweise", 2: "markante Wetter", 3: "schwere Unwetter", 4: "extreme Unwetter"}
SUBSCRIPTION_NAMES = {
    "warnungen": ("warnings", "Unwetterwarnungen"),
    "briefing": ("briefing", "Das Morgenbriefing"),
    "muell": ("waste", "Der Müllabfuhr-Hinweis"),
    "anrufe": ("calls", "Anrufhinweise"),
    "system": ("system", "Systemhinweise"),
}
_TIME = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")
_ON = {"an", "ein", "ja", "on", "true"}
_OFF = {"aus", "nein", "off", "false", "nie"}


class ActivityControl(Protocol):
    async def change(self) -> Activity | None: ...
    async def enable(self, on: bool) -> None: ...
    def suggest(self, kind: str, text: str) -> str | None:
        """Save an own saying; returns the problem, or ``None`` if it was accepted."""


class VoiceControl(Protocol):
    async def join(self, origin: Origin, channel_id: str | None) -> str: ...
    async def leave(self, origin: Origin) -> str: ...


# -- parsing (pure) -------------------------------------------------------------------------------------
def parse_subscription(what: str, setting: str) -> tuple[bool, dict[str, Any]] | str:
    """The new state of a subscription, or a German explanation what was wrong."""
    word = setting.strip().lower()
    if what == "warnungen":
        if word in _OFF:
            return False, {}
        level = 3 if word in _ON or not word else LEVELS.get(word)
        if level is None:
            return "Sag „an“, „aus“ oder eine Stufe von 1 bis 4."
        return True, {"level": level}
    if what == "briefing":
        if word in _OFF:
            return False, {}
        parts = word.split()
        first = parts[0] if parts else ""
        match = _TIME.match("6:45" if first in {"", *_ON} else first)
        if not match:
            return (
                "Sag „aus“ oder eine Uhrzeit wie 06:45 (mit „wochentags“ nur Montag bis Freitag)."
            )
        return True, {
            "time": f"{int(match.group(1)):02d}:{match.group(2)}",
            "weekdays": "wochentags" in parts,
        }
    if word in _ON:
        return True, {}
    if word in _OFF:
        return False, {}
    return "Sag „an“ oder „aus“."


def parse_quiet(text: str) -> str | None:
    """ "22:00-07:00" → itself, "aus" → never quiet, "" → the default; ``None`` if not understood."""
    word = text.strip().lower()
    if word in {"", "standard"}:
        return ""
    if word in _OFF:
        return "00:00-00:00"
    match = re.fullmatch(
        r"([01]?\d|2[0-3])[:.]([0-5]\d)\s*[-–]\s*([01]?\d|2[0-3])[:.]([0-5]\d)", word
    )
    if match is None:
        return None
    a, b, c, d = match.groups()
    return f"{int(a):02d}:{b}-{int(c):02d}:{d}"


def _home_line(principal: dict[str, Any]) -> str:
    if not principal.get("home_name"):
        return "wie zu Hause"
    return f"{principal['home_name']} ({principal.get('home_postal_code') or '–'})"


def format_due(value: str, timezone: str) -> str:
    moment = datetime.fromisoformat(value)
    return moment.astimezone(ZoneInfo(timezone)).strftime("%d.%m. %H:%M")


REMINDER_LINE_CHARS = 80


def _short(text: str, limit: int = REMINDER_LINE_CHARS) -> str:
    """One line of a list: no line breaks, at most ``limit`` characters."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _local(value: str, timezone: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone))


def format_calls(overview: dict[str, Any], timezone: str) -> str:
    """Status and the last calls, without any content (docs/plan/14 §12)."""
    phone = overview.get("phone") or {}
    lines = [
        "📞 Gerade läuft ein Anruf."
        if phone.get("in_call")
        else f"📞 Telefon: {phone.get('registration') or 'nicht erreichbar'} – gerade frei."
    ]
    calls = overview.get("calls") or []
    if not calls:
        lines.append("Noch keine Anrufe.")
    for call in calls[:10]:
        started = _local(call["started_at"], timezone)
        length = ""
        if call.get("ended_at"):
            minutes = (_local(call["ended_at"], timezone) - started).total_seconds() / 60
            length = f" · {max(1, round(minutes))} min"
        who = re.search(r"sip:([^@;>]+)", str(call.get("remote_uri") or ""))
        lines.append(
            f"• {started.strftime('%d.%m. %H:%M')}{length} · Nebenstelle {who.group(1) if who else '?'}"
            + (f" · {call['end_reason']}" if call.get("end_reason") else "")
        )
    return "\n".join(lines)


def help_text(
    topic: str,
    *,
    names: list[str],
    features: commands.Features,
    voice: bool,
    owner: bool,
) -> str:
    """The help page; only what really works is listed (docs/plan/14 §7)."""
    if topic == "datenschutz":
        return (
            "**Datenschutz** 🔒\n"
            "Discord speichert alle Textnachrichten auf eigenen Servern – deshalb schicke ich keine "
            "Telefon-Mitschnitte, Zugangsdaten oder Systemdetails hierher. Im Sprachkanal nehme ich "
            "nichts auf; das Audio liegt nur im Arbeitsspeicher. Keine Sorge – ich spiele nicht "
            "wirklich mit deinen Daten 😇"
        )
    if topic == "sprache":
        if not voice:
            return "Der Sprachkanal ist bei mir gerade nicht eingerichtet."
        return (
            "**Sprachkanal** 🔊\n"
            "Mit `/joinvc` komme ich in deinen Sprachkanal und verhalte mich wie am Telefon: du "
            "sprichst, ich antworte. Sag „Nikita, …“, damit ich weiß, dass du mich meinst, und „Tschüss“, "
            "wenn wir fertig sind. Sprachnachrichten verstehe ich auch."
        )
    if topic == "admin":
        return (
            "**Verwaltung** 🛠️ (nur Owner, nur im Direktchat)\n`/admin status` · `version` · `logs` · "
            "`neu-laden` · `wartung` · `neustart`"
            if owner
            else "Die Verwaltung ist nur für den Owner."
        )
    lines = [
        "**Das kann ich** ✨",
        "Schreib mir einfach, was du wissen möchtest – oder nimm einen Befehl:",
    ]
    shown = [s for s in commands.active_specs(features) if s.name in names]
    for spec in shown:
        lines.append(f"`/{spec.name}` – {spec.description}")
    lines.append("\n`/hilfe datenschutz` erklärt, was ich speichere.")
    return "\n".join(lines)


class LocalCommands:
    def __init__(
        self,
        core: CoreApi,
        settings: Callable[[], Settings],
        policy: AccessPolicy,
        styler: Styler,
        admin: AdminCommands,
        features: Callable[[], commands.Features],
        *,
        activity: ActivityControl | None = None,
        voice: VoiceControl | None = None,
    ) -> None:
        self.core = core
        self.settings = settings
        self.policy = policy
        self.styler = styler
        self.admin = admin
        self.features = features
        self.activity = activity
        self.voice = voice

    async def run(
        self, spec: commands.Spec, values: dict[str, Any], origin: Origin, sender: Sender
    ) -> None:
        if spec.name in {s.name for s in (commands.find("admin") or spec).subcommands}:
            await self.admin.run(spec, values, origin, sender)
            return
        handler = getattr(self, f"_{spec.name}")
        try:
            await handler(values, origin, sender)
        except CoreForbidden:
            await sender.send(
                OutMessage(content="Das darf ich dir nicht erlauben.", ephemeral=True)
            )
        except CoreUnavailable as exc:
            detail = exc.detail.get("error") if isinstance(exc.detail, dict) else None
            text = (
                "Den Ort kenne ich leider nicht 🙈"
                if detail == "unknown_place"
                else self.styler.error("unavailable")
            )
            await sender.send(OutMessage(content=text, ephemeral=True))

    def _nice(self, text: str, emoji: str) -> str:
        return f"{text} {emoji}" if self.styler.cute else text

    # -- /abo ---------------------------------------------------------------------------------------------
    async def _abo(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        what = str(values["was"])
        parsed = parse_subscription(what, str(values.get("einstellung", "")))
        if isinstance(parsed, str):
            await sender.send(OutMessage(content=parsed, ephemeral=True))
            return
        enabled, params = parsed
        kind, label = SUBSCRIPTION_NAMES[what]
        await self.core.subscribe(origin.user_id, kind, enabled=enabled, **params)
        if not enabled:
            text = self._nice(f"{label}: aus.", "🔕")
        elif what == "warnungen":
            text = self._nice(
                f"{label} sind an – ab Stufe {params['level']} ({LEVEL_NAMES[params['level']]}).",
                "🔔",
            )
        elif what == "briefing":
            days = "Montag bis Freitag" if params["weekdays"] else "jeden Tag"
            text = self._nice(f"{label} kommt {days} um {params['time']} Uhr.", "☀️")
        else:
            text = self._nice(f"{label}: an.", "🔔")
        await sender.send(OutMessage(content=text, ephemeral=True))

    # -- /einstellungen -------------------------------------------------------------------------------------
    async def _einstellungen(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        changes: dict[str, str] = {}
        notes: list[str] = []
        if values.get("heimatort") is not None:
            changes["home"] = str(values["heimatort"]).strip()
        if values.get("ruhezeit") is not None:
            quiet = parse_quiet(str(values["ruhezeit"]))
            if quiet is None:
                await sender.send(
                    OutMessage(
                        content="Die Ruhezeit schreibst du so: 22:00-07:00, „aus“ oder leer.",
                        ephemeral=True,
                    )
                )
                return
            changes["quiet_hours"] = quiet
        if values.get("sprachantwort") is not None:
            changes["voice_reply"] = str(values["sprachantwort"])
        if changes:
            answer = await self.core.set_principal(origin.user_id, **changes)
            if answer.get("home"):
                notes.append(
                    f"Heimatort: {answer['home']['name']} ({answer['home']['postal_code']})"
                )
            elif changes.get("home") == "":
                notes.append("Heimatort: wieder der von zu Hause")
            if "quiet_hours" in changes:
                notes.append("Ruhezeit geändert")
            if "voice_reply" in changes:
                notes.append("Sprachantwort geändert")
        current = await self.core.principal(origin.user_id)
        default_quiet = self.settings().discord.quiet_hours
        subs = ", ".join(s["kind"] for s in current.get("subscriptions", [])) or "keine"
        card = {
            "title": "Deine Einstellungen",
            "description": (self._nice("; ".join(notes) + ".", "✅") if notes else ""),
            "fields": [
                {
                    "name": "📍 Heimatort",
                    "value": _home_line(current),
                    "inline": True,
                },
                {
                    "name": "🌙 Ruhezeit",
                    "value": current.get("quiet_hours") or f"{default_quiet} (Standard)",
                    "inline": True,
                },
                {
                    "name": "🎤 Sprachantwort",
                    "value": current.get("voice_reply") or "spiegeln (Standard)",
                    "inline": True,
                },
                {"name": "🔔 Abos", "value": subs, "inline": False},
                {
                    "name": "⏰ Offene Erinnerungen",
                    "value": str(current.get("reminders", 0)),
                    "inline": True,
                },
            ],
            "color": "info",
        }
        await sender.send(OutMessage(embed=build_embed(card), ephemeral=True))

    # -- /erinnerungen ----------------------------------------------------------------------------------------------
    async def _erinnerungen(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        if values.get("loeschen"):
            done = await self.core.cancel_reminder(origin.user_id, int(values["loeschen"]))
            text = "Gelöscht." if done else "Die Nummer finde ich bei deinen Erinnerungen nicht."
            await sender.send(
                OutMessage(content=self._nice(text, "🗑️" if done else "🙈"), ephemeral=True)
            )
            return
        items = await self.core.reminders(origin.user_id)
        if not items:
            await sender.send(
                OutMessage(
                    content=self._nice("Du hast keine offenen Erinnerungen.", "✨"), ephemeral=True
                )
            )
            return
        timezone = self.settings().general.timezone
        head, foot = "**Deine Erinnerungen** ⏰", "\nZum Löschen: `/erinnerungen loeschen:<Nummer>`"
        lines: list[str] = []
        room = MESSAGE_LIMIT - len(head) - len(foot) - 40  # 40: room for "… und N weitere"
        for index, item in enumerate(items[:20]):
            line = (
                f"`{item['id']}` · {format_due(item['due_at'], timezone)} · {_short(item['text'])}"
            )
            if room - len(line) - 1 < 0:
                lines.append(f"… und {len(items) - index} weitere")
                break
            room -= len(line) + 1
            lines.append(line)
        else:
            if len(items) > 20:
                lines.append(f"… und {len(items) - 20} weitere")
        await sender.send(OutMessage(content="\n".join([head, *lines, foot]), ephemeral=True))

    # -- /aktivitaet ------------------------------------------------------------------------------------------------
    async def _aktivitaet(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        if self.activity is None:
            await sender.send(OutMessage(content="Aktivitäten sind ausgeschaltet.", ephemeral=True))
            return
        action = str(values["aktion"])
        if action == "neu":
            current = await self.activity.change()
            text = f"Jetzt: {current.text}" if current else "Ich weiß gerade nichts Lustiges."
            await sender.send(OutMessage(content=self._nice(text, "🎲"), ephemeral=True))
        elif action in {"an", "aus"}:
            await self.activity.enable(action == "an")
            text = (
                "Ich zeige wieder, was ich so treibe."
                if action == "an"
                else "Ich zeige nur noch „online“."
            )
            await sender.send(
                OutMessage(
                    content=self._nice(text, "🙈" if action == "aus" else "😈"), ephemeral=True
                )
            )
        else:
            text, kind = str(values.get("text") or "").strip(), str(values.get("art") or "playing")
            problem = None if kind in KINDS else "Die Art kenne ich nicht."
            if not text:
                problem = "Schreib mir den Spruch bei `text`."
            problem = problem or self.activity.suggest(kind, text)
            await sender.send(
                OutMessage(
                    content=problem or self._nice("Kommt in die Rotation.", "✨"), ephemeral=True
                )
            )

    # -- /anrufe -------------------------------------------------------------------------------------------------------
    async def _anrufe(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        overview = await self.core.overview()
        timezone = self.settings().general.timezone
        await sender.send(OutMessage(content=format_calls(overview, timezone), ephemeral=True))

    # -- /hilfe ------------------------------------------------------------------------------------------------------------
    async def _hilfe(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        features = self.features()
        names = [
            s.name
            for s in commands.active_specs(features)
            if self.policy.command_allowed(origin.user_id, s.rule, origin.where)
        ]
        text = help_text(
            str(values.get("thema") or "befehle"),
            names=names,
            features=features,
            voice=features.has("voice"),
            owner=self.policy.role(origin.user_id) is Role.OWNER,
        )
        await sender.send(OutMessage(content=text, ephemeral=True))

    # -- voice channel ----------------------------------------------------------------------------------------------------------
    async def _joinvc(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        if self.voice is None:
            await sender.send(
                OutMessage(content="Der Sprachkanal ist noch nicht eingerichtet.", ephemeral=True)
            )
            return
        channel = values.get("kanal")
        text = await self.voice.join(origin, str(channel.id) if channel is not None else None)
        await sender.send(OutMessage(content=text))

    async def _leavevc(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        if self.voice is None:
            await sender.send(
                OutMessage(content="Ich bin gerade in keinem Sprachkanal.", ephemeral=True)
            )
            return
        await sender.send(OutMessage(content=await self.voice.leave(origin)))

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Owner commands (docs/plan/14 §13): status, version, logs, reload, maintenance, restart.

Only the owner, only in a direct message. Dangerous ones wait for a button press (60 s) and – if
``admin_pin`` is set in ``passwords.txt`` – for the PIN. Nothing here changes secrets, runs commands
or reads files; the main process does the work and checks the role once more.
"""

from __future__ import annotations

import hmac
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from moritz_agent import __version__
from moritz_agent.discord import components
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.core import CoreApi, CoreForbidden, CoreUnavailable
from moritz_agent.discord.render import Button, OutMessage, build_embed, redact
from moritz_agent.discord.sender import Origin, Sender

STATE_LABELS = {
    "ready": "läuft",
    "degraded": "eingeschränkt",
    "starting": "startet",
    "failed": "AUSGEFALLEN",
    "disabled": "aus",
}
COMPONENT_NAMES = {
    "inference": "Sprachmodell",
    "search": "Suche",
    "skills": "Sofortauskünfte",
    "storage": "Datenbank",
    "config": "Konfiguration",
    "agent": "Agent",
    "phone": "Telefon",
}
CONFIRM_TEXT = {
    "reload": "Soll ich die Konfiguration und `passwords.txt` neu laden?",
    "drainon": "Soll ich den Wartungsmodus einschalten? Neue Anrufe werden dann abgewiesen.",
    "drainoff": "Soll ich den Wartungsmodus ausschalten?",
    "restart": "Soll ich den Dienst neu starten? Das geht nur ohne laufenden Anruf.",
}
NEEDS_PIN = {"restart"}


def duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} d {hours} h"
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def memory_line() -> str:
    """Free and total RAM of the machine (Linux); empty if unknown."""
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            values[key] = int(rest.split()[0])
        total, free = values["MemTotal"], values["MemAvailable"]
    except (OSError, KeyError, ValueError, IndexError):
        return ""
    return f"{(total - free) / 1048576:.1f} von {total / 1048576:.1f} GB belegt"


def disk_line(path: Path) -> str:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return ""
    return f"{usage.used / 1e9:.1f} von {usage.total / 1e9:.1f} GB belegt ({usage.used * 100 // usage.total} %)"


def status_card(overview: dict[str, Any], local: dict[str, Any], data_root: Path) -> dict[str, Any]:
    """The admin status as a card (docs/plan/14 §13)."""
    fields: list[dict[str, Any]] = []
    phone = overview.get("phone") or {}
    if phone:
        registration = phone.get("registration") or "unbekannt"
        call = "gerade im Gespräch" if phone.get("in_call") else "frei"
        fields.append(
            {
                "name": "Telefon",
                "value": f"Registrierung: {registration}\n{call} · {phone.get('calls_total', 0)} Anrufe",
                "inline": True,
            }
        )
    fields.append(
        {
            "name": "Discord",
            "value": (
                f"Latenz {local.get('latency_ms') or '?'} ms · {local.get('guilds', 0)} Server\n"
                + ("Sprachsitzung läuft" if local.get("voice") else "keine Sprachsitzung")
            ),
            "inline": True,
        }
    )
    failed = False
    for key, component in (overview.get("components") or {}).items():
        state = component.get("state", "")
        failed = failed or state == "failed"
        fields.append(
            {
                "name": f"{COMPONENT_NAMES.get(key, key)} ({STATE_LABELS.get(state, state or '?')})",
                "value": str(component.get("message") or component.get("state"))[:200],
                "inline": True,
            }
        )
    system = [line for line in (memory_line(), disk_line(data_root)) if line]
    if system:
        fields.append(
            {
                "name": "System",
                "value": f"RAM: {system[0]}"
                + (f"\nPlatte: {system[-1]}" if len(system) > 1 else ""),
                "inline": False,
            }
        )
    warning = overview.get("situation", {}).get("warning_level", 0)
    return {
        "title": "Anton – Status",
        "description": (
            f"Version {overview.get('version', __version__)} · läuft seit "
            f"{duration(overview.get('uptime_s', 0))}"
            + (" · Wartungsmodus" if overview.get("draining") else "")
            + (f" · Warnstufe {warning}" if warning else "")
        ),
        "fields": fields,
        "color": "danger" if failed else "good",
    }


def reload_text(result: dict[str, Any], secrets: list[str]) -> str:
    """What a reload did, in one or two lines (never values, only places)."""
    if not result.get("ok"):
        why = redact("; ".join(result.get("errors") or ["unbekannter Fehler"]), secrets)
        return f"Die neue Konfiguration wurde abgelehnt, ich bleibe bei der alten: {why}"
    changed = result.get("changed") or []
    text = "Neu geladen. " + (
        "Geändert: " + ", ".join(changed) if changed else "Es hat sich nichts geändert."
    )
    if result.get("restart_required"):
        text += "\nErst nach einem Neustart wirksam: " + ", ".join(result["restart_required"])
    return text


class AdminCommands:
    def __init__(
        self,
        core: CoreApi,
        confirmations: components.Confirmations,
        *,
        secrets: Callable[[], list[str]] = list,
        admin_pin: Callable[[], str] = lambda: "",
        local_status: Callable[[], dict[str, Any]] = dict,
        data_root: Path = Path("."),
    ) -> None:
        self.core = core
        self.confirmations = confirmations
        self.secrets = secrets
        self.admin_pin = admin_pin
        self.local_status = local_status
        self.data_root = data_root

    def pin_ok(self, pin: str) -> bool:
        expected = self.admin_pin()
        return bool(expected) and hmac.compare_digest(pin.strip().encode(), expected.encode())

    # -- the commands -----------------------------------------------------------------------------------
    async def run(
        self, spec: commands.Spec, values: dict[str, Any], origin: Origin, sender: Sender
    ) -> None:
        handler = {
            "status": self._status,
            "version": self._version,
            "logs": self._logs,
            "neu-laden": lambda *a: self._ask("reload", *a),
            "wartung": self._maintenance,
            "neustart": lambda *a: self._ask("restart", *a),
        }[spec.name]
        try:
            await handler(values, origin, sender)
        except CoreForbidden:
            await sender.send(OutMessage(content="Das darf nur der Owner.", ephemeral=True))
        except CoreUnavailable as exc:
            await sender.send(
                OutMessage(
                    content=f"Das hat nicht geklappt ({exc.status or 'keine Verbindung'}).",
                    ephemeral=True,
                )
            )

    async def _status(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        overview = await self.core.overview()
        card = status_card(overview, self.local_status(), self.data_root)
        await sender.send(OutMessage(embed=build_embed(card), ephemeral=True))

    async def _version(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        overview = await self.core.overview()
        text = (
            f"moritz-agent {overview.get('version', '?')} · Discord-Teil {__version__} · "
            f"läuft seit {duration(overview.get('uptime_s', 0))}"
        )
        await sender.send(OutMessage(content=text, ephemeral=True))

    async def _logs(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        category = str(values.get("kategorie") or "")
        lines = int(values.get("zeilen") or 100)
        found = await self.core.admin_logs(origin.user_id, category, lines)
        if not found:
            await sender.send(OutMessage(content="Keine passenden Logzeilen.", ephemeral=True))
            return
        text = redact("\n".join(found), self.secrets())
        name = f"log-{category.lower() or 'alles'}.txt"
        await sender.send(
            OutMessage(
                content=f"Die letzten {len(found)} Zeilen (Zugangsdaten sind geschwärzt).",
                file=(name, text.encode("utf-8")),
                ephemeral=True,
            )
        )

    async def _maintenance(self, values: dict[str, Any], origin: Origin, sender: Sender) -> None:
        await self._ask(
            "drainon" if values.get("modus") == "an" else "drainoff", values, origin, sender
        )

    # -- confirmation ------------------------------------------------------------------------------------
    async def _ask(
        self, action: str, values: dict[str, Any], origin: Origin, sender: Sender
    ) -> None:
        needs_pin = action in NEEDS_PIN and bool(self.admin_pin())
        nonce = self.confirmations.ask(action, origin.user_id, needs_pin=needs_pin)
        text = CONFIRM_TEXT[action] + (" Danach brauche ich deine PIN." if needs_pin else "")
        await sender.send(
            OutMessage(
                content=text + " (60 Sekunden)",
                buttons=[
                    Button("Ja", components.encode_confirm(action, nonce, "ok"), "danger"),
                    Button("Nein", components.encode_confirm(action, nonce, "no"), "secondary"),
                ],
                ephemeral=True,
            )
        )

    async def execute(self, action: str, origin: Origin, sender: Sender) -> None:
        """The confirmed action."""
        user = origin.user_id
        try:
            if action == "reload":
                text = reload_text(await self.core.admin_reload(user), self.secrets())
            elif action in {"drainon", "drainoff"}:
                result = await self.core.admin_drain(user, action == "drainon")
                text = (
                    "Wartungsmodus ist an." if result.get("draining") else "Wartungsmodus ist aus."
                )
            elif action == "restart":
                await self.core.admin_restart(user)
                text = "Ich starte neu – bis gleich!"
            else:
                return
        except CoreForbidden:
            text = "Das darf nur der Owner."
        except CoreUnavailable as exc:
            text = (
                "Es läuft gerade ein Anruf – bitte später noch einmal."
                if exc.status == 409
                else f"Das hat nicht geklappt ({exc.status or 'keine Verbindung'})."
            )
        await sender.send(OutMessage(content=text, ephemeral=True))

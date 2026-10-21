# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""NINA (BBK): official civil-protection warnings for a district (docs/plan/13 §6.6, §7.6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.skills.providers.brightsky import clean_text
from moritz_agent.skills.providers.http import HttpClient, HttpError

BASE = "https://warnung.bund.de/api31/dashboard/{ars}.json"
SEVERITY_LEVEL = {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}
PROVIDERS = {
    "MOWAS": "Katastrophenschutz",
    "KATWARN": "KATWARN",
    "BIWAPP": "BIWAPP",
    "LHP": "Hochwasserzentralen",
    "POLICE": "Polizei",
    "DWD": "Deutscher Wetterdienst",
}


@dataclass(frozen=True)
class CivilWarning:
    title: str
    provider: str
    level: int
    sent: datetime | None
    uid: str = ""


async def fetch(http: HttpClient, ars: str) -> list[Any]:
    raw = await http.get_json(BASE.format(ars=ars))
    if not isinstance(raw, list):
        raise HttpError("bad_data", "nina: unexpected answer")
    return raw


def parse(raw: list[Any], tz: str, *, skip_dwd: bool = True) -> list[CivilWarning]:
    """Warnings, the most severe first; DWD entries are left out (Bright Sky has them)."""
    zone = ZoneInfo(tz)
    found: list[CivilWarning] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        provider = str(data.get("provider") or "").upper()
        if skip_dwd and provider == "DWD":
            continue
        if str(data.get("msgType") or "Alert").lower() == "cancel":
            continue
        title = (
            (item.get("i18nTitle") or {}).get("de")
            if isinstance(item.get("i18nTitle"), dict)
            else None
        )
        title = clean_text(title or data.get("headline"), 140)
        if not title:
            continue
        sent = None
        if item.get("sent"):
            try:
                sent = datetime.fromisoformat(str(item["sent"])).astimezone(zone)
            except ValueError:
                sent = None
        found.append(
            CivilWarning(
                title=title,
                provider=PROVIDERS.get(provider, provider.title() or "BBK"),
                level=SEVERITY_LEVEL.get(str(data.get("severity") or "minor").lower(), 1),
                sent=sent,
                uid=str(item.get("id") or payload.get("id") or ""),
            )
        )
    found.sort(key=lambda w: (-w.level, w.sent or datetime.min.replace(tzinfo=zone)))
    return found

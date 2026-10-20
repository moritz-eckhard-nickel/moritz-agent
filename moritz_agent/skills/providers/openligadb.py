# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Football results and tables from OpenLigaDB (community project, free to use)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.skills.geo.gazetteer import fold
from moritz_agent.skills.providers.http import HttpClient, HttpError

BASE = "https://api.openligadb.de"


@dataclass(frozen=True)
class Match:
    start: datetime
    home: str
    away: str
    finished: bool
    goals_home: int | None = None
    goals_away: int | None = None


@dataclass(frozen=True)
class TableRow:
    rank: int
    team: str
    points: int
    matches: int


def season_of(day: date) -> int:
    """Season start year: from July on the new season counts."""
    return day.year if day.month >= 7 else day.year - 1


async def fetch_matches(http: HttpClient, league: str, season: int) -> list[Any]:
    raw = await http.get_json(f"{BASE}/getmatchdata/{league}/{season}")
    if not isinstance(raw, list):
        raise HttpError("bad_data", "openligadb: unexpected answer")
    return raw


async def fetch_table(http: HttpClient, league: str, season: int) -> list[Any]:
    raw = await http.get_json(f"{BASE}/getbltable/{league}/{season}")
    if not isinstance(raw, list):
        raise HttpError("bad_data", "openligadb: unexpected answer")
    return raw


def matches_of(raw: list[Any], team: str, tz: str) -> list[Match]:
    zone = ZoneInfo(tz)
    wanted = fold(team)
    found = []
    for item in raw:
        try:
            home = str(item["team1"]["teamName"])
            away = str(item["team2"]["teamName"])
            if wanted not in fold(home) and wanted not in fold(away):
                continue
            start = datetime.fromisoformat(
                str(item["matchDateTimeUTC"]).replace("Z", "+00:00")
            ).astimezone(zone)
            results = item.get("matchResults") or []
            final = next(
                (r for r in results if r.get("resultTypeID") == 2), results[-1] if results else None
            )
            found.append(
                Match(
                    start=start,
                    home=home,
                    away=away,
                    finished=bool(item.get("matchIsFinished")),
                    goals_home=int(final["pointsTeam1"]) if final else None,
                    goals_away=int(final["pointsTeam2"]) if final else None,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(found, key=lambda m: m.start)


def table_of(raw: list[Any]) -> list[TableRow]:
    rows = []
    for index, item in enumerate(raw, 1):
        try:
            rows.append(
                TableRow(
                    index, str(item["teamName"]), int(item["points"]), int(item.get("matches") or 0)
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows

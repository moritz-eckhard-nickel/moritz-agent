# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""DWD Open Data: pollen forecast index "s31fg" (CC BY 4.0, docs/plan/13 §6.7, §7.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from moritz_agent.skills.geo.gazetteer import fold
from moritz_agent.skills.providers.http import HttpClient, HttpError

URL = "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
ALLERGENS = {
    "Hasel": "Hasel",
    "Erle": "Erle",
    "Esche": "Esche",
    "Birke": "Birke",
    "Graeser": "Gräser",
    "Roggen": "Roggen",
    "Beifuss": "Beifuß",
    "Ambrosia": "Ambrosia",
}
DAYS = ("today", "tomorrow", "dayafter_to")
# "-1" (or an empty value) means "no forecast for this day" – usually ``dayafter_to`` except on Fridays
NO_FORECAST = {"-1", ""}
# index → numeric level (the DWD writes "1-2" for "between 1 and 2")
LEVELS = {"0": 0.0, "0-1": 0.5, "1": 1.0, "1-2": 1.5, "2": 2.0, "2-3": 2.5, "3": 3.0}
LEVEL_WORDS = (
    (0.25, "keine"),
    (0.75, "kaum"),
    (1.25, "gering"),
    (1.75, "gering bis mäßig"),
    (2.25, "mäßig"),
    (2.75, "mäßig bis stark"),
    (9.0, "stark"),
)
# state → DWD region names (the part regions of a state share a prefix of the region name)
STATE_REGIONS = {
    "SH": "Schleswig-Holstein und Hamburg",
    "HH": "Schleswig-Holstein und Hamburg",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen und Bremen",
    "HB": "Niedersachsen und Bremen",
    "NW": "Nordrhein-Westfalen",
    "BB": "Brandenburg und Berlin",
    "BE": "Brandenburg und Berlin",
    "ST": "Sachsen-Anhalt",
    "TH": "Thüringen",
    "SN": "Sachsen",
    "HE": "Hessen",
    "RP": "Rheinland-Pfalz und Saarland",
    "SL": "Rheinland-Pfalz und Saarland",
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
}


@dataclass
class PollenForecast:
    region: str
    partregion: str
    last_update: str
    days: dict[str, dict[str, float]] = field(default_factory=dict)  # day key → allergen → level

    def level(self, day: str, allergen: str) -> float:
        return self.days.get(day, {}).get(allergen, 0.0)

    @property
    def issued(self) -> date | None:
        """The issue date of the file; ``today``/``tomorrow``/``dayafter_to`` count from it."""
        return issue_date(self.last_update)

    def day_key(self, day: date, fallback: date) -> str | None:
        """The day key that covers ``day`` (``None`` when the file has no forecast for it).

        ``fallback`` is used as issue date when ``last_update`` cannot be read.
        """
        offset = (day - (self.issued or fallback)).days
        if not 0 <= offset < len(DAYS):
            return None
        key = DAYS[offset]
        return key if self.days.get(key) else None


def issue_date(last_update: str) -> date | None:
    """ "2026-10-18 11:00 Uhr" → 2026-10-18."""
    match = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", last_update or "")
    if match is None:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def level_word(level: float) -> str:
    for limit, word in LEVEL_WORDS:
        if level < limit:
            return word
    return "stark"


async def fetch(http: HttpClient) -> dict[str, Any]:
    raw = await http.get_json(URL)
    if not isinstance(raw, dict) or not isinstance(raw.get("content"), list):
        raise HttpError("bad_data", "dwd pollen: unexpected answer")
    return raw


def choose(raw: dict[str, Any], partregion: str, state: str = "") -> dict[str, Any] | None:
    """The content entry for ``partregion`` (by name) or for the DWD region of ``state``."""
    wanted = fold(partregion)
    entries = [e for e in raw["content"] if isinstance(e, dict)]
    for entry in entries:
        if wanted and fold(str(entry.get("partregion_name") or "")) == wanted:
            return entry
    region = STATE_REGIONS.get(state, "")
    if region:
        matching = [e for e in entries if fold(str(e.get("region_name") or "")) == fold(region)]
        if matching:
            return matching[0]
    return None


def parse(entry: dict[str, Any], last_update: str = "") -> PollenForecast:
    forecast = PollenForecast(
        region=str(entry.get("region_name") or ""),
        partregion=str(entry.get("partregion_name") or entry.get("region_name") or ""),
        last_update=last_update,
    )
    pollen = entry.get("Pollen")
    if not isinstance(pollen, dict):
        raise HttpError("bad_data", "dwd pollen: no pollen values")
    for key, name in ALLERGENS.items():
        values = pollen.get(key)
        if not isinstance(values, dict):
            continue
        for day in DAYS:
            value = values.get(day)
            text = "" if value is None else str(value).strip()
            if text in NO_FORECAST:
                continue
            level = LEVELS.get(text)
            if level is None:
                raise HttpError("bad_data", "dwd pollen: unknown index value")
            forecast.days.setdefault(day, {})[name] = level
    if not forecast.days:
        raise HttpError("bad_data", "dwd pollen: no allergens")
    return forecast

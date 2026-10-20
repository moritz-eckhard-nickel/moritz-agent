# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Reading a weather pack: weather classes, day sections, extremes, trends (docs/plan/13 §7.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

from moritz_agent.skills.data import load_toml
from moritz_agent.skills.weather.model import DayPoint, HourPoint, WeatherPack

WET = {"regen", "schauer", "schnee", "glatt"}
# worse comes first
SEVERITY = ["gewitter", "glatt", "schnee", "regen", "schauer", "nebel", "trocken"]
# blocks of the day used for "vormittags trocken, ab dem Nachmittag Schauer"
BLOCKS = (("vormittags", 6, 12), ("nachmittags", 12, 18), ("abends", 18, 24))


def code_info(code: int | None, is_day: bool = True) -> dict[str, str]:
    codes = load_toml("wetter/wmo-codes.de.toml")["codes"]
    info = codes.get(str(code)) if code is not None else None
    if info is None:
        return {"text": "", "klasse": "trocken", "kurz": ""}
    return {
        "text": info["tag"] if is_day else info["nacht"],
        "klasse": info["klasse"],
        "kurz": info["kurz"],
    }


def hour_class(hour: HourPoint) -> str:
    """Weather class of one hour: the code, corrected by the amount and the probability."""
    base = code_info(hour.code, hour.is_day)["klasse"]
    amount = hour.precipitation or 0.0
    prob = hour.precip_prob
    cold = hour.temperature is not None and hour.temperature <= 1.0
    if base in {"trocken", "nebel"}:
        if amount >= 0.3:
            if cold and (hour.snowfall or 0) > 0:
                return "schnee"
            return "schauer" if (hour.showers or 0) >= amount / 2 and amount < 2 else "regen"
        return base
    if base in {"regen", "schauer"}:
        if amount < 0.1 and (prob is None or prob < 30):
            return "trocken"
        return base
    if base == "schnee" and amount < 0.05 and (prob is None or prob < 30):
        return "trocken"
    return base


def sky(hours: list[HourPoint]) -> str:
    """Sky word of a dry stretch: sonnig, heiter, wolkig, bewölkt, bedeckt (klar at night)."""
    clouds = [h.cloud_cover for h in hours if h.cloud_cover is not None]
    if not clouds:
        codes = [h.code for h in hours if h.code is not None]
        if not codes:
            return ""
        top = max(codes)
        daylight = any(h.is_day for h in hours)
        return (
            {0: "sonnig", 1: "sonnig", 2: "wolkig"}.get(top, "bedeckt")
            if daylight
            else ({0: "klar", 1: "klar", 2: "wolkig"}.get(top, "bedeckt"))
        )
    cover = mean(clouds)
    daylight = sum(1 for h in hours if h.is_day) >= len(hours) / 2
    if cover < 20:
        return "sonnig" if daylight else "klar"
    if cover < 45:
        return "heiter" if daylight else "überwiegend klar"
    if cover < 75:
        return "wolkig"
    if cover < 90:
        return "stark bewölkt"
    return "bedeckt"


def block_class(hours: list[HourPoint]) -> str:
    """One class for several hours: the worst one that matters (light drizzle does not)."""
    if not hours:
        return "trocken"
    classes = [hour_class(h) for h in hours]
    if "gewitter" in classes:
        return "gewitter"
    if "glatt" in classes:
        return "glatt"
    wet = [(c, h) for c, h in zip(classes, hours, strict=True) if c in WET]
    if wet:
        total = sum(h.precipitation for _, h in wet)
        peak = max((h.precip_prob or 0) for _, h in wet)
        if total >= 0.4 or peak >= 60 or len(wet) >= 2:
            kinds = {c for c, _ in wet}
            if "schnee" in kinds:
                return "schnee"
            if kinds == {"schauer"}:
                return "schauer"
            return "regen" if len(wet) >= max(2, len(hours) // 2) else "schauer"
    if "nebel" in classes and classes.count("nebel") >= max(1, len(hours) // 2):
        return "nebel"
    return "trocken"


@dataclass(frozen=True)
class Section:
    kind: str  # trocken | schauer | regen | schnee | gewitter | glatt | nebel
    first: int  # block index
    last: int
    sky: str = ""  # for dry sections


def day_sections(pack: WeatherPack, day: date, now: datetime | None = None) -> list[Section]:
    """Sections of a day (from ``now`` on, when ``day`` is today): at most two, else "wechselhaft"."""
    zone = pack.hours[0].time.tzinfo if pack.hours else None
    entries: list[tuple[int, str, str]] = []
    for index, (_, first, last) in enumerate(BLOCKS):
        start = datetime(day.year, day.month, day.day, tzinfo=zone) + timedelta(hours=first)
        end = start + timedelta(hours=last - first)
        if now is not None and end <= now:
            continue
        if now is not None and start < now:
            start = now.replace(minute=0, second=0, microsecond=0)
        hours = pack.hours_between(start, end)
        if not hours:
            continue
        entries.append((index, block_class(hours), sky(hours)))
    sections: list[Section] = []
    for index, kind, sky_word in entries:
        if sections and sections[-1].kind == kind and sections[-1].last == index - 1:
            previous = sections[-1]
            sections[-1] = Section(kind, previous.first, index, previous.sky or sky_word)
        else:
            sections.append(Section(kind, index, index, sky_word if kind == "trocken" else ""))
    return sections


def worst(kinds: list[str]) -> str:
    for kind in SEVERITY:
        if kind in kinds:
            return kind
    return "trocken"


# -- extremes ------------------------------------------------------------------------------
def temperature_range(hours: list[HourPoint]) -> tuple[float, float] | None:
    temps = [h.temperature for h in hours if h.temperature is not None]
    return (min(temps), max(temps)) if temps else None


def peak(hours: list[HourPoint], attr: str, *, high: bool = True) -> HourPoint | None:
    values = [h for h in hours if getattr(h, attr) is not None]
    if not values:
        return None
    return (max if high else min)(values, key=lambda h: getattr(h, attr))


def wet_hours(hours: list[HourPoint]) -> list[HourPoint]:
    return [h for h in hours if hour_class(h) in WET]


def day_class(day: DayPoint, hours: list[HourPoint]) -> str:
    """One word for a whole day in a multi-day trend."""
    if hours:
        kind = block_class([h for h in hours if 6 <= h.time.hour < 22] or hours)
        if kind != "trocken":
            return kind
        word = sky([h for h in hours if h.is_day] or hours)
        return {"sonnig": "sonnig", "heiter": "freundlich", "klar": "sonnig"}.get(word, "wolkig")
    info = code_info(day.code)
    return {"trocken": "wolkig"}.get(info["klasse"], info["klasse"])


def week_trend(pack: WeatherPack, first: date, last: date) -> list[tuple[str, date, date, float]]:
    """Runs of days with the same class: (class, first day, last day, highest maximum)."""
    runs: list[tuple[str, date, date, float]] = []
    for day in pack.days_between(first, last):
        hours = [h for h in pack.hours if h.time.date() == day.day]
        kind = day_class(day, hours)
        high = day.tmax if day.tmax is not None else -99.0
        if runs and runs[-1][0] == kind:
            prev = runs[-1]
            runs[-1] = (kind, prev[1], day.day, max(prev[3], high))
        else:
            runs.append((kind, day.day, day.day, high))
    return runs

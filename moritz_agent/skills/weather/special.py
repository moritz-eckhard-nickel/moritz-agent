# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Weather answers that compare, search or look back: yesterday, compare, extremes, when does it
change, the region overview and station measurements (docs/plan/13 §6.4)."""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta

from moritz_agent.skills.base import SkillResult
from moritz_agent.skills.providers import ProviderUnavailable
from moritz_agent.skills.render import german as g
from moritz_agent.skills.slots.when import find_dates
from moritz_agent.skills.slots.where import Where, find_places, home_place
from moritz_agent.skills.weather import text as t
from moritz_agent.skills.weather.analysis import (
    WET,
    code_info,
    day_class,
    hour_class,
    sky,
    temperature_range,
)
from moritz_agent.skills.weather.answers import (
    CHAR,
    day_hours,
    head_day,
    out_of_range,
    window,
)
from moritz_agent.skills.weather.frame import OFFLINE_TEXT, Frame
from moritz_agent.skills.weather.model import WeatherPack


# -- yesterday ----------------------------------------------------------------------------------
def answer_yesterday(frame: Frame) -> SkillResult:
    when = frame.when
    day = when.day if when and when.day else frame.now.date() - timedelta(days=1)
    point = frame.pack.day(day)
    hours = day_hours(frame, day)
    if point is None or not hours:
        return out_of_range(frame, day)
    low, high = point.tmin, point.tmax
    rain = (
        point.precipitation
        if point.precipitation is not None
        else sum(h.precipitation for h in hours)
    )
    head = head_day(day, frame.now.date())
    place = frame.in_place()
    in_place = f" in {frame.place_name()}" if place else ""
    text = (
        f"{head} war es{in_place} bis {t.deg(high)}"
        if high is not None
        else f"{head} war es{in_place}"
    )
    if low is not None and high is not None and "gefallen" not in frame.req.text:
        text = f"{head} war es{in_place} zwischen {t.deg_n(low)} und {t.deg(high)}"
    asks_rain = any(w in frame.req.text for w in ("regen", "geregnet", "niederschlag"))
    wet_text = f"es hat {t.liters(rain)} geregnet" if rain >= 0.2 else "es blieb trocken"
    if asks_rain:
        text = (
            g.sentence(f"{head} {wet_text}")
            if rain >= 0.2
            else g.sentence(f"{head} hat es nicht geregnet")
        )
        if rain >= 0.2:
            text = g.sentence(f"{head} sind {t.liters(rain)} gefallen")
    else:
        text = g.sentence(text) + " " + g.sentence(wet_text)
    return frame.finish(text, aspect="yesterday")


# -- comparing -----------------------------------------------------------------------------------
# word -> (metric, direction, comparative, opposite, adjective)
_COMPARATIVES = {
    "wärmer": ("tmax", 1, "wärmer", "kälter", "warm"),
    "milder": ("tmax", 1, "milder", "kälter", "mild"),
    "kälter": ("tmax", -1, "kälter", "wärmer", "kalt"),
    "kühler": ("tmax", -1, "kühler", "wärmer", "kühl"),
    "nasser": ("rain", 1, "nasser", "trockener", "nass"),
    "trockener": ("rain", -1, "trockener", "nasser", "trocken"),
    "windiger": ("wind", 1, "windiger", "weniger windig", "windig"),
}


def _comparative(text: str) -> tuple[str, int, str, str, str] | None:
    for word, spec in _COMPARATIVES.items():
        if re.search(rf"\b{word}\b", text):
            return spec
    return None


def _metric(pack: WeatherPack, day: date, metric: str) -> float | None:
    point = pack.day(day)
    if point is None:
        return None
    return {
        "tmax": point.tmax,
        "rain": point.precipitation,
        "gusts": point.gusts_max,
        "wind": point.wind_max,
    }[metric]


def _current_temperature(pack: WeatherPack, now: datetime) -> float | None:
    if pack.current is not None and pack.current.temperature is not None:
        return pack.current.temperature
    hour = pack.hour_at(now)
    return hour.temperature if hour else None


def _wind_metric(metric: str, *cases: tuple[WeatherPack, date]) -> str:
    """ "windiger" compares gusts when both sides have them, the mean wind otherwise."""
    if metric != "wind":
        return metric
    if all(_metric(pack, day, "gusts") is not None for pack, day in cases):
        return "gusts"
    return "wind"


async def answer_compare(frame: Frame) -> SkillResult | None:
    spec = _comparative(frame.req.text)
    if spec is None:
        return None
    metric, direction, word_up, word_down, adjective = spec
    svc = frame.req.svc
    places = find_places(frame.req.text, svc, frame.req.ctx)
    named = [w for w in places if w.kind in {"place", "home"} and w.place]
    now = frame.now
    dates = find_dates(frame.req.text, now)
    if len(named) >= 2 and named[0].place != named[1].place:
        # two places: the first one (already in the frame) against the second one
        second = named[1].place
        try:
            fetched = await svc.providers.weather(second, need="forecast")  # type: ignore[union-attr]
        except (ProviderUnavailable, AttributeError):
            return SkillResult(text=OFFLINE_TEXT, prompt="skills_offline", serious=True)
        other = fetched.data
        day = dates[0] if dates else None
        if day is None and metric == "tmax":
            a, b = _current_temperature(frame.pack, now), _current_temperature(other, now)
            day = now.date()
        else:
            day = day or now.date()
            metric = _wind_metric(metric, (frame.pack, day), (other, day))
            a, b = _metric(frame.pack, day, metric), _metric(other, day, metric)
        when_part = "" if day == now.date() else f"{g.day_label(day, now.date())} "
        subject = f"{when_part}in {frame.place_name()}"
        reference = f"in {second.spoken}"
    else:
        if not dates:
            return None
        day = dates[0]
        base = dates[1] if len(dates) > 1 else now.date()
        if day == base:
            base = now.date() - timedelta(days=1) if day == now.date() else now.date()
        metric = _wind_metric(metric, (frame.pack, day), (frame.pack, base))
        a, b = _metric(frame.pack, day, metric), _metric(frame.pack, base, metric)
        subject = g.day_label(day, now.date())
        reference = g.day_label(base, now.date())
    if a is None or b is None:
        return out_of_range(frame, day)
    verb = "wird es" if day > now.date() else "ist es" if day == now.date() else "war es"
    if metric == "tmax":
        gap = round(abs(a - b))
        unit_text = f"{gap} Grad " if gap else ""
        value = f"mit {t.deg(a)} "
    elif metric == "rain":
        unit_text = ""
        value = f"mit {t.liters(a)} " if a >= 0.2 else "ohne Regen "
    elif metric == "gusts":
        unit_text = ""
        value = f"mit Böen bis {t.round5(a)} Kilometer pro Stunde "
    else:
        unit_text = ""
        value = f"mit Wind bis {t.round5(a)} Kilometer pro Stunde "
    threshold = 0.5 if metric == "tmax" else 1.0
    if abs(a - b) < threshold:
        text = f"Nein, {subject} {verb} etwa genauso {adjective} wie {reference}"
    elif (a - b) * direction > 0:
        text = f"Ja, {subject} {verb} {value}{unit_text}{word_up} als {reference}"
    else:
        text = f"Nein, {subject} {verb} {value}{unit_text}{word_down} als {reference}"
    return frame.finish(g.sentence(text), aspect="compare")


# -- extremes ---------------------------------------------------------------------------------------
_SUPERLATIVES = {
    "wärmsten": ("tmax", True),
    "heißesten": ("tmax", True),
    "kältesten": ("tmin", False),
    "kühlsten": ("tmin", False),
    "windigsten": ("wind", True),
    "nassesten": ("rain", True),
    "sonnigsten": ("sun", True),
    "schönsten": ("nice", True),
    "besten": ("nice", True),
    "trockensten": ("rain", False),
}


def answer_extremes(frame: Frame) -> SkillResult | None:
    spec = next((v for k, v in _SUPERLATIVES.items() if k in frame.req.text), None)
    if spec is None:
        return None
    metric, high = spec
    when = frame.when
    multi_day = bool(re.search(r"\b(tag|woche|wochenende|tage)\b", frame.req.text)) or (
        when is not None and when.granularity in {"week", "days", "weekend"}
    )
    if multi_day:
        first = max(frame.now.date(), when.start.date()) if when else frame.now.date()
        if first == frame.now.date() and frame.now.hour >= 18:
            first += timedelta(days=1)  # the evening is not the day to judge
        last = (
            (when.end - timedelta(seconds=1)).date()
            if when and when.granularity in {"week", "days", "weekend"}
            else first + timedelta(days=6)
        )
        if (when is None or when.granularity == "week") and (last - first).days < 2:
            last = first + timedelta(days=6)
        points = frame.pack.days_between(first, last)
        if not points:
            return out_of_range(frame, first)

        def score(p):
            if metric == "tmax":
                return p.tmax if p.tmax is not None else -99
            if metric == "tmin":
                return p.tmin if p.tmin is not None else 99
            if metric == "wind":
                return p.gusts_max or 0
            if metric == "rain":
                return p.precipitation or 0
            if metric == "sun":
                return p.sunshine_s or 0
            return (
                (p.tmax or 0) / 4
                + (p.sunshine_s or 0) / 7200
                - (p.precipitation or 0) * 1.5
                - (p.gusts_max or 0) / 40
            )

        best = max(points, key=score) if high else min(points, key=score)
        kind = day_class(best, day_hours(frame, best.day))
        char = CHAR.get(kind, kind)
        word = {
            "tmax": "am wärmsten",
            "tmin": "am kältesten",
            "wind": "am windigsten",
            "rain": "am nassesten" if high else "am trockensten",
            "sun": "am sonnigsten",
            "nice": "am schönsten",
        }[metric]
        text = f"{word.capitalize()} {'ist' if best.day == frame.now.date() else 'wird'} {'der ' + t.weekday(best.day) if (best.day - frame.now.date()).days >= 2 else head_day(best.day, frame.now.date()).rstrip(',').lower()}: {char}"
        if best.tmax is not None:
            text += f" bis {t.deg(best.tmax)}"
        return frame.finish(g.sentence(text), aspect="extremes")
    start, end, label = window(frame)
    if when is None:
        start = frame.now.replace(minute=0, second=0, microsecond=0)
        end = datetime.combine(
            frame.now.date() + timedelta(days=1), datetime.min.time(), frame.now.tzinfo
        )
        label = "heute"
    hours = frame.pack.hours_between(start, end)
    if not hours:
        return out_of_range(frame, start.date())
    if metric in {"tmax", "tmin"}:
        pick = (
            max(hours, key=lambda h: h.temperature if h.temperature is not None else -99)
            if metric == "tmax"
            else min(hours, key=lambda h: h.temperature if h.temperature is not None else 99)
        )
        if pick.temperature is None:
            return None
        word = "wärmsten" if metric == "tmax" else "kältesten"
        text = f"Am {word} wird es {label} {t.at_hour(pick.time)} mit {t.deg(pick.temperature)}"
    elif metric == "wind":
        pick = max(hours, key=lambda h: h.gusts or h.wind or 0)
        text = f"Am windigsten wird es {label} {t.at_hour(pick.time)}: {t.wind_phrase(pick.wind, pick.wind_dir, pick.gusts)}"
    else:
        return None
    return frame.finish(g.sentence(text), aspect="extremes")


# -- when does it change ---------------------------------------------------------------------------------
# (pattern, found text, none text, test per day) – the none text is followed by the horizon
_CHANGES = (
    (
        r"\b(?:warm|wärmer|mild|milder|sommerlich)\b",
        "wird es wieder warm",
        "wird es nicht wärmer als {tmax}",
        lambda p: p.tmax is not None and p.tmax >= 20,
    ),
    (
        r"\b(?:kalt|kälter|kühl|kühler)\b",
        "wird es kalt",
        "wird es nicht kälter als {tmin}",
        lambda p: p.tmax is not None and p.tmax <= 8,
    ),
    (
        r"\b(?:sonnig|sonne|schön|besser)\b",
        "scheint wieder die Sonne",
        "scheint kaum die Sonne",
        lambda p: (p.sunshine_s or 0) >= 6 * 3600 and (p.precipitation or 0) < 0.5,
    ),
    (
        r"\b(?:trocken)\b",
        "bleibt es wieder trocken",
        "bleibt es nicht trocken",
        lambda p: (p.precipitation or 0) < 0.2,
    ),
    (
        r"\b(?:regen|regnen|regnet|nass)\b",
        "regnet es wieder",
        "regnet es nicht",
        lambda p: (p.precipitation or 0) >= 0.5,
    ),
    (
        r"\b(?:frost|friert|gefrier)\b",
        "gibt es den nächsten Frost",
        "gibt es keinen Frost",
        lambda p: p.tmin is not None and p.tmin <= 0,
    ),
    (
        r"\b(?:schnee|schneit|schneien)\b",
        "schneit es",
        "schneit es nicht",
        lambda p: (p.snowfall or 0) > 0.1,
    ),
)


def answer_when_change(frame: Frame) -> SkillResult | None:
    text = frame.req.text
    spec = next((c for c in _CHANGES if re.search(c[0], text)), None)
    if spec is None:
        return None
    _, found, none, test = spec
    today = frame.now.date()
    ahead = [p for p in frame.pack.days if p.day >= today]
    for point in ahead:
        if not test(point):
            continue
        if point.day == today and frame.now.hour >= 12 and "kalt" not in found:
            continue  # the day is mostly over
        delta = (point.day - today).days
        when_text = g.day_label(point.day, today) if delta <= 2 else f"am {t.weekday(point.day)}"
        extra = ""
        if "warm" in found and point.tmax is not None:
            extra = f", dann bis zu {t.deg(point.tmax)}"
        if "Frost" in found and point.tmin is not None:
            extra = f", bis {t.deg(point.tmin)}"
        if "regnet" in found and point.precipitation:
            extra = f", etwa {t.liters(point.precipitation)}"
        return frame.finish(
            g.sentence(f"Laut Vorhersage {found} {when_text}{extra}"), aspect="when_change"
        )
    highs = [p.tmax for p in ahead if p.tmax is not None]
    lows = [p.tmin for p in ahead if p.tmin is not None]
    none = none.format(
        tmax=t.deg(max(highs)) if highs else "", tmin=t.deg(min(lows)) if lows else ""
    )
    return frame.finish(
        g.sentence(f"Laut Vorhersage {none} in den nächsten {len(ahead)} Tagen"),
        aspect="when_change",
    )


# -- the region ---------------------------------------------------------------------------------------------
async def answer_region(frame: Frame) -> SkillResult:
    svc = frame.req.svc
    home = home_place(svc, frame.req.ctx)
    gaz = svc.gazetteer
    places = [home]
    for name in svc.cfg.home.region_places:
        looked = gaz.find(name, near=home) if gaz else None
        if looked and looked.best and looked.best.place.name != home.name:
            places.append(looked.best.place)
    providers = svc.providers

    async def current(place):
        try:
            return place, (await providers.weather(place, need="current")).data  # type: ignore[union-attr]
        except (ProviderUnavailable, AttributeError):
            return place, None

    results = await asyncio.gather(*(current(p) for p in places))
    pieces: list[str] = []
    skies: list[str] = []
    wet: list[str] = []
    for place, pack in results:
        if pack is None:
            continue
        now = svc.clock.now(place.tz)
        cur = pack.current
        hour = pack.hour_at(now)
        temp = (
            cur.temperature
            if cur and cur.temperature is not None
            else (hour.temperature if hour else None)
        )
        if temp is None:
            continue
        pieces.append(f"in {place.spoken} {t.deg_n(temp)}")
        probe = hour or None
        if probe is not None:
            skies.append(
                sky([probe])
                if hour_class(probe) not in WET
                else code_info(probe.code, probe.is_day)["text"]
            )
            if hour_class(probe) in WET and (probe.precipitation or 0) >= 0.1:
                wet.append(place.spoken)
    if not pieces:
        return SkillResult(text=OFFLINE_TEXT, prompt="skills_offline", serious=True)
    body = g.join_and(pieces)
    text = f"{body[:1].upper() + body[1:]} Grad"
    if skies and len(set(skies)) == 1:
        text += f", überall {skies[0]}"
    if wet:
        text += f", Regen gerade in {g.join_and(wet)}"
    return frame.finish(g.sentence(text), aspect="region")


# -- station measurements -------------------------------------------------------------------------------------
async def answer_observed(frame: Frame) -> SkillResult | None:
    providers = frame.req.svc.providers
    try:
        current, station, km = await providers.observed(frame.place)  # type: ignore[union-attr]
    except (ProviderUnavailable, AttributeError):
        return SkillResult(
            text="Messwerte der Wetterstation kann ich gerade nicht abrufen.", serious=True
        )
    if current is None or current.temperature is None:
        return None
    where = f"Die Wetterstation {station}" if station else "Die nächste Wetterstation"
    if km is not None:
        where += f", {g.number(round(km))} Kilometer entfernt,"
    text = f"{where} misst gerade {g.number(round(current.temperature, 1), 1)} Grad"
    if current.wind is not None and current.wind >= 6:
        text += f", {t.beaufort_word(current.wind)}"
    return frame.finish(g.sentence(text), aspect="observed")


def temperature_text(frame: Frame, hours) -> str:
    rng = temperature_range(hours)
    return t.temp_range(*rng) if rng else ""


__all__ = [
    "Where",
    "answer_compare",
    "answer_extremes",
    "answer_observed",
    "answer_region",
    "answer_when_change",
    "answer_yesterday",
]

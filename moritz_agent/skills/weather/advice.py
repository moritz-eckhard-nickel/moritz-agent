# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Everyday advice from fixed thresholds (docs/plan/13 §6.8, §7.7). Every answer gives its reason."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from moritz_agent.skills.base import SkillResult
from moritz_agent.skills.render import german as g
from moritz_agent.skills.weather import text as t
from moritz_agent.skills.weather.analysis import WET, hour_class, sky, temperature_range
from moritz_agent.skills.weather.answers import out_of_range
from moritz_agent.skills.weather.frame import Frame
from moritz_agent.skills.weather.model import HourPoint

_HOUR = timedelta(hours=1)


def _midnight(day: date, tz) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz)


def _span(frame: Frame, default_from: int, default_to: int, *, tonight: bool = False):
    """(hours, label, day) of the asked time, else today between two hours (or tomorrow)."""
    now, when = frame.now, frame.when
    if when is not None and when.granularity not in {"now"}:
        start, end, label = when.start, when.end, when.label
        if when.granularity == "day":  # only the hours that matter for this advice
            midnight = _midnight(start.date(), now.tzinfo)
            start = max(start, midnight + timedelta(hours=default_from))
            end = min(end, midnight + timedelta(hours=default_to))
        if start < now < end:
            start = now.replace(minute=0, second=0, microsecond=0)
        return frame.pack.hours_between(start, end), label, start.date()
    day = now.date()
    start = _midnight(day, now.tzinfo) + timedelta(hours=default_from)
    end = _midnight(day, now.tzinfo) + timedelta(hours=default_to)
    label = "heute"
    if now >= end:
        day += timedelta(days=1)
        start, end, label = start + timedelta(days=1), end + timedelta(days=1), "morgen"
    elif start < now:
        start = now.replace(minute=0, second=0, microsecond=0)
    if tonight:
        label = "heute Nacht" if label == "heute" else "morgen Nacht"
    return frame.pack.hours_between(start, end), label, day


def _dry(hour: HourPoint, limit: float = 20) -> bool:
    return (
        hour_class(hour) not in WET
        and (hour.precip_prob or 0) <= limit
        and hour.precipitation < 0.1
    )


def _longest_dry(hours: list[HourPoint], limit: float = 20) -> list[HourPoint]:
    best: list[HourPoint] = []
    run: list[HourPoint] = []
    for hour in hours:
        if _dry(hour, limit):
            run.append(hour)
            if len(run) > len(best):
                best = list(run)
        else:
            run = []
    return best


def _first_wet(hours: list[HourPoint]) -> HourPoint | None:
    return next((h for h in hours if not _dry(h, 40)), None)


def _lead(text: str) -> str:
    return text[:1].upper() + text[1:]


def _no_data(frame: Frame, day: date) -> SkillResult:
    return out_of_range(frame, day)


# -- clothes ---------------------------------------------------------------------------------------
def jacket(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 0, 22)
    if not hours:
        return _no_data(frame, day)
    temps = [(h.apparent if h.apparent is not None else h.temperature, h) for h in hours]
    temps = [(v, h) for v, h in temps if v is not None]
    low, low_hour = min(temps, key=lambda item: item[0])
    rain = max((h.precip_prob or 0) for h in hours)
    if low < 15 or rain >= 50:
        thick = "eine dicke Jacke" if low < 5 else "eine Jacke"
        reasons = []
        if low < 15:
            reasons.append(f"{t.at_hour(low_hour.time).replace('gegen', 'gegen')} nur {t.deg(low)}")
        if rain >= 50:
            reasons.append("es regnet" if low >= 15 else "dazu Regen")
        text = f"Ja, {thick} – {' und '.join(reasons)}"
    elif low >= 20 and rain < 30:
        text = f"Nein, {label} reicht ein T-Shirt, mindestens {t.deg(low)} und trocken"
    else:
        text = f"Eine leichte Jacke reicht, {label} bleibt es bei {t.deg(low)} bis {t.deg(max(v for v, _ in temps))}"
    return frame.finish(g.sentence(text), aspect="advice")


def laundry(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 8, 19)
    if not hours:
        return _no_data(frame, day)
    stretch = _longest_dry(hours, 20)
    humidity = [h.humidity for h in stretch if h.humidity is not None]
    temps = [h.temperature for h in stretch if h.temperature is not None]
    wind = [h.wind for h in stretch if h.wind is not None]
    if len(stretch) >= 4 and humidity and max(humidity) < 75 and temps and min(temps) >= 10:
        extra = " und etwas Wind" if wind and max(wind) >= 5 else ""
        word = "sonnig" if sky(stretch) in {"sonnig", "heiter"} else "trocken"
        text = f"{_lead(label)} gut: {word}{extra}, {t.deg(max(temps))}"
        return frame.finish(g.sentence(text), aspect="advice")
    wet = _first_wet(hours)
    if wet is not None and (wet.precip_prob or 0) >= 30:
        reason = (
            "es regnet"
            if wet.time <= hours[0].time
            else f"ab etwa {t.at_hour(wet.time).replace('gegen ', '')} kommt Regen"
        )
    elif humidity and max(humidity) >= 75:
        reason = f"die Luft ist mit {round(max(humidity))} Prozent zu feucht"
    elif temps and min(temps) < 10:
        reason = f"es ist mit {t.deg(min(temps))} zu kalt"
    else:
        reason = "es bleibt nicht lange genug trocken"
    return frame.finish(g.sentence(f"Eher nicht: {reason}"), aspect="advice")


def bbq(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 17, 22)
    if not hours:
        return _no_data(frame, day)
    temp = max((h.temperature for h in hours if h.temperature is not None), default=None)
    gusts = max((h.gusts or 0) for h in hours)
    wet = [h for h in hours if not _dry(h, 20)]
    if wet:
        thunder = any(hour_class(h) == "gewitter" for h in hours)
        reason = (
            "Gewitter sind möglich"
            if thunder
            else f"ab etwa {t.at_hour(wet[0].time).replace('gegen ', '')} droht Regen"
        )
        return frame.finish(g.sentence(f"Eher nicht, {reason}"), aspect="advice")
    if temp is not None and temp < 10:
        return frame.finish(
            g.sentence(f"Eher nicht, mit {t.deg(temp)} ist es zu kalt"), aspect="advice"
        )
    if gusts >= 40:
        return frame.finish(
            g.sentence(f"Eher nicht, es gibt Böen bis {t.round5(gusts)} Kilometer pro Stunde"),
            aspect="advice",
        )
    if temp is not None and temp >= 15:
        word = "heute Abend" if label == "heute" else label
        return frame.finish(
            g.sentence(f"{_lead(word)} ja: trocken und {t.deg(temp)}"), aspect="advice"
        )
    return frame.finish(
        g.sentence(f"Es geht, trocken, aber nur {t.deg(temp or 0)}"), aspect="advice"
    )


def bike(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 7, 21)
    if not hours:
        return _no_data(frame, day)
    if any(hour_class(h) in {"gewitter", "glatt"} for h in hours):
        return frame.finish(
            g.sentence("Lieber nicht, es gibt Gewitter oder Glätte"), aspect="advice"
        )
    gusts = max((h.gusts or 0) for h in hours)
    low = temperature_range(hours)
    if gusts >= 50:
        return frame.finish(
            g.sentence(f"Lieber nicht, die Böen gehen bis {t.round5(gusts)} Kilometer pro Stunde"),
            aspect="advice",
        )
    if low and low[0] < 0:
        return frame.finish(
            g.sentence(f"Vorsicht, mit bis zu {t.deg(low[0])} kann es glatt sein"), aspect="advice"
        )
    wet = _first_wet(hours)
    if wet is None:
        return frame.finish(
            g.sentence(
                f"Ja, {label} bleibt es trocken, bis {t.deg(low[1]) if low else ''}".rstrip(", ")
            ),
            aspect="advice",
        )
    if wet.time <= hours[0].time + _HOUR:
        return frame.finish(
            g.sentence("Eher nicht, es regnet oder fängt gleich an"), aspect="advice"
        )
    return frame.finish(
        g.sentence(
            f"Bis {t.at_hour(wet.time).replace('gegen ', '')} trocken, danach Regen – lieber vorher los"
        ),
        aspect="advice",
    )


def run(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 6, 21)
    if not hours:
        return _no_data(frame, day)

    def penalty(h: HourPoint) -> float:
        temp = h.temperature if h.temperature is not None else 12
        bad = (h.precip_prob or 0) + abs(temp - 13) * 3 + (h.gusts or 0) / 2
        if hour_class(h) in {"gewitter", "glatt"} or temp >= 30 or temp < -5:
            bad += 500
        return bad

    best = min(hours, key=penalty)
    if penalty(best) >= 100:
        return frame.finish(
            g.sentence(f"{_lead(label)} eher nicht, das Wetter ist zum Laufen ungünstig"),
            aspect="advice",
        )
    detail = "trocken" if _dry(best, 30) else "mit leichtem Regenrisiko"
    return frame.finish(
        g.sentence(
            f"Am besten {t.at_hour(best.time)}, {detail} und {t.deg(best.temperature or 0)}"
        ),
        aspect="advice",
    )


# -- garden and house ---------------------------------------------------------------------------------
def garden_water(frame: Frame) -> SkillResult:
    pack, today = frame.pack, frame.now.date()
    past = [pack.day(today - timedelta(days=i)) for i in (1, 2, 3)]
    past = [d for d in past if d is not None]
    if not past:
        return _no_data(frame, today)
    fallen = sum(d.precipitation or 0 for d in past)
    evaporated = sum(d.et0 or 0 for d in past)
    ahead = sum(
        h.precipitation for h in pack.hours_between(frame.now, frame.now + timedelta(hours=24))
    )
    if ahead >= 5 or fallen >= 5:
        why = (
            f"in den nächsten 24 Stunden kommen {t.liters(ahead)}"
            if ahead >= 5
            else f"es sind schon {t.liters(fallen)} gefallen"
        )
        return frame.finish(g.sentence(f"Nein, {why}"), aspect="advice")
    if fallen - evaporated < -5 and ahead < 2:
        return frame.finish(
            g.sentence(
                f"Eher ja: in den letzten drei Tagen fielen nur {t.liters(fallen)}, und es kommt kaum Regen"
            ),
            aspect="advice",
        )
    return frame.finish(
        g.sentence("Nicht dringend, die Erde ist noch feucht genug"), aspect="advice"
    )


def mow(frame: Frame) -> SkillResult:
    pack, now = frame.pack, frame.now
    before = pack.hours_between(now - timedelta(hours=6), now)
    after = pack.hours_between(now, now + timedelta(hours=3))
    if any(h.precipitation >= 0.2 for h in before):
        return frame.finish(
            g.sentence("Lieber nicht, der Rasen ist nach dem Regen noch nass"), aspect="advice"
        )
    if any(not _dry(h, 40) for h in after):
        return frame.finish(
            g.sentence("Lieber nicht, in den nächsten Stunden kommt Regen"), aspect="advice"
        )
    humid = [h.humidity for h in after if h.humidity is not None]
    if humid and max(humid) >= 85:
        return frame.finish(
            g.sentence("Eher nicht, die Luft ist feucht und der Rasen bleibt nass"), aspect="advice"
        )
    return frame.finish(g.sentence("Ja, es ist trocken und bleibt es auch"), aspect="advice")


def ventilate(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 0, 22, tonight=frame.when is None and frame.now.hour >= 20)
    if not hours:
        return _no_data(frame, day)
    if max((h.gusts or 0) for h in hours) >= 50:
        return frame.finish(
            g.sentence(f"Lieber geschlossen lassen, {label} gibt es starke Böen"), aspect="advice"
        )
    if max((h.precip_prob or 0) for h in hours) >= 50:
        return frame.finish(
            g.sentence(f"Lieber nicht lange offen lassen, {label} regnet es"), aspect="advice"
        )
    return frame.finish(
        g.sentence(f"Ja, {label} bleibt es trocken, lüften ist in Ordnung"), aspect="advice"
    )


def car_wash(frame: Frame) -> SkillResult:
    hours = frame.pack.hours_between(frame.now, frame.now + timedelta(hours=48))
    wet = _first_wet(hours)
    if wet is None:
        return frame.finish(
            g.sentence("Ja, in den nächsten zwei Tagen bleibt es trocken"), aspect="advice"
        )
    day = g.day_label(wet.time.date(), frame.now.date())
    return frame.finish(
        g.sentence(f"Eher nicht, {day} {t.at_hour(wet.time)} soll es regnen"), aspect="advice"
    )


def swim(frame: Frame) -> SkillResult:
    hours, _label, day = _span(frame, 11, 19)
    if not hours:
        return _no_data(frame, day)
    top = max(hours, key=lambda h: h.temperature or -99)
    storm = any(hour_class(h) == "gewitter" for h in hours)
    if storm:
        return frame.finish(g.sentence("Nein, es sind Gewitter möglich"), aspect="advice")
    if (top.temperature or 0) >= 25 and sky(hours) in {"sonnig", "heiter", "wolkig"}:
        return frame.finish(
            g.sentence(f"Mit {t.deg(top.temperature or 0)} und {sky(hours)} ja"), aspect="advice"
        )
    return frame.finish(
        g.sentence(f"Eher nicht, mit {t.deg(top.temperature or 0)} ist es zu kühl"), aspect="advice"
    )


def hike(frame: Frame) -> SkillResult:
    hours, label, day = _span(frame, 8, 19)
    if not hours:
        return _no_data(frame, day)
    rng = temperature_range(hours)
    bits = [f"{_lead(label)} {t.temp_range(*rng)}" if rng else _lead(label)]
    wet = _first_wet(hours)
    bits.append(f"ab etwa {t.at_hour(wet.time).replace('gegen ', '')} Regen" if wet else "trocken")
    warnings = []
    if any(hour_class(h) == "gewitter" for h in hours):
        warnings.append("Vorsicht, Gewittergefahr")
    if rng and rng[1] >= 30:
        warnings.append("Hitze, nimm viel Wasser mit")
    if any(hour_class(h) == "glatt" for h in hours) or (rng and rng[0] < 0):
        warnings.append("Achtung, es kann glatt sein")
    return frame.finish(
        g.sentence(", ".join(bits)) + (" " + g.sentence(". ".join(warnings)) if warnings else ""),
        aspect="advice",
    )


def plants_frost(frame: Frame) -> SkillResult:
    hours, label, _day = _span(frame, 20, 31)  # tonight until 7 h
    if not hours:
        hours = frame.pack.hours_between(frame.now, frame.now + timedelta(hours=12))
    low = temperature_range(hours)
    ground = [h.soil_temperature for h in hours if h.soil_temperature is not None]
    if low and low[0] <= 2:
        return frame.finish(
            g.sentence(f"Ja, {label} wird es bis {t.deg(low[0])} kalt, Frost ist möglich"),
            aspect="advice",
        )
    if ground and min(ground) <= 0:
        return frame.finish(
            g.sentence(
                f"Ja, am Boden ist Frost möglich, die Luft kühlt auf {t.deg(low[0]) if low else 'wenig'} ab"
            ),
            aspect="advice",
        )
    return frame.finish(
        g.sentence(
            f"Nein, {label} bleibt es mit mindestens {t.deg(low[0]) if low else '?'} frostfrei"
        ),
        aspect="advice",
    )


def heating(frame: Frame) -> SkillResult:
    day = frame.when.day if frame.when and frame.when.day else frame.now.date()
    point = frame.pack.day(day)
    if point is None or point.tmax is None or point.tmin is None:
        return _no_data(frame, day)
    mean = (point.tmax + point.tmin) / 2
    name = g.day_label(day, frame.now.date())
    if mean < 15:
        return frame.finish(
            g.sentence(f"Ja, {name} ist ein Heiztag, im Mittel nur {t.deg(mean)}"), aspect="advice"
        )
    return frame.finish(
        g.sentence(
            f"Nein, {name} liegt der Tagesschnitt bei {t.deg(mean)}, geheizt werden muss nicht"
        ),
        aspect="advice",
    )

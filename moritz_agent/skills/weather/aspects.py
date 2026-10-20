# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Single-aspect weather answers: rain, snow, frost, wind, thunder, UV … (docs/plan/13 §6.5, §7.7)."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean

from moritz_agent.skills.base import SkillResult
from moritz_agent.skills.render import german as g
from moritz_agent.skills.weather import text as t
from moritz_agent.skills.weather.analysis import (
    WET,
    block_class,
    code_info,
    hour_class,
    peak,
    sky,
    temperature_range,
)
from moritz_agent.skills.weather.answers import (
    is_past,
    next_wet_period,
    out_of_range,
    raining_now,
    sentence_join,
    uv_word,
    window,
)
from moritz_agent.skills.weather.frame import Frame
from moritz_agent.skills.weather.model import HourPoint

_HOUR = timedelta(hours=1)


def _hours(frame: Frame, default_hours: int = 0) -> tuple[list[HourPoint], datetime, datetime, str]:
    start, end, label = window(frame, default_hours)
    return frame.pack.hours_between(start, end), start, end, label


def _clock(moment: datetime) -> str:
    return t.at_quarter(moment)


def _span(first: datetime, last: datetime, start: datetime, end: datetime) -> str:
    """ "ab etwa 15 Uhr", "bis etwa 17 Uhr", "von 15 bis 17 Uhr", "durchgehend"."""
    from_start = first <= start
    to_end = last >= end
    if from_start and to_end:
        return "durchgehend"
    if from_start:
        return f"bis etwa {_clock(last)}"
    if to_end:
        return f"ab etwa {_clock(first)}"
    return f"zwischen {first.hour} und {last.hour} Uhr"


def _lead(label: str) -> str:
    """Time words for the start of a sentence: "heute" → "Heute", "am Samstag" → "Am Samstag"."""
    return label[:1].upper() + label[1:]


# -- rain ------------------------------------------------------------------------------------
def answer_rain(frame: Frame) -> SkillResult:
    hours, start, end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    wet = [
        h
        for h in hours
        if hour_class(h) in WET and (h.precipitation >= 0.1 or (h.precip_prob or 0) >= 50)
    ]
    total = sum(h.precipitation for h in hours)
    peak_prob = max((h.precip_prob or 0) for h in hours)
    past = is_past(frame)
    if not wet:
        if past:
            text = f"Nein, {label} hat es nicht geregnet"
        elif peak_prob >= 30:
            text = (
                f"Eher nicht, {label} liegt das Regenrisiko bei {t.round_prob(peak_prob)} Prozent"
            )
        else:
            text = f"Nein, {label} bleibt es trocken"
        return frame.finish(g.sentence(text), detail=_rain_detail(hours), aspect="rain")
    kind = block_class(wet)
    first, last = wet[0].time, wet[-1].time + _HOUR
    if past:
        text = f"Ja, {label} hat es geregnet, insgesamt etwa {t.liters(total)}"
    else:
        sure = "wahrscheinlich" if max((h.precip_prob or 0) for h in wet) >= 60 else "möglich"
        span = _span(first, last, start, end)
        if kind == "schauer":
            verb = f"sind Schauer {sure}"
        elif kind == "gewitter":
            verb = f"sind Gewitter {sure}"
        elif kind == "schnee":
            verb = f"ist Schnee {sure}"
        else:
            verb = f"ist Regen {sure}"
        if span == "durchgehend":
            text = f"Ja, {label} {verb}, ziemlich durchgehend"
        elif label in {"heute", "in den nächsten Stunden"}:
            text = f"Ja, {span} {verb}"
        else:
            text = f"Ja, {label} {span} {verb}"
    return frame.finish(
        g.sentence(text),
        detail=_rain_detail(hours),
        aspect="rain",
        data={"rain_mm": round(total, 1)},
    )


def _rain_detail(hours: list[HourPoint]) -> str:
    total = sum(h.precipitation for h in hours)
    if total < 0.2:
        return "Es werden keine nennenswerten Niederschläge erwartet."
    peak_hour = peak(hours, "precipitation")
    text = f"Insgesamt fallen etwa {t.liters(total)}"
    if peak_hour and peak_hour.precipitation >= 0.5:
        text += f", am meisten {t.at_hour(peak_hour.time)}"
    return g.sentence(text)


def answer_rain_when(frame: Frame) -> SkillResult:
    now = frame.now
    text = frame.req.text
    wants_end = any(
        w in text for w in ("aufhören", "aufhört", "hört", "vorbei", "noch regnen", "wie lange")
    )
    if raining_now(frame):
        period = next_wet_period(frame, now, 24)
        if period and period[1] is not None:
            return frame.finish(
                g.sentence(f"Der Regen soll {t.at_hour(period[1])} aufhören"), aspect="rain_when"
            )
        return frame.finish(
            "Der Regen hält voraussichtlich noch länger als einen Tag an.", aspect="rain_when"
        )
    period = next_wet_period(frame, now, 48)
    if period is None:
        if wants_end:
            return frame.finish(
                "Im Moment regnet es nicht, und es sieht auch nicht danach aus.", aspect="rain_when"
            )
        return frame.finish(
            "In den nächsten zwei Tagen bleibt es voraussichtlich trocken.", aspect="rain_when"
        )
    first, last = period
    day_note = ""
    delta = (first.date() - now.date()).days
    if delta == 1:
        day_note = " morgen"
    elif delta >= 2:
        day_note = f" am {t.weekday(first.date())}"
    if wants_end:
        text = f"Im Moment regnet es nicht. Der nächste Regen beginnt{day_note} ab etwa {_clock(first)}"
        if last is not None:
            text += f" und hört {t.at_hour(last)} wieder auf"
        return frame.finish(g.sentence(text), aspect="rain_when")
    text = f"Der Regen fängt voraussichtlich{day_note} ab etwa {_clock(first)} an"
    if last is not None:
        text += f" und hört {t.at_hour(last)} wieder auf"
    return frame.finish(g.sentence(text), aspect="rain_when")


def answer_rain_now(frame: Frame) -> SkillResult:
    if raining_now(frame):
        hour = frame.pack.hour_at(frame.now)
        current = frame.pack.current
        mm = (current.precipitation if current and current.precipitation else None) or (
            hour.precipitation if hour else 0
        )
        strength = "leicht" if mm < 0.5 else "kräftig" if mm >= 2.5 else "mäßig"
        place = frame.in_place()
        text = f"Ja, {place + ' ' if place else ''}regnet es gerade {strength}"
        period = next_wet_period(frame, frame.now, 12)
        if period and period[1] is not None:
            text += f", der Regen soll {t.at_hour(period[1])} aufhören"
        return frame.finish(g.sentence(text), aspect="rain_now")
    place = frame.in_place()
    return frame.finish(
        g.sentence(f"Nein, {place + ' ' if place else ''}regnet es gerade nicht"), aspect="rain_now"
    )


def answer_rain_amount(frame: Frame) -> SkillResult:
    hours, start, _end, label = _hours(frame, default_hours=0)
    if not hours:
        return out_of_range(frame, start.date())
    total = sum(h.precipitation for h in hours)
    past = is_past(frame)
    if total < 0.2:
        text = (
            f"{_lead(label)} {'hat es' if past else 'wird es'} nicht nennenswert regnen"
            if not past
            else f"{_lead(label)} hat es nicht geregnet"
        )
        return frame.finish(g.sentence(text), aspect="rain_amount")
    if past:
        text = f"{_lead(label)} sind etwa {t.liters(total)} gefallen"
    else:
        text = f"{_lead(label)} sollen etwa {t.liters(total)} fallen"
    return frame.finish(
        g.sentence(text),
        detail=_rain_detail(hours),
        aspect="rain_amount",
        data={"rain_mm": round(total, 1)},
    )


# -- umbrella ----------------------------------------------------------------------------------
def answer_umbrella(frame: Frame) -> SkillResult:
    now = frame.now
    when = frame.when
    if when is None or when.granularity == "now":
        start = now.replace(minute=0, second=0, microsecond=0)
        end = datetime.combine(now.date(), datetime.min.time(), now.tzinfo) + timedelta(hours=22)
        label = "bis heute Abend"
        if now.hour >= 21:
            start = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(), now.tzinfo
            ) + timedelta(hours=6)
            end = start + timedelta(hours=16)
            label = "morgen"
    else:
        start, end, label = when.start, when.end, when.label
    hours = frame.pack.hours_between(start, end)
    if not hours:
        return out_of_range(frame, start.date())
    peak_prob = max((h.precip_prob or 0) for h in hours)
    total = sum(h.precipitation for h in hours)
    wet = [h for h in hours if hour_class(h) in WET and (h.precip_prob or 0) >= 40]
    if peak_prob >= 50 or total >= 0.5:
        first, last = (
            (wet[0].time, wet[-1].time + _HOUR) if wet else (hours[0].time, hours[-1].time + _HOUR)
        )
        span = _span(first, last, start, end)
        reason = (
            "es regnet durchgehend"
            if span == "durchgehend"
            else f"{span} sind Schauer wahrscheinlich"
        )
        if block_class(wet or hours) == "regen" and span != "durchgehend":
            reason = f"{span} ist Regen wahrscheinlich"
        text = f"Ja, {reason}"
    elif peak_prob >= 30:
        text = f"Ein kleiner Schirm schadet nicht, das Regenrisiko liegt {label} bei {t.round_prob(peak_prob)} Prozent"
    else:
        text = f"Nein, {label} bleibt es trocken"
    return frame.finish(g.sentence(text), detail=_rain_detail(hours), aspect="umbrella")


# -- snow ----------------------------------------------------------------------------------------
def answer_snow(frame: Frame) -> SkillResult:
    hours, start, end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    snow = [h for h in hours if hour_class(h) == "schnee" or (h.snowfall or 0) > 0.05]
    if not snow:
        low = temperature_range(hours)
        extra = f", es bleibt mit mindestens {t.deg(low[0])} zu warm" if low and low[0] > 3 else ""
        return frame.finish(
            g.sentence(f"Nein, {label} ist kein Schnee in Sicht{extra}"), aspect="snow"
        )
    amount = sum(h.snowfall or 0 for h in snow)
    depth = max((h.snow_depth or 0) for h in hours) * 100  # m → cm
    cold = all((h.temperature or 0) <= 1 for h in snow)
    when_text = _span(snow[0].time, snow[-1].time + _HOUR, start, end)
    text = f"Ja, {label} kann es schneien"
    if when_text != "durchgehend":
        text += f", {when_text}"
    if amount >= 1:
        text += f", etwa {g.number(round(amount))} Zentimeter Neuschnee"
    text += (
        ", er bleibt wohl liegen"
        if depth >= 1 or (cold and amount >= 1)
        else ", liegen bleiben soll kaum etwas"
    )
    return frame.finish(g.sentence(text), aspect="snow", data={"snow_cm": round(amount, 1)})


# -- frost ----------------------------------------------------------------------------------------
def answer_frost(frame: Frame) -> SkillResult:
    now, when = frame.now, frame.when
    if when is None or when.granularity == "now":
        if now.hour < 9:
            start = now.replace(minute=0, second=0, microsecond=0)
            end = datetime.combine(now.date(), datetime.min.time(), now.tzinfo) + timedelta(hours=9)
            label, morning = "heute früh", True
        else:
            start = datetime.combine(now.date(), datetime.min.time(), now.tzinfo) + timedelta(
                hours=22
            )
            end = start + timedelta(hours=11)
            label, morning = "heute Nacht", False
    else:
        start, end, label = when.start, when.end, when.label
        morning = when.daypart in {"früh", "nacht"} or when.granularity == "day"
    hours = frame.pack.hours_between(start, end)
    if not hours:
        return out_of_range(frame, start.date())
    glatt = [h for h in hours if hour_class(h) == "glatt"]
    low = temperature_range(hours)
    ground = [h.soil_temperature for h in hours if h.soil_temperature is not None]
    text_parts = []
    if glatt:
        text_parts.append(f"Achtung, {label} droht Glatteis durch gefrierenden Regen")
    if low and low[0] <= 0:
        scrape = " – du musst wohl die Scheiben kratzen" if morning else ""
        text_parts.append(f"{_lead(label)} gibt es Frost, bis {t.deg(low[0])}{scrape}")
    elif low and low[0] <= 3 and ground and min(ground) <= 0:
        text_parts.append(
            f"{_lead(label)} ist Bodenfrost möglich, die Luft kühlt auf {t.deg(low[0])} ab"
        )
    elif low:
        text_parts.append(
            f"Nein, {label} gibt es keinen Frost, der Tiefstwert liegt bei {t.deg(low[0])}"
        )
    if not text_parts:
        return frame.finish("Dazu habe ich gerade keine Wetterdaten.", aspect="frost", serious=True)
    return frame.finish(
        sentence_join(*text_parts), aspect="frost", data={"tmin": round(low[0], 1) if low else None}
    )


# -- wind -----------------------------------------------------------------------------------------
def answer_wind(frame: Frame) -> SkillResult:
    text = frame.req.text
    asks_storm = any(w in text for w in ("sturm", "stürmisch", "orkan"))
    asks_gusts = any(w in text for w in ("böe", "böen"))
    when = frame.when
    now_mode = when is None or when.granularity == "now"
    if now_mode:
        current = frame.pack.current
        start = frame.now.replace(minute=0, second=0, microsecond=0)
        hours = frame.pack.hours_between(start, frame.now + timedelta(hours=8))
        label = "in den nächsten Stunden"
        speed = (
            current.wind
            if current and current.wind is not None
            else (hours[0].wind if hours else None)
        )
        direction = current.wind_dir if current else (hours[0].wind_dir if hours else None)
        gusts = max(
            [
                x
                for x in [current.gusts if current else None, *[h.gusts for h in hours[:6]]]
                if x is not None
            ],
            default=None,
        )
    else:
        hours, start, _end, label = _hours(frame)
        if not hours:
            return out_of_range(frame, start.date())
        speeds = [h.wind for h in hours if h.wind is not None]
        speed = mean(speeds) if speeds else None
        top = peak(hours, "wind")
        direction = top.wind_dir if top else None
        gusts = max((h.gusts for h in hours if h.gusts is not None), default=None)
    if speed is None:
        return frame.finish("Dazu habe ich gerade keine Winddaten.", aspect="wind", serious=True)
    phrase = t.wind_phrase(speed, direction, gusts)
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    if asks_storm:
        peak_gust = gusts or speed
        if peak_gust >= 75:
            answer = f"Ja, {label}{in_place} gibt es Sturm, Böen bis {t.round5(peak_gust)} Kilometer pro Stunde"
        elif peak_gust >= 62:
            answer = f"Es wird stürmisch, Böen bis {t.round5(peak_gust)} Kilometer pro Stunde"
        else:
            answer = f"Nein, {label}{in_place} ist kein Sturm in Sicht: {phrase}"
    elif asks_gusts:
        answer = (
            f"Die Böen erreichen {label}{in_place} bis zu {t.round5(gusts)} Kilometer pro Stunde"
            if gusts
            else _lead(phrase)
        )
    elif now_mode:
        answer = f"{in_place[1:].capitalize()}: {phrase}" if in_place else _lead(phrase)
    else:
        answer = f"{_lead(label)}{in_place}: {phrase}"
    return frame.finish(
        g.sentence(answer),
        aspect="wind",
        data={"wind_kmh": round(speed), "gust_kmh": round(gusts) if gusts else None},
    )


# -- thunder, fog -----------------------------------------------------------------------------------
def answer_thunder(frame: Frame) -> SkillResult:
    hours, start, end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    storm = [
        h
        for h in hours
        if hour_class(h) == "gewitter" or ((h.cape or 0) >= 2000 and (h.precip_prob or 0) >= 60)
    ]
    if not storm:
        return frame.finish(
            g.sentence(f"Nein, {label} sind keine Gewitter in Sicht"), aspect="thunder"
        )
    heavy = any(h.precipitation >= 2 for h in storm)
    span = _span(storm[0].time, storm[-1].time + _HOUR, start, end)
    text = f"Ja, {label} sind Gewitter möglich"
    if span != "durchgehend":
        text += f", {span}"
    if heavy:
        text += ", örtlich mit Starkregen"
    return frame.finish(g.sentence(text), aspect="thunder")


def answer_fog(frame: Frame) -> SkillResult:
    hours, start, end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    foggy = [
        h
        for h in hours
        if hour_class(h) == "nebel" or (h.visibility is not None and h.visibility < 1000)
    ]
    if not foggy:
        return frame.finish(g.sentence(f"Nein, {label} ist kein Nebel in Sicht"), aspect="fog")
    place = frame.in_place()
    span = _span(foggy[0].time, foggy[-1].time + _HOUR, start, end)
    text = f"{_lead(label)} ist {place + ' ' if place else ''}Nebel möglich"
    if span != "durchgehend":
        text += f", {span}"
    return frame.finish(g.sentence(text), aspect="fog")


# -- numbers: temperature, feels like, humidity, pressure ---------------------------------------------
def answer_temperature(frame: Frame) -> SkillResult:
    text = frame.req.text
    wants_low = any(w in text for w in ("kalt", "kälter", "tiefst", "minimum", "abkühl"))
    wants_high = any(w in text for w in ("warm", "wärm", "heiß", "höchst", "maximum", "heiss"))
    when = frame.when
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    if when is None or when.granularity == "now":
        current = frame.pack.current
        hour = frame.pack.hour_at(frame.now)
        temp = (
            current.temperature
            if current and current.temperature is not None
            else (hour.temperature if hour else None)
        )
        if temp is None:
            return frame.finish(
                "Dazu habe ich gerade keine Wetterdaten.", aspect="temperature", serious=True
            )
        apparent = current.apparent if current else (hour.apparent if hour else None)
        felt = t.feels_like_note(temp, apparent)
        today = frame.pack.day(frame.now.date())
        base = (
            f"{place[:1].upper() + place[1:]} sind es gerade {t.deg(temp)}"
            if place
            else f"Gerade sind es {t.deg(temp)}"
        )
        if felt:
            base += f", {felt}"
        extra = ""
        if today and today.tmax is not None and frame.now.hour < 15:
            extra = f"Heute werden es bis zu {t.deg(today.tmax)}"
        return frame.finish(
            sentence_join(base, extra), aspect="temperature", data={"temperature": round(temp, 1)}
        )
    hours, start, _end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    rng = temperature_range(hours)
    assert rng is not None
    low, high = rng
    night = when.daypart == "nacht" or (when.daypart == "früh")
    if (wants_low and not wants_high) or night:
        text_out = (
            f"{_lead(label)}{in_place} {'wird es' if not is_past(frame) else 'war es'} "
            f"{'frostig' if low < 0 else 'kalt'}, bis {t.deg(low)}"
            if low < 5
            else f"{_lead(label)}{in_place} kühlt es auf {t.deg(low)} ab"
        )
    elif wants_high and not wants_low:
        text_out = f"{_lead(label)}{in_place} {'werden es' if not is_past(frame) else 'waren es'} bis zu {t.deg(high)}"
    else:
        text_out = f"{_lead(label)}{in_place} {'werden es' if not is_past(frame) else 'waren es'} {t.temp_range(low, high)}"
    return frame.finish(
        g.sentence(text_out),
        aspect="temperature",
        data={"tmin": round(low, 1), "tmax": round(high, 1)},
    )


def answer_feels_like(frame: Frame) -> SkillResult:
    current = frame.pack.current
    hour = frame.pack.hour_at(frame.now)
    temp = (
        current.temperature
        if current and current.temperature is not None
        else (hour.temperature if hour else None)
    )
    apparent = (
        current.apparent
        if current and current.apparent is not None
        else (hour.apparent if hour else None)
    )
    if temp is None or apparent is None:
        return frame.finish(
            "Dazu habe ich gerade keine Wetterdaten.", aspect="feels_like", serious=True
        )
    wind = current.wind if current and current.wind is not None else (hour.wind if hour else 0)
    humidity = (
        current.humidity
        if current and current.humidity is not None
        else (hour.humidity if hour else 50)
    )
    if abs(apparent - temp) < 2:
        text = f"Gefühlt ist es etwa so, wie es gemessen ist: {t.deg(temp)}"
    else:
        reason = (
            "wegen des Windes"
            if apparent < temp and (wind or 0) >= 15
            else "wegen der Luftfeuchtigkeit"
            if apparent > temp and (humidity or 0) >= 70
            else ""
        )
        text = f"Gefühlt sind es {reason + ' ' if reason else ''}{t.deg(apparent)}, gemessen {t.deg(temp)}"
    return frame.finish(g.sentence(text), aspect="feels_like")


def answer_humidity(frame: Frame) -> SkillResult:
    current = frame.pack.current
    hour = frame.pack.hour_at(frame.now)
    humidity = (
        current.humidity
        if current and current.humidity is not None
        else (hour.humidity if hour else None)
    )
    if humidity is None:
        return frame.finish("Dazu habe ich gerade keine Daten.", aspect="humidity", serious=True)
    dew = hour.dew_point if hour else None
    sultry = "schwül" in frame.req.text
    if sultry:
        if dew is not None and dew >= 16:
            text = f"Ja, es ist schwül: Taupunkt {t.deg(dew)}, Luftfeuchtigkeit {round(humidity)} Prozent"
        else:
            text = f"Nein, schwül ist es nicht, die Luftfeuchtigkeit liegt bei {round(humidity)} Prozent"
    else:
        text = f"Die Luftfeuchtigkeit liegt bei {round(humidity)} Prozent"
    return frame.finish(g.sentence(text), aspect="humidity")


def answer_pressure(frame: Frame) -> SkillResult:
    pack, now = frame.pack, frame.now
    current = pack.current
    hour = pack.hour_at(now)
    pressure = (
        current.pressure
        if current and current.pressure is not None
        else (hour.pressure if hour else None)
    )
    if pressure is None:
        return frame.finish("Dazu habe ich gerade keine Daten.", aspect="pressure", serious=True)
    earlier = pack.hour_at(now - timedelta(hours=3))
    trend = ""
    if earlier and earlier.pressure is not None:
        diff = pressure - earlier.pressure
        trend = (
            ", gleichbleibend"
            if abs(diff) < 1
            else ", leicht steigend"
            if 1 <= diff < 3
            else ", steigend"
            if diff >= 3
            else ", leicht fallend"
            if -3 < diff <= -1
            else ", fallend"
        )
    return frame.finish(
        g.sentence(f"Der Luftdruck liegt bei {g.number(round(pressure))} Hektopascal{trend}"),
        aspect="pressure",
    )


# -- sun, clouds, UV, visibility ---------------------------------------------------------------------------
def answer_sunshine(frame: Frame) -> SkillResult:
    hours, start, _end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    seconds = sum(h.sunshine_s or 0 for h in hours)
    best = peak(hours, "sunshine_s")
    if seconds < 900:
        return frame.finish(
            g.sentence(f"{_lead(label)} ist kaum Sonne zu erwarten"), aspect="sunshine"
        )
    amount = seconds / 3600
    text = f"{_lead(label)} sind etwa {g.number(round(amount))} {'Sonnenstunde' if round(amount) == 1 else 'Sonnenstunden'} drin"
    if best and (best.sunshine_s or 0) >= 1800:
        text += f", am meisten {t.at_hour(best.time)}"
    return frame.finish(g.sentence(text), aspect="sunshine")


def answer_clouds(frame: Frame) -> SkillResult:
    hours, start, _end, label = _hours(frame)
    if not hours:
        return out_of_range(frame, start.date())
    word = sky(hours)
    night = all(not h.is_day for h in hours)
    if "sterne" in frame.req.text or "klar" in frame.req.text:
        clear = word in {"klar", "überwiegend klar", "sonnig", "heiter"}
        text = (
            f"{_lead(label)} wird es überwiegend klar, Sterne sind gut zu sehen"
            if clear and night
            else (
                f"{_lead(label)} ist es bewölkt, viel von den Sternen wirst du nicht sehen"
                if night
                else f"{_lead(label)} ist es {word}"
            )
        )
    else:
        text = f"{_lead(label)} ist es {word}"
    return frame.finish(g.sentence(text), aspect="clouds")


def answer_uv(frame: Frame) -> SkillResult:
    hours, _start, _end, label = _hours(frame)
    daytime = [h for h in hours if h.uv is not None]
    if not daytime:
        return frame.finish("Dazu habe ich gerade keine UV-Daten.", aspect="uv", serious=True)
    top = max(daytime, key=lambda h: h.uv or 0)
    value = round(top.uv or 0)
    cream = ", Sonnencreme ist sinnvoll" if value >= 3 else ", Sonnencreme brauchst du nicht"
    if value < 1:
        return frame.finish(
            g.sentence(f"{_lead(label)} ist der UV-Index praktisch null"), aspect="uv"
        )
    text = f"{_lead(label)} erreicht der UV-Index {value} – {uv_word(top.uv or 0)}{cream}"
    return frame.finish(g.sentence(text), aspect="uv", data={"uv": value})


def answer_visibility(frame: Frame) -> SkillResult:
    hour = frame.pack.hour_at(frame.now)
    if hour is None or hour.visibility is None:
        return frame.finish("Dazu habe ich gerade keine Daten.", aspect="visibility", serious=True)
    meters = hour.visibility
    if meters >= 10000:
        text = "Die Sicht ist gut, mehr als zehn Kilometer"
    elif meters >= 1000:
        text = f"Die Sicht beträgt etwa {g.number(round(meters / 1000, 1), 1)} Kilometer"
    else:
        text = f"Die Sicht beträgt nur etwa {int(round(meters, -1))} Meter"
        if code_info(hour.code)["klasse"] == "nebel":
            text += " – Nebel"
    return frame.finish(g.sentence(text), aspect="visibility")

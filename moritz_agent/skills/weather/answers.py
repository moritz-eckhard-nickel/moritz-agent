# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The weather answers (docs/plan/13 §6.4, §6.5, §7.4, §7.5).

Each function turns a ``Frame`` (place, time span, weather pack) into a ``SkillResult``. Facts come
only from the pack; what the pack does not contain is not said.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import mean

from moritz_agent.skills.base import SkillResult
from moritz_agent.skills.render import german as g
from moritz_agent.skills.weather import text as t
from moritz_agent.skills.weather.analysis import (
    WET,
    block_class,
    code_info,
    day_class,
    day_sections,
    hour_class,
    peak,
    sky,
    temperature_range,
    week_trend,
    worst,
)
from moritz_agent.skills.weather.frame import Frame
from moritz_agent.skills.weather.model import DayPoint, HourPoint

CHAR = {
    "sonnig": "sonnig",
    "freundlich": "freundlich",
    "wolkig": "wolkig",
    "regen": "regnerisch",
    "schauer": "wechselhaft",
    "schnee": "winterlich mit Schnee",
    "gewitter": "gewittrig",
    "glatt": "glatt",
    "nebel": "trüb mit Nebel",
}
_UV_WORDS = ((3, "niedrig"), (6, "mäßig"), (8, "hoch"), (11, "sehr hoch"), (99, "extrem"))


# -- small helpers -------------------------------------------------------------------------
def head_day(day: date, today: date) -> str:
    """ "Heute", "Morgen, Montag,", "Am Samstag" – the start of a day sentence."""
    delta = (day - today).days
    if delta == 0:
        return "Heute"
    if delta == 1:
        return f"Morgen, {t.weekday(day)},"
    if delta == 2:
        return f"Übermorgen, {t.weekday(day)},"
    if delta == -1:
        return "Gestern"
    if delta == -2:
        return "Vorgestern"
    return g.day_label(day, today, capital=True)


def day_hours(frame: Frame, day: date) -> list[HourPoint]:
    return [h for h in frame.pack.hours if h.time.date() == day]


def verb(frame: Frame) -> str:
    return "war es" if frame.when and frame.when.end <= frame.now else "wird es"


def is_past(frame: Frame) -> bool:
    return bool(frame.when and frame.when.end <= frame.now)


def window(frame: Frame, default_hours: int = 0) -> tuple[datetime, datetime, str]:
    """Start, end and label of the span the question is about."""
    when, now = frame.when, frame.now
    if when is not None and when.granularity != "now":
        start, end = when.start, when.end
        if when.granularity in {"day", "weekend", "week", "days"} and start < now < end:
            start = now.replace(minute=0, second=0, microsecond=0)
        return start, end, when.label
    if default_hours:
        start = now.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=default_hours), "in den nächsten Stunden"
    start = now.replace(minute=0, second=0, microsecond=0)
    if now.hour >= 20:
        end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), now.tzinfo) + (
            timedelta(hours=9)
        )
        return start, end, "heute Nacht"
    end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), now.tzinfo)
    return start, end, "heute"


def next_wet_period(
    frame: Frame, start: datetime, hours: int = 24
) -> tuple[datetime, datetime | None] | None:
    """(start, end) of the next stretch with rain/snow from ``start`` on, 15-minute exact if possible."""
    pack = frame.pack
    end_limit = start + timedelta(hours=hours)
    points: list[tuple[datetime, bool]] = []
    minutes = pack.minutes_between(start, end_limit)
    if minutes:
        points = [(m.time, m.precipitation >= 0.05) for m in minutes]
    else:
        points = [
            (h.time, hour_class(h) in WET)
            for h in pack.hours_between(start - timedelta(hours=1), end_limit)
        ]
    first: datetime | None = None
    for stamp, wet in points:
        if wet and first is None:
            first = max(stamp, start)
        elif not wet and first is not None:
            return first, stamp
    return (first, None) if first is not None else None


def raining_now(frame: Frame) -> bool:
    current = frame.pack.current
    if current is not None and current.precipitation is not None and current.precipitation > 0.05:
        return True
    hour = frame.pack.hour_at(frame.now)
    return bool(hour and hour_class(hour) in WET and (hour.precipitation or 0) >= 0.1)


def sentence_join(*parts: str) -> str:
    return " ".join(g.sentence(p) for p in parts if p)


def when_phrase(label: str) -> str:
    return label


def uv_word(value: float) -> str:
    for limit, word in _UV_WORDS:
        if value < limit:
            return word
    return "extrem"


# -- overview: right now ---------------------------------------------------------------------
def answer_now(frame: Frame) -> SkillResult:
    pack, now = frame.pack, frame.now
    current = pack.current
    hour = pack.hour_at(now)
    if current is None and hour is None:
        return no_data(frame)
    temp = (
        current.temperature
        if current and current.temperature is not None
        else (hour.temperature if hour else None)
    )
    if temp is None:
        return no_data(frame)
    apparent = current.apparent if current else (hour.apparent if hour else None)
    code = current.code if current and current.code is not None else (hour.code if hour else None)
    is_day = current.is_day if current else (hour.is_day if hour else True)
    info = code_info(code, is_day)
    clouds = (
        current.cloud_cover
        if current and current.cloud_cover is not None
        else (hour.cloud_cover if hour else None)
    )
    if (
        info["klasse"] in {"trocken", "nebel"}
        and clouds is not None
        and info["klasse"] == "trocken"
    ):
        probe = HourPoint(time=now, cloud_cover=clouds, is_day=is_day, code=code)
        sky_text = sky([probe])
    else:
        sky_text = info["text"]
    speed = current.wind if current and current.wind is not None else (hour.wind if hour else None)
    direction = current.wind_dir if current else (hour.wind_dir if hour else None)
    gusts = current.gusts if current else (hour.gusts if hour else None)
    wind = t.wind_phrase(speed, direction, gusts) if speed is not None and speed >= 6 else ""
    felt = t.feels_like_note(temp, apparent)
    place = frame.in_place()
    opener = f"{place[:1].upper() + place[1:]} sind es gerade" if place else "Gerade sind es"
    parts = [f"{opener} {t.deg(temp)}"]
    if sky_text:
        parts.append(sky_text)
    if felt:
        parts.append(felt)
    if wind:
        parts.append(wind)
    first = ", ".join(parts)
    outlook = outlook_sentence(frame)
    detail = details_now(frame)
    return frame.finish(
        sentence_join(first, outlook),
        detail=detail,
        aspect="overview",
        data={"temperature": round(temp, 1), "code": code},
    )


def outlook_sentence(frame: Frame) -> str:
    """What changes in the next hours: rain starting or ending, a frost night, a warning-worthy gust."""
    now, pack = frame.now, frame.pack
    if raining_now(frame):
        period = next_wet_period(frame, now, 12)
        if period and period[1] is not None:
            return f"Der Regen soll {t.at_hour(period[1])} aufhören"
        return ""
    period = next_wet_period(frame, now + timedelta(minutes=15), 8)
    if period:
        kind = block_class(
            pack.hours_between(period[0] - timedelta(hours=1), period[0] + timedelta(hours=2))
        )
        word = {"schnee": "Schnee", "gewitter": "Gewitter", "schauer": "Schauer"}.get(kind, "Regen")
        return f"Ab etwa {t.at_quarter(period[0])} ist mit {word} zu rechnen"
    evening = pack.hours_between(now, now + timedelta(hours=10))
    lows = temperature_range(evening)
    if lows and lows[0] <= 0 and now.hour >= 15:
        return f"In der Nacht wird es frostig, bis {t.deg(lows[0])}"
    return ""


def details_now(frame: Frame) -> str:
    current, hour = frame.pack.current, frame.pack.hour_at(frame.now)
    bits = []
    humidity = (
        current.humidity
        if current and current.humidity is not None
        else (hour.humidity if hour else None)
    )
    if humidity is not None:
        bits.append(f"Die Luftfeuchtigkeit liegt bei {round(humidity)} Prozent")
    pressure = (
        current.pressure
        if current and current.pressure is not None
        else (hour.pressure if hour else None)
    )
    if pressure is not None:
        bits.append(f"der Luftdruck bei {g.number(round(pressure))} Hektopascal")
    if hour is not None and hour.visibility is not None and hour.visibility < 5000:
        bits.append(f"die Sicht beträgt etwa {int(round(hour.visibility, -1))} Meter")
    today = frame.pack.day(frame.now.date())
    if today and today.tmax is not None and today.tmin is not None:
        bits.append(f"heute zwischen {t.deg_n(today.tmin)} und {t.deg(today.tmax)}")
    if today and today.sunset:
        bits.append(f"die Sonne geht um {g.clock_digital(today.sunset)} unter")
    return g.sentence(", ".join(bits)) if bits else ""


# -- overview: a day ------------------------------------------------------------------------
def answer_today(frame: Frame) -> SkillResult:
    now, pack = frame.now, frame.pack
    today = now.date()
    day = pack.day(today)
    if day is None:
        return no_data(frame)
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    if now.hour >= 18:
        sections = day_sections(pack, today, now)
        night = pack.hours_between(
            now,
            datetime.combine(today + timedelta(days=1), datetime.min.time(), now.tzinfo)
            + timedelta(hours=7),
        )
        low = temperature_range(night)
        evening = t.sections_text(sections) or "ruhig"
        head = f"Heute Abend{in_place}: {evening}"
        if low:
            head += f", in der Nacht bis {t.deg(low[0])}"
        tomorrow = answer_day_text(frame, today + timedelta(days=1), brief=True)
        return frame.finish(
            sentence_join(head, tomorrow), detail=details_day(frame, today), aspect="overview"
        )
    sections = day_sections(pack, today, now)
    high = day.tmax
    parts = [f"Heute{in_place} bis {t.deg(high)}" if high is not None else f"Heute{in_place}"]
    if sections:
        parts.append(t.sections_text(sections))
    return frame.finish(
        sentence_join(", ".join(parts)),
        detail=details_day(frame, today),
        aspect="overview",
        data={"tmax": high},
    )


def answer_day_text(frame: Frame, day: date, *, brief: bool = False) -> str:
    pack = frame.pack
    point = pack.day(day)
    if point is None or point.tmax is None or point.tmin is None:
        return ""
    hours = day_hours(frame, day)
    kind = day_class(point, hours)
    char = CHAR.get(kind, kind)
    sections = day_sections(pack, day)
    head = head_day(day, frame.now.date())
    place = frame.in_place() if not brief else ""
    in_place = f" {place}" if place else ""
    if brief:
        return f"{head} {char} bei {t.temp_range(point.tmin, point.tmax)}"
    text = f"{head}{in_place} {verb(frame)} {char} bei {t.temp_range(point.tmin, point.tmax)}"
    kinds = {s.kind for s in sections}
    if len(sections) >= 2 and kinds != {"trocken"}:
        text += ". " + g.sentence(t.sections_text(sections))
    return text


def answer_day(frame: Frame, day: date | None = None) -> SkillResult:
    day = day or (
        frame.when.day if frame.when and frame.when.day else frame.now.date() + timedelta(days=1)
    )
    if frame.pack.day(day) is None:
        return out_of_range(frame, day)
    text = answer_day_text(frame, day)
    if not text:
        return no_data(frame)
    text = tendency_prefix(frame, day) + text if (day - frame.now.date()).days >= 7 else text
    return frame.finish(g.sentence(text), detail=details_day(frame, day), aspect="overview")


def tendency_prefix(frame: Frame, day: date) -> str:
    return "Als grobe Tendenz: "


def details_day(frame: Frame, day: date) -> str:
    point = frame.pack.day(day)
    if point is None:
        return ""
    bits = []
    if point.precipitation is not None:
        bits.append(
            "es bleibt trocken"
            if point.precipitation < 0.2
            else f"insgesamt etwa {t.liters(point.precipitation)} Niederschlag"
        )
    if point.precip_prob_max is not None and point.precipitation and point.precipitation >= 0.2:
        bits.append(f"Regenrisiko bis {t.round_prob(point.precip_prob_max)} Prozent")
    if point.wind_max is not None:
        bits.append(t.wind_phrase(point.wind_max, point.wind_dir, point.gusts_max))
    if point.sunshine_s is not None:
        hours = point.sunshine_s / 3600
        if hours >= 0.5:
            bits.append(f"etwa {g.number(round(hours))} Sonnenstunden")
    if point.uv_max is not None and point.uv_max >= 3:
        bits.append(f"UV-Index bis {round(point.uv_max)}")
    if point.sunrise and point.sunset:
        bits.append(
            f"Sonnenaufgang um {g.clock_digital(point.sunrise)}, Sonnenuntergang um {g.clock_digital(point.sunset)}"
        )
    return g.sentence(", ".join(b for b in bits if b)) if bits else ""


# -- overview: part of a day, hour --------------------------------------------------------------
def answer_daypart(frame: Frame) -> SkillResult:
    when = frame.when
    assert when is not None
    hours = frame.pack.hours_between(when.start, when.end)
    if not hours:
        return out_of_range(frame, when.start.date())
    kind = block_class(hours)
    rng = temperature_range(hours)
    label = when.label[:1].upper() + when.label[1:]
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    is_night = when.daypart == "nacht"
    if kind == "trocken":
        word = sky(hours)
        char = (
            f"{word} und {t.temp_word(rng[0] if is_night else rng[1])}"
            if rng and word
            else (word or "trocken")
        )
    else:
        char = {
            "regen": "regnerisch",
            "schauer": "wechselhaft mit Schauern",
            "schnee": "winterlich mit Schnee",
            "gewitter": "gewittrig",
            "glatt": "glatt",
            "nebel": "neblig",
        }[kind]
    temps = ""
    if rng:
        temps = f", bis {t.deg(rng[0])}" if is_night else f", {t.temp_range(*rng)}"
        if is_night and rng[0] <= 0:
            temps = f", Tiefstwert {t.deg(rng[0])}"
    extra = frost_hint(hours) if is_night or when.daypart == "früh" else ""
    gust = peak(hours, "gusts")
    if gust and gust.gusts and gust.gusts >= 60 and not extra:
        extra = f"Vorsicht, Böen bis {t.round5(gust.gusts)} Kilometer pro Stunde"
    text = f"{label}{in_place} {verb(frame)} {char}{temps}"
    return frame.finish(sentence_join(text, extra), detail=details_hours(hours), aspect="overview")


def frost_hint(hours: list[HourPoint]) -> str:
    low = temperature_range(hours)
    ground = [h.soil_temperature for h in hours if h.soil_temperature is not None]
    if any(hour_class(h) == "glatt" for h in hours):
        return "Achtung, Glätte durch gefrierenden Regen"
    if low and low[0] <= 0:
        return "Es gibt Frost"
    if low and low[0] <= 3 and ground and min(ground) <= 0:
        return "Bodenfrost ist möglich"
    return ""


def details_hours(hours: list[HourPoint]) -> str:
    bits = []
    rain = sum(h.precipitation for h in hours)
    bits.append("trocken" if rain < 0.2 else f"insgesamt etwa {t.liters(rain)}")
    top = peak(hours, "wind")
    if top and top.wind is not None:
        bits.append(
            t.wind_phrase(top.wind, top.wind_dir, max((h.gusts or 0) for h in hours) or None)
        )
    humidity = [h.humidity for h in hours if h.humidity is not None]
    if humidity:
        bits.append(f"Luftfeuchtigkeit um {round(mean(humidity))} Prozent")
    return g.sentence(", ".join(bits))


def answer_hour(frame: Frame) -> SkillResult:
    when = frame.when
    assert when is not None
    hour = frame.pack.hour_at(when.start)
    if hour is None:
        return out_of_range(frame, when.start.date())
    info = code_info(hour.code, hour.is_day)
    kind = hour_class(hour)
    word = sky([hour]) if kind == "trocken" else info["text"]
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    stamp = when.start
    if when.clock is not None:
        stamp_text = f"um {g.clock_digital(hour=when.clock.hour, minute=when.clock.minute)}"
    else:
        stamp_text = when.label
    if when.label.startswith(("morgen", "übermorgen", "am ")) and when.clock is not None:
        stamp_text = when.label
    risk = ""
    if hour.precip_prob is not None and hour.precip_prob >= 10:
        risk = f", Regenrisiko {t.round_prob(hour.precip_prob)} Prozent"
    sentence = (
        f"{stamp_text[:1].upper() + stamp_text[1:]}{in_place} sollen es {t.deg(hour.temperature)} sein, {word}{risk}"
        if hour.temperature is not None
        else ""
    )
    if not sentence:
        return no_data(frame)
    del stamp
    return frame.finish(g.sentence(sentence), detail=details_hours([hour]), aspect="overview")


# -- overview: weekend, week, several days ---------------------------------------------------
def answer_days(frame: Frame, first: date, last: date, *, label: str) -> SkillResult:
    pack = frame.pack
    days = pack.days_between(first, last)
    if not days:
        return out_of_range(frame, first)
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    pieces = []
    for point in days:
        kind = day_class(point, day_hours(frame, point.day))
        char = CHAR.get(kind, kind)
        if point.tmax is None:
            continue
        if kind in {"regen", "schauer", "gewitter", "schnee"} and point.tmax is not None:
            pieces.append(f"{t.weekday(point.day)} {char} bei höchstens {t.deg(point.tmax)}")
        else:
            pieces.append(f"{t.weekday(point.day)} {char} bis {t.deg(point.tmax)}")
    if not pieces:
        return no_data(frame)
    text = f"{label[:1].upper() + label[1:]}{in_place}: " + ", ".join(pieces)
    bits = [details_day(frame, p.day) for p in days]
    return frame.finish(g.sentence(text), detail=" ".join(b for b in bits if b), aspect="overview")


def answer_weekend(frame: Frame) -> SkillResult:
    when = frame.when
    assert when is not None
    first, last = when.start.date(), (when.end - timedelta(seconds=1)).date()
    today = frame.now.date()
    if first < today:
        first = today
    if first == last == today and frame.now.hour >= 17 and last.weekday() == 6:
        first = last = today + timedelta(days=6)  # Sunday evening: next Saturday
        first, last = first, first + timedelta(days=1)
        return answer_days(frame, first, last, label="am nächsten Wochenende")
    return answer_days(frame, first, last, label=when.label)


def answer_week(frame: Frame) -> SkillResult:
    when = frame.when
    assert when is not None
    pack = frame.pack
    first = max(when.start.date(), frame.now.date())
    last = min((when.end - timedelta(seconds=1)).date(), pack.last_day or first)
    label = when.label
    if when.label == "diese Woche" and (last - first).days < 4:
        last = min(first + timedelta(days=5), pack.last_day or first)  # the rest of a week is short
        label = "in den nächsten Tagen"
    runs = week_trend(pack, first, last)
    if not runs:
        return out_of_range(frame, first)
    if len(runs) > 3:
        head, rest = runs[:2], runs[2:]
        merged_high = max(r[3] for r in rest)
        runs = [*head, ("wechselhaft", rest[0][1], rest[-1][2], merged_high)]
    place = frame.in_place()
    in_place = f" {place}" if place else ""
    pieces = []
    for index, (kind, start, end, high) in enumerate(runs):
        char = CHAR.get(kind, kind)
        if index == 0:
            span = (
                "Bis " + t.weekday(end)
                if end > first
                else g.day_label(first, frame.now.date(), capital=True)
            )
        else:
            span = (
                "ab " + t.weekday(start)
                if index < len(runs) - 1 or end > start
                else "am " + t.weekday(start)
            )
        phrase = f"{char} bis {t.deg(high)}" if high > -90 else char
        pieces.append(f"{span} {phrase}")
    text = f"{label[:1].upper() + label[1:]}{in_place}: " + ", ".join(pieces)
    if (last - frame.now.date()).days >= 6:
        text += ". Ab dem siebten Tag ist das nur eine Tendenz"
    return frame.finish(g.sentence(text), detail=details_day(frame, first), aspect="overview")


# -- errors and limits ---------------------------------------------------------------------------
def no_data(frame: Frame) -> SkillResult:
    return SkillResult(text="Dazu habe ich gerade keine Wetterdaten.", serious=True)


def out_of_range(frame: Frame, day: date) -> SkillResult:
    pack = frame.pack
    last = pack.last_day
    first = pack.first_day
    if first and day < first:
        return SkillResult(
            text="So weit zurück habe ich keine Wetterdaten, nur die letzten drei Tage.",
            serious=True,
        )
    days = (last - frame.now.date()).days + 1 if last else 0
    return SkillResult(
        text=(
            "So weit im Voraus gibt es keine verlässliche Vorhersage – "
            f"höchstens {days} Tage, und ab etwa einer Woche nur als grobe Tendenz."
        ),
        serious=True,
    )


def day_point(frame: Frame, day: date) -> DayPoint | None:
    return frame.pack.day(day)


def worst_class(hours: list[HourPoint]) -> str:
    return worst([hour_class(h) for h in hours])

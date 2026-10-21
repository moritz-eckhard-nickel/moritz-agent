# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Spoken German for warnings, pollen and air quality (docs/plan/13 §6.6, §6.7, §7.6)."""

from __future__ import annotations

from datetime import datetime

from moritz_agent.skills.providers.brightsky import Warning
from moritz_agent.skills.providers.dwd import PollenForecast, level_word
from moritz_agent.skills.render import german as g

_ADJECTIVE_ENDINGS = ("es", "er", "e")
_LEVEL_PHRASE = {
    1: "eine Wetterwarnung vor {event}",
    2: "eine Warnung vor markantem Wetter: {event}",
    3: "eine Unwetterwarnung vor {event}",
    4: "eine Warnung vor extremem Unwetter: {event}",
}
POLLEN_NAMES = {
    "Hasel": "Haselpollen",
    "Erle": "Erlenpollen",
    "Esche": "Eschenpollen",
    "Birke": "Birkenpollen",
    "Gräser": "Gräserpollen",
    "Roggen": "Roggenpollen",
    "Beifuß": "Beifußpollen",
    "Ambrosia": "Ambrosiapollen",
}
POLLEN_ASKED = {
    "hasel": "Hasel",
    "erle": "Erle",
    "esche": "Esche",
    "birke": "Birke",
    "birken": "Birke",
    "gräser": "Gräser",
    "gras": "Gräser",
    "roggen": "Roggen",
    "beifuß": "Beifuß",
    "beifuss": "Beifuß",
    "ambrosia": "Ambrosia",
}
DAY_KEYS = ("today", "tomorrow", "dayafter_to")


# -- warnings ------------------------------------------------------------------------------------
def event_dative(event: str) -> str:
    """ "Starker schneefall" → "starkem Schneefall", "Sturmböen" stays (after "vor")."""
    words = event.replace("-", "-").split()
    if len(words) < 2:
        return event
    noun = words[-1].lower()
    plural = noun.endswith("n") and not noun.endswith(("ung", "ing"))
    out = []
    for word in words[:-1]:
        low = word.lower()
        if (low.endswith(("es", "er")) and not low.endswith("ger")) or low.endswith("er"):
            out.append(low[:-2] + "em")
        elif low.endswith("e"):
            out.append(low + ("n" if plural else "r"))
        else:
            out.append(low)
    out.append(words[-1][:1].upper() + words[-1][1:].lower())
    return " ".join(out)


def day_time(moment: datetime, now: datetime) -> str:
    """ "heute 22 Uhr", "morgen 6 Uhr", "am Dienstag 6 Uhr"."""
    clock = g.clock_digital(moment)
    return f"{g.day_label(moment.date(), now.date())} {clock}"


def validity(warning: Warning, now: datetime) -> str:
    """ "bis heute 22 Uhr" / "ab morgen 6 Uhr bis morgen 12 Uhr"."""
    end = f" bis {day_time(warning.end, now)}" if warning.end else ""
    if warning.start <= now:
        return f"bis {day_time(warning.end, now)}" if warning.end else "bis auf Weiteres"
    return f"ab {day_time(warning.start, now)}{end}"


def warning_phrase(warning: Warning, now: datetime) -> str:
    event = event_dative(warning.event) if warning.event else "Wetter"
    phrase = _LEVEL_PHRASE.get(warning.level, _LEVEL_PHRASE[1]).format(event=event)
    return f"{validity(warning, now)} {phrase}"


def warnings_text(place_name: str, warnings: list[Warning], now: datetime) -> str:
    """Up to three warnings, the most severe first."""
    active = [w for w in warnings if w.end is None or w.end > now]
    if not active:
        return f"Nein, für {place_name} gibt es gerade keine Wetterwarnung."
    first, rest = active[0], active[1:3]
    text = f"Ja, für {place_name} gilt {warning_phrase(first, now)}"
    if rest:
        text += ". Außerdem " + g.join_and([f"gilt {warning_phrase(w, now)}" for w in rest])
    if len(active) > 3:
        text += f". Insgesamt sind es {len(active)} Warnungen"
    return g.sentence(text)


def warning_detail(warnings: list[Warning]) -> str | None:
    """What the DWD writes about the most severe warning, shortened (never read out unasked)."""
    if not warnings:
        return None
    top = warnings[0]
    parts = [top.description, top.instruction]
    text = " ".join(p for p in parts if p)
    return text or None


# -- pollen ----------------------------------------------------------------------------------------
def pollen_text(
    forecast: PollenForecast,
    day: str,
    *,
    asked: list[str] | None = None,
    label: str = "heute",
    only: list[str] | None = None,
    region: str = "",
) -> str:
    levels = forecast.days.get(day, {})
    region = region.replace("Bay. Wald", "Bayerischer Wald").replace("/", ", ")
    lead = f"Für {region}: " if region else ""
    if asked:
        pieces = [f"{POLLEN_NAMES[name]} {level_word(levels.get(name, 0.0))}" for name in asked]
        return g.sentence(f"{lead}{label.capitalize()} {g.join_and(pieces)}")
    shown = {k: v for k, v in levels.items() if v >= 1.0 and (not only or k in only)}
    if not shown:
        return g.sentence(f"{lead}{label.capitalize()} ist kaum Pollenflug")
    ranked = sorted(shown.items(), key=lambda item: -item[1])
    pieces = [f"{POLLEN_NAMES[name]} {level_word(level)}" for name, level in ranked[:4]]
    verb = "fliegen"
    others = "" if len(ranked) >= len(levels) else ", alles andere kaum"
    return g.sentence(f"{lead}{label.capitalize()} {verb} {g.join_and(pieces)}{others}")


# -- air ---------------------------------------------------------------------------------------------
AIR_WORDS = ((20, "sehr gut"), (40, "gut"), (60, "mäßig"), (80, "schlecht"), (100, "sehr schlecht"))


def air_word(index: float) -> str:
    for limit, word in AIR_WORDS:
        if index < limit:
            return word
    return "extrem schlecht"


def ozone_word(value: float) -> str:
    """EU information threshold 180 µg/m³; below 120 the air is fine."""
    if value < 120:
        return "unproblematisch"
    if value < 180:
        return "erhöht"
    if value < 240:
        return "hoch"
    return "sehr hoch"

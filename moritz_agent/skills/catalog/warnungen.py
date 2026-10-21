# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Warnings, pollen and air quality (docs/plan/13 §6.6, §6.7).

DWD warnings come from Bright Sky, civil-protection messages from NINA, pollen from the DWD pollen
index and air quality from Open-Meteo (CAMS) – all free, all open (docs/plan/13 §7.1).
"""

from __future__ import annotations

import re

from moritz_agent.skills.base import Request, SkillResult, Source
from moritz_agent.skills.catalog.common import briefing_part
from moritz_agent.skills.providers import Providers, ProviderUnavailable
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.router import followup_state
from moritz_agent.skills.slots.when import find_when
from moritz_agent.skills.slots.where import home_place
from moritz_agent.skills.weather import health as h
from moritz_agent.skills.weather.frame import (
    SOURCES,
    Resolved,
    resolve,
    unavailable,
    when_text,
)

GROUP = "warnungen"
DWD_SOURCE = Source("Deutscher Wetterdienst über Bright Sky", "https://brightsky.dev/", "CC BY 4.0")
NINA_SOURCE = Source("NINA (Bundesamt für Bevölkerungsschutz)", "https://warnung.bund.de/", "")
POLLEN_SOURCE = Source(
    "Deutscher Wetterdienst, Pollenflug-Gefahrenindex", "https://www.dwd.de/", "CC BY 4.0"
)
AIR_SOURCE = Source("Open-Meteo Luftqualität (CAMS)", "https://open-meteo.com/", "CC BY 4.0")

_CIVIL = r"katastroph\w*|bevölkerungs\w*|\bnina\b|katwarn|mowas|zivilschutz"


_KREIS_WARN = r"warn\w*.*\b(?:landkreis|kreis)\b|\b(?:landkreis|kreis)\b.*warn\w*"


def _line(*alternatives: str) -> str:
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


def _providers(req: Request) -> Providers | None:
    providers = req.svc.providers
    return providers if isinstance(providers, Providers) else None


# -- DWD warnings --------------------------------------------------------------------------------------
async def _warn_weather(req: Request) -> SkillResult | None:
    if not req.svc.cfg.warnings.enabled or "dwd" not in req.svc.cfg.warnings.sources:
        return SkillResult(text="Wetterwarnungen sind bei mir gerade ausgeschaltet.", serious=True)
    resolved = await resolve(req, "warn.weather", parse_when=False)
    if not isinstance(resolved, Resolved):
        return resolved
    place = resolved.place
    if not place.domestic:
        return SkillResult(text="Amtliche Warnungen habe ich nur für Deutschland.", serious=True)
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("alerts", "offline"), "Warnungen")
    try:
        fetched = await providers.alerts(place)
    except ProviderUnavailable as exc:
        return unavailable(exc, "Warnungen")
    now = resolved.now
    text = h.warnings_text(place.spoken, fetched.data, now)
    active = [w for w in fetched.data if w.end is None or w.end > now]
    detail = h.warning_detail(active)
    sources = [DWD_SOURCE]
    civil_text = ""
    is_home = (place.lat, place.lon) == (
        home_place(req.svc, req.ctx).lat,
        home_place(req.svc, req.ctx).lon,
    )
    if is_home and "nina" in req.svc.cfg.warnings.sources and req.svc.cfg.warnings.nina_ars:
        try:
            civil = (await providers.civil_warnings()).data
        except ProviderUnavailable:
            civil = []
        if civil:
            civil_text = f"Außerdem gibt es eine Meldung des Bevölkerungsschutzes: {civil[0].title}"
            sources.append(NINA_SOURCE)
    stale = ""
    if fetched.cache == "stale":
        stale = (
            "Ich komme gerade nicht an neue Warnungen. Stand von vor "
            + g.plural(max(1, round(fetched.age_s / 60)), "Minute", "Minuten")
            + ": "
        )
        text = text[:1].lower() + text[1:]
    full = stale + (text if not civil_text else f"{text} {g.sentence(civil_text)}")
    return SkillResult(
        text=full,
        detail=detail,
        sources=tuple(sources),
        followup=followup_state("warn.weather", where=resolved.where),
        serious=bool(active),
        data={"warnings": len(active), "max_level": max((w.level for w in active), default=0)},
    )


skill(
    "warn.weather",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    help="Wetterwarnungen",
    examples=("Gibt es Unwetterwarnungen?", "Gibt's Warnungen für Weilburg?"),
    patterns=(
        (
            _line(
                r"unwetter\w*",
                r"wetterwarnung\w*",
                r"warnung\w*",
                r"(?:sturm|hitze|frost|gewitter|hochwasser|orkan)warnung\w*",
                r"warnt",
                r"gewarnt",
                r"unwetterwarnung\w*",
            ),
            1.0,
        ),
    ),
    exclude=(_CIVIL, _KREIS_WARN, r"\bwas soll ich\b", r"\bwas genau\b"),
)(_warn_weather)


async def _warn_detail(req: Request) -> SkillResult | None:
    last = req.ctx.last
    if last is None or last.skill_id not in {"warn.weather", "warn.civil"}:
        return None
    if not req.ctx.last_detail:
        return SkillResult(text="Mehr hat der Deutsche Wetterdienst dazu nicht geschrieben.")
    detail, req.ctx.last_detail = req.ctx.last_detail, None
    return SkillResult(text=detail, serious=True)


skill(
    "warn.weather_detail",
    group=GROUP,
    online=True,  # needs the warning that was just read out
    priority="S",
    max_words=8,
    patterns=(
        (r"^(?:.*\s)?was soll ich (?:da |dann |jetzt )?(?:tun|machen)\b.*$", 1.0),
        (r"^(?:.*\s)?was (?:genau|steht da|bedeutet (?:das|die warnung))\b.*$", 0.95),
        (r"^(?:.*\s)?was heißt das\b.*$", 0.95),
    ),
    examples=("Was soll ich tun?",),
)(_warn_detail)


# -- NINA ---------------------------------------------------------------------------------------------------
async def _warn_civil(req: Request) -> SkillResult | None:
    cfg = req.svc.cfg.warnings
    if not cfg.enabled or not cfg.nina_ars or "nina" not in cfg.sources:
        return SkillResult(
            text="Meldungen des Bevölkerungsschutzes sind bei mir ausgeschaltet.", serious=True
        )
    providers = _providers(req)
    if providers is None:
        return unavailable(
            ProviderUnavailable("nina", "offline"), "Meldungen des Bevölkerungsschutzes"
        )
    try:
        fetched = await providers.civil_warnings()
    except ProviderUnavailable as exc:
        return unavailable(exc, "Meldungen des Bevölkerungsschutzes")
    items = fetched.data
    place = home_place(req.svc, req.ctx)
    if not items:
        text = f"Nein, für den Kreis {place.district or place.spoken} liegt gerade keine Meldung des Bevölkerungsschutzes vor."
        return SkillResult(
            text=text, sources=(NINA_SOURCE,), followup=followup_state("warn.civil", where=None)
        )
    lines = [f"{w.title}" for w in items[:2]]
    count = "eine Meldung" if len(items) == 1 else f"{len(items)} Meldungen"
    text = f"Ja, es gibt {count} für den Kreis: " + "; ".join(lines)
    return SkillResult(
        text=g.sentence(text),
        sources=(NINA_SOURCE,),
        serious=True,
        followup=followup_state("warn.civil", where=None),
        data={"messages": len(items)},
    )


skill(
    "warn.civil",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    examples=(
        "Gibt es Warnungen im Landkreis?",
        "Gibt es eine Katastrophenwarnung?",
        "Ist was mit Hochwasser?",
    ),
    patterns=(
        (rf"^(?:.*\s)?(?:{_CIVIL})(?:\s.*)?$", 1.05),
        (rf"^(?:.*\s)?(?:{_KREIS_WARN})(?:\s.*)?$", 1.1),
    ),
    exclude=(r"\bwetter\b", r"\bwie hoch ist die lahn\b", r"\bpegel\b", r"\bwasserstand\b"),
)(_warn_civil)


# -- greeting hint ---------------------------------------------------------------------------------------------
_THRESHOLD = {"moderate": 2, "severe": 3, "extreme": 4}


async def greeting_hint(svc, ctx=None) -> str | None:
    """One sentence for the start of a call when a serious warning is in force (cache only)."""
    cfg = svc.cfg.warnings
    providers = svc.providers
    if cfg.announce_on_greeting == "off" or not cfg.enabled or not isinstance(providers, Providers):
        return None
    home = home_place(svc, ctx)
    warnings = providers.cached_alerts(home)
    if not warnings:
        return None
    now = svc.clock.now(home.tz or svc.timezone)
    serious = [
        w
        for w in warnings
        if w.level >= _THRESHOLD[cfg.announce_on_greeting] and (w.end is None or w.end > now)
    ]
    if not serious:
        return None
    top = serious[0]
    return g.sentence(f"Übrigens: Für {home.spoken} gilt {h.warning_phrase(top, now)}")


# -- pollen -------------------------------------------------------------------------------------------------------
async def _pollen(req: Request) -> SkillResult | None:
    cfg = req.svc.cfg.pollen
    if not cfg.enabled:
        return SkillResult(text="Pollenauskünfte sind bei mir ausgeschaltet.", serious=True)
    resolved = await resolve(req, "pollen.today", parse_when=False)
    if not isinstance(resolved, Resolved):
        return resolved
    place = resolved.place
    if not place.domestic:
        return SkillResult(text="Den Pollenflug kann ich nur für Deutschland sagen.", serious=True)
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("pollen", "offline"), "Pollendaten")
    try:
        fetched = await providers.pollen(place)
    except ProviderUnavailable as exc:
        if exc.reason == "empty":
            return SkillResult(text=f"Für {place.spoken} habe ich keine Pollendaten.", serious=True)
        return unavailable(exc, "Pollendaten")
    today = resolved.now.date()
    day, label = today, "heute"
    when = req.overrides.get("when") or find_when(when_text(req.text), resolved.now)
    if when is not None and when.day is not None:
        delta = (when.day - today).days
        if delta < 0 or delta > 2:
            return SkillResult(
                text="Den Pollenflug gibt der Deutsche Wetterdienst nur für heute und die nächsten zwei Tage an.",
                serious=True,
            )
        day = when.day
        label = ("heute", "morgen", "übermorgen")[delta]
    # the day keys of the file count from its issue date, not from today
    day_key = fetched.data.day_key(day, today)
    if day_key is None:
        return SkillResult(
            text=g.sentence(
                f"Für {label} hat der Deutsche Wetterdienst noch keine Pollenvorhersage"
            ),
            detail=f"Stand der Pollendaten: {fetched.data.last_update}.",
            sources=(POLLEN_SOURCE,),
            serious=True,
        )
    asked_names = [
        name
        for name in h.POLLEN_NAMES
        if any(
            re.search(rf"\b{word}\w*\b", req.text)
            for word, n in h.POLLEN_ASKED.items()
            if n == name
        )
    ]
    wanted = {a.lower() for a in cfg.allergens}
    only = [
        n for n in h.POLLEN_NAMES if n.lower() in wanted or n.lower().replace("ß", "ss") in wanted
    ]
    region = "" if resolved.where.kind == "home" else fetched.data.partregion
    text = h.pollen_text(
        fetched.data,
        day_key,
        asked=asked_names or None,
        label=label,
        only=only or None,
        region=region,
    )
    detail = (
        f"Das ist der Pollenflug-Gefahrenindex des Deutschen Wetterdienstes für {fetched.data.partregion}, "
        f"Stand {fetched.data.last_update}."
    )
    return SkillResult(
        text=text,
        detail=detail,
        sources=(POLLEN_SOURCE,),
        followup=followup_state("pollen.today", where=resolved.where, when=when),
        data={"region": fetched.data.partregion},
    )


def _pollen_followup(rest, ctx, svc, last):
    when = find_when(when_text(rest), svc.now())
    if when is None or not re.search(r"\b(?:heute|morgen|übermorgen)\b", rest):
        return None
    return {"when": when}


skill(
    "pollen.today",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    help="den Pollenflug",
    followup=_pollen_followup,
    examples=("Wie ist der Pollenflug?", "Fliegen heute Pollen?", "Wie sieht's mit Birke aus?"),
    patterns=(
        (_line(r"pollen\w*", r"heuschnupfen", r"allergie\w*"), 1.0),
        (
            r"^(?:.*\s)?wie (?:sieht|schaut) es mit (?:birke|gräsern|gräser|hasel|erle|esche|roggen|beifuß|ambrosia)\b.*$",
            1.0,
        ),
    ),
)(_pollen)

skill(
    "pollen.forecast",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    followup=_pollen_followup,
    examples=("Wie wird der Pollenflug morgen?",),
    patterns=((r"^(?:.*\s)?pollen\w*\b.*\b(?:morgen|übermorgen)\b.*$", 1.05),),
)(_pollen)


# -- air quality ---------------------------------------------------------------------------------------------------
async def _air(req: Request) -> SkillResult | None:
    if not req.svc.cfg.air.enabled:
        return SkillResult(text="Luftqualitätsauskünfte sind bei mir ausgeschaltet.", serious=True)
    resolved = await resolve(req, "air.quality", parse_when=False)
    if not isinstance(resolved, Resolved):
        return resolved
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("air", "offline"), "Luftdaten")
    try:
        fetched = await providers.air_quality(resolved.place)
    except ProviderUnavailable as exc:
        return unavailable(exc, "Luftdaten")
    air = fetched.data
    place = resolved.place
    in_place = "" if resolved.where.kind == "home" else f" in {place.spoken}"
    ozone_asked = bool(re.search(r"\bozon\w*\b", req.text))
    if ozone_asked:
        value = air.ozone_peak if air.ozone_peak is not None else air.ozone
        if value is None:
            return SkillResult(text="Den Ozonwert habe ich gerade nicht.", serious=True)
        if air.ozone_peak_time is not None:
            text = (
                f"Ozon{in_place} erreicht heute gegen {air.ozone_peak_time.hour} Uhr bis zu "
                f"{round(value)} Mikrogramm pro Kubikmeter, das ist {h.ozone_word(value)}"
            )
        else:
            text = (
                f"Ozon{in_place} liegt bei {round(value)} Mikrogramm pro Kubikmeter, "
                f"das ist {h.ozone_word(value)}"
            )
        return SkillResult(
            text=g.sentence(text), sources=(AIR_SOURCE,), data={"ozone": round(value)}
        )
    if air.aqi is None:
        return SkillResult(text="Die Luftqualität habe ich gerade nicht.", serious=True)
    word = h.air_word(air.aqi)
    text = f"Die Luftqualität{in_place} ist {word}, europäischer Index {round(air.aqi)}"
    if air.aqi >= 40:
        bits = []
        if air.pm10 is not None and air.pm10 >= 40:
            bits.append(f"Feinstaub PM10 {round(air.pm10)}")
        if air.ozone is not None and air.ozone >= 120:
            bits.append(f"Ozon {round(air.ozone)}")
        if bits:
            text += ", vor allem " + g.join_and(bits) + " Mikrogramm pro Kubikmeter"
    return SkillResult(
        text=g.sentence(text),
        detail=(
            f"Feinstaub PM10 {round(air.pm10)}, PM2,5 {round(air.pm25)} und Ozon {round(air.ozone)} "
            "Mikrogramm pro Kubikmeter."
            if None not in (air.pm10, air.pm25, air.ozone)
            else None
        ),
        sources=(AIR_SOURCE,),
        followup=followup_state("air.quality", where=resolved.where),
        data={"aqi": air.aqi},
    )


skill(
    "air.quality",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    examples=("Wie ist die Luftqualität?", "Wie ist die Luft?", "Wie ist der Feinstaub?"),
    patterns=(
        (
            _line(
                r"luftqualität",
                r"feinstaub\w*",
                r"luftverschmutzung",
                r"luftgüte",
                r"wie ist die luft",
                r"wie sauber ist die luft",
            ),
            1.0,
        ),
    ),
)(_air)

skill(
    "air.ozone",
    group=GROUP,
    online=True,
    priority="K",
    max_words=10,
    examples=("Wie hoch ist das Ozon?",),
    patterns=((_line(r"ozon\w*"), 1.05),),
)(_air)


# -- morning overview ----------------------------------------------------------------------------------------------------
@briefing_part(35)
async def _briefing_warning(req: Request) -> str | None:
    hint = await greeting_hint(req.svc, req.ctx)
    return hint.removeprefix("Übrigens: ") if hint else None


__all__ = ["SOURCES", "greeting_hint"]

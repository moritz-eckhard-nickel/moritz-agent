# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Weather skills (docs/plan/13 §6.4, §6.5): overview, single aspects, comparisons, region.

All of them answer from one weather pack per place. The overview skills share one set of patterns
and decline unless the time expression fits their kind (now, today, day part, day, weekend, week,
hour, further ahead, past) – the router then tries the next candidate.
"""

from __future__ import annotations

import re
from typing import Any

from moritz_agent.skills.base import FollowupState, Request, Services, SkillContext, SkillResult
from moritz_agent.skills.catalog.common import briefing_part
from moritz_agent.skills.registry import skill
from moritz_agent.skills.slots.when import When, find_when
from moritz_agent.skills.slots.where import find_places
from moritz_agent.skills.weather import answers as a
from moritz_agent.skills.weather import aspects as s
from moritz_agent.skills.weather import special as sp
from moritz_agent.skills.weather.frame import Frame, make_frame, when_text

GROUP = "wetter"


def _line(*alternatives: str) -> str:
    """Pattern that covers the whole sentence (full coverage in the router score)."""
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


_NOT_WEATHER = (
    r"\bmir egal\b",
    r"\bist mir (?:wurst|schnuppe|piepe)\b",
    r"\bwar\b.*\b(?:urlaub|ferien|reise|hochzeit|konzert|geburtstag|wandern|wanderung)\b",
    r"\b(?:fahrenheit|celsius|kelvin)\b",
    r"\b(?:wetterfest|wetterhahn|wettbewerb)\b",
)
_TIME_WORDS = (
    r"heute|morgen|übermorgen|gestern|vorgestern|jetzt|gerade|abend|nacht|früh|mittag|nachmittag|"
    r"vormittag|wochenende|woche|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
    r"weihnachten|silvester|ostern"
)
_WETTER = _line(r"wetter", r"wettervorhersage", r"wetterbericht", r"wettervorschau", r"vorhersage")
_HOW_IS_IT = rf"^wie (?:wird|ist|war|sieht) (?:es|der tag|alles)(?: so)? (?:\w+ )*?(?:{_TIME_WORDS}|draußen|aus)\b.*$"
_HOW_PERIOD = (
    r"^wie (?:wird|ist|sieht) (?:die|der|das) (?:\w+ )?"
    r"(?:woche|tage|tag|wochenende|abend|nacht|morgen|nachmittag|vormittag)\b.*$"
)
_HOW_PLACE = r"^wie (?:wird|ist|war) (?:es|der tag) (?:in|bei|für) \w.*$"
OVERVIEW_PATTERNS = (
    (_WETTER, 0.95),
    (_HOW_IS_IT, 0.85),
    (_HOW_PERIOD, 0.85),
    (_HOW_PLACE, 0.85),
    (r"^wie ist es draußen$", 0.9),
)


# -- time domains of the overview skills -----------------------------------------------------------
def domain_of(when: When | None, today) -> str:
    """now | hour | daypart | today | day | weekend | week | far | past."""
    if when is None or when.granularity == "now":
        return "now"
    if when.day is not None and when.day < today:
        return "past"
    if when.granularity in {"month", "year"}:
        return "far"
    if when.granularity == "hour":
        return "hour"
    if when.granularity == "daypart":
        return "daypart"
    if when.granularity == "weekend":
        return "weekend"
    if when.granularity in {"week", "days"}:
        return "week"
    if when.granularity == "day" and when.day is not None:
        delta = (when.day - today).days
        return "today" if delta == 0 else "far" if delta >= 10 else "day"
    return "day"


def _domain(req: Request) -> str:
    when: When | None
    if "when" in req.overrides:
        when = req.overrides["when"]
    else:
        when = find_when(when_text(req.text), req.now)
    return domain_of(when, req.now.date())


async def _overview(req: Request, skill_id: str, domains: set[str]) -> SkillResult | None:
    if _domain(req) not in domains:
        return None
    if (
        re.search(r"\b(?:region|landkreis|umkreis|gegend)\b", req.text)
        and "where" not in req.overrides
    ) and any(w.kind == "region" for w in find_places(req.text, req.svc, req.ctx)):
        return None  # weather.region
    frame = await make_frame(req, skill_id)
    if not isinstance(frame, Frame):
        return frame
    return _run_overview(frame)


def _run_overview(frame: Frame) -> SkillResult:
    domain = domain_of(frame.when, frame.now.date())
    match domain:
        case "now":
            return a.answer_now(frame)
        case "today":
            return a.answer_today(frame)
        case "daypart":
            return a.answer_daypart(frame)
        case "hour":
            return a.answer_hour(frame)
        case "weekend":
            return a.answer_weekend(frame)
        case "week":
            return a.answer_week(frame)
        case "past":
            return sp.answer_yesterday(frame)
        case _:
            return a.answer_day(frame)


# -- follow-ups ("Und morgen?", "Und in Limburg?", "Und der Wind?") --------------------------------
_ASPECT_SKILLS = (
    (r"\b(?:wind|windig|böen|sturm|stürmisch)\b", "weather.wind"),
    (r"\b(?:regen|regnet|regnen|niederschlag|nass|schauer)\b", "weather.rain"),
    (r"\bschirm\b", "weather.umbrella"),
    (r"\b(?:temperatur|warm|kalt|grad|heiß|kühl)\b", "weather.temperature"),
    (r"\bgewitter\b", "weather.thunder"),
    (r"\b(?:schnee|schneit|schneien)\b", "weather.snow"),
    (r"\b(?:frost|glatt|glatteis|kratzen)\b", "weather.frost"),
    (r"\b(?:uv|sonnencreme|sonnenbrand)\b", "weather.uv"),
    (r"\b(?:luftfeuchtigkeit|schwül)\b", "weather.humidity"),
    (r"\bluftdruck\b", "weather.pressure"),
    (r"\b(?:nebel|neblig|sicht)\b", "weather.fog"),
    (r"\b(?:sonne|sonnenstunden|sonnig)\b", "weather.sunshine"),
    (r"\bgefühlt\b", "weather.feels_like"),
)
_OVERVIEW_BY_DOMAIN = {
    "now": "weather.now",
    "today": "weather.today",
    "daypart": "weather.daypart",
    "day": "weather.day",
    "far": "weather.long_range",
    "weekend": "weather.weekend",
    "week": "weather.week",
    "hour": "weather.hour",
    "past": "weather.yesterday",
}
_OVERVIEW_IDS = set(_OVERVIEW_BY_DOMAIN.values())


def weather_followup(
    rest: str, ctx: SkillContext, svc: Services, last: FollowupState
) -> dict[str, Any] | None:
    if re.match(
        r"^(?:wie|wird|ist|gibt|brauch\w*|regnet|schneit|kann|muss|scheint|soll|hat|haben|sind)\b",
        rest,
    ):
        return None  # a full question: it carries its own place and time
    if re.search(r"\bwetter\b", rest):
        return None
    params: dict[str, Any] = {}
    target = last.skill_id
    aspect_skill = next((sid for pattern, sid in _ASPECT_SKILLS if re.search(pattern, rest)), None)
    places = find_places(rest, svc, ctx)
    if places:
        params["where"] = places[0]
    when = find_when(when_text(rest), svc.now())
    if when is not None and re.search(rf"\b(?:{_TIME_WORDS}|uhr|am|um|in)\b", rest):
        params["when"] = when
        if target in _OVERVIEW_IDS and aspect_skill is None:
            target = _OVERVIEW_BY_DOMAIN.get(domain_of(when, svc.now().date()), target)
    if aspect_skill is not None:
        target = aspect_skill
        params.setdefault("aspect", aspect_skill)
    if not params:
        return None
    if (
        aspect_skill is None
        and target in _OVERVIEW_IDS
        and "where" in params
        and "when" not in params
    ):
        previous = last.params.get("when")
        target = _OVERVIEW_BY_DOMAIN.get(domain_of(previous, svc.now().date()), "weather.now")
    params["skill"] = target
    return params


# -- overview skills ---------------------------------------------------------------------------------
def _overview_skill(skill_id: str, domains: set[str], **kwargs):
    return skill(
        skill_id,
        group=GROUP,
        online=True,
        max_words=14,
        patterns=OVERVIEW_PATTERNS,
        exclude=_NOT_WEATHER,
        followup=weather_followup,
        **kwargs,
    )


@_overview_skill(
    "weather.now",
    {"now"},
    priority="M",
    help="das Wetter",
    examples=(
        "Wie ist das Wetter?",
        "Wie isses Wedder drauße?",
        "Wie ist das Wetter in Berlin?",
        "Wetter in 60311",
    ),
)
async def weather_now(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.now", {"now"})


@_overview_skill(
    "weather.today",
    {"today"},
    priority="M",
    examples=("Wie wird das Wetter heute?", "Wie werd's heit?"),
)
async def weather_today(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.today", {"today"})


@_overview_skill(
    "weather.daypart",
    {"daypart"},
    priority="M",
    examples=("Wie wird es heute Abend?", "Wie ist das Wetter morgen früh?"),
)
async def weather_daypart(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.daypart", {"daypart"})


@_overview_skill(
    "weather.day",
    {"day"},
    priority="M",
    examples=("Wie wird das Wetter morgen?", "Wetter am Samstag", "Wie wird's übermorgen?"),
)
async def weather_day(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.day", {"day"})


@_overview_skill(
    "weather.weekend",
    {"weekend"},
    priority="M",
    examples=("Wie wird das Wetter am Wochenende?",),
)
async def weather_weekend(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.weekend", {"weekend"})


@_overview_skill(
    "weather.week",
    {"week"},
    priority="M",
    examples=("Wie wird die Woche?", "Wetter für die nächsten Tage"),
)
async def weather_week(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.week", {"week"})


@_overview_skill(
    "weather.hour",
    {"hour"},
    priority="M",
    examples=("Wie ist das Wetter um 15 Uhr?", "Wie wird es in zwei Stunden?"),
)
async def weather_hour(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.hour", {"hour"})


@_overview_skill(
    "weather.long_range",
    {"far"},
    priority="S",
    examples=("Wie wird das Wetter in zwei Wochen?", "Wird es an Weihnachten schneien?"),
)
async def weather_long_range(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.long_range", {"far"})


@_overview_skill(
    "weather.yesterday",
    {"past"},
    priority="S",
    examples=("Wie war das Wetter gestern?", "Wie viel hat es gestern geregnet?"),
)
async def weather_yesterday(req: Request) -> SkillResult | None:
    return await _overview(req, "weather.yesterday", {"past"})


# -- single aspects ------------------------------------------------------------------------------------
def _aspect_skill(skill_id: str, *patterns, examples=(), priority="M", exclude=(), weight=1.0):
    return skill(
        skill_id,
        group=GROUP,
        online=True,
        max_words=14,
        priority=priority,
        patterns=tuple((p, weight) if isinstance(p, str) else p for p in patterns),
        exclude=_NOT_WEATHER + tuple(exclude),
        examples=examples,
        followup=weather_followup,
    )


def _aspect(skill_id: str, answer, *, need: str = "forecast"):
    async def handler(req: Request) -> SkillResult | None:
        frame = await make_frame(req, skill_id, need=need)
        if not isinstance(frame, Frame):
            return frame
        return answer(frame)

    return handler


_RAIN_WORDS = r"regnet|regnen|regen|nieselt|schauer|niederschlag|geregnet"
_ASK_END = r"aufhören|aufhört|hört|anfangen|fängt|losgeht|vorbei|beginnt|startet"


async def _weather_rain(req: Request) -> SkillResult | None:
    return await _aspect("weather.rain", s.answer_rain)(req)


skill(
    "weather.rain",
    group=GROUP,
    online=True,
    max_words=14,
    priority="M",
    patterns=((_line(_RAIN_WORDS, r"wird es (?:\w+ )?nass"), 1.0),),
    exclude=(
        *_NOT_WEATHER,
        r"\b(?:schirm|regenschirm|regenjacke)\b",
        rf"\bwann\b.*\b(?:{_RAIN_WORDS})\b",
        rf"\b(?:{_ASK_END})\b",
    ),
    examples=("Regnet es heute?", "Gibt's Regen?", "Wird's nass?"),
    followup=weather_followup,
)(_weather_rain)

skill(
    "weather.rain_when",
    group=GROUP,
    online=True,
    max_words=14,
    priority="M",
    patterns=(
        (rf"^(?:.*\s)?wann\b.*\b(?:{_RAIN_WORDS})\b.*$", 1.1),
        (rf"^(?:.*\s)?(?:{_RAIN_WORDS})\b.*\b(?:{_ASK_END})\b.*$", 1.1),
        (r"^(?:.*\s)?wie lange (?:regnet|noch regen|dauert der regen).*$", 1.1),
    ),
    exclude=_NOT_WEATHER,
    examples=("Wann fängt es an zu regnen?", "Wann hört der Regen auf?"),
    followup=weather_followup,
)(_aspect("weather.rain_when", s.answer_rain_when))

skill(
    "weather.rain_now",
    group=GROUP,
    online=True,
    max_words=10,
    priority="S",
    patterns=((r"^(?:.*\s)?regnet es (?:gerade|jetzt|im moment|schon|draußen)\b.*$", 1.1),),
    exclude=_NOT_WEATHER,
    examples=("Regnet es gerade?",),
    followup=weather_followup,
)(_aspect("weather.rain_now", s.answer_rain_now, need="current"))

skill(
    "weather.rain_amount",
    group=GROUP,
    online=True,
    max_words=14,
    priority="S",
    patterns=(
        (rf"^(?:.*\s)?wie viel\b.*\b(?:{_RAIN_WORDS})\b.*$", 1.1),
        (r"^(?:.*\s)?regenmenge.*$", 1.1),
    ),
    exclude=_NOT_WEATHER,
    examples=("Wie viel Regen kommt?", "Wie viel hat es geregnet?"),
    followup=weather_followup,
)(_aspect("weather.rain_amount", s.answer_rain_amount))

_aspect_skill(
    "weather.umbrella",
    _line(r"schirm", r"regenschirm", r"regenjacke", r"regencape"),
    examples=("Brauche ich einen Schirm?", "Brauch isch en Schermche?"),
)(_aspect("weather.umbrella", s.answer_umbrella))

_aspect_skill(
    "weather.snow",
    _line(r"schnee", r"schneit", r"schneien", r"schneefall", r"weiße weihnacht\w*"),
    examples=("Schneit es morgen?", "Gibt es weiße Weihnachten?"),
    exclude=(r"\bschneebesen\b",),
)(_aspect("weather.snow", s.answer_snow))

_aspect_skill(
    "weather.frost",
    _line(
        r"frost",
        r"kratzen",
        r"glatteis",
        r"glatt",
        r"glätte",
        r"friert",
        r"gefriert",
        r"eisglätte",
        r"bodenfrost",
    ),
    examples=("Gibt es heute Nacht Frost?", "Muss ich morgen kratzen?", "Wird es glatt?"),
    exclude=(r"\bgefrierschrank\b", r"\bglatt\s+(?:rasieren|bügeln)\b"),
)(_aspect("weather.frost", s.answer_frost))

_aspect_skill(
    "weather.wind",
    _line(r"wind", r"windig", r"böen", r"sturm", r"stürmisch", r"orkan"),
    examples=("Wie windig ist es?", "Gibt es Sturm?", "Wie stark sind die Böen?"),
    exclude=(r"\b(?:sturmwarnung|windows|windel|windrad|windkraft|sturmtief)\b",),
)(_aspect("weather.wind", s.answer_wind, need="current"))

_aspect_skill(
    "weather.thunder",
    _line(r"gewitter", r"gewittert", r"gewittrig", r"donner", r"blitz\w*"),
    examples=("Gibt es Gewitter?", "Wird's heute gewittrig?"),
    exclude=(r"\bgewitterwarnung\b",),
)(_aspect("weather.thunder", s.answer_thunder))

_aspect_skill(
    "weather.fog",
    _line(r"nebel", r"neblig"),
    examples=("Ist es neblig?", "Gibt es morgen früh Nebel?"),
    priority="S",
)(_aspect("weather.fog", s.answer_fog))

_aspect_skill(
    "weather.visibility",
    _line(r"sichtweite", r"wie ist die sicht", r"wie weit kann man sehen"),
    examples=("Wie ist die Sicht?",),
    priority="K",
)(_aspect("weather.visibility", s.answer_visibility, need="current"))

_TEMP_WORDS = (
    r"wie (?:warm|kalt|heiß|kühl|heiss)",
    r"wie viel grad",
    r"wieviel grad",
    r"wie (?:viele|viel) grad",
    r"temperatur",
    r"grad (?:hat|sind|ist)",
    r"höchsttemperatur",
    r"tiefsttemperatur",
    r"höchstwert",
    r"tiefstwert",
)
_aspect_skill(
    "weather.temperature",
    _line(*_TEMP_WORDS),
    examples=("Wie warm wird es heute?", "Wie viel Grad hat es?", "Wie kalt wird es heute Nacht?"),
    exclude=(
        r"\bgefühlt\b",
        r"\bfühlt\b",
        r"\b(?:fieber|körper|wasser|ofen|backofen|kühlschrank|motor|wohnung|zimmer)\b",
        r"\bwie (?:warm|kalt) (?:ist|wird) (?:das |der |die )?(?:wasser|suppe|kaffee|tee|essen)\b",
    ),
)(_aspect("weather.temperature", s.answer_temperature, need="current"))

_aspect_skill(
    "weather.feels_like",
    _line(r"gefühlt\w*", r"fühlt (?:es )?sich\b.*", r"gefühlte temperatur"),
    examples=("Wie kalt fühlt es sich an?",),
    priority="S",
    weight=1.05,
)(_aspect("weather.feels_like", s.answer_feels_like, need="current"))

_aspect_skill(
    "weather.humidity",
    _line(r"luftfeuchtigkeit", r"luftfeuchte", r"schwül", r"schwüle"),
    examples=("Wie hoch ist die Luftfeuchtigkeit?", "Ist es schwül?"),
    priority="S",
)(_aspect("weather.humidity", s.answer_humidity, need="current"))

_aspect_skill(
    "weather.pressure",
    _line(r"luftdruck", r"hektopascal", r"barometer"),
    examples=("Wie ist der Luftdruck?",),
    priority="K",
)(_aspect("weather.pressure", s.answer_pressure, need="current"))

_aspect_skill(
    "weather.sunshine",
    _line(
        r"sonnenstunden",
        r"sonnenschein",
        r"scheint (?:heute |morgen )?(?:die )?sonne",
        r"sonne scheint",
        r"sonnig",
    ),
    examples=("Scheint heute die Sonne?", "Wie viele Sonnenstunden?"),
    priority="S",
    exclude=(
        r"\b(?:sonnenaufgang|sonnenuntergang|auf|unter)\s?geht\b",
        r"\bsonnenuntergang\b",
        r"\bsonnenaufgang\b",
    ),
)(_aspect("weather.sunshine", s.answer_sunshine))

_aspect_skill(
    "weather.clouds",
    _line(r"bewölkt", r"wolken", r"wolkig", r"sterne\w*", r"sternenhimmel", r"klarer himmel"),
    examples=("Ist es bewölkt?", "Kann man heute Nacht Sterne sehen?"),
    priority="K",
    exclude=(r"\bcloud\b",),
)(_aspect("weather.clouds", s.answer_clouds))

_aspect_skill(
    "weather.uv",
    _line(r"uv", r"uv-index", r"sonnencreme", r"sonnenbrand", r"lichtschutzfaktor"),
    examples=("Wie hoch ist der UV-Index?", "Brauche ich Sonnencreme?"),
    priority="S",
)(_aspect("weather.uv", s.answer_uv))


# -- comparison, extremes, change, region, station -----------------------------------------------------
async def _compare(req: Request) -> SkillResult | None:
    frame = await make_frame(req, "weather.compare", parse_when=True)
    if not isinstance(frame, Frame):
        return frame
    return await sp.answer_compare(frame)


skill(
    "weather.compare",
    group=GROUP,
    online=True,
    max_words=16,
    priority="S",
    patterns=(
        (r"^(?:.*\s)?(?:wärmer|kälter|milder|kühler|nasser|trockener|windiger)\b.*\bals\b.*$", 1.1),
    ),
    exclude=_NOT_WEATHER,
    examples=("Wird es morgen wärmer als heute?", "Ist es in Frankfurt wärmer als hier?"),
    followup=weather_followup,
)(_compare)


async def _extremes(req: Request) -> SkillResult | None:
    frame = await make_frame(req, "weather.extremes")
    if not isinstance(frame, Frame):
        return frame
    return sp.answer_extremes(frame)


skill(
    "weather.extremes",
    group=GROUP,
    online=True,
    max_words=14,
    priority="S",
    patterns=(
        (
            r"^(?:.*\s)?(?:am )?(?:wärmsten|kältesten|heißesten|kühlsten|windigsten|nassesten|sonnigsten|schönsten|trockensten)\b.*$",
            1.1,
        ),
        (r"^(?:.*\s)?welcher tag .*\b(?:am besten|beste)\b.*$", 1.1),
    ),
    exclude=_NOT_WEATHER,
    examples=("Wann ist es heute am wärmsten?", "Welcher Tag wird diese Woche am schönsten?"),
    followup=weather_followup,
)(_extremes)


async def _when_change(req: Request) -> SkillResult | None:
    frame = await make_frame(req, "weather.when_change", parse_when=False)
    if not isinstance(frame, Frame):
        return frame
    return sp.answer_when_change(frame)


skill(
    "weather.when_change",
    group=GROUP,
    online=True,
    max_words=14,
    priority="S",
    patterns=(
        (
            r"^(?:.*\s)?wann (?:wird|ist|gibt|kommt|scheint|schneit)\b.*\b(?:wieder )?(?:warm|kalt|sonnig|trocken|besser|frost|schnee|schneit)\b.*$",
            1.05,
        ),
        (r"^(?:.*\s)?wann scheint (?:mal )?wieder (?:die )?sonne\b.*$", 1.05),
        (
            r"^(?:.*\s)?wann kommt (?:der |die |das )?(?:nächste |nächsten )?(?:frost|schnee|sonne)\b.*$",
            1.05,
        ),
    ),
    exclude=_NOT_WEATHER,
    examples=("Wann wird es wieder warm?", "Wann kommt der nächste Frost?"),
)(_when_change)


async def _region(req: Request) -> SkillResult | None:
    if not any(w.kind == "region" for w in find_places(req.text, req.svc, req.ctx)):
        return None
    frame = await make_frame(
        req, "weather.region", need="current", allow_region=True, parse_when=False
    )
    if not isinstance(frame, Frame):
        return frame
    return await sp.answer_region(frame)


skill(
    "weather.region",
    group=GROUP,
    online=True,
    max_words=14,
    priority="S",
    patterns=((_line(r"wetter", r"temperatur", r"wie warm ist es"), 1.05),),
    exclude=_NOT_WEATHER,
    examples=("Wie ist das Wetter in der Region?", "Wie warm ist es im Landkreis?"),
)(_region)


async def _observed(req: Request) -> SkillResult | None:
    frame = await make_frame(req, "weather.observed", need="current", parse_when=False)
    if not isinstance(frame, Frame):
        return frame
    return await sp.answer_observed(frame)


skill(
    "weather.observed",
    group=GROUP,
    online=True,
    max_words=12,
    priority="K",
    patterns=(
        (r"^(?:.*\s)?(?:wetterstation|was misst|gemessen\w*)\b.*$", 1.1),
        (r"^(?:.*\s)?wie (?:warm|kalt) ist es (?:wirklich|tatsächlich|echt)\b.*$", 1.1),
    ),
    exclude=_NOT_WEATHER,
    examples=("Was misst die Wetterstation?", "Wie warm ist es wirklich?"),
)(_observed)


async def _source(req: Request) -> SkillResult:
    cfg = req.svc.cfg.weather
    text = (
        "Das Wetter kommt von Open-Meteo, berechnet mit den Modellen des Deutschen Wetterdienstes."
        if cfg.provider == "open-meteo"
        else f"Das Wetter kommt von {cfg.provider}."
    )
    if cfg.fallback_provider == "brightsky":
        text += (
            " Fällt der Dienst aus, springt Bright Sky mit Daten des Deutschen Wetterdienstes ein."
        )
    return SkillResult(text=text)


skill(
    "weather.source",
    group=GROUP,
    priority="S",
    max_words=10,
    patterns=((r"^(?:.*\s)?(?:welcher|welchen|von welchem) wetterdienst\b.*$", 1.1),),
    examples=("Welcher Wetterdienst?",),
)(_source)


# -- part of the morning overview ---------------------------------------------------------------------------
@briefing_part(30)
async def _briefing_weather(req: Request) -> str | None:
    frame = await make_frame(req, "briefing", parse_when=False)
    if not isinstance(frame, Frame):
        return None
    result = a.answer_today(frame)
    return result.text

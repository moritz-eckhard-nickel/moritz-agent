# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The instant answers as read-only tools for the language model (SKILL-23, AGENT-11, P1-07).

The model gets structured tools (``get_weather``, ``get_warnings`` …) or, for open areas, one tool
with a free German question (``calendar_info``, ``calculate`` …). Both end in the same place as a
spoken question: the tool writes the sentence, the router picks the skill among the allowed ones and
the skill answers with real data. The result carries the numbers (``data``), a finished sentence
(``speakable``) and the sources. Writing skills (notes, timers) are deliberately not offered.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, ClassVar

from moritz_agent.skills.base import Services, Skill, SkillContext, SkillResult
from moritz_agent.skills.router import Router, new_context
from moritz_agent.tools.base import BaseTool, ToolContext, ToolResult

Builder = Callable[[dict[str, Any]], str]

_PLACE = {
    "type": "string",
    "description": "Ortsname oder fünfstellige Postleitzahl; weglassen für den Heimatort Weilburg",
    "maxLength": 80,
}
_WHEN = {
    "type": "string",
    "description": (
        "Zeitpunkt oder Zeitraum, z. B. jetzt, heute, heute Abend, morgen früh, Samstag, "
        "Wochenende, nächste Woche, 24. Oktober, 15 Uhr"
    ),
    "maxLength": 60,
}
_QUESTION = {
    "type": "string",
    "description": "Die Frage als kurzer deutscher Satz, möglichst so, wie Moritz sie gestellt hat",
    "minLength": 3,
    "maxLength": 200,
}
_MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def _when(args: dict[str, Any]) -> str:
    """The time words of an argument; ``2026-10-24`` becomes "am 24. Oktober 2026"."""
    value = str(args.get("when") or "").strip()
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    return f"am {day.day}. {_MONTHS[day.month - 1]} {day.year}"


def _in(args: dict[str, Any]) -> str:
    place = str(args.get("place") or "").strip()
    return f"in {place}" if place else ""


def _join(*parts: str) -> str:
    return " ".join(part for part in parts if part)


class ToolArgumentError(ValueError):
    """A combination of arguments the sentence builder cannot turn into a question."""


class SkillTool(BaseTool):
    """One tool backed by the skills ``only`` selects."""

    timeout_s = 12.0

    def __init__(
        self,
        router: Router,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        only: Callable[[Skill], bool],
        sentence: Builder,
    ) -> None:
        self.router = router
        self.name = name
        self.description = description
        self.parameters = parameters
        self.only = only
        self.sentence = sentence

    @property
    def svc(self) -> Services:
        return self.router.svc

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        skill_ctx: SkillContext = ctx.skills or new_context(self.svc)
        try:
            sentence = self.sentence(args)
        except ToolArgumentError as exc:
            return ToolResult.failure("invalid_arguments", str(exc))
        outcome = await self.router.ask(sentence, skill_ctx, only=self.only, surface=ctx.surface)
        result = outcome.result
        if result is None or not (result.text or result.markdown):
            return ToolResult.failure(
                "no_answer",
                "Dazu habe ich keine Auskunft. Frag kurz nach oder sag ehrlich, dass du es nicht weißt.",
            )
        return to_tool_result(result, outcome.skill_id)


def to_tool_result(result: SkillResult, skill_id: str | None) -> ToolResult:
    """Numbers and sentence of a skill answer in the shape of every tool."""
    text = result.text or result.markdown or ""
    data: dict[str, Any] = {"skill": skill_id, "text": text}
    if result.detail:
        data["detail"] = result.detail
    if result.stale_s:
        data["age_seconds"] = result.stale_s
    if result.clarify is not None:
        data["question_for_user"] = result.clarify.question
    facts = {
        key: value
        for key, value in (result.data or {}).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    if facts:
        data["facts"] = facts
    sources = [
        {
            key: value
            for key, value in (("name", s.name), ("url", s.url), ("license", s.license))
            if value
        }
        for s in result.sources
    ]
    return ToolResult.success(data, speakable=text, sources=sources)


# -- builders -------------------------------------------------------------------------------------
_WEATHER = {
    "overview": "Wie ist das Wetter",
    "rain": "Regnet es",
    "temperature": "Wie warm wird es",
    "feels_like": "Wie kalt fühlt es sich an",
    "wind": "Wie windig ist es",
    "snow": "Schneit es",
    "frost": "Gibt es Frost",
    "thunder": "Gibt es Gewitter",
    "fog": "Ist es neblig",
    "humidity": "Wie hoch ist die Luftfeuchtigkeit",
    "pressure": "Wie hoch ist der Luftdruck",
}


def weather_sentence(args: dict[str, Any]) -> str:
    question = str(args.get("question") or "").strip()
    if question:  # the whole question in the caller's words (also used by the weather guard)
        return question
    return _join(_WEATHER[args.get("aspect", "overview")], _when(args), _in(args))


_WARNINGS = {
    "weather": "Gibt es Unwetterwarnungen",
    "civil": "Gibt es Warnungen vom Bevölkerungsschutz",
}


def warnings_sentence(args: dict[str, Any]) -> str:
    return _join(_WARNINGS[args.get("kind", "weather")], _in(args))


def pollen_sentence(args: dict[str, Any]) -> str:
    return _join(
        "Wie ist der Pollenflug", _when(args), str(args.get("pollen") or "").strip(), _in(args)
    )


def air_sentence(args: dict[str, Any]) -> str:
    base = (
        "Wie hoch ist das Ozon" if args.get("pollutant") == "ozone" else "Wie ist die Luftqualität"
    )
    return _join(base, _in(args))


_SKY = {
    "sunrise": "Wann geht die Sonne auf",
    "sunset": "Wann geht die Sonne unter",
    "dark": "Wann wird es dunkel",
    "daylength": "Wie lange ist es hell",
    "moon_phase": "Welche Mondphase haben wir",
    "full_moon": "Wann ist der nächste Vollmond",
    "new_moon": "Wann ist der nächste Neumond",
    "moonrise": "Wann geht der Mond auf",
    "moonset": "Wann geht der Mond unter",
    "season_start": "Wann beginnt der {season}",
}


def sky_sentence(args: dict[str, Any]) -> str:
    what = args["what"]
    base = _SKY[what]
    if what == "season_start":
        if not args.get("season"):
            raise ToolArgumentError("Bei season_start muss 'season' angegeben werden.")
        return base.format(season=args["season"])
    if what in {"full_moon", "new_moon"}:
        return base
    place = _in(args) if what != "moon_phase" else ""
    if what == "daylength":  # "Wie lange ist es heute hell" – the day word must stand before "hell"
        return _join("Wie lange ist es", _when(args) or "heute", "hell", place)
    return _join(base, _when(args), place)


def question_sentence(args: dict[str, Any]) -> str:
    return _join(str(args["question"]), _in(args) if args.get("place") else "")


# -- the tools ------------------------------------------------------------------------------------
def _groups(*groups: str, exclude: tuple[str, ...] = ()) -> Callable[[Skill], bool]:
    return lambda skill: skill.group in groups and skill.id not in exclude


def _object(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


class _Spec:
    """Declaration of one skill tool (kept as data so tests and the prompt can read it)."""

    SPECS: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "get_weather",
            "description": (
                "Wetter für einen Ort und Zeitraum aus echten Wetterdaten. Immer nutzen, wenn es um "
                "Wetter, Temperatur, Regen, Wind, Schnee, Frost oder Gewitter geht – nie die Websuche. "
                "Ohne Ortsangabe gilt der Heimatort Weilburg (35781)."
            ),
            "parameters": _object(
                {
                    "place": _PLACE,
                    "when": _WHEN,
                    "aspect": {
                        "type": "string",
                        "enum": list(_WEATHER),
                        "description": "Worum es geht; Standard ist overview (allgemeines Wetter)",
                        "default": "overview",
                    },
                    "question": {
                        "type": "string",
                        "description": "Nur wenn sich die Frage nicht in Ort, Zeit und Aspekt fassen lässt: die ganze Frage",
                        "maxLength": 200,
                    },
                }
            ),
            "only": _groups("wetter"),
            "sentence": weather_sentence,
        },
        {
            "name": "get_warnings",
            "description": (
                "Amtliche Warnungen (Deutscher Wetterdienst, Bevölkerungsschutz) für einen Ort. "
                "Nutze es bei Fragen nach Unwetter, Sturm, Hochwasser oder Warnungen."
            ),
            "parameters": _object(
                {
                    "place": _PLACE,
                    "kind": {
                        "type": "string",
                        "enum": ["weather", "civil"],
                        "description": "weather = Wetterwarnungen, civil = Bevölkerungsschutz (NINA)",
                        "default": "weather",
                    },
                }
            ),
            "only": _groups(
                "warnungen", exclude=("pollen.today", "pollen.forecast", "air.quality", "air.ozone")
            ),
            "sentence": warnings_sentence,
        },
        {
            "name": "get_pollen",
            "description": "Pollenflug-Vorhersage des Deutschen Wetterdienstes für heute, morgen oder übermorgen.",
            "parameters": _object(
                {
                    "place": _PLACE,
                    "when": _WHEN,
                    "pollen": {
                        "type": "string",
                        "description": "Pollenart, z. B. Birke, Gräser, Hasel, Beifuß; weglassen für alle",
                        "maxLength": 30,
                    },
                }
            ),
            "only": lambda skill: skill.id.startswith("pollen."),
            "sentence": pollen_sentence,
        },
        {
            "name": "get_air_quality",
            "description": "Luftqualität (Feinstaub, Stickstoffdioxid) oder Ozon für einen Ort.",
            "parameters": _object(
                {
                    "place": _PLACE,
                    "pollutant": {
                        "type": "string",
                        "enum": ["overall", "ozone"],
                        "default": "overall",
                    },
                }
            ),
            "only": lambda skill: skill.id.startswith("air."),
            "sentence": air_sentence,
        },
        {
            "name": "get_sun_moon",
            "description": (
                "Sonne und Mond: Auf- und Untergang, Dämmerung, Tageslänge, Mondphase, nächster Voll- "
                "oder Neumond, Beginn der Jahreszeiten. Rechnet genau, ohne Internet."
            ),
            "parameters": _object(
                {
                    "what": {"type": "string", "enum": list(_SKY)},
                    "place": _PLACE,
                    "when": _WHEN,
                    "season": {
                        "type": "string",
                        "enum": ["Frühling", "Sommer", "Herbst", "Winter"],
                        "description": "nur für season_start",
                    },
                },
                required=("what",),
            ),
            "only": _groups("himmel"),
            "sentence": sky_sentence,
        },
        {
            "name": "calendar_info",
            "description": (
                "Kalenderfragen exakt beantworten: Wochentag eines Datums, Tage bis oder seit einem "
                "Datum, Kalenderwoche, Feiertage in Hessen, Schulferien, Brückentage, Alter, Sternzeichen."
            ),
            "parameters": _object({"question": _QUESTION}, required=("question",)),
            "only": _groups("kalender"),
            "sentence": question_sentence,
        },
        {
            "name": "calculate",
            "description": (
                "Rechnet exakt: Grundrechenarten, Prozent, Mehrwertsteuer, Trinkgeld, Rechnung teilen, "
                "Brüche, Einheiten umrechnen (ohne Währungen). Rechne nie im Kopf."
            ),
            "parameters": _object({"question": _QUESTION}, required=("question",)),
            "only": _groups("rechnen"),
            "sentence": question_sentence,
        },
        {
            "name": "money_info",
            "description": "Wechselkurse der Europäischen Zentralbank, Strombörsenpreis und Spritpreise.",
            "parameters": _object({"question": _QUESTION}, required=("question",)),
            "only": _groups("geld"),
            "sentence": question_sentence,
        },
        {
            "name": "regional_info",
            "description": (
                "Regionales: Pegel der Lahn und Hochwasser, Müllabfuhr, Bundesliga (Eintracht), "
                "Schlagzeilen der Tagesschau."
            ),
            "parameters": _object({"question": _QUESTION}, required=("question",)),
            "only": _groups("region", exclude=("notes.add", "notes.read", "notes.clear")),
            "sentence": question_sentence,
        },
        {
            "name": "place_info",
            "description": "Orte: Postleitzahl zu Ort und umgekehrt, Entfernung, Bundesland oder Kreis eines Ortes.",
            "parameters": _object({"question": _QUESTION}, required=("question",)),
            "only": _groups("orte"),
            "sentence": question_sentence,
        },
        {
            "name": "everyday_advice",
            "description": (
                "Alltagsrat aus dem Wetter: Jacke, Wäsche aufhängen, Grillen, Fahrrad, Joggen, Rasen mähen, "
                "Lüften, Autowaschen, Baden, Wandern, Pflanzen und Frost."
            ),
            "parameters": _object({"question": _QUESTION, "place": _PLACE}, required=("question",)),
            "only": _groups("ratschlaege"),
            "sentence": question_sentence,
        },
    ]


def skill_tools(router: Router) -> list[SkillTool]:
    """All read-only skill tools, bound to ``router``."""
    return [SkillTool(router, **spec) for spec in _Spec.SPECS]

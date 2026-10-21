# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Everyday advice from the weather: jacket, laundry, barbecue, bike, garden … (docs/plan/13 §6.8)."""

from __future__ import annotations

from collections.abc import Callable

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.catalog.wetter import weather_followup
from moritz_agent.skills.registry import skill
from moritz_agent.skills.weather import advice
from moritz_agent.skills.weather.frame import Frame, make_frame

GROUP = "ratschlaege"
_NOT = (
    r"\bmir egal\b",
    r"\b(?:fahrrad|auto)\b.*\b(?:kaufen|reparieren|kosten|preis)\b",
    r"\b(?:neue[nrms]?|kaufen|geschenk|geburtstag|reparieren|kaputt|kosten|preis)\b",
)


def _line(*alternatives: str) -> str:
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


def _advice(skill_id: str, answer: Callable[[Frame], SkillResult], *, need: str = "forecast"):
    async def handler(req: Request) -> SkillResult | None:
        if not req.svc.cfg.advice.enabled:
            return SkillResult(text="Alltagsratschläge sind bei mir ausgeschaltet.", serious=True)
        frame = await make_frame(req, skill_id, need=need)
        if not isinstance(frame, Frame):
            return frame
        return answer(frame)

    return handler


def _register(skill_id, answer, *patterns, examples=(), priority="S", exclude=(), need="forecast"):
    skill(
        skill_id,
        group=GROUP,
        online=True,
        priority=priority,
        max_words=12,
        patterns=tuple((_line(p), 1.0) for p in patterns),
        exclude=_NOT + tuple(exclude),
        examples=examples,
        followup=weather_followup,
    )(_advice(skill_id, answer, need=need))


_register(
    "advice.jacket",
    advice.jacket,
    r"jacke",
    r"was soll ich (?:\w+ )?anziehen",
    r"was zieh ich an",
    r"warm anziehen",
    r"pullover",
    r"mantel",
    r"kurze hose",
    examples=("Brauche ich eine Jacke?", "Was soll ich anziehen?"),
    exclude=(r"\bregenjacke\b",),
)
_register(
    "advice.laundry",
    advice.laundry,
    r"wäsche (?:draußen )?(?:aufhängen|trocknen)",
    r"wäsche (?:draußen|raus)",
    r"trocknet (?:die |meine )?wäsche",
    r"(?:draußen|raus) wäsche",
    r"wäscheleine",
    examples=("Kann ich Wäsche draußen aufhängen?",),
)
_register(
    "advice.bbq",
    advice.bbq,
    r"grillwetter",
    r"grillen",
    r"grillabend",
    examples=("Ist heute Grillwetter?",),
)
_register(
    "advice.bike",
    advice.bike,
    r"fahrradwetter",
    r"mit dem (?:fahr)?rad fahren",
    r"fahrrad fahren",
    r"radfahren",
    r"radeln",
    examples=("Ist Fahrradwetter?", "Kann ich mit dem Rad fahren?"),
)
_register(
    "advice.run",
    advice.run,
    r"joggen",
    r"laufen gehen",
    r"zum laufen",
    r"laufwetter",
    r"beste zeit zum laufen",
    examples=("Kann ich joggen gehen?", "Wann ist heute die beste Zeit zum Laufen?"),
    priority="K",
)
_register(
    "advice.garden_water",
    advice.garden_water,
    r"(?:garten|rasen|pflanzen|beete?|blumen|tomaten) gießen",
    r"gießen",
    r"bewässern",
    examples=("Muss ich den Garten gießen?",),
    exclude=(r"\b(?:in|nach|aus|von|bei|für) gießen\b",),  # the town
)
_register(
    "advice.mow",
    advice.mow,
    r"rasen mähen",
    r"rasenmähen",
    r"mähen",
    examples=("Kann ich Rasen mähen?",),
    priority="K",
)
_register(
    "advice.ventilate",
    advice.ventilate,
    r"lüften",
    r"fenster (?:auf|offen)(?:lassen)?",
    examples=("Soll ich lüften?", "Fenster auflassen heute Nacht?"),
    priority="K",
)
_register(
    "advice.car_wash",
    advice.car_wash,
    r"auto (?:waschen|wasch)",
    r"autowaschen",
    r"autowäsche",
    examples=("Lohnt sich Autowaschen?",),
    priority="K",
)
_register(
    "advice.swim",
    advice.swim,
    r"badewetter",
    r"baden gehen",
    r"schwimmen gehen",
    r"zum schwimmen",
    r"freibad",
    r"zum baden",
    examples=("Ist Badewetter?",),
    priority="K",
)
_register(
    "advice.hike",
    advice.hike,
    r"wandern",
    r"wanderwetter",
    r"wanderung",
    r"spazieren(?: gehen)?",
    r"spaziergang",
    examples=("Wie ist das Wetter zum Wandern am Samstag?",),
    priority="K",
    exclude=(r"\bwie (?:ist|wird) das wetter\b(?!.*\b(?:wandern|spazier))",),
)
_register(
    "advice.plants_frost",
    advice.plants_frost,
    r"pflanzen (?:rein|ins haus|abdecken)",
    r"pflanzen reinholen",
    r"pflanzen .*(?:reinholen|reinstellen|reinstellen)",
    r"muss ich .* pflanzen .* (?:rein|abdecken)",
    r"geranien",
    examples=("Muss ich die Pflanzen reinholen?",),
    priority="K",
)
_register(
    "advice.heating",
    advice.heating,
    r"heiztag",
    r"heizen",
    r"heizung (?:an|anmachen|einschalten)",
    r"brauche ich die heizung",
    examples=("Wird es kalt genug zum Heizen?",),
    priority="K",
    exclude=(r"\bheizung (?:kaputt|reparieren)\b",),
)

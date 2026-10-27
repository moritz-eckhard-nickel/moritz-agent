# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""One exchange with the core and its answer in a form every channel can carry (P1-31).

``TurnResult`` is plain data (JSON-able): it travels from the main process to the Discord worker
and to the web interface. The skills' structured parts – card, follow-up buttons, question back
with options, sources – are kept; for skills without a card of their own a card is derived.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from moritz_agent.core.principal import Principal
from moritz_agent.core.surface import Surface
from moritz_agent.skills.base import Card, SkillResult

# readable German names of the skill groups for the title of a card
_TITLES = {
    "weather": "Wetter",
    "warn": "Warnung",
    "pollen": "Pollenflug",
    "air": "Luftqualität",
    "advice": "Tipp",
    "sun": "Sonne",
    "moon": "Mond",
    "season": "Jahreszeiten",
    "sky": "Himmel",
    "money": "Geld",
    "water": "Pegel",
    "waste": "Müllabfuhr",
    "football": "Fußball",
    "news": "Nachrichten",
    "date": "Datum",
    "time": "Uhrzeit",
    "holiday": "Feiertage",
    "school": "Schulferien",
    "calc": "Rechnen",
    "convert": "Umrechnen",
    "geo": "Orte",
    "remind": "Erinnerung",
    "timer": "Timer",
    "notes": "Notizen",
    "briefing": "Tagesüberblick",
}
_COLORS = {"warn": "warn", "weather": "info", "sun": "info", "moon": "info", "pollen": "info"}


@dataclass
class Turn:
    text: str
    principal: Principal
    surface: Surface
    conversation_id: str  # one per DM / channel / thread / voice session / call
    place: str = "dm"  # dm | guild | thread | voice | web | phone
    foreign_guild: bool = False  # a server that is not ours (user app)
    reply_target: str = "default"  # where a reminder goes: "default" | "dm:<id>" | "channel:<id>"
    # files dropped into this message (WebUI, P2-05): [{"id", "name", "text", …}]
    files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TurnResult:
    text: str = ""
    markdown: str = ""
    card: dict[str, Any] | None = None
    actions: list[dict[str, str]] = field(default_factory=list)  # [{"label", "say"}]
    sources: list[dict[str, str]] = field(default_factory=list)
    clarify: dict[str, Any] | None = None  # {"question": str, "options": [str, …]}
    serious: bool = False
    detail: str = ""
    skill_id: str | None = None
    prompt: str | None = None
    hangup: bool = False
    tools: list[str] = field(default_factory=list)
    reminder: dict[str, Any] | None = None  # {"id", "due", "text"} when one was set
    stats: dict[str, Any] = field(default_factory=dict)  # steps, ms, dropped_turns of the model
    ms: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TurnResult:
        known = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**known)

    @property
    def spoken(self) -> str:
        return self.text


def _card_dict(card: Card) -> dict[str, Any]:
    return {
        "title": card.title,
        "description": card.description,
        "fields": [{"name": n, "value": v, "inline": i} for n, v, i in card.fields],
        "color": card.color,
        "footer": card.footer,
    }


def footer_for(result: SkillResult) -> str:
    """The attribution line of a card: source and licence (SKILL-14)."""
    parts = []
    for source in result.sources:
        parts.append(f"{source.name} ({source.license})" if source.license else source.name)
    return " · ".join(dict.fromkeys(parts))


def auto_card(skill_id: str | None, result: SkillResult) -> dict[str, Any] | None:
    """A card for skills that deliver data from a service (sources) and have no card of their own."""
    if result.card is not None:
        return _card_dict(result.card)
    if not result.sources or not result.text:
        return None
    key = (skill_id or "").split(".")[0]
    fields = []
    if result.detail:
        fields.append({"name": "Mehr Details", "value": result.detail[:1000], "inline": False})
    return {
        "title": _TITLES.get(key, "Auskunft"),
        "description": result.text,
        "fields": fields,
        "color": "warn" if result.serious else _COLORS.get(key, "info"),
        "footer": footer_for(result),
    }


def from_skill(
    result: SkillResult,
    skill_id: str | None = None,
    *,
    ms: int = 0,
    surface: Surface = Surface.CHAT,
) -> TurnResult:
    """The wire form of a skill answer."""
    clarify = None
    if result.clarify is not None:
        clarify = {
            "question": result.clarify.question,
            "options": [option.label for option in result.clarify.options],
        }
    sources = [
        {
            key: value
            for key, value in (("name", s.name), ("url", s.url), ("license", s.license))
            if value
        }
        for s in result.sources
    ]
    return TurnResult(
        text=result.text or "",
        markdown=result.markdown or result.text or "",
        card=auto_card(skill_id, result) if surface is Surface.CHAT else None,
        actions=[{"label": a.label, "say": a.say} for a in result.actions],
        sources=sources,
        clarify=clarify,
        serious=result.serious,
        detail=result.detail or "",
        skill_id=skill_id,
        prompt=result.prompt,
        hangup=result.hangup,
        ms=ms,
    )

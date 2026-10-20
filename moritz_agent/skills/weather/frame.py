# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Everything one weather answer needs: place, time span, weather pack, honest error answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from moritz_agent.skills.base import (
    Action,
    Clarification,
    Option,
    Request,
    SkillResult,
    Source,
)
from moritz_agent.skills.geo.gazetteer import Place
from moritz_agent.skills.providers import Fetched, ProviderUnavailable
from moritz_agent.skills.render import german as g
from moritz_agent.skills.router import followup_state
from moritz_agent.skills.slots.when import When, find_when
from moritz_agent.skills.slots.where import Where, find_places, geocode_online, home_place
from moritz_agent.skills.weather.model import WeatherPack

SOURCES = {
    "open-meteo": Source("Open-Meteo.com", "https://open-meteo.com/", "CC BY 4.0"),
    "brightsky": Source(
        "Deutscher Wetterdienst über Bright Sky", "https://brightsky.dev/", "CC BY 4.0"
    ),
}
OFFLINE_TEXT = "Ich komme gerade nicht an die Wetterdaten. Versuch es bitte gleich noch einmal."
DISABLED_TEXT = "Wetterabfragen sind bei mir gerade ausgeschaltet."


@dataclass
class Frame:
    req: Request
    where: Where
    place: Place
    pack: WeatherPack
    fetched: Fetched[WeatherPack]
    now: datetime
    when: When | None
    skill_id: str = "weather.now"

    # -- place wording ------------------------------------------------------------------------
    @property
    def is_home(self) -> bool:
        return self.where.kind == "home"

    def place_name(self) -> str:
        name = self.place.spoken
        if self.where.how == "online" and not self.place.domestic and self.place.country:
            return f"{name} in {self.place.country}"
        return name

    def in_place(self) -> str:
        """ "in Weilburg" – for the home place only the first two times of a conversation."""
        ctx = self.req.ctx
        if self.is_home:
            if ctx.place_mentions >= 2 and not self.where.named:
                return ""
            ctx.place_mentions += 1
        return f"in {self.place_name()}"

    def intro(self) -> str:
        """Prefix that tells how the place was understood ("Für 60311, das ist …")."""
        where = self.where
        if where.how == "postcode" and where.postcode:
            return f"Für {where.postcode}, das ist {self.place_name()}: "
        if where.guessed:
            return f"Ich nehme an, du meinst {self.place_name()}. "
        return ""

    # -- finishing ----------------------------------------------------------------------------
    def stale_note(self) -> str:
        fetched = self.fetched
        if fetched.cache != "stale":
            return ""
        hours = max(1, round(fetched.age_s / 3600))
        return (
            "Ich komme gerade nicht an neue Wetterdaten. "
            f"Stand von vor {g.plural(hours, 'Stunde', 'Stunden')}: "
        )

    def source(self) -> Source:
        base = SOURCES.get(self.pack.source, SOURCES["open-meteo"])
        return Source(base.name, base.url, base.license, self.pack.fetched_at)

    def finish(
        self,
        text: str,
        *,
        detail: str | None = None,
        aspect: str = "overview",
        data: dict[str, Any] | None = None,
        actions: tuple[Action, ...] | None = None,
        serious: bool = False,
    ) -> SkillResult:
        body = self.intro() + text if self.intro() else text
        body = self.stale_note() + (body[:1].lower() + body[1:] if self.stale_note() else body)
        params = {"where": self.where, "when": self.when, "aspect": aspect, "place": self.place}
        return SkillResult(
            text=body,
            detail=detail,
            data={
                "place": self.place.name,
                "source": self.pack.source,
                "cache": self.fetched.cache,
                "age_s": round(self.fetched.age_s),
                **(data or {}),
            },
            sources=(self.source(),),
            followup=followup_state(self.skill_id, **params),
            actions=actions if actions is not None else default_actions(self),
            stale_s=round(self.fetched.age_s) if self.fetched.cache == "stale" else None,
            serious=serious,
        )


def default_actions(frame: Frame) -> tuple[Action, ...]:
    label = frame.when.label if frame.when else ""
    if "morgen" in label:
        return (Action("Übermorgen", "und übermorgen"), Action("Wochenende", "und am Wochenende"))
    return (Action("Morgen", "und morgen"), Action("Wochenende", "und am Wochenende"))


def when_text(text: str) -> str:
    """The sentence as the time parser should see it: no postcodes, "die Woche" = "diese Woche"."""
    text = re.sub(r"\b\d{5}\b", " ", text)
    return re.sub(r"\bdie woche\b", "diese woche", text)


async def make_frame(
    req: Request,
    skill_id: str,
    *,
    need: str = "forecast",
    allow_region: bool = False,
    parse_when: bool = True,
) -> Frame | SkillResult | None:
    """Resolve place, time and data for a weather question.

    Returns a ``Frame`` to answer from, a ready ``SkillResult`` (unknown place, a question back,
    no data) or ``None`` when the sentence is no weather question after all.
    """
    svc = req.svc
    overrides = req.overrides
    where: Where | None = overrides.get("where")
    if where is None:
        found = find_places(req.text, svc, req.ctx)
        where = found[0] if found else Where("home", home_place(svc, req.ctx), named=False)
    if where.kind == "region" and not allow_region:
        where = Where("home", home_place(svc, req.ctx), named=False)
    if where.kind == "unknown":
        where = await geocode_online(where, svc)
    if where.kind == "unknown":
        return SkillResult(text=f"Den Ort {where.spoken} kenne ich nicht.", serious=True)
    if where.kind == "bad_postcode":
        hint = (
            f" Meinst du {where.suggestion.postal_codes[0]}, {where.suggestion.spoken}?"
            if (where.suggestion and where.suggestion.postal_codes)
            else ""
        )
        return SkillResult(
            text=f"Die Postleitzahl {where.postcode} kenne ich nicht.{hint}", serious=True
        )
    place = where.place or home_place(svc, req.ctx)
    now = svc.clock.now(place.tz or svc.timezone)

    if "when" in overrides:
        when = overrides["when"]
    elif parse_when:
        when = find_when(when_text(req.text), now)
    else:
        when = None

    if where.kind == "ambiguous":
        return _ask_which_place(req, skill_id, where, when)

    providers = svc.providers
    if providers is None:
        return SkillResult(text=OFFLINE_TEXT, prompt="skills_offline", serious=True)
    try:
        fetched = await providers.weather(
            place,
            need=need,
            on_miss=lambda: setattr(req.ctx, "thinking_prompt", "thinking_weather"),
        )
    except ProviderUnavailable as exc:
        if exc.reason == "disabled":
            return SkillResult(text=DISABLED_TEXT, serious=True)
        return SkillResult(text=OFFLINE_TEXT, prompt="skills_offline", serious=True)
    pack = fetched.data
    return Frame(req, where, place, pack, fetched, now, when, skill_id)


def _ask_which_place(req: Request, skill_id: str, where: Where, when: When | None) -> SkillResult:
    first, second = where.options[:2]
    options = []
    for place in (first, second):
        aliases = tuple(word for word in (place.state_name, place.district, place.country) if word)
        options.append(
            Option(
                label=place.spoken,
                params={
                    "where": Where("place", place, where.spoken, "exact", named=True),
                    "when": when,
                },
                aliases=aliases,
            )
        )
    name = where.spoken
    question = f"Welches {name} meinst du – {first.spoken} oder {second.spoken}?"
    return SkillResult(
        text=question,
        clarify=Clarification(question, tuple(options), skill_id),
    )

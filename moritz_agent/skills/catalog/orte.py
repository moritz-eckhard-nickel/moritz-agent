# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Places and distances, all offline (docs/plan/13 §6.10)."""

from __future__ import annotations

import re

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.catalog.common import say
from moritz_agent.skills.geo.distance import bearing_deg, compass_de, haversine_km
from moritz_agent.skills.geo.gazetteer import Place
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.slots.where import Where, find_places, home_place
from moritz_agent.skills.weather import text as t

GROUP = "orte"


def _line(*alternatives: str) -> str:
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


def _named(req: Request) -> list[Where]:
    return [w for w in find_places(req.text, req.svc, req.ctx) if w.kind in {"place", "home"}]


def _problem(req: Request) -> SkillResult | None:
    """An honest answer when the user named something we cannot resolve."""
    for where in find_places(req.text, req.svc, req.ctx):
        if where.kind == "bad_postcode":
            hint = ""
            if where.suggestion and where.suggestion.postal_codes:
                hint = f" Meinst du {where.suggestion.postal_codes[0]}, {where.suggestion.spoken}?"
            return say(f"Die Postleitzahl {where.postcode} kenne ich nicht.{hint}", serious=True)
        if where.kind == "unknown":
            return say(f"Den Ort {where.spoken} kenne ich nicht.", serious=True)
        if where.kind == "ambiguous" and len(where.options) >= 2:
            first, second = where.options[:2]
            return say(
                f"Welches {where.spoken} meinst du – {first.spoken} oder {second.spoken}?",
                serious=True,
            )
    return None


def _where_phrase(place: Place) -> str:
    phrase = place.location_phrase()
    return f" {phrase}" if phrase else ""


@skill(
    "geo.plz_to_place",
    group=GROUP,
    priority="S",
    help="Postleitzahlen und Orte",
    examples=("Wo ist 35781?", "Welcher Ort hat die Postleitzahl 65549?"),
    max_words=12,
    patterns=(
        (_line(r"postleitzahl", r"plz"), 0.9),
        (r"^wo (?:ist|liegt) \d{5}$", 1.0),
        (r"^(?:zu )?welche[mr]? ort (?:gehört|hat) .*\d{5}.*$", 1.0),
    ),
    exclude=(
        r"\b(?:wetter|regen|temperatur|warm|kalt|pollen)\b",
        r"\bwelche (?:postleitzahl|plz)\b",
    ),
)
async def plz_to_place(req: Request) -> SkillResult | None:
    problem = _problem(req)
    if problem is not None:
        return problem
    found = [w for w in find_places(req.text, req.svc, req.ctx) if w.how == "postcode"]
    if not found or found[0].place is None:
        return None
    place = found[0].place
    return say(f"{found[0].postcode} ist {place.spoken}{_where_phrase(place)}.")


@skill(
    "geo.place_to_plz",
    group=GROUP,
    priority="S",
    examples=("Welche Postleitzahl hat Limburg?", "PLZ von Weilburg"),
    max_words=12,
    patterns=(
        (r"^(?:.*\s)?(?:welche|wie lautet die) (?:postleitzahl|plz)\b.*$", 1.0),
        (r"^(?:.*\s)?(?:postleitzahl|plz) (?:von|für|vom) .*$", 1.0),
    ),
)
async def place_to_plz(req: Request) -> SkillResult | None:
    problem = _problem(req)
    if problem is not None:
        return problem
    named = [w for w in _named(req) if w.place is not None and w.how != "default"]
    if not named:
        place = home_place(req.svc, req.ctx)
        subject = place
    else:
        subject = named[0].place  # type: ignore[assignment]
    gaz = req.svc.gazetteer
    codes = gaz.postcodes_of(subject) if gaz else list(subject.postal_codes)
    if not codes:
        return say(f"Die Postleitzahl von {subject.spoken} kenne ich nicht.", serious=True)
    runs: list[list[int]] = []
    for code in codes:
        number = int(code)
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    parts = [f"{r[0]:05d}" if len(r) == 1 else f"{r[0]:05d} bis {r[-1]:05d}" for r in runs[:3]]
    if subject.parent:
        return say(
            f"{subject.spoken} gehört zu {subject.parent} und hat die Postleitzahl {parts[0]}."
        )
    if len(codes) == 1:
        return say(f"{subject.spoken} hat die Postleitzahl {parts[0]}.")
    more = " und weitere" if len(runs) > 3 else ""
    return say(f"{subject.spoken} hat die Postleitzahlen {g.join_and(parts)}{more}.")


def _kilometers(km: float) -> str:
    if km < 10:
        value = round(km)
        return "weniger als 1 Kilometer" if value < 1 else f"{value} {'Kilometer'}"
    step = 1 if km < 100 else 5 if km < 1000 else 10
    value = int(round(km / step) * step)
    return f"{g.number(value)} Kilometer"


@skill(
    "geo.distance",
    group=GROUP,
    priority="S",
    help="Entfernungen",
    examples=("Wie weit ist es nach Frankfurt?", "Entfernung Weilburg Gießen"),
    max_words=12,
    patterns=(
        (r"^(?:.*\s)?wie weit (?:ist|sind)\b.*$", 0.85),
        (r"^(?:.*\s)?(?:entfernung|luftlinie|distanz|abstand)\b.*$", 1.0),
    ),
    exclude=(r"\b(?:wetter|sonne|mond|regen)\b",),
)
async def distance(req: Request) -> SkillResult | None:
    problem = _problem(req)
    if problem is not None:
        return problem
    places = [w for w in _named(req) if w.place is not None]
    home = home_place(req.svc, req.ctx)
    if len(places) == 1 and places[0].kind == "place":
        origin, target = home, places[0].place
    elif len(places) >= 2:
        origin, target = places[0].place, places[1].place
        if re.search(r"\bvon\b.*\bentfernt\b", req.text):
            origin, target = target, origin
    else:
        return None
    assert origin is not None and target is not None
    if (origin.lat, origin.lon) == (target.lat, target.lon):
        return say(f"{origin.spoken} und {target.spoken} sind derselbe Ort.")
    km = haversine_km(origin.lat, origin.lon, target.lat, target.lon)
    direction = compass_de(bearing_deg(origin.lat, origin.lon, target.lat, target.lon))
    start = "bis" if len(places) == 1 else f"von {origin.spoken} nach"
    text = (
        f"Luftlinie sind es {start} {target.spoken} etwa {_kilometers(km)}, Richtung {direction}."
    )
    if km > 2000:
        text += " Das ist weit weg."
    return say(text)


@skill(
    "geo.region_of",
    group=GROUP,
    priority="S",
    examples=("In welchem Bundesland liegt Wetzlar?", "Zu welchem Kreis gehört Runkel?"),
    max_words=12,
    patterns=(
        (r"^(?:.*\s)?(?:in )?welche[mn]? (?:bundesland|kreis|landkreis|land|staat)\b.*$", 1.0),
        (r"^(?:.*\s)?zu welche[mn]? (?:kreis|landkreis|bundesland|land)\b.*$", 1.0),
    ),
)
async def region_of(req: Request) -> SkillResult | None:
    problem = _problem(req)
    if problem is not None:
        return problem
    named = [w for w in _named(req) if w.place is not None and w.named]
    if not named:
        return None
    place = named[0].place
    assert place is not None
    if not place.domestic:
        return say(f"{place.spoken} liegt in {place.country}.")
    wants_state = "bundesland" in req.text
    if place.district and not wants_state:
        district = (
            place.district
            if place.district.startswith(("Landkreis", "Kreis", "Region"))
            else f"Landkreis {place.district}"
        )
        return say(f"{place.spoken} gehört zum {district} in {place.state_name}.")
    return say(f"{place.spoken} liegt in {place.state_name}.")


@skill(
    "geo.home",
    group=GROUP,
    priority="M",
    help="den Heimatort",
    examples=("Wo bin ich?", "Für welchen Ort sagst du das Wetter?", "Was ist mein Standort?"),
    max_words=10,
    patterns=(
        r"^wo bin ich$",
        r"^(?:was|wo) ist (?:mein|unser) (?:standort|heimatort|wohnort|zuhause)$",
        r"^(?:.*\s)?für welchen ort\b.*$",
        r"^(?:.*\s)?welcher ort ist (?:eingestellt|mein heimatort)\b.*$",
        r"^wo wohne ich$",
    ),
)
async def home(req: Request) -> SkillResult:
    place = home_place(req.svc, req.ctx)
    code = f", {place.postal_codes[0]}" if place.postal_codes else ""
    extra = ""
    if place.district:
        extra = (
            f" im Landkreis {place.district}"
            if not place.district.startswith(("Landkreis", "Kreis"))
            else f" im {place.district}"
        )
    if place.state_name:
        extra += f", {place.state_name}"
    return say(
        f"Dein Heimatort ist {place.spoken}{code}{extra}. "
        "Wetter und Termine beziehen sich darauf, wenn du keinen anderen Ort nennst.",
        detail=f"Die Koordinaten sind {t.deg_n(place.lat)} Komma {abs(round(place.lat % 1 * 100))} Nord.",
    )

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Place expressions → a place (docs/plan/13 §4.4).

``find_places`` works offline on the prepared utterance and returns one ``Where`` per place the
user names, in the order they were spoken. A ``Where`` is one of

* ``home``       – no place named, or "hier", "bei mir", "zu Hause", "in Weilburg"
* ``place``      – a place from the gazetteer (``how`` says whether it was exact, fuzzy …)
* ``region``     – "in der Region", "im Landkreis"
* ``ambiguous``  – several equally likely places ("Neustadt"): ``options`` has the top two
* ``unknown``    – something that looks like a place name but is not in the gazetteer (the weather
                   skills then try the online geocoder, see ``geocode_online``)
* ``bad_postcode`` – five digits that are no postcode we know (``suggestion``: one digit off)
* ``unclear``    – "in meinem Urlaub": not a place, the skill should decline
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from moritz_agent.skills.geo.gazetteer import Gazetteer, Place, fold

if TYPE_CHECKING:
    from moritz_agent.skills.base import Services, SkillContext

SIGNALS = {"in", "für", "bei", "nach", "von", "aus", "bis", "zwischen", "um", "rund", "nahe"}
# these only count when a known place follows (a stray "ist Essen fertig" must not become a city)
KEYWORDS = {
    "wetter", "plz", "postleitzahl", "vorwahl", "ist", "liegt", "sind", "gehört", "entfernung",
    "distanz", "luftlinie", "abstand", "temperatur", "und",
}  # fmt: skip
_SKIP_AFTER = {"hat", "von", "vom", "für", "ist", "liegt", "gehört", "zu", "nach", "zwischen"}
# words that end a place name (time, question and verb words)
_STOP = {
    "heute", "morgen", "übermorgen", "gestern", "vorgestern", "jetzt", "gerade", "aktuell",
    "früh", "vormittag", "mittag", "nachmittag", "abend", "nacht", "morgens", "mittags",
    "abends", "nachts", "wochenende", "woche", "wochen", "montag", "dienstag", "mittwoch",
    "donnerstag", "freitag", "samstag", "sonntag", "am", "um", "ab", "bis", "wird", "ist",
    "sind", "war", "wie", "was", "wann", "wo", "wetter", "regnet", "schneit", "noch", "wieder",
    "auch", "eigentlich", "denn", "dann", "oder", "und", "ob", "gibt", "gibts", "hat", "haben",
    "kann", "soll", "muss", "mal", "bitte", "wirklich", "wohl", "so", "bei", "mit", "ohne",
    "für", "kalt", "warm", "heiß", "nass", "trocken", "sonnig", "windig", "der", "uhr",
    "im", "zur", "zum", "sonne", "temperatur", "regen", "schnee", "wind", "frost", "gewitter",
    "grad", "luft", "pollen", "warnung", "warnungen", "entfernung", "weit", "postleitzahl", "plz",
    "vorwahl", "zeitzone", "bundesland", "kreis", "landkreis", "wärmer", "kälter", "los",
    "uns", "mir", "dir", "euch", "ihnen", "mich", "dich", "hier", "dort", "da", "draußen",
    "auf", "an", "zu", "es", "man", "ich", "du", "wir", "sie", "er", "sturm", "nebel", "glatteis",
    "hagel", "hitze", "kälte", "nässe", "tag", "tage", "dunkelheit", "dämmerung", "licht", "zeit",
    "weg", "dran", "davon", "dabei", "dafür", "damit", "danach", "davor", "dazu", "darauf",
}  # fmt: skip
_DETERMINERS = {"der", "die", "das", "dem", "den", "des", "ein", "einer", "einem", "einen", "eine"}
# "in der Nacht", "in der Gegend": not a place
_TIME_NOUNS = {
    "nacht", "früh", "frühe", "nähe", "gegend", "region", "woche", "wochen", "tage", "tagen",
    "zeit", "nächsten", "kommenden", "folgenden", "letzten", "ersten", "zweiten", "dritten",
    "stunde", "stunden", "minute", "minuten", "monat", "monaten", "jahr", "jahren", "mitte",
    "ende", "anfang", "sonne", "kürze", "folge", "umgebung", "stadt", "innenstadt", "heimat",
    "wohnung", "haus", "garten", "küche", "luft", "sonnen", "regen", "dunkelheit", "dämmerung",
    "höhe", "tiefe", "ferne", "welt", "hitze", "kälte", "heutigen", "jetzigen",
}  # fmt: skip
_POSSESSIVE = {
    "mein", "meinem", "meiner", "meinen", "meine", "dein", "deinem", "deiner", "deinen", "unser",
    "unserem", "unserer", "unseren", "dieser", "diesem", "diesen", "dieses", "jener", "jedem",
    "jeder", "jedes", "welcher", "welchem", "welchen", "manchem", "solchem", "einigen",
}  # fmt: skip
_HOME_PHRASES = (
    r"\b(?:bei mir|bei uns|zu hause|zuhause|daheim|hier|draußen|vor der tür|vor die tür)\b",
    r"\bin (?:meiner|unserer) (?:stadt|gegend|umgebung|nähe|heimat|region)\b",
    r"\bin der (?:nähe|umgebung|stadt)\b",
    r"\bbei mir (?:in|um) der (?:nähe|gegend)\b",
)
_REGION_PHRASES = (
    r"\bin der (?:region|gegend)\b",
    r"\bim (?:landkreis|umkreis|kreis)\b",
    r"\b(?:rund um uns|um uns herum|in der umgebung)\b",
    r"\bin (?:unserer|meiner) region\b",
    r"\bregional\b",
)


@dataclass
class Where:
    kind: str  # home | place | region | ambiguous | unknown | bad_postcode | unclear
    place: Place | None = None
    spoken: str = ""  # as the user said it (for "Den Ort ‚X‘ kenne ich nicht")
    how: str = "default"  # default|home|postcode|exact|stripped|district|fuzzy|phonetic|online
    options: tuple[Place, ...] = ()
    suggestion: Place | None = None
    postcode: str = ""
    named: bool = False  # the user said something (False = default home)

    @property
    def guessed(self) -> bool:
        return self.how in {"fuzzy", "phonetic"}


def home_place(svc: Services, ctx: SkillContext | None = None) -> Place:
    """The place "hier" means: a personal home (Discord users) or ``skills.home``."""
    if ctx is not None and ctx.home is not None:
        return ctx.home
    cfg = svc.cfg.home
    gaz = svc.gazetteer
    if gaz is None:
        return Place(
            name=cfg.name,
            postal_codes=(cfg.postal_code,),
            state=cfg.state,
            lat=cfg.latitude,
            lon=cfg.longitude,
        )
    home = gaz.home
    if (
        home is None
        or cfg.postal_code not in {*home.postal_codes, ""}
        or (cfg.name and fold(cfg.name) != fold(home.name) and fold(cfg.name) != fold(home.parent))
        or (
            (cfg.latitude or cfg.longitude)
            and (home.lat, home.lon) != (cfg.latitude, cfg.longitude)
        )
    ):
        home = gaz.set_home(cfg.postal_code, cfg.name, cfg.latitude, cfg.longitude)
    return home


def _tokens(text: str) -> list[str]:
    return text.split()


def _home_position(text: str) -> int | None:
    """Token index of the first "hier", "bei mir", "zu Hause" … or None."""
    for pattern in _HOME_PHRASES:
        match = re.search(pattern, text)
        if match:
            return text[: match.start()].count(" ")
    return None


def find_places(text: str, svc: Services, ctx: SkillContext | None = None) -> list[Where]:
    """All places named in ``text`` (prepared utterance), in spoken order."""
    gaz = svc.gazetteer
    found: list[tuple[int, Where]] = []
    taken: set[int] = set()

    # 1. postcodes
    tokens = _tokens(text)
    for index, size, plz in _postcode_runs(tokens):
        place = gaz.by_postcode(plz) if gaz else None
        signalled = _has_postcode_signal(tokens, index) or len(tokens) - size <= 2
        if place is not None and signalled:
            taken.update(range(index, index + size))
            found.append((index, Where("place", place, plz, "postcode", postcode=plz, named=True)))
        elif place is None and (signalled or not gaz):
            taken.update(range(index, index + size))
            similar = gaz.similar_postcodes(plz) if gaz else []
            found.append(
                (
                    index,
                    Where(
                        "bad_postcode",
                        spoken=plz,
                        postcode=plz,
                        suggestion=similar[0] if similar else None,
                        named=True,
                    ),
                )
            )
    postcodes_present = bool(found)

    # 2. region and home words
    if any(re.search(p, text) for p in _REGION_PHRASES):
        found.append((0, Where("region", home_place(svc, ctx), "region", "home", named=True)))
    home_at = _home_position(text)

    # 3. names after signal words
    if gaz is not None:
        for i, token in enumerate(tokens):
            if i in taken:
                continue
            start = i
            if token in SIGNALS or token in KEYWORDS:
                start = i + 1
                if token == "rund" and tokens[start : start + 1] == ["um"]:
                    start += 1
                if token in KEYWORDS:
                    while start < len(tokens) and tokens[start] in _SKIP_AFTER:
                        start += 1
            elif i == 0 and gaz.known_prefix(tokens[0:]) and len(tokens) <= 3:
                start = 0  # "Weilburg?" / "Berlin morgen"
            else:
                continue
            where = _window(tokens, start, gaz, svc, ctx, allow_unknown=token in SIGNALS)
            if where is None:
                continue
            size, result = where
            taken.update(range(start, start + size))
            found.append((start, result))
            # "Entfernung Weilburg Gießen", "zwischen A und B": more known places right behind
            follow = start + size
            while follow < len(tokens) and token not in {"wetter"}:
                if tokens[follow] == "und":
                    follow += 1
                if follow >= len(tokens) or not gaz.known_prefix(tokens[follow:]):
                    break
                again = _window(tokens, follow, gaz, svc, ctx, allow_unknown=False)
                if again is None:
                    break
                taken.update(range(follow, follow + again[0]))
                found.append((follow, again[1]))
                follow += again[0]

    if home_at is not None and not any(w.kind == "home" for _, w in found):
        found.append((home_at, Where("home", home_place(svc, ctx), "hier", "home", named=True)))
    found.sort(key=lambda item: item[0])
    results = [w for _, w in found]
    if postcodes_present:
        results = [w for w in results if w.kind != "unknown"] or results
    # the same place twice ("in Weilburg" next to "hier"): keep the first
    unique: list[Where] = []
    for w in results:
        if not any(
            u.kind == w.kind and u.place == w.place and u.spoken == w.spoken for u in unique
        ):
            unique.append(w)
    return unique


def find_where(text: str, svc: Services, ctx: SkillContext | None = None) -> Where:
    """The (first) place of ``text``; the home place when none is named."""
    places = find_places(text, svc, ctx)
    if places:
        return places[0]
    return Where("home", home_place(svc, ctx), how="default", named=False)


def _postcode_runs(tokens: list[str]) -> list[tuple[int, int, str]]:
    """(first token, token count, digits) of every run of digit tokens that makes five digits."""
    runs: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        digits, count = "", 0
        for token in tokens[index : index + 5]:
            token = token.strip(".,")
            if not token.isdigit():
                break
            digits += token
            count += 1
            if len(digits) >= 5:
                break
        if len(digits) == 5:
            runs.append((index, count, digits))
            index += count
        else:
            index += 1
    return runs


def _has_postcode_signal(tokens: list[str], index: int) -> bool:
    """Five digits count as a (wrong) postcode only after "in", "für", "plz" …"""
    before = tokens[max(0, index - 2) : index]
    return bool(set(before) & {*SIGNALS, "plz", "postleitzahl", "wetter"})


def _window(
    tokens: list[str],
    start: int,
    gaz: Gazetteer,
    svc: Services,
    ctx: SkillContext | None,
    *,
    allow_unknown: bool = True,
) -> tuple[int, Where] | None:
    """Read a place name starting at ``tokens[start]``; returns (tokens used, result)."""
    window: list[str] = []
    if start < len(tokens) and tokens[start] in SIGNALS:
        return None  # the signal word handles itself ("wetter in den Alpen")
    for token in tokens[start : start + 6]:
        if token in _STOP and window:
            break
        if token in _STOP and not window and token not in _DETERMINERS:
            return None
        window.append(token)
    if not window:
        return None
    first = window[0]
    if first.isdigit() or re.match(r"^\d", first):
        return None  # "in 3 tagen", "in 35781" (handled as postcode)
    skipped = 0
    if first in _DETERMINERS and len(window) >= 2:
        # "in der Nacht" is time, "in den Alpen" is a place we do not know
        if window[1] in _TIME_NOUNS or window[1] in _POSSESSIVE:
            return None
        if gaz.known_prefix(window[1:]) == 0:
            name = " ".join(window[1:3])
            if allow_unknown and _plausible_name(window[1]):
                return 2, Where("unknown", spoken=_pretty(name), named=True)
            return None
        skipped = 1
        window = window[1:]
    elif first in _DETERMINERS:
        return None
    if window[0] in _POSSESSIVE:
        return None
    # longest known name first
    size = gaz.known_prefix(window)
    if size:
        name = " ".join(window[:size])
        return skipped + size, _lookup(name, gaz, svc, ctx)
    # unscharf: up to three words
    for size in (3, 2, 1):
        if size > len(window):
            continue
        name = " ".join(window[:size])
        if len(fold(name)) < 4:
            continue
        looked = gaz.find(name, near=home_place(svc, ctx))
        if looked.best is not None and looked.best.how in {"fuzzy", "phonetic"}:
            return skipped + size, _from_lookup(looked, name, svc)
    if not allow_unknown or not _plausible_name(window[0]):
        return None
    name = " ".join(window[:2]) if len(window) > 1 and _plausible_name(window[1]) else window[0]
    return skipped + len(name.split()), Where("unknown", spoken=_pretty(name), named=True)


def _plausible_name(word: str) -> bool:
    return (
        len(word) >= 3
        and word not in _STOP
        and word not in _TIME_NOUNS
        and word not in _POSSESSIVE
        and re.fullmatch(r"[a-zäöüß.-]+", word) is not None
    )


def _pretty(name: str) -> str:
    return re.sub(r"(^|[ -])([a-zäöüß])", lambda m: m.group(1) + m.group(2).upper(), name)


def _lookup(name: str, gaz: Gazetteer, svc: Services, ctx: SkillContext | None) -> Where:
    looked = gaz.find(name, near=home_place(svc, ctx))
    return _from_lookup(looked, name, svc)


def _from_lookup(looked, name: str, svc: Services) -> Where:
    best = looked.best
    if best is None:
        return Where("unknown", spoken=_pretty(name), named=True)
    home = svc.gazetteer.home if svc.gazetteer else None
    if (
        home is not None
        and best.how in {"exact", "stripped", "district"}
        and best.place.name == home.name
        and best.place.state == home.state
    ):
        # "in Weilburg" is the home place (coordinates may be configured)
        return Where("home", home, name, "home", named=True)
    if looked.ambiguous and len(looked.hits) > 1:
        options = tuple(h.place for h in looked.hits[:2])
        return Where("ambiguous", options[0], _pretty(name), best.how, options=options, named=True)
    return Where("place", best.place, _pretty(name), best.how, named=True)


async def geocode_online(where: Where, svc: Services) -> Where:
    """Ask the online geocoder about an ``unknown`` place; unchanged if offline or not found."""
    providers = svc.providers
    if where.kind != "unknown" or providers is None or not svc.cfg.online:
        return where
    try:
        place = await providers.geocode(where.spoken)
    except Exception:  # offline, blocked, malformed: stay "unknown"
        return where
    if place is None:
        return where
    return Where("place", place, where.spoken, "online", named=True)

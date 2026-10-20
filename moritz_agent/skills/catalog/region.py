# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Region and everyday life: river level, waste collection, football, news, notes
(docs/plan/13 §6.13)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from moritz_agent.skills.base import Clarification, Option, Request, SkillResult, Source
from moritz_agent.skills.providers import Providers, ProviderUnavailable, ics
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.router import followup_state
from moritz_agent.skills.slots.when import find_when
from moritz_agent.skills.slots.where import home_place
from moritz_agent.skills.weather.frame import unavailable
from moritz_agent.tools.time_tool import WEEKDAYS_DE

GROUP = "region"
PEGEL_SOURCE = Source(
    "PEGELONLINE (Wasserstraßen- und Schifffahrtsverwaltung des Bundes)",
    "https://www.pegelonline.wsv.de/",
    "Datenlizenz Deutschland – Namensnennung 2.0",
)
LIGA_SOURCE = Source("OpenLigaDB", "https://www.openligadb.de/", "")
NEWS_SOURCE = Source("tagesschau.de", "https://www.tagesschau.de/", "")


def _line(*alternatives: str) -> str:
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


def _providers(req: Request) -> Providers | None:
    providers = req.svc.providers
    return providers if isinstance(providers, Providers) else None


def _level(cm: float) -> str:
    """ "1 Meter 42" / "78 Zentimeter"."""
    value = round(cm)
    if value >= 100:
        meters, rest = divmod(value, 100)
        return f"{meters} Meter {rest}" if rest else f"{meters} Meter"
    return f"{value} Zentimeter"


_TREND = {1: "steigend", -1: "fallend", 0: "gleichbleibend"}


# -- water ----------------------------------------------------------------------------------------------
async def _gauge(req: Request):
    cfg = req.svc.cfg.water
    if not cfg.enabled:
        return SkillResult(text="Pegelauskünfte sind bei mir ausgeschaltet.", serious=True), None
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("pegel", "offline"), "Pegeldaten"), None
    from moritz_agent.skills.providers import pegelonline

    place = home_place(req.svc, req.ctx)
    try:
        fetched = await providers.water_levels(place)
    except ProviderUnavailable as exc:
        return unavailable(exc, "Pegeldaten"), None
    gauge = pegelonline.choose(fetched.data, cfg.station)
    if gauge is None:
        return SkillResult(text="Für den Fluss habe ich keinen Pegel gefunden.", serious=True), None
    return None, (gauge, fetched)


def _vs_mean(gauge) -> str:
    if gauge.mean_cm is None:
        return ""
    diff = gauge.value_cm - gauge.mean_cm
    if gauge.high_cm is not None and gauge.value_cm >= gauge.high_cm:
        return "über dem mittleren Hochwasser, das ist ein erhöhter Stand"
    if abs(diff) <= 15:
        return "etwa beim mittleren Wasserstand"
    if diff > 0:
        return (
            "über dem mittleren Wasserstand"
            if diff > 40
            else "etwas über dem mittleren Wasserstand"
        )
    return (
        "unter dem mittleren Wasserstand" if diff < -40 else "etwas unter dem mittleren Wasserstand"
    )


async def _water_level(req: Request) -> SkillResult | None:
    problem, found = await _gauge(req)
    if problem is not None:
        return problem
    gauge, fetched = found
    river = gauge.river or "Der Fluss"
    text = f"Die {river.capitalize()} am Pegel {gauge.name} steht bei {_level(gauge.value_cm)}, {_TREND.get(gauge.trend, 'gleichbleibend')}"
    mean = _vs_mean(gauge)
    if mean:
        text += f", {mean}"
    stale = fetched.cache == "stale"
    if stale and gauge.measured is not None:
        text = (
            f"Der letzte Wert, den ich habe, ist von {g.clock_digital(gauge.measured)}: "
            + text[:1].lower()
            + text[1:]
        )
    return SkillResult(
        text=g.sentence(text),
        sources=(PEGEL_SOURCE,),
        data={"gauge": gauge.name, "level_cm": gauge.value_cm, "trend": gauge.trend},
        followup=followup_state("water.level"),
    )


skill(
    "water.level",
    group=GROUP,
    online=True,
    priority="S",
    max_words=10,
    help="den Pegel der Lahn",
    examples=("Wie hoch steht die Lahn?", "Wasserstand Lahn?", "Steigt die Lahn?"),
    patterns=(
        (r"^(?:.*\s)?(?:wasserstand|pegel\w*)\b.*$", 1.0),
        (r"^(?:.*\s)?wie hoch (?:steht|ist) (?:die |der )?(?:lahn|fluss|wasserstand)\b.*$", 1.0),
        (r"^(?:.*\s)?(?:steigt|fällt|sinkt) die lahn\b.*$", 1.0),
    ),
    exclude=(r"\b(?:wetter|regen)\b",),
)(_water_level)


async def _water_flood(req: Request) -> SkillResult | None:
    problem, found = await _gauge(req)
    if problem is not None:
        return problem
    gauge, _ = found
    providers = _providers(req)
    messages = []
    if providers is not None and req.svc.cfg.warnings.nina_ars:
        try:
            messages = [
                m
                for m in (await providers.civil_warnings()).data
                if "hochwasser" in m.title.lower()
            ]
        except ProviderUnavailable:
            messages = []
    high = gauge.state == "high" or (gauge.high_cm is not None and gauge.value_cm >= gauge.high_cm)
    if high:
        text = f"Ja, die Lahn am Pegel {gauge.name} ist mit {_level(gauge.value_cm)} deutlich erhöht, {_TREND.get(gauge.trend, 'gleichbleibend')}"
    else:
        text = f"Nein, die Lahn am Pegel {gauge.name} steht mit {_level(gauge.value_cm)} im üblichen Bereich"
    if messages:
        text += f". Der Bevölkerungsschutz meldet: {messages[0].title}"
    return SkillResult(
        text=g.sentence(text), sources=(PEGEL_SOURCE,), serious=high or bool(messages)
    )


skill(
    "water.flood",
    group=GROUP,
    online=True,
    priority="S",
    max_words=10,
    examples=("Gibt es Hochwasser?", "Ist was mit Hochwasser?"),
    patterns=((_line(r"hochwasser\w*", r"überschwemmung\w*"), 1.05),),
)(_water_flood)


# -- waste ---------------------------------------------------------------------------------------------------
async def _pickups(req: Request, first: date, last: date):
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("waste", "offline"), "Abfalldaten"), None
    if not req.svc.cfg.waste.enabled:
        return SkillResult(text="Der Abfallkalender ist bei mir ausgeschaltet.", serious=True), None
    try:
        fetched = await providers.waste_calendar()
    except ProviderUnavailable as exc:
        if exc.reason in {"nosource", "nofile"}:
            return SkillResult(
                text="Einen Abfallkalender habe ich noch nicht. Trag in der Konfiguration unter skills.waste einen iCal-Link ein.",
                serious=True,
            ), None
        return unavailable(exc, "Abfalldaten"), None
    except Exception as exc:
        from moritz_agent.skills.providers.http import HttpError

        if isinstance(exc, HttpError):
            return SkillResult(
                text="Der Abfallkalender ist nicht erlaubt oder nicht erreichbar.", serious=True
            ), None
        raise
    return None, ics.parse(fetched.data, first, last)


_KIND_WORDS = (
    ("Biotonne", r"bio\w*"),
    ("Papiertonne", r"papier\w*|blaue\w* tonne|altpapier"),
    ("gelbe Tonne", r"gelbe\w*|wertstoff\w*|gelber sack"),
    ("Restmülltonne", r"rest\w*|schwarze\w* tonne|graue\w* tonne|hausmüll"),
    ("Sperrmüll", r"sperr\w*"),
    ("Glascontainer", r"glas\w*"),
)


def _asked_kind(text: str) -> str | None:
    for name, pattern in _KIND_WORDS:
        if re.search(rf"\b(?:{pattern})\b", text):
            return name
    return None


def _noun_phrase(kind: str) -> str:
    return {
        "Biotonne": "die Biotonne",
        "Papiertonne": "die Papiertonne",
        "gelbe Tonne": "die gelbe Tonne",
        "Restmülltonne": "die Restmülltonne",
        "Sperrmüll": "der Sperrmüll",
        "Glascontainer": "der Glascontainer",
    }.get(kind, kind)


async def _waste_next(req: Request) -> SkillResult | None:
    today = req.now.date()
    problem, pickups = await _pickups(req, today, today + timedelta(days=400))
    if problem is not None:
        return problem
    assert pickups is not None
    kind = _asked_kind(req.text)
    when = find_when(req.text, req.now)
    if kind is not None:
        for pickup in pickups:
            if ics.kind_of(pickup.summary) == kind and pickup.day >= today:
                delta = (pickup.day - today).days
                when_text = (
                    g.day_label(pickup.day, today)
                    if delta <= 1
                    else f"am {WEEKDAYS_DE[pickup.day.weekday()]}, {g.date_plain(pickup.day)}"
                )
                word = {
                    "Sperrmüll": "Der nächste Sperrmüll",
                    "Glascontainer": "Der nächste Glascontainer",
                }.get(kind, f"Die nächste {kind}" if kind != "Biotonne" else "Die nächste Biotonne")
                verb = "wird abgeholt" if kind not in {"Glascontainer"} else "wird geleert"
                return SkillResult(
                    text=g.sentence(f"{word} {verb} {when_text}"),
                    data={"day": pickup.day.isoformat()},
                )
        return SkillResult(
            text=f"Für {kind} finde ich in meinem Kalender keinen Termin.", serious=True
        )
    day = (
        when.day
        if when is not None and when.day is not None
        else today + timedelta(days=1 if re.search(r"\bmorgen\b", req.text) else 0)
    )
    kinds = sorted({ics.kind_of(p.summary) for p in pickups if p.day == day})
    label = g.day_label(day, today)
    if not kinds:
        return SkillResult(
            text=g.sentence(f"{label.capitalize()} wird nichts abgeholt"),
            data={"pickups": 0, "day": day.isoformat()},
        )
    phrase = g.join_and([_noun_phrase(k) for k in kinds])
    verb = "wird" if len(kinds) == 1 else "werden"
    return SkillResult(
        text=g.sentence(f"{label.capitalize()} {verb} {phrase} abgeholt"),
        data={"pickups": len(kinds), "day": day.isoformat()},
    )


skill(
    "waste.next",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    help="die Müllabfuhr",
    examples=("Welche Tonne kommt morgen?", "Wann kommt die gelbe Tonne?", "Wann ist Sperrmüll?"),
    patterns=(
        (
            r"^(?:.*\s)?(?:wann|welche[rsmn]?|was)\b.*\b(?:\w*tonne\w*|\w*müll\w*|\w*abfuhr|altpapier|gelber sack|gelbe säcke)\b.*$",
            1.0,
        ),
        (
            r"^(?:.*\s)?(?:\w*tonne\w*|\w*müll\w*|altpapier|gelber sack)\b.*\b(?:kommt|abgeholt|geleert|abholung|rausstellen|raus)\b.*$",
            1.0,
        ),
        (r"^(?:.*\s)?(?:müllabfuhr|abfuhrkalender|abfallkalender|müllkalender)\b.*$", 1.0),
    ),
    exclude=(r"\b(?:rechner|gruppenchat|mülleimer kaufen)\b",),
)(_waste_next)


async def _waste_week(req: Request) -> SkillResult | None:
    today = req.now.date()
    when = find_when(req.text, req.now)
    first = max(when.start.date(), today) if when is not None else today
    last = (
        (when.end - timedelta(seconds=1)).date()
        if when is not None
        else today + timedelta(days=(6 - today.weekday()))
    )
    if last - first < timedelta(days=3):
        last = first + timedelta(days=6)  # the rest of the week is short: look a week ahead
    problem, pickups = await _pickups(req, first, last)
    if problem is not None:
        return problem
    assert pickups is not None
    if not pickups:
        return SkillResult(text="In diesem Zeitraum wird nichts abgeholt.")
    pieces = [
        f"{g.day_label(p.day, today)} {_noun_phrase(ics.kind_of(p.summary))}" for p in pickups[:5]
    ]
    return SkillResult(text=g.sentence("Abgeholt wird: " + "; ".join(pieces)))


skill(
    "waste.week",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Was wird diese Woche abgeholt?",),
    patterns=(
        (
            r"^(?:.*\s)?was wird (?:\w+ )?(?:woche|nächste woche|diese woche)\b.*\babgeholt\b.*$",
            1.05,
        ),
    ),
)(_waste_week)


# -- football --------------------------------------------------------------------------------------------------
async def _football(req: Request, mode: str) -> SkillResult | None:
    cfg = req.svc.cfg.football
    if not cfg.enabled:
        return SkillResult(text="Fußballergebnisse sind bei mir ausgeschaltet.", serious=True)
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("liga", "offline"), "Fußballdaten")
    today = req.now.date()
    try:
        if mode == "table":
            table = (await providers.football_table(today)).data
            for row in table:
                if cfg.team.lower().split()[0] in row.team.lower():
                    return SkillResult(
                        text=g.sentence(
                            f"{row.team} steht auf Platz {row.rank} mit {row.points} Punkten nach {row.matches} Spielen"
                        ),
                        sources=(LIGA_SOURCE,),
                    )
            return SkillResult(text=f"{cfg.team} finde ich in der Tabelle nicht.", serious=True)
        matches = (await providers.football_matches(today)).data
    except ProviderUnavailable as exc:
        return unavailable(exc, "Fußballdaten")
    now = req.now
    if mode == "last":
        played = [m for m in matches if m.finished and m.start <= now]
        if not played:
            return SkillResult(
                text="Ein abgeschlossenes Spiel finde ich gerade nicht.", serious=True
            )
        match = played[-1]
        us_home = cfg.team.lower().split()[0] in match.home.lower()
        ours, theirs = (
            (match.goals_home, match.goals_away)
            if us_home
            else (match.goals_away, match.goals_home)
        )
        other = match.away if us_home else match.home
        word = (
            "gewonnen"
            if ours > theirs
            else "verloren"
            if ours < theirs
            else "unentschieden gespielt"
        )
        day = g.day_label(match.start.date(), now.date())
        day = (
            day
            if (now.date() - match.start.date()).days <= 1
            else f"am {WEEKDAYS_DE[match.start.weekday()]}"
        )
        if word == "unentschieden gespielt":
            text = f"{cfg.team} hat {day} {ours} zu {theirs} unentschieden gegen {other} gespielt"
        else:
            text = f"{cfg.team} hat {day} {max(ours, theirs)} zu {min(ours, theirs)} gegen {other} {word}"
        return SkillResult(text=g.sentence(text), sources=(LIGA_SOURCE,))
    upcoming = [m for m in matches if m.start > now]
    if not upcoming:
        return SkillResult(
            text="Ein nächstes Spiel finde ich im Spielplan gerade nicht.", serious=True
        )
    match = upcoming[0]
    us_home = cfg.team.lower().split()[0] in match.home.lower()
    other = match.away if us_home else match.home
    delta = (match.start.date() - now.date()).days
    day = (
        g.day_label(match.start.date(), now.date())
        if delta <= 1
        else f"am {WEEKDAYS_DE[match.start.weekday()]}, {g.date_plain(match.start.date())}"
    )
    place = "zu Hause" if us_home else "auswärts"
    return SkillResult(
        text=g.sentence(
            f"Das nächste Spiel ist {day} um {g.clock_digital(match.start)} {place} gegen {other}"
        ),
        sources=(LIGA_SOURCE,),
    )


async def _football_last(req: Request) -> SkillResult | None:
    return await _football(req, "last")


async def _football_next(req: Request) -> SkillResult | None:
    return await _football(req, "next")


async def _football_table(req: Request) -> SkillResult | None:
    return await _football(req, "table")


skill(
    "football.last",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Wie hat die Eintracht gespielt?",),
    patterns=(
        (
            r"^(?:.*\s)?wie (?:hat|haben) (?:\w+ )?(?:eintracht|die eintracht|frankfurt|unsere jungs)\b.*\b(?:gespielt|gewonnen|verloren)\b.*$",
            1.0,
        ),
        (_line(r"letzte[sn]? spiel\w*", r"spielergebnis\w*"), 0.95),
    ),
)(_football_last)

skill(
    "football.next",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Wann spielt die Eintracht?",),
    patterns=(
        (r"^(?:.*\s)?wann spielt (?:\w+ )?(?:eintracht|die eintracht|frankfurt)\b.*$", 1.0),
        (_line(r"nächste[sn]? spiel\w*"), 0.95),
    ),
)(_football_next)

skill(
    "football.table",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Auf welchem Platz steht die Eintracht?",),
    patterns=(
        (
            r"^(?:.*\s)?(?:welchem platz|tabelle|tabellenplatz)\b.*\b(?:eintracht|frankfurt)?\b.*$",
            0.95,
        ),
    ),
    exclude=(r"\b(?:wetter|parkplatz|sitzplatz)\b",),
)(_football_table)


# -- news --------------------------------------------------------------------------------------------------------
async def _headlines(req: Request) -> SkillResult | None:
    cfg = req.svc.cfg.news
    if not cfg.enabled:
        return SkillResult(text="Nachrichten sind bei mir ausgeschaltet.", serious=True)
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("news", "offline"), "Nachrichten")
    try:
        fetched = await providers.headlines()
    except ProviderUnavailable as exc:
        return unavailable(exc, "Nachrichten")
    titles = fetched.data
    if not titles:
        return SkillResult(text="Ich finde gerade keine Schlagzeilen.", serious=True)
    text = "Laut tagesschau.de: " + "; ".join(titles)
    return SkillResult(text=g.sentence(text), sources=(NEWS_SOURCE,), data={"count": len(titles)})


skill(
    "news.headlines",
    group=GROUP,
    online=True,
    priority="K",
    max_words=8,
    examples=("Was gibt's Neues?", "Nachrichten?"),
    patterns=(
        (r"^(?:.*\s)?(?:nachrichten|schlagzeilen|neuigkeiten)\b.*$", 1.0),
        (r"^was gibt es neues$", 1.0),
    ),
)(_headlines)


# -- notes ------------------------------------------------------------------------------------------------------------
def _list_name(text: str) -> str:
    return "einkaufsliste" if re.search(r"einkaufs|einkauf|shopping", text) else "notizen"


def _list_label(name: str) -> str:
    return "Einkaufsliste" if name == "einkaufsliste" else "Notizen"


def _notes_enabled(req: Request) -> SkillResult | None:
    if not req.svc.cfg.notes.enabled or req.svc.store is None:
        return SkillResult(text="Notizen sind bei mir ausgeschaltet.", serious=True)
    if req.ctx.role != "owner":  # docs/plan/14 §5.1: the notes are Moritz' alone
        return SkillResult(text="Auf die Notizen hast du bei mir keinen Zugriff.", serious=True)
    return None


async def _notes_add(req: Request) -> SkillResult | None:
    off = _notes_enabled(req)
    if off:
        return off
    match = re.search(
        r"(?:schreib|schreibe|setz|setze|pack|packe|tu|tue|trag|trage|notier|notiere|merk dir|merke dir)\s+(.+?)\s+(?:auf|in|ein auf) (?:die |meine |der )?(?:einkaufsliste|einkaufszettel|liste|notizen)\b",
        req.text,
    )
    if match is None:
        match = re.search(
            r"(?:notiz|notier|notiere|merk dir|merke dir|merk|schreib auf|schreibe auf)\s*:?\s+(.+)$",
            req.text,
        )
    if match is None:
        return None
    item = match.group(1).strip(" .,")
    item = re.sub(r"^(?:bitte |mal )+", "", item)
    item = item[:1].upper() + item[1:]
    if not item or len(item) > 120:
        return None
    name = _list_name(req.text)
    req.svc.store.add(name, item)
    where = "auf die Einkaufsliste" if name == "einkaufsliste" else "in deine Notizen"
    return SkillResult(text=g.sentence(f"Ich habe {item} {where} geschrieben"))


skill(
    "notes.add",
    group=GROUP,
    priority="K",
    max_words=12,
    examples=("Schreib Milch auf die Einkaufsliste.", "Notiz: Reifen wechseln."),
    patterns=(
        (
            r"^(?:.*\s)?(?:schreib|schreibe|setz|setze|pack|packe|tu|tue|trag|trage|notier|notiere|merk dir|merke dir)\b.*\b(?:einkaufsliste|einkaufszettel|liste|notizen)\b.*$",
            1.0,
        ),
        (r"^(?:notiz|notizen?)\s*:?\s+\S.*$", 1.0),
        (r"^(?:merk dir|merke dir|notier|notiere)\s+\S.*$", 0.95),
    ),
    exclude=(r"\b(?:lies|lese|vorlesen|was steht)\b",),
)(_notes_add)


async def _notes_read(req: Request) -> SkillResult | None:
    off = _notes_enabled(req)
    if off:
        return off
    name = _list_name(req.text)
    items = req.svc.store.read(name)
    label = _list_label(name)
    if not items:
        return SkillResult(
            text=f"Auf der {label} steht nichts."
            if name == "einkaufsliste"
            else "Du hast keine Notizen."
        )
    if name == "einkaufsliste":
        start = "Auf der Einkaufsliste steht" if len(items) == 1 else "Auf der Einkaufsliste stehen"
    else:
        start = "Deine Notiz ist" if len(items) == 1 else "Deine Notizen sind"
    return SkillResult(
        text=g.sentence(f"{start} {g.join_and(items[:15])}"), data={"count": len(items)}
    )


skill(
    "notes.read",
    group=GROUP,
    priority="K",
    max_words=10,
    examples=("Was steht auf der Einkaufsliste?", "Lies meine Notizen vor."),
    patterns=(
        (
            r"^(?:.*\s)?was steht (?:auf|in) (?:der |meiner |meinen |den )?(?:einkaufsliste|einkaufszettel|liste|notizen)\b.*$",
            1.0,
        ),
        (r"^(?:.*\s)?(?:lies|lese|les)\b.*\b(?:einkaufsliste|notizen|liste)\b.*$", 1.0),
    ),
)(_notes_read)


async def _notes_clear(req: Request) -> SkillResult | None:
    off = _notes_enabled(req)
    if off:
        return off
    name = _list_name(req.overrides.get("list", req.text))
    if req.overrides.get("yes"):
        removed = req.svc.store.clear(req.overrides["list"])
        return SkillResult(
            text=f"Okay, {_list_label(req.overrides['list'])} ist gelöscht, {g.plural(removed, 'Eintrag', 'Einträge')}."
        )
    if req.overrides.get("no"):
        return SkillResult(text="Alles klar, ich lasse es.")
    items = req.svc.store.read(name)
    if not items:
        return SkillResult(text="Da steht ohnehin nichts.")
    question = f"Wirklich alles löschen? Auf der {_list_label(name)} stehen {g.plural(len(items), 'Eintrag', 'Einträge')}."
    return SkillResult(
        text=question,
        clarify=Clarification(
            question,
            (
                Option("Ja", {"yes": True, "list": name}, ("löschen",)),
                Option("Nein", {"no": True, "list": name}, ("behalten",)),
            ),
            "notes.clear",
        ),
    )


skill(
    "notes.clear",
    group=GROUP,
    priority="K",
    max_words=10,
    examples=("Lösch die Einkaufsliste.",),
    patterns=(
        (r"^(?:.*\s)?(?:lösch|lösche|leere|leer)\b.*\b(?:einkaufsliste|notizen|liste)\b.*$", 1.0),
    ),
)(_notes_clear)

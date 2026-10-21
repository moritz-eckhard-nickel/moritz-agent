# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Sun, moon and seasons, all offline (docs/plan/13 §6.9, §8.5)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from moritz_agent.skills.astro import moon, seasons, sun
from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.catalog.common import say
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.router import followup_state
from moritz_agent.skills.weather.frame import Resolved, resolve
from moritz_agent.tools.time_tool import WEEKDAYS_DE

GROUP = "himmel"


def _line(*alternatives: str) -> str:
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


def _cap(text: str) -> str:
    """First letter upper case, the rest untouched ("am Montag, dem 21. Juni" → "Am Montag, …")."""
    return text[:1].upper() + text[1:]


def _minute(moment: datetime) -> datetime:
    """Round to the nearest minute (the voice never says seconds)."""
    return (moment + timedelta(seconds=30)).replace(second=0, microsecond=0)


def _clock(moment: datetime) -> str:
    return g.clock_digital(_minute(moment))


def _day_word(day: date, today: date) -> str:
    return g.day_label(day, today)


async def _where(req: Request, skill_id: str) -> Resolved | SkillResult:
    return await resolve(req, skill_id, parse_when=True)


def _target_day(resolved: Resolved) -> date:
    when = resolved.when
    return when.day if when is not None and when.day is not None else resolved.now.date()


def _in(resolved: Resolved) -> str:
    return f"in {resolved.place.spoken}"


def _follow(skill_id: str, resolved: Resolved):
    return followup_state(skill_id, where=resolved.where, when=resolved.when)


# -- sunrise and sunset ----------------------------------------------------------------------------
async def _sun_rise_set(req: Request) -> SkillResult | None:
    resolved = await _where(req, "sun.rise_set")
    if not isinstance(resolved, Resolved):
        return resolved
    place, now = resolved.place, resolved.now
    day = _target_day(resolved)
    times = sun.sun_day(place.lat, place.lon, day, place.tz)
    text = req.text
    wants_rise = bool(re.search(r"\b(?:aufgang|aufgeht|aufgehen|auf)\b|\bhell wird\b", text))
    wants_set = bool(re.search(r"\b(?:untergang|untergeht|untergehen|unter)\b", text))
    both = wants_rise == wants_set
    label = _day_word(day, now.date())
    where = _in(resolved)
    if times.sunrise is None or times.sunset is None:
        polar = "Polartag" if times.noon_elevation > 0 else "Polarnacht"
        return say(f"{_cap(label)} ist {where} {polar}: Die Sonne geht nicht auf und nicht unter.")
    rise, set_ = _clock(times.sunrise), _clock(times.sunset)
    today = day == now.date()
    if both:
        if not today or now < times.sunrise:
            reply = f"{_cap(label)} geht {where} die Sonne um {rise} auf und um {set_} unter."
        elif now < times.sunset:
            reply = f"Heute ist {where} die Sonne um {rise} aufgegangen und geht um {set_} unter."
        else:
            tomorrow = sun.sun_day(place.lat, place.lon, day + timedelta(days=1), place.tz)
            reply = (
                f"Heute ist {where} die Sonne um {rise} aufgegangen und um {set_} untergegangen. "
                f"Morgen geht sie um {_clock(tomorrow.sunrise)} auf."
                if tomorrow.sunrise
                else f"Heute ist {where} die Sonne um {set_} untergegangen."
            )
    elif wants_rise:
        if not today or now < times.sunrise:
            reply = f"{_cap(label)} geht {where} die Sonne um {rise} auf."
        else:
            reply = f"Heute ist {where} die Sonne um {rise} aufgegangen."
            tomorrow = sun.sun_day(place.lat, place.lon, day + timedelta(days=1), place.tz)
            if tomorrow.sunrise:
                reply += f" Morgen geht sie um {_clock(tomorrow.sunrise)} auf."
    else:
        if not today or now < times.sunset:
            reply = f"{_cap(label)} geht {where} die Sonne um {set_} unter."
        else:
            reply = f"Heute ist {where} die Sonne um {set_} untergegangen."
            tomorrow = sun.sun_day(place.lat, place.lon, day + timedelta(days=1), place.tz)
            if tomorrow.sunset:
                reply += f" Morgen geht sie um {_clock(tomorrow.sunset)} unter."
    return SkillResult(
        text=reply,
        followup=_follow("sun.rise_set", resolved),
        data={
            "sunrise": _minute(times.sunrise).isoformat(),
            "sunset": _minute(times.sunset).isoformat(),
        },
    )


skill(
    "sun.rise_set",
    group=GROUP,
    priority="M",
    max_words=12,
    help="Sonnenaufgang und Sonnenuntergang",
    examples=(
        "Wann geht die Sonne auf?",
        "Wann ist morgen Sonnenuntergang in Berlin?",
        "Wann geht die Sonne unter?",
    ),
    patterns=(
        (_line(r"sonnenaufgang\w*", r"sonnenuntergang\w*"), 1.0),
        (
            r"^(?:.*\s)?wann geht (?:morgen |heute |übermorgen )?die sonne (?:\w+ )*?(?:auf|unter)\b.*$",
            1.0,
        ),
        (r"^(?:.*\s)?wann geht die sonne\b.*$", 0.95),
    ),
    exclude=(r"\bmond\b", r"\bwetter\b"),
    followup=lambda rest, ctx, svc, last: _sun_followup(rest, svc),
)(_sun_rise_set)


def _sun_followup(rest: str, svc):
    from moritz_agent.skills.slots.when import find_when
    from moritz_agent.skills.slots.where import find_places

    if re.match(
        r"^(?:wie|wann|wo|was|welche[rmns]?|ist|gibt|kann|haben|wird|werden|brauch\w*)\b", rest
    ):
        return None  # a full question carries its own place and day
    params = {}
    when = find_when(rest, svc.now())
    if when is not None and re.search(
        r"\b(?:heute|morgen|übermorgen|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
        rest,
    ):
        params["when"] = when
    places = find_places(rest, svc, None)
    if places:
        params["where"] = places[0]
    return params or None


# -- hell and dark -----------------------------------------------------------------------------------
async def _sun_dark(req: Request) -> SkillResult | None:
    resolved = await _where(req, "sun.dark")
    if not isinstance(resolved, Resolved):
        return resolved
    place, now = resolved.place, resolved.now
    today = sun.sun_day(place.lat, place.lon, now.date(), place.tz)
    tomorrow = sun.sun_day(place.lat, place.lon, now.date() + timedelta(days=1), place.tz)
    if today.dawn is None or today.dusk is None:
        return say("Hier wird es um diese Jahreszeit nicht richtig dunkel oder hell.")
    text = req.text
    where = f" {_in(resolved)}" if resolved.where.kind != "home" else ""
    daylight = today.dawn <= now < today.dusk
    asked = re.search(
        r"\b(?:noch|schon|draußen|ist es|es ist)(?: schon| noch| draußen)? (hell|dunkel)\b", text
    )
    if asked and not re.search(r"\b(?:wann|wie ?lange|wie ?viel uhr)\b", text):  # a yes/no question
        yes, no = ("Ja", "Nein") if asked.group(1) == "hell" else ("Nein", "Ja")
        if daylight:
            return say(f"{yes}, es ist noch hell{where}, bis etwa {_clock(today.dusk)}.")
        if now < today.dawn:
            return say(f"{no}, es ist noch dunkel{where}, hell wird es gegen {_clock(today.dawn)}.")
        return say(f"{no}, es ist schon dunkel{where}, seit etwa {_clock(today.dusk)}.")
    if re.search(r"\bhell\b", text) and not re.search(r"\bdunkel\b", text):
        if now < today.dawn:
            return say(f"Es wird heute{where} gegen {_clock(today.dawn)} hell.")
        if tomorrow.dawn:
            return say(f"Morgen wird es{where} gegen {_clock(tomorrow.dawn)} hell.")
    if now < today.dusk:
        return say(f"Heute wird es{where} gegen {_clock(today.dusk)} richtig dunkel.")
    if tomorrow.dusk:
        return say(
            f"Heute ist es schon dunkel{where}. Morgen wird es gegen {_clock(tomorrow.dusk)} dunkel."
        )
    return None


skill(
    "sun.dark",
    group=GROUP,
    priority="S",
    max_words=10,
    examples=("Wann wird es dunkel?", "Wann wird es hell?", "Ist es draußen noch hell?"),
    patterns=(
        (r"^(?:.*\s)?wann wird es (?:\w+ )?(?:dunkel|hell)\b.*$", 1.0),
        (r"^(?:.*\s)?ist es (?:draußen )?(?:noch |schon )?(?:hell|dunkel)\b.*$", 1.0),
        (r"^(?:.*\s)?wann (?:ist|wird) (?:es )?(?:heute |morgen )?dunkel\b.*$", 1.0),
    ),
    exclude=(r"\bmond\b", r"\bwie lange (?:ist|wird) es (?:heute |morgen )?hell\b"),
)(_sun_dark)


async def _daylength(req: Request) -> SkillResult | None:
    resolved = await _where(req, "sun.daylength")
    if not isinstance(resolved, Resolved):
        return resolved
    place, now = resolved.place, resolved.now
    day = _target_day(resolved)
    today = sun.sun_day(place.lat, place.lon, day, place.tz)
    before = sun.sun_day(place.lat, place.lon, day - timedelta(days=1), place.tz)
    if today.daylight is None:
        return say("Hier gibt es um diese Jahreszeit keinen normalen Tag.")
    minutes = round(today.daylight.total_seconds() / 60)
    hours, rest = divmod(minutes, 60)
    length = f"{g.plural(hours, 'Stunde', 'Stunden')} und {g.plural(rest, 'Minute', 'Minuten')}"
    text = f"{_cap(_day_word(day, now.date()))} ist es {_in(resolved)} {length} hell"
    if before.daylight is not None:
        diff = round((today.daylight - before.daylight).total_seconds() / 60)
        than = "gestern" if day == now.date() else "am Tag davor"
        if diff:
            text += f", {g.plural(abs(diff), 'Minute', 'Minuten')} {'mehr' if diff > 0 else 'weniger'} als {than}"
    return say(g.sentence(text))


skill(
    "sun.daylength",
    group=GROUP,
    priority="S",
    max_words=12,
    examples=("Wie lange ist es heute hell?", "Wie viel kürzer werden die Tage?"),
    patterns=(
        (r"^(?:.*\s)?wie lange ist es (?:\w+ )?(?:noch )?hell\b.*$", 1.0),
        (r"^(?:.*\s)?(?:tageslänge|länge des tages|sonnenstunden)\b.*$", 0.9),
        (r"^(?:.*\s)?wie viel (?:kürzer|länger) werden die tage\b.*$", 1.0),
        (r"^(?:.*\s)?wie lang ist der tag\b.*$", 1.0),
    ),
    exclude=(r"\bwetter\b",),
)(_daylength)


async def _noon(req: Request) -> SkillResult | None:
    resolved = await _where(req, "sun.noon")
    if not isinstance(resolved, Resolved):
        return resolved
    place, now = resolved.place, resolved.now
    day = _target_day(resolved)
    times = sun.sun_day(place.lat, place.lon, day, place.tz)
    height = round(times.noon_elevation)
    return say(
        g.sentence(
            f"{_cap(_day_word(day, now.date()))} steht die Sonne {_in(resolved)} gegen "
            f"{_clock(times.noon)} am höchsten, {height} Grad über dem Horizont"
        )
    )


skill(
    "sun.noon",
    group=GROUP,
    priority="K",
    max_words=10,
    examples=("Wann steht die Sonne am höchsten?",),
    patterns=(
        (r"^(?:.*\s)?wann steht die sonne am höchsten\b.*$", 1.0),
        (r"^(?:.*\s)?sonnenhöchststand\b.*$", 1.0),
    ),
)(_noon)


async def _golden(req: Request) -> SkillResult | None:
    resolved = await _where(req, "sun.golden_hour")
    if not isinstance(resolved, Resolved):
        return resolved
    place, now = resolved.place, resolved.now
    day = _target_day(resolved)
    times = sun.sun_day(place.lat, place.lon, day, place.tz)
    if times.golden_start is None or times.sunset is None:
        return say("Hier gibt es um diese Jahreszeit keine goldene Stunde.")
    return say(
        g.sentence(
            f"{_cap(_day_word(day, now.date()))} beginnt die goldene Stunde {_in(resolved)} gegen "
            f"{_clock(times.golden_start)} und endet mit dem Sonnenuntergang um {_clock(times.sunset)}"
        )
    )


skill(
    "sun.golden_hour",
    group=GROUP,
    priority="K",
    max_words=10,
    examples=("Wann ist die goldene Stunde?",),
    patterns=(
        (_line(r"goldene stunde", r"golden hour", r"beste[sn]? licht\w*", r"fotografieren"), 1.0),
    ),
)(_golden)


def _next_solstice(now: datetime, season: str) -> datetime:
    this = seasons.season_start(now.year, season, str(now.tzinfo))
    return this if this > now else seasons.season_start(now.year + 1, season, str(now.tzinfo))


async def _solstice(req: Request) -> SkillResult | None:
    now = req.now
    zone = str(now.tzinfo)
    text = req.text
    wants_longer = bool(re.search(r"\blänger\b", text)) or not re.search(r"\bkürzer\b", text)
    summer = seasons.season_start(now.year, "summer", zone)
    winter = seasons.season_start(now.year, "winter", zone)
    lengthening = winter <= now or now < summer  # between the winter and the summer solstice
    if re.search(r"\bam (?:längsten|kürzesten)\b", text):
        target = _next_solstice(now, "summer" if "längsten" in text else "winter")
        what = "am längsten" if "längsten" in text else "am kürzesten"
        return say(
            g.sentence(
                f"Die Tage sind {what} um die {'Sommer' if 'längsten' in text else 'Winter'}sonnenwende, "
                f"das ist am {g.date_plain(target.date())}"
            )
        )
    if wants_longer:
        if lengthening:
            target = _next_solstice(now, "summer")
            return say(
                g.sentence(
                    f"Die Tage werden schon länger, noch bis zur Sommersonnenwende am {g.date_plain(target.date())}"
                )
            )
        target = _next_solstice(now, "winter")
        return say(
            g.sentence(
                f"Ab dem {g.date_plain(target.date())}, der Wintersonnenwende, werden die Tage wieder länger"
            )
        )
    if lengthening:
        target = _next_solstice(now, "summer")
        return say(
            g.sentence(
                f"Ab dem {g.date_plain(target.date())}, der Sommersonnenwende, werden die Tage wieder kürzer"
            )
        )
    target = _next_solstice(now, "winter")
    return say(
        g.sentence(
            f"Die Tage werden schon kürzer, noch bis zur Wintersonnenwende am {g.date_plain(target.date())}"
        )
    )


skill(
    "sun.solstice",
    group=GROUP,
    priority="S",
    max_words=12,
    examples=("Ab wann werden die Tage wieder länger?", "Wann sind die Tage am kürzesten?"),
    patterns=(
        (r"^(?:.*\s)?ab wann werden die tage (?:\w+ )?(?:länger|kürzer)\b.*$", 1.0),
        (r"^(?:.*\s)?wann sind die tage am (?:längsten|kürzesten)\b.*$", 1.0),
        (_line(r"sonnenwende\w*", r"wintersonnenwende", r"sommersonnenwende"), 1.0),
    ),
)(_solstice)


# -- moon ---------------------------------------------------------------------------------------------
def _moon_now(now: datetime) -> tuple[float, float]:
    jd = sun.julian_day(now)
    return moon.elongation(jd), moon.illumination(jd)


def _datum(moment: datetime, today: date) -> str:
    day = moment.date()
    delta = (day - today).days
    if 0 <= delta <= 1:
        return f"{g.day_label(day, today)} um {_clock(moment)}"
    return f"am {WEEKDAYS_DE[day.weekday()]}, {g.date_plain(day)}, um {_clock(moment)}"


async def _moon_phase(req: Request) -> SkillResult | None:
    now = req.now
    angle, lit = _moon_now(now)
    name = moon.phase_name(angle)
    nxt_full = moon.next_phase("full", now)
    nxt_new = moon.next_phase("new", now)
    asks_full = bool(re.search(r"\bvollmond\b", req.text)) and re.search(
        r"\b(?:ist|haben)\b", req.text
    )
    asks_new = bool(re.search(r"\bneumond\b", req.text)) and re.search(
        r"\b(?:ist|haben)\b", req.text
    )
    if asks_full or asks_new:
        full = asks_full
        close = abs(angle - 180) < 12 if full else min(angle, 360 - angle) < 12
        target = nxt_full if full else nxt_new
        word = "Vollmond" if full else "Neumond"
        if close:
            kind = "full" if full else "new"
            exact = min(
                (moon.previous_phase(kind, now), moon.next_phase(kind, now)),
                key=lambda moment: abs((moment - now).total_seconds()),
            )
            near = "" if exact.date() == now.date() else "fast "
            return say(f"Ja, heute ist {near}{word}.")
        when = f"{word} ist am {WEEKDAYS_DE[target.weekday()]}, {g.date_plain(target.date())}"
        return say(g.sentence(f"Nein, {when}"))
    percent = round(lit * 100)
    following = nxt_full if angle < 180 else nxt_new
    follow_name = "Vollmond" if angle < 180 else "Neumond"
    text = (
        f"{name[:1].upper() + name[1:]}, etwa {percent} Prozent beleuchtet; "
        f"{follow_name} ist am {WEEKDAYS_DE[following.weekday()]}, {g.date_plain(following.date())}"
    )
    return say(g.sentence(text), data={"phase": name, "illumination": percent})


skill(
    "moon.phase",
    group=GROUP,
    priority="S",
    max_words=12,
    help="Mond und Mondphasen",
    examples=("Welche Mondphase haben wir?", "Ist heute Vollmond?", "Wie sieht der Mond aus?"),
    patterns=(
        (
            _line(
                r"mondphase\w*",
                r"wie sieht der mond aus",
                r"wie (?:voll|groß) ist der mond",
                r"wie ist der mond",
            ),
            1.0,
        ),
        (r"^(?:.*\s)?ist (?:heute )?(?:vollmond|neumond)\b.*$", 1.0),
        (r"^(?:.*\s)?haben wir (?:heute )?(?:vollmond|neumond|halbmond)\b.*$", 1.0),
        (r"^(?:.*\s)?welcher mond\b.*$", 0.9),
        (r"^(?:.*\s)?(?:zunehmender|abnehmender) mond\b.*$", 0.9),
    ),
    exclude=(r"\bwann\b",),
)(_moon_phase)


async def _moon_next(req: Request) -> SkillResult | None:
    now = req.now
    text = req.text
    if "vollmond" in text:
        kind, word = "full", "Vollmond"
    elif "neumond" in text:
        kind, word = "new", "Neumond"
    elif re.search(r"halbmond|viertel", text):
        first, last = moon.next_phase("first_quarter", now), moon.next_phase("last_quarter", now)
        kind, word = (
            ("first_quarter", "zunehmende Halbmond")
            if first < last
            else ("last_quarter", "abnehmende Halbmond")
        )
    else:
        return None
    moment = moon.next_phase(kind, now)
    if word.endswith("Halbmond"):
        return say(g.sentence(f"Der nächste {word} ist {_datum(moment, now.date())}"))
    return say(
        g.sentence(f"Der nächste {word} ist {_datum(moment, now.date())}"),
        data={"at": moment.isoformat()},
    )


skill(
    "moon.next",
    group=GROUP,
    priority="S",
    max_words=12,
    examples=("Wann ist der nächste Vollmond?", "Wann ist Neumond?"),
    patterns=(
        (
            r"^(?:.*\s)?wann (?:ist|kommt|gibt es) (?:der |das )?(?:nächste[nrs]? )?(?:vollmond|neumond|halbmond)\b.*$",
            1.0,
        ),
        (r"^(?:.*\s)?nächste[nrs]? (?:vollmond|neumond|halbmond|mondviertel)\b.*$", 1.0),
    ),
)(_moon_next)


async def _moon_rise_set(req: Request) -> SkillResult | None:
    resolved = await _where(req, "moon.rise_set")
    if not isinstance(resolved, Resolved):
        return resolved
    place, now = resolved.place, resolved.now
    day = _target_day(resolved)
    rise, set_ = moon.rise_set(place.lat, place.lon, day, place.tz)
    label = _day_word(day, now.date())
    asks_rise = bool(re.search(r"\bauf\b|aufgang", req.text))
    asks_set = bool(re.search(r"\bunter\b|untergang", req.text))
    parts = []
    if rise and (asks_rise or not asks_set):
        parts.append(f"geht der Mond um etwa {_clock(rise)} auf")
    if set_ and (asks_set or not asks_rise):
        parts.append(
            f"um etwa {_clock(set_)} unter"
            if parts
            else f"geht der Mond um etwa {_clock(set_)} unter"
        )
    # the moon is up about 50 minutes longer each day, so one calendar day per month has no set
    # (or no rise): say when it happens instead
    wanted = "unter" if asks_set and not asks_rise else "auf" if asks_rise and not asks_set else ""
    if (wanted == "unter" and set_ is None) or (wanted == "auf" and rise is None):
        later = day + timedelta(days=1)
        next_rise, next_set = moon.rise_set(place.lat, place.lon, later, place.tz)
        when = next_set if wanted == "unter" else next_rise
        if when is not None:
            return say(
                f"{_cap(label)} geht der Mond {_in(resolved)} nicht {wanted}. "
                f"Das passiert erst {g.day_label(later, now.date())} um etwa {_clock(when)}."
            )
    if not parts:
        return say(f"{_cap(label)} geht der Mond {_in(resolved)} weder auf noch unter.")
    return say(g.sentence(f"{_cap(label)} {' und '.join(parts)}"))


skill(
    "moon.rise_set",
    group=GROUP,
    priority="K",
    max_words=10,
    examples=("Wann geht der Mond auf?", "Wann geht der Mond unter?"),
    patterns=(
        (r"^(?:.*\s)?wann geht (?:morgen |heute )?der mond (?:\w+ )*?(?:auf|unter)\b.*$", 1.0),
        (_line(r"mondaufgang\w*", r"monduntergang\w*"), 1.0),
    ),
)(_moon_rise_set)


# -- seasons -------------------------------------------------------------------------------------------
_SEASON_WORDS = {
    "frühling": "spring",
    "frühlingsanfang": "spring",
    "sommer": "summer",
    "sommeranfang": "summer",
    "herbst": "autumn",
    "herbstanfang": "autumn",
    "winter": "winter",
    "winteranfang": "winter",
}


async def _season(req: Request) -> SkillResult | None:
    text = req.text
    found = next(
        (s for word, s in _SEASON_WORDS.items() if re.search(rf"\b{word}\w*\b", text)), None
    )
    if found is None:
        return None
    now = req.now
    zone = str(now.tzinfo)
    start = seasons.season_start(now.year, found, zone)
    if start < now:
        start = seasons.season_start(now.year + 1, found, zone)
    month, day_ = seasons.meteorological_start(start.year, found)
    meteo = date(start.year, month, day_)
    astro_text = f"{g.date_plain(start.date())} um {_clock(start)}"
    name = seasons.NAMES[found]
    sentence = (
        f"Astronomisch beginnt der {name} am {astro_text}, "
        f"meteorologisch schon am {g.date_plain(meteo)}"
    )
    return say(g.sentence(sentence))


skill(
    "season.start",
    group=GROUP,
    priority="S",
    max_words=10,
    examples=("Wann ist Frühlingsanfang?", "Wann beginnt der Winter?"),
    patterns=(
        (
            r"^(?:.*\s)?wann (?:ist|beginnt|fängt) (?:der )?(?:frühling|sommer|herbst|winter)\w*(?: an)?\b.*$",
            1.0,
        ),
        (_line(r"frühlingsanfang", r"sommeranfang", r"herbstanfang", r"winteranfang"), 1.0),
    ),
    exclude=(r"\bferien\b", r"\bzeit\b", r"\bsommerzeit\b", r"\bwinterzeit\b"),
)(_season)


# -- stars --------------------------------------------------------------------------------------------------
async def _stars(req: Request) -> SkillResult | None:
    now = req.now
    angle, lit = _moon_now(now)
    percent = round(lit * 100)
    name = moon.phase_name(angle)
    if percent >= 85:
        moonlight = f"Der Mond ist mit {name} fast voll und hellt den Himmel stark auf"
    elif percent <= 15:
        moonlight = f"Mit {name} ist es dunkel genug, Sterne sieht man sehr gut"
    else:
        moonlight = f"Der Mond ist {name}, etwa {percent} Prozent beleuchtet"
    sky_note = ""
    providers = req.svc.providers
    if providers is not None:
        from moritz_agent.skills.providers import ProviderUnavailable
        from moritz_agent.skills.slots.where import home_place
        from moritz_agent.skills.weather.analysis import sky

        try:
            fetched = await providers.weather(home_place(req.svc, req.ctx))
            hours = fetched.data.hours_between(now, now + timedelta(hours=8))
            night = [h for h in hours if not h.is_day]
            if night:
                word = sky(night)
                if word in {"klar", "überwiegend klar"}:
                    sky_note = "Heute Nacht wird es überwiegend klar. "
                elif word in {"bedeckt", "stark bewölkt"}:
                    sky_note = "Heute Nacht ist es bewölkt, viel wirst du nicht sehen. "
                else:
                    sky_note = "Heute Nacht ist es wolkig. "
        except ProviderUnavailable:
            sky_note = ""
    return say(g.sentence(sky_note + moonlight) if sky_note else g.sentence(moonlight))


skill(
    "sky.stars",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Kann man heute Nacht Sterne sehen?",),
    patterns=((r"^(?:.*\s)?(?:sterne\w*|sternenhimmel|sternschnuppen?)\b.*$", 1.0),),
    exclude=(r"\bbewölkt\b",),
)(_stars)

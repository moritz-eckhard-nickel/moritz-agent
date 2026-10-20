# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Date and calendar: weekdays, date arithmetic, calendar weeks, holidays, school holidays, work days
(docs/plan/13 §6.2, §6.3)."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.calendar import holidays as hol
from moritz_agent.skills.calendar import school, workdays
from moritz_agent.skills.calendar.special import (
    SPECIAL_DAYS,
    find_special,
    next_occurrence,
    special_date,
)
from moritz_agent.skills.catalog.common import (
    dative_until,
    next_weekday,
    say,
    special_target,
    target_date,
    when_of,
)
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.slots.when import add_months, find_dates, find_when
from moritz_agent.tools.time_tool import MONTHS_DE, WEEKDAYS_DE

_ZODIAC = (
    ((1, 20), "Wassermann"), ((2, 19), "Fische"), ((3, 21), "Widder"), ((4, 20), "Stier"),
    ((5, 21), "Zwillinge"), ((6, 21), "Krebs"), ((7, 23), "Löwe"), ((8, 23), "Jungfrau"),
    ((9, 23), "Waage"), ((10, 23), "Skorpion"), ((11, 22), "Schütze"), ((12, 22), "Steinbock"),
)  # fmt: skip


def _workdays(req: Request) -> tuple[int, ...]:
    return tuple(req.svc.cfg.calendar.workdays)


def _state(req: Request) -> str:
    """Federal state for holidays: one named in the sentence ("in Bayern"), else the home state."""
    named = next(
        (
            c
            for w in re.findall(r"[a-zäöüß]+(?:-[a-zäöüß]+)?", req.text)
            if (c := hol.state_code(w))
        ),
        None,
    )
    return req.overrides.get("state") or named or req.svc.cfg.home.state


def _where(state: str) -> str:
    return "in Hessen" if state == "HE" else f"in {hol.state_names()[state]}"


# ---------------------------------------------------------------------------------------------
# date
# ---------------------------------------------------------------------------------------------
@skill(
    "date.today",
    group="kalender",
    priority="M",
    help="das Datum",
    examples=(
        "Welches Datum ist heute?",
        "Der Wievielte ist heute?",
        "Was hammer heit fürn Datum?",
    ),
    patterns=(
        r"\bwelches datum\b",
        r"\bder wievielte\b",
        r"\bden wievielten\b",
        r"\bdatum (?:haben wir|ist heute|heute)\b",
        r"\bheutige[sn]? datum\b",
        r"\bfür ?e?n datum\b",
        r"\bwas haben wir (?:heute )?für ein datum\b",
        r"\bwelcher tag ist heute\b.*\bdatum\b",
    ),
    exclude=(
        r"\b(?:morgen|übermorgen|gestern|vorgestern)\b",
        r"\b(?:in|vor) \d+ (?:tagen|wochen|monaten|jahren)\b",
        r"\buhrzeit\b",
        r"\btag des jahres\b",
    ),
)
async def date_today(req: Request) -> SkillResult:
    return say(f"Heute ist {g.date_long(req.now.date())}.")


@skill(
    "date.weekday",
    group="kalender",
    priority="M",
    help="den Wochentag",
    examples=("Welcher Tag ist heute?", "Welcher Wochentag ist heute?"),
    patterns=(
        r"\bwelcher tag (?:ist (?:es )?heute|haben wir)\b",
        r"\bwelcher wochentag(?: ist (?:es )?heute| haben wir)?\b",
        r"\bwas (?:ist|für ein tag ist) heute(?: für ein tag)?\b",
        r"\bwelchen wochentag\b",
        r"\bwas für ein tag ist heute\b",
    ),
    exclude=(
        r"\b(?:morgen|übermorgen|gestern|vorgestern)\b",
        r"\bdatum\b",
        r"\bder wievielte\b",
        r"\d",
    ),
)
async def date_weekday(req: Request) -> SkillResult:
    today = req.now.date()
    text = f"Heute ist {WEEKDAYS_DE[today.weekday()]}."
    holiday = hol.holiday_on(today, req.svc.cfg.home.state)
    if holiday:
        text = f"Heute ist {WEEKDAYS_DE[today.weekday()]} – und {holiday.name}."
    return say(text)


@skill(
    "date.relative",
    group="kalender",
    priority="M",
    help="den Tag morgen oder gestern",
    examples=(
        "Welcher Tag ist morgen?",
        "Welches Datum war gestern?",
        "Welcher Tag ist übermorgen?",
    ),
    patterns=(
        r"\bwelcher (?:wochen)?tag (?:ist|war|wird) (?:es )?(?:morgen|übermorgen|gestern|vorgestern)\b",
        r"\bwelches datum (?:ist|war|wird) (?:es )?(?:morgen|übermorgen|gestern|vorgestern)\b",
        r"\bwas (?:ist|war) (?:morgen|übermorgen|gestern|vorgestern)(?: für ein tag)?\b",
        r"\bder wievielte (?:ist|war|wird) (?:es )?(?:morgen|übermorgen|gestern|vorgestern)\b",
        r"\b(?:morgen|übermorgen|gestern|vorgestern) (?:ist|war) (?:welcher|der wievielte)\b",
    ),
)
async def date_relative(req: Request) -> SkillResult | None:
    today = req.now.date()
    word = re.search(r"\b(vorgestern|gestern|übermorgen|morgen)\b", req.text)
    if not word:
        return None
    offset = {"vorgestern": -2, "gestern": -1, "morgen": 1, "übermorgen": 2}[word.group(1)]
    day = today + timedelta(days=offset)
    verb = "war" if offset < 0 else "ist"
    label = word.group(1).capitalize()
    return say(f"{label} {verb} {g.date_long(day, with_year=False)}.")


@skill(
    "date.weekday_of",
    group="kalender",
    priority="M",
    help="den Wochentag eines Datums",
    examples=(
        "Was für ein Tag ist der 24. Dezember?",
        "Welcher Wochentag war der 3. Oktober 1990?",
    ),
    patterns=(
        r"\b(?:was für ein|welcher|welchen) (?:wochen)?tag (?:ist|war|wird|fällt)\b",
        r"\bauf welchen (?:wochen)?tag fällt\b",
        r"\bwelcher wochentag (?:ist|war|wird)\b",
        r"\bwelcher (?:wochen)?tag (?:ist|war) (?:der|das)\b",
        r"\ban welchem (?:wochen)?tag (?:ist|war|wird|findet)\b",
    ),
)
async def date_weekday_of(req: Request) -> SkillResult | None:
    text = req.text
    dates = find_dates(text, req.now)
    for key in ("heute",):
        if key in text:
            return None
    if not dates:
        return None
    day = dates[0]
    explicit_year = bool(re.search(r"\b\d{4}\b", text)) or bool(re.search(r"\.\d{2}\b", text))
    today = req.now.date()
    tense = "war" if day < today else "ist"
    when = g.date_plain(day, with_year=explicit_year or day.year != today.year)
    return say(f"Der {when} {tense} ein {WEEKDAYS_DE[day.weekday()]}.")


@skill(
    "date.offset",
    group="kalender",
    priority="S",
    examples=("Welches Datum ist in drei Wochen?", "Was ist heute in 100 Tagen?"),
    patterns=(
        r"\b(?:welches datum|welcher tag|der wievielte|was für ein datum)\b.*\b(?:in|vor) \d+ (?:tagen|wochen|monaten|jahren|tag|woche|monat|jahr)\b",
        r"\bwas ist (?:heute )?(?:in|vor) \d+ (?:tagen|wochen|monaten|jahren)\b",
        r"\b(?:in|vor) \d+ (?:tagen|wochen|monaten|jahren)\b.*\b(?:welches datum|welcher tag)\b",
    ),
)
async def date_offset(req: Request) -> SkillResult | None:
    m = re.search(r"\b(in|vor) (\d+) (tag|woche|monat|jahr)\w*\b", req.text)
    if not m:
        return None
    sign = 1 if m.group(1) == "in" else -1
    amount = int(m.group(2)) * sign
    unit = m.group(3)
    today = req.now.date()
    if unit == "tag":
        day = today + timedelta(days=amount)
    elif unit == "woche":
        day = today + timedelta(weeks=amount)
    elif unit == "monat":
        day = add_months(today, amount)
    else:
        day = add_months(today, 12 * amount)
    verb = "ist" if sign > 0 else "war"
    count = int(m.group(2))
    unit_words = {
        "tag": ("Tag", "Tagen"),
        "woche": ("Woche", "Wochen"),
        "monat": ("Monat", "Monaten"),
        "jahr": ("Jahr", "Jahren"),
    }[unit]
    span = f"{count} {unit_words[0] if count == 1 else unit_words[1]}"
    lead = "In" if sign > 0 else "Vor"
    return say(f"{lead} {span} {verb} {g.date_long(day, with_year=day.year != today.year)}.")


def _resolve_target(req: Request) -> tuple[date, str] | None:
    """The date a "bis …" question aims at, with the German phrase after "bis"."""
    today = req.now.date()
    text = req.text
    state = req.svc.cfg.home.state
    special = special_target(text, today)
    if special:
        key, day = special
        return day, dative_until(key)
    if re.search(r"\bwochenende\b", text):
        return next_weekday(today, 5), "zum Wochenende"
    if re.search(r"ferien\b", text):
        vac = school.upcoming(today, _vacation_kind(text))
        return (vac.first, f"zum Beginn der {vac.name}") if vac else None
    if re.search(r"\bfeiertag\b", text):
        hday = hol.next_holiday(today + timedelta(days=1), state)
        return (hday.day, f"zum nächsten Feiertag, {hday.name}") if hday else None
    if re.search(r"\b(?:monatsende|ende des monats|monatsletzten)\b", text):
        last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return last, "zum Monatsende"
    if re.search(r"\b(?:jahresende|ende des jahres|jahreswechsel)\b", text):
        return date(today.year, 12, 31), "zum Jahresende"
    if re.search(r"\bwochenanfang|\bnächsten montag\b", text):
        return next_weekday(today, 0, include_today=False), "zum Montag"
    when = when_of(req)
    if when is not None and when.day is not None and when.granularity in {"day"}:
        d = when.day
        return d, f"zum {g.date_plain(d, with_year=d.year != today.year)}"
    dates = find_dates(text, req.now)
    if dates:
        d = dates[0]
        return d, f"zum {g.date_plain(d, with_year=d.year != today.year)}"
    return None


@skill(
    "date.days_until",
    group="kalender",
    priority="M",
    help="Tage bis Weihnachten oder zu einem Datum",
    examples=(
        "Wie viele Tage noch bis Weihnachten?",
        "Wie lange noch bis Silvester?",
        "Wie viele Tage bis zum Wochenende?",
    ),
    patterns=(
        r"\bwie viele? tage (?:sind es |ist es )?(?:noch )?(?:bis|dauert es bis)\b",
        r"\bwie lange (?:ist es )?(?:noch )?(?:hin )?bis\b",
        r"\bnoch wie viele? tage (?:bis|sind es bis)\b",
        r"\bwie viele? tage (?:fehlen|dauert|bleiben) (?:noch )?(?:bis|zu)\b",
        r"\bwie viele? (?:wochen|monate) (?:noch )?bis\b",
        r"\bwann ist (?:es )?(?:wieder )?(?:\w+ )?wochenende\b",
        r"\bwie viele? mal schlafen bis\b",
    ),
)
async def date_days_until(req: Request) -> SkillResult | None:
    target = _resolve_target(req)
    if target is None:
        return None
    day, phrase = target
    today = req.now.date()
    n = (day - today).days
    if n < 0:
        return None
    if n == 0:
        return say(f"Das ist heute, {g.date_long(day, with_year=False)}!")
    if n == 1:
        return say(f"Das ist schon morgen, {g.date_long(day, with_year=False)}.")
    if re.search(r"\bwochen\b", req.text):
        weeks, rest = divmod(n, 7)
        extra = f" und {g.plural(rest, 'Tag', 'Tage')}" if rest else ""
        return say(f"Noch {g.plural(weeks, 'Woche', 'Wochen')}{extra} bis {phrase}.")
    if "monate" in req.text:
        months = round(n / 30.44)
        return say(f"Noch etwa {g.plural(months, 'Monat', 'Monate')} bis {phrase}.")
    schlafen = "mal schlafen" in req.text
    noun = g.plural(
        n, "Mal schlafen" if schlafen else "Tag", "Mal schlafen" if schlafen else "Tage"
    )
    return say(f"Noch {noun} bis {phrase}.", data={"days": n, "date": day.isoformat()})


@skill(
    "date.days_since",
    group="kalender",
    priority="S",
    examples=("Wie viele Tage sind seit Neujahr vergangen?", "Wie lange ist der 1. Mai her?"),
    patterns=(
        r"\bwie viele? tage (?:sind |ist )?(?:es )?seit\b",
        r"\bwie lange ist (?:der|die|das)\b.*\bher\b",
        r"\bseit wann\b.*\b(?:ist|haben wir)\b",
        r"\bwie viele? tage (?:ist|sind) .* (?:her|vorbei|vergangen)\b",
    ),
)
async def date_days_since(req: Request) -> SkillResult | None:
    today = req.now.date()
    dates = find_dates(req.text, req.now)
    found = find_special(req.text)
    if found and not re.search(r"\d", req.text):
        key, _ = found
        day = special_date(key, today.year)
        if day > today:
            day = special_date(key, today.year - 1)
        label = SPECIAL_DAYS[key][0]
    elif dates:
        day = dates[0]
        if day > today and not re.search(r"\b\d{4}\b", req.text):
            day = date(day.year - 1, day.month, day.day)
        label = f"der {g.date_plain(day, with_year=day.year != today.year)}"
    else:
        return None
    n = (today - day).days
    if n < 0:
        return None
    if n == 0:
        return say("Das ist heute.")
    dative = label.replace("der ", "dem ", 1) if label.startswith("der ") else label
    return say(f"Seit {dative} sind {g.plural(n, 'Tag', 'Tage')} vergangen.")


@skill(
    "date.between",
    group="kalender",
    priority="S",
    examples=("Wie viele Tage liegen zwischen dem 1. März und dem 15. April?",),
    patterns=(
        r"\bwie viele? tage (?:liegen |sind es |ist es )?zwischen\b",
        r"\bwie viele? tage (?:sind es |ist es )?(?:vom|von) .* bis\b",
        r"\bwie viele? tage (?:dauert|geht) .* bis\b",
    ),
)
async def date_between(req: Request) -> SkillResult | None:
    dates = find_dates(req.text, req.now)
    if len(dates) < 2:
        return None
    a, b = sorted(dates[:2])
    n = (b - a).days
    weeks, rest = divmod(n, 7)
    detail = (
        f" – das sind {g.plural(weeks, 'Woche', 'Wochen')}"
        + (f" und {g.plural(rest, 'Tag', 'Tage')}" if rest else "")
        if weeks
        else ""
    )
    return say(f"Dazwischen liegen {g.plural(n, 'Tag', 'Tage')}{detail}.")


@skill(
    "date.calendar_week",
    group="kalender",
    priority="M",
    help="die Kalenderwoche",
    examples=(
        "Welche Kalenderwoche haben wir?",
        "Welche KW?",
        "In welcher Kalenderwoche ist der 24.12.?",
    ),
    patterns=(
        r"\bwelche (?:kalender)?(?:woche|kw)\b",
        r"\b(?:kalenderwoche|kw)\b",
        r"\bin welcher (?:kalender)?woche\b",
        r"\bdie wievielte (?:kalender)?woche\b",
    ),
    exclude=(
        r"\b(?:wann ist|von wann bis wann|wie viele|gehen) .*(?:kw|kalenderwoche)\b",
        r"\b(?:kw|kalenderwoche) \d{1,2}\b",
    ),
)
async def date_calendar_week(req: Request) -> SkillResult:
    day = target_date(req) or req.now.date()
    week = day.isocalendar().week
    today = req.now.date()
    if day == today:
        return say(f"Wir haben Kalenderwoche {week}.")
    return say(
        f"Der {g.date_plain(day, with_year=day.year != today.year)} liegt in Kalenderwoche {week}."
    )


@skill(
    "date.week_range",
    group="kalender",
    priority="S",
    examples=("Wann ist KW 50?",),
    patterns=(r"\b(?:kw|kalenderwoche) (\d{1,2})\b",),
    exclude=(r"\bwelche\b",),
)
async def date_week_range(req: Request) -> SkillResult | None:
    m = re.search(r"\b(?:kw|kalenderwoche) (\d{1,2})\b", req.text)
    if not m:
        return None
    week = int(m.group(1))
    year_m = re.search(r"\b(20\d{2})\b", req.text)
    year = int(year_m.group(1)) if year_m else req.now.year
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError:
        return say(f"Das Jahr {year} hat keine Kalenderwoche {week}.")
    sunday = monday + timedelta(days=6)
    return say(
        f"Kalenderwoche {week} geht von Montag, {g.date_plain(monday)}, bis Sonntag, {g.date_plain(sunday, with_year=sunday.year != req.now.year)}."
    )


@skill(
    "date.weeks_in_year",
    group="kalender",
    priority="K",
    examples=("Wie viele Kalenderwochen hat 2026?",),
    patterns=(r"\bwie viele (?:kalender)?wochen hat\b",),
)
async def date_weeks_in_year(req: Request) -> SkillResult:
    m = re.search(r"\b(\d{4})\b", req.text)
    year = int(m.group(1)) if m else req.now.year
    weeks = date(year, 12, 28).isocalendar().week
    return say(f"{year} hat {weeks} Kalenderwochen.")


@skill(
    "date.day_of_year",
    group="kalender",
    priority="S",
    examples=("Der wievielte Tag des Jahres ist heute?", "Wie viele Tage hat das Jahr noch?"),
    patterns=(
        r"\bder wievielte tag (?:des|im) jahr",
        r"\bwie viele tage hat (?:das|dieses) jahr noch\b",
        r"\bwie viele tage (?:sind|bleiben) (?:es )?noch (?:in diesem jahr|dieses jahr|im jahr)\b",
    ),
)
async def date_day_of_year(req: Request) -> SkillResult:
    today = req.now.date()
    number = today.timetuple().tm_yday
    total = 366 if calendar.isleap(today.year) else 365
    return say(f"Heute ist der {number}. Tag des Jahres, es bleiben noch {total - number}.")


@skill(
    "date.month_info",
    group="kalender",
    priority="S",
    examples=("Wie viele Tage hat der Februar 2028?",),
    patterns=(
        r"\bwie viele tage hat (?:der |im |den monat )?(?:januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b",
    ),
)
async def date_month_info(req: Request) -> SkillResult | None:
    m = re.search(
        r"\b(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\b(?: (\d{4}))?",
        req.text,
    )
    if not m:
        return None
    month = MONTHS_DE.index(m.group(1).capitalize()) + 1 if m.group(1) != "märz" else 3
    year = int(m.group(2)) if m.group(2) else req.now.year
    days = calendar.monthrange(year, month)[1]
    extra = f" – {year} ist ein Schaltjahr" if month == 2 and calendar.isleap(year) else ""
    return say(f"Der {MONTHS_DE[month - 1]} {year} hat {days} Tage{extra}.")


@skill(
    "date.leap_year",
    group="kalender",
    priority="S",
    examples=("Ist 2028 ein Schaltjahr?",),
    patterns=(r"\bschaltjahr\b",),
)
async def date_leap_year(req: Request) -> SkillResult:
    m = re.search(r"\b(\d{4})\b", req.text)
    year = int(m.group(1)) if m else req.now.year
    if calendar.isleap(year):
        return say(f"Ja, {year} ist ein Schaltjahr.")
    nxt = next(y for y in range(year + 1, year + 9) if calendar.isleap(y))
    return say(f"Nein, {year} ist kein Schaltjahr. Das nächste ist {nxt}.")


@skill(
    "date.age",
    group="kalender",
    priority="S",
    examples=(
        "Wie alt ist jemand, der am 12. Mai 1990 geboren ist?",
        "Wie alt bin ich, wenn ich 1995 geboren bin?",
    ),
    patterns=(r"\bwie alt (?:ist|bin|wäre|wird|war)\b", r"\bwie alt (?:ist|bin) .*geboren\b"),
)
async def date_age(req: Request) -> SkillResult | None:
    today = req.now.date()
    full = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", req.text)
    if not full:
        full_words = re.search(
            r"\b(\d{1,2})\.? (januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember) (\d{4})\b",
            req.text,
        )
        if full_words:
            month = (
                [
                    "januar",
                    "februar",
                    "märz",
                    "april",
                    "mai",
                    "juni",
                    "juli",
                    "august",
                    "september",
                    "oktober",
                    "november",
                    "dezember",
                ].index(full_words.group(2))
            ) + 1
            born = date(int(full_words.group(3)), month, int(full_words.group(1)))
        else:
            only_year = re.search(r"\b(19\d{2}|20[0-2]\d)\b", req.text)
            if not only_year:
                return None
            year = int(only_year.group(1))
            low, high = today.year - year - 1, today.year - year
            if low == high:
                return say(f"{high} Jahre.")
            return say(
                f"{low} oder {high} Jahre, je nachdem, ob der Geburtstag dieses Jahr schon war."
            )
    else:
        born = date(int(full.group(3)), int(full.group(2)), int(full.group(1)))
    if born > today:
        return say("Das ist erst in der Zukunft.")
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return say(f"{g.plural(years, 'Jahr', 'Jahre')}.")


@skill(
    "date.year_progress",
    group="kalender",
    priority="K",
    examples=("Wie viel vom Jahr ist schon rum?",),
    patterns=(
        r"\bwie viel (?:vom|des) jahr(?:es)? ist (?:schon )?(?:rum|vorbei|um|geschafft)\b",
        r"\bwie weit ist das jahr\b",
    ),
)
async def date_year_progress(req: Request) -> SkillResult:
    today = req.now.date()
    number = today.timetuple().tm_yday
    total = 366 if calendar.isleap(today.year) else 365
    return say(f"Etwa {round(number / total * 100)} Prozent – {number} von {total} Tagen.")


@skill(
    "date.zodiac",
    group="kalender",
    priority="K",
    examples=("Welches Sternzeichen hat der 12. Mai?",),
    patterns=(r"\bsternzeichen\b",),
)
async def date_zodiac(req: Request) -> SkillResult | None:
    dates = find_dates(req.text, req.now)
    if not dates:
        return None
    d = dates[0]
    sign = _ZODIAC[-1][1]
    for (month, day), name in _ZODIAC:
        if (d.month, d.day) >= (month, day):
            sign = name
    if (d.month, d.day) < (1, 20):
        sign = "Steinbock"
    return say(f"Wer am {g.date_plain(d)} geboren ist, hat das Sternzeichen {sign}.")


@skill(
    "date.special",
    group="kalender",
    priority="M",
    help="Termine wie Ostern oder der erste Advent",
    examples=("Wann ist Muttertag?", "Wann ist der erste Advent?", "Wann ist Ostern 2027?"),
    patterns=(
        r"\bwann (?:ist|war|wird|fällt|beginnt|sind|findet)\b",
        r"\b(?:datum|termin) (?:von|vom|für)\b",
    ),
    exclude=(
        r"\bnächste[rn]? feiertag\b",
        r"\bferien\b",
        r"\bvollmond|neumond|mondphase|sonnen|mond\b",
        r"\bkw\b|\bkalenderwoche\b",
        r"\bmüll|tonne|abfall\b",
        r"\bwetter|regen|sturm\b",
    ),
)
async def date_special(req: Request) -> SkillResult | None:
    found = find_special(req.text)
    if not found:
        return None
    key, _ = found
    year_m = re.search(r"\b(20\d{2})\b", req.text)
    today = req.now.date()
    day = special_date(key, int(year_m.group(1))) if year_m else next_occurrence(key, today)
    name = SPECIAL_DAYS[key][0]
    name = name[0].upper() + name[1:]
    past = day < today
    verb = "war" if past else "ist"
    when = f"am {WEEKDAYS_DE[day.weekday()]}, {g.date_plain(day, with_year=day.year != today.year)}"
    alias = next((w for w in ("vatertag", "herrentag") if w in req.text), None)
    if alias:  # "Wann ist Vatertag?" – name the thing that was asked for
        return say(f"{alias.capitalize()} {verb} {name} – {when}.")
    return say(f"{name} {verb} {when}.")


# ---------------------------------------------------------------------------------------------
# holidays, school holidays, work days
# ---------------------------------------------------------------------------------------------
@skill(
    "holiday.next",
    group="kalender",
    priority="M",
    help="den nächsten Feiertag",
    examples=("Wann ist der nächste Feiertag?",),
    patterns=(
        r"\bwann ist (?:der )?nächste[rn]? feiertag\b",
        r"\bnächste[rn]? feiertag\b",
        r"\bwann ist (?:wieder )?feiertag\b",
        r"\bwann (?:haben|ist) wir? (?:wieder )?(?:einen )?feiertag\b",
    ),
)
async def holiday_next(req: Request) -> SkillResult | None:
    state = _state(req)
    today = req.now.date()
    holiday = hol.next_holiday(today, state)
    if holiday is None:
        return None
    where = _where(state)
    when = (
        "heute"
        if holiday.day == today
        else f"am {WEEKDAYS_DE[holiday.day.weekday()]}, {g.date_plain(holiday.day)}"
    )
    if holiday.day == today:
        return say(f"Heute ist {holiday.name} – ein Feiertag {where}!")
    return say(f"Der nächste Feiertag {where} ist {holiday.name}, {when}.")


@skill(
    "holiday.is",
    group="kalender",
    priority="M",
    help="ob ein Tag ein Feiertag ist",
    examples=("Ist morgen ein Feiertag?", "Ist heute Feiertag?", "Haben wir morgen Feiertag?"),
    patterns=(
        r"\bist (?:\w+ )?(?:heute|morgen|übermorgen|gestern|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|der \d.*|am \d.*) (?:ein )?feiertag\b",
        r"\bist (?:heute|morgen|übermorgen|gestern) (?:ein )?(?:gesetzlicher )?feiertag\b",
        r"\bhaben wir (?:heute|morgen|übermorgen) feiertag\b",
        r"\bist .* (?:ein )?(?:gesetzlicher )?feiertag\b",
        r"\bist (?:heute|morgen|übermorgen|gestern) feiertag\b",
    ),
)
async def holiday_is(req: Request) -> SkillResult | None:
    state = _state(req)
    today = req.now.date()
    found = find_special(req.text)
    if (
        found
        and found[0] in SPECIAL_DAYS
        and not re.search(r"\b(heute|morgen|übermorgen|gestern)\b", req.text)
    ):
        day = next_occurrence(found[0], today)
        subject = SPECIAL_DAYS[found[0]][0]
    else:
        day = target_date(req)
        if day is None:
            return None
        label = g.day_label(day, today)
        subject = (
            label
            if label in {"heute", "morgen", "übermorgen", "gestern"}
            else f"der {g.date_plain(day, with_year=day.year != today.year)}"
        )
    where = _where(state)
    tense = "war" if day < today else "ist"
    holiday = hol.holiday_on(day, state)
    if holiday:
        if (
            found
            and found[0] in SPECIAL_DAYS
            and holiday.name.lower().endswith(subject.lower()[-6:])
        ):
            return say(f"Ja, {subject} {tense} {where} ein Feiertag.")
        return say(f"Ja, {subject} {tense} {holiday.name} – ein Feiertag {where}.")
    others = hol.holiday_states_on(day)
    if others:
        names = [hol.state_names()[c] for c in others]
        listed = g.join_and(names[:3]) if len(names) <= 3 else ", ".join(names[:3]) + " und anderen"
        return say(f"Nein, {subject} {tense} {where} kein Feiertag – aber in {listed}.")
    return say(f"Nein, {subject} {tense} {where} kein Feiertag.")


@skill(
    "holiday.list",
    group="kalender",
    priority="S",
    examples=("Welche Feiertage gibt es im Dezember?", "Feiertage 2027?"),
    patterns=(
        r"\bwelche feiertage\b",
        r"\bfeiertage (?:im|in|2\d{3}|diesen|dieses)\b",
        r"\bliste der feiertage\b",
        r"\balle feiertage\b",
    ),
)
async def holiday_list(req: Request) -> SkillResult:
    state = _state(req)
    today = req.now.date()
    when = find_when(req.text, req.now)
    year_m = re.search(r"\b(20\d{2})\b", req.text)
    year = int(year_m.group(1)) if year_m else today.year
    items = [h for h in hol.holidays(year, state) if not h.sunday]
    label = f"{year}"
    if when is not None and when.granularity == "month":
        first, last = when.start.date(), (when.end - timedelta(seconds=1)).date()
        items = [
            h for h in hol.holidays(first.year, state) if first <= h.day <= last and not h.sunday
        ]
        label = when.label
    else:
        items = [h for h in items if h.day >= today] if year == today.year else items
        label = "dieses Jahr noch" if year == today.year else f"{year}"
    label = label[0].upper() + label[1:]
    if not items:
        return say(f"{label} gibt es in Hessen keine weiteren Feiertage.")
    shown = items[:4]
    parts = [f"{h.name} am {g.date_plain(h.day)}" for h in shown]
    more = f" Und {len(items) - 4} weitere." if len(items) > 4 else ""
    where = _where(state)
    return say(
        f"{label} {where}: {g.join_and(parts)}.{more}",
        detail=g.join_and([f"{h.name} am {g.date_plain(h.day)}" for h in items]) + ".",
    )


@skill(
    "holiday.long_weekend",
    group="kalender",
    priority="S",
    examples=("Wann ist das nächste lange Wochenende?", "Brückentage?"),
    patterns=(r"\blanges? wochenende\b", r"\bbrückentage?\b", r"\bbrücken tage?\b"),
)
async def holiday_long_weekend(req: Request) -> SkillResult | None:
    state = _state(req)
    found = workdays.long_weekends(req.now.date(), state)
    if not found:
        return None
    nxt = found[0]
    if nxt.bridge:
        return say(
            f"Das nächste lange Wochenende: {nxt.holiday.name} am {WEEKDAYS_DE[nxt.holiday.day.weekday()]}, "
            f"{g.date_plain(nxt.holiday.day)}. Mit einem Brückentag am {WEEKDAYS_DE[nxt.bridge.weekday()]}, "
            f"{g.date_plain(nxt.bridge)}, hast du {nxt.days} Tage frei."
        )
    return say(
        f"Das nächste lange Wochenende ist {nxt.holiday.name}, vom {WEEKDAYS_DE[nxt.first.weekday()]}, "
        f"{g.date_plain(nxt.first)}, bis {WEEKDAYS_DE[nxt.last.weekday()]}, {g.date_plain(nxt.last)} – {nxt.days} Tage frei."
    )


@skill(
    "holiday.workdays",
    group="kalender",
    priority="S",
    examples=("Wie viele Arbeitstage hat der November?", "Arbeitstage bis Weihnachten?"),
    patterns=(r"\barbeitstage?\b", r"\bwerktage?\b"),
)
async def holiday_workdays(req: Request) -> SkillResult | None:
    state = _state(req)
    today = req.now.date()
    wd = _workdays(req)
    when = find_when(req.text, req.now)
    where = _where(state)
    if when is not None and when.granularity in {"month", "week", "weekend", "year"}:
        first, last = when.start.date(), (when.end - timedelta(seconds=1)).date()
        n = workdays.count_workdays(first, last, state, wd)
        label = when.label[0].upper() + when.label[1:]
        if label.startswith("Im "):
            label = "Der " + label[3:]
        verb = "hat" if when.granularity == "month" else "gibt es"
        return say(f"{label} {verb} {n} Arbeitstage {where}.")
    target = _resolve_target(req)
    if target:
        day, phrase = target
        if day > today:
            n = workdays.count_workdays(
                today + timedelta(days=1), day - timedelta(days=1), state, wd
            )
            return say(
                f"Bis {phrase} sind es noch {g.plural(n, 'Arbeitstag', 'Arbeitstage')} {where}."
            )
    n = workdays.count_workdays(
        today,
        date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]),
        state,
        wd,
    )
    return say(f"Bis Monatsende sind es noch {g.plural(n, 'Arbeitstag', 'Arbeitstage')} {where}.")


def _vacation_kind(text: str) -> str | None:
    for word in re.findall(r"[a-zäöüß]*ferien", text):
        if word in school.ALIASES:
            return school.ALIASES[word]
    return None


@skill(
    "school.next",
    group="kalender",
    priority="S",
    help="die nächsten Schulferien",
    examples=("Wann sind die nächsten Ferien?", "Wann sind Sommerferien?"),
    patterns=(
        r"\bwann (?:sind|beginnen|fangen an|gehen) (?:die |wieder )?(?:nächsten |\w+ )?ferien\b",
        r"\bwann (?:sind|beginnen) (?:die )?(?:herbst|weihnachts|oster|sommer)ferien\b",
        r"\b(?:nächsten|nächste) (?:schul)?ferien\b",
        r"\b(?:herbst|weihnachts|oster|sommer)ferien\b",
    ),
    exclude=(
        r"\bsind (?:gerade|heute|jetzt) ferien\b",
        r"\bnoch\b.*\bferien\b",
        r"\bwie viele tage\b",
    ),
)
async def school_next(req: Request) -> SkillResult | None:
    today = req.now.date()
    kind = _vacation_kind(req.text)
    year_m = re.search(r"\b(20\d{2})\b", req.text)
    if year_m and kind:
        year = int(year_m.group(1))
        vac = next(
            (v for v in school.all_vacations() if v.kind == kind and v.first.year == year), None
        )
    else:
        vac = school.upcoming(today, kind)
        current = school.current(today)
        if current and (kind is None or current.kind == kind):
            return say(
                f"Gerade sind {current.name} in Hessen – noch bis {WEEKDAYS_DE[current.last.weekday()]}, {g.date_plain(current.last)}."
            )
    if vac is None:
        label = f"die {school.NAMES[kind]}" if kind else "weitere Ferien"
        return say(
            f"Für {label} habe ich noch keine Termine. Meine Ferientabelle reicht bis {g.date_plain(school.last_covered_day(), with_year=True)}."
        )
    return say(
        f"Die {vac.name} in Hessen gehen vom {WEEKDAYS_DE[vac.first.weekday()]}, {g.date_plain(vac.first, with_year=vac.first.year != today.year)}, "
        f"bis {WEEKDAYS_DE[vac.last.weekday()]}, {g.date_plain(vac.last, with_year=vac.last.year != today.year)}."
    )


@skill(
    "school.now",
    group="kalender",
    priority="S",
    examples=("Sind gerade Ferien?", "Wie lange gehen die Herbstferien noch?"),
    patterns=(
        r"\bsind (?:gerade |heute |jetzt |morgen )?(?:schul)?ferien\b",
        r"\bhaben wir (?:gerade |heute )?(?:schul)?ferien\b",
        r"\bwie lange (?:gehen|dauern) (?:die )?\w*ferien noch\b",
        r"\bnoch ferien\b",
    ),
)
async def school_now(req: Request) -> SkillResult:
    day = req.now.date() + timedelta(days=1 if "morgen" in req.text else 0)
    current = school.current(day)
    label = "morgen" if "morgen" in req.text else "gerade"
    if current:
        left = (current.last - day).days
        return say(
            f"Ja, {label} sind {current.name} in Hessen, noch bis {WEEKDAYS_DE[current.last.weekday()]}, {g.date_plain(current.last)}. "
            f"Die Schule beginnt wieder am {WEEKDAYS_DE[current.school_resumes.weekday()]}, {g.date_plain(current.school_resumes)}."
            + (f" Noch {g.plural(left, 'Tag', 'Tage')}." if left > 1 else "")
        )
    upcoming = school.upcoming(day)
    if upcoming is None:
        return say(f"Nein, {label} sind keine Ferien. Weitere Termine habe ich noch nicht.")
    n = (upcoming.first - day).days
    return say(
        f"Nein, {label} sind keine Ferien in Hessen. Die nächsten sind die {upcoming.name}, "
        f"ab {g.date_plain(upcoming.first)} – in {g.plural(n, 'Tag', 'Tagen')}."
    )

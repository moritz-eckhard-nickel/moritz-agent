# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Time of day: clock, world time, time zones, daylight saving (docs/plan/13 §6.1)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.calendar.special import dst_change
from moritz_agent.skills.catalog.common import say
from moritz_agent.skills.geo.zones import display_name, find_zone
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.slots.when import find_when

_NOT_THE_CLOCK = (
    r"\b(fährt|fahren|abfahrt|ankunft|öffnet|öffnen|schließt|schließen|beginnt|beginn|startet|anfang|"
    r"kommt|zug|bus|bahn|flug|film|termin|treffen|spiel|konzert|laden|geschäft|sendung|ab wann|bis wann|"
    r"wann|sonnenaufgang|sonnenuntergang|zeitzone|geht die|gehen die|fängt|endet|ende)\b",
    r"\bum wie ?viel uhr\b",
    r"\b(in|bei|auf) [a-zäöüß]{3,}",
    r"\bzeitumstellung|\bsommerzeit|\bwinterzeit|\bumgestellt\b",
    r"\b(datum|wochentag|kalenderwoche|kw)\b",
)


def _clock_text(req: Request, moment: datetime) -> str:
    if req.svc.cfg.time.spoken_style == "umgangssprachlich":
        return g.clock_colloquial(moment)
    return g.clock_digital(moment)


@skill(
    "time.now",
    group="zeit",
    priority="M",
    help="die Uhrzeit",
    examples=("Wie viel Uhr ist es?", "Wie spät isses?", "Wie viel Uhr hammer?", "Uhrzeit?"),
    patterns=(
        r"\bwie ?viel uhr\b",
        r"\bwie spät\b",
        r"\bwelche uhrzeit\b",
        r"\buhrzeit\b",
        (r"\b(?:wie )?spät ist es\b", 1.0),
    ),
    exclude=_NOT_THE_CLOCK,
)
async def time_now(req: Request) -> SkillResult:
    moment = req.now
    return say(f"Es ist {_clock_text(req, moment)}.", data={"time": moment.strftime("%H:%M")})


@skill(
    "time.datetime",
    group="zeit",
    priority="M",
    help="Datum und Uhrzeit",
    examples=("Datum und Uhrzeit?",),
    patterns=(r"\b(?:datum und uhrzeit|uhrzeit und datum|datum und zeit|zeit und datum)\b",),
)
async def time_datetime(req: Request) -> SkillResult:
    moment = req.now
    return say(f"Heute ist {g.date_long(moment.date())}, und es ist {_clock_text(req, moment)}.")


@skill(
    "time.timestamp_talk",
    group="zeit",
    priority="K",
    examples=("Sag mir die genaue Uhrzeit",),
    patterns=(r"\bgenaue (?:uhrzeit|zeit)\b", r"\bauf die sekunde\b"),
)
async def time_precise(req: Request) -> SkillResult:
    moment = req.now + timedelta(seconds=2)  # the voice needs about two seconds to get going
    return say(f"Es ist {g.clock_digital(moment)} und {moment.second} Sekunden.")


@skill(
    "time.world",
    group="zeit",
    priority="S",
    help="die Uhrzeit in anderen Städten",
    examples=("Wie spät ist es in New York?", "Uhrzeit in Tokio?"),
    patterns=(r"\b(?:wie spät|wie ?viel uhr|uhrzeit|zeit)\b.*\b(?:in|bei|auf)\b",),
)
async def time_world(req: Request) -> SkillResult | None:
    found = find_zone(req.text)
    if not found:
        return None
    name, zone = found
    there = req.svc.clock.now(zone)
    here = req.now
    diff_h = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600  # type: ignore[operator]
    place = display_name(name)
    if diff_h == 0:
        extra = "genauso spät wie hier"
    else:
        hours = abs(diff_h)
        amount = g.number(hours, 1)
        unit = "Stunde" if hours == 1 else "Stunden"
        extra = f"{amount} {unit} {'später' if diff_h > 0 else 'früher'} als hier"
    day_note = ""
    if there.date() != here.date():
        day_note = " morgen" if there.date() > here.date() else " gestern"
        day_note = f", das ist{day_note}" if day_note else ""
    return say(f"In {place} ist es jetzt {g.clock_digital(there)}, {extra}{day_note}.")


@skill(
    "time.offset",
    group="zeit",
    priority="S",
    examples=("Wie viel Zeitunterschied ist es nach Sydney?",),
    patterns=(r"\b(?:zeitunterschied|zeitverschiebung|zeitdifferenz)\b",),
)
async def time_offset(req: Request) -> SkillResult | None:
    found = find_zone(req.text)
    if not found:
        return None
    name, zone = found
    there, here = req.svc.clock.now(zone), req.now
    diff_h = (there.utcoffset() - here.utcoffset()).total_seconds() / 3600  # type: ignore[operator]
    place = display_name(name)
    if diff_h == 0:
        return say(f"{place} hat dieselbe Uhrzeit wie wir.")
    amount = g.number(abs(diff_h), 1)
    unit = "Stunde" if abs(diff_h) == 1 else "Stunden"
    return say(f"{place} ist uns gerade {amount} {unit} {'voraus' if diff_h > 0 else 'hinterher'}.")


@skill(
    "time.in_duration",
    group="zeit",
    priority="S",
    examples=("Wie spät ist es in drei Stunden?", "Wann ist es in 90 Minuten?"),
    patterns=(
        r"\b(?:wie spät|wie ?viel uhr|wann)\b.*\bin (?:\d+|einer|einer halben|anderthalb|eineinhalb) (?:minuten?|stunden?)\b",
    ),
)
async def time_in_duration(req: Request) -> SkillResult | None:
    when = find_when(req.text, req.now)
    if when is None or when.granularity != "hour" or not when.label.startswith("in "):
        return None
    return say(f"{when.label[0].upper()}{when.label[1:]} ist es {g.clock_digital(when.start)}.")


@skill(
    "time.until",
    group="zeit",
    priority="S",
    examples=("Wie lange noch bis 22 Uhr?", "Wie lange ist es noch bis Mitternacht?"),
    patterns=(r"\bwie lange (?:ist es )?(?:noch )?bis\b", r"\bwie viel zeit (?:noch )?bis\b"),
)
async def time_until(req: Request) -> SkillResult | None:
    text = (
        req.text.replace("mitternacht", "0:00 uhr").replace("mittag", "12:00 uhr")
        if "mitternacht" in req.text
        else req.text
    )
    when = find_when(text, req.now)
    if when is None or when.clock is None:
        return None
    target = when.start
    if "mitternacht" in req.text:
        target = (req.now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = target - req.now
    if delta.total_seconds() <= 0:
        return None
    return say(f"Noch {g.duration(delta)}.")


@skill(
    "time.dst_now",
    group="zeit",
    priority="S",
    examples=("Haben wir gerade Sommerzeit?",),
    patterns=(
        r"\b(?:haben wir|gilt|ist) (?:gerade |jetzt |schon |noch )?(?:sommer|winter)zeit\b",
        r"\bsommerzeit oder winterzeit\b",
    ),
)
async def time_dst_now(req: Request) -> SkillResult:
    moment = req.now
    summer = bool(moment.dst())
    year = moment.year
    asked_summer = "sommer" in req.text and "winter" not in req.text.split("sommer")[0]
    if "winter" in req.text and "sommer" not in req.text:
        asked_summer = False
    if summer:
        end = dst_change(year, False)
        tail = f"bis Sonntag, {g.date_plain(end)}. Dann wird die Uhr eine Stunde zurückgestellt."
        if asked_summer:
            return say(f"Ja, es gilt die Sommerzeit – {tail}")
        return say(f"Nein, noch gilt die Sommerzeit – {tail}")
    day = dst_change(year, True)
    start = day if moment.date() < day else dst_change(year + 1, True)
    tail = f"Die Sommerzeit beginnt am Sonntag, {g.date_plain(start)}."
    if asked_summer:
        return say(f"Nein, es gilt die Winterzeit. {tail}")
    return say(f"Ja, es gilt die Winterzeit. {tail}")


@skill(
    "time.dst_next",
    group="zeit",
    priority="M",
    help="die Zeitumstellung",
    examples=("Wann wird die Uhr umgestellt?", "Zeitumstellung?"),
    patterns=(
        r"\bzeitumstellung\b",
        r"\buhr (?:wird |muss )?(?:umgestellt|umgedreht|vorgestellt|zurückgestellt)\b",
        r"\bwann (?:wird |muss )?(?:man )?(?:die |an der )?uhr(?:en)? (?:umgestellt|gedreht|umstellen|umdrehen|vorstellen|zurückstellen)\b",
        r"\bwann (?:ist|kommt) (?:die )?(?:sommer|winter)zeit\b",
        r"\bsommerzeit\b.*\bwann\b|\bwinterzeit\b.*\bwann\b",
    ),
    exclude=(r"\bhaben wir\b",),
)
async def time_dst_next(req: Request) -> SkillResult:
    moment = req.now
    zone = ZoneInfo(req.svc.timezone)
    for year in (moment.year, moment.year + 1):
        for spring in (True, False):
            day = dst_change(year, spring)
            change = (
                datetime(day.year, day.month, day.day, 3, tzinfo=zone)
                if not spring
                else datetime(day.year, day.month, day.day, 2, tzinfo=zone)
            )
            if change.date() >= moment.date() and change > moment:
                if spring:
                    return say(
                        f"Am Sonntag, {g.date_plain(day)}, um 2 Uhr wird die Uhr auf 3 Uhr vorgestellt – "
                        "eine Stunde weniger Schlaf."
                    )
                return say(
                    f"Am Sonntag, {g.date_plain(day)}, um 3 Uhr wird die Uhr auf 2 Uhr zurückgestellt – "
                    "eine Stunde länger schlafen."
                )
    return say("Das kann ich gerade nicht ausrechnen.")


@skill(
    "time.clock_check",
    group="zeit",
    priority="K",
    examples=("Geht meine Uhr richtig? Bei mir ist es 19:15.",),
    patterns=(r"\b(?:geht|stimmt) meine uhr\b",),
)
async def time_clock_check(req: Request) -> SkillResult | None:
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", req.text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    moment = req.now
    theirs = moment.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
    diff = (theirs - moment).total_seconds()
    if abs(diff) > 12 * 3600:
        theirs += timedelta(days=-1 if diff > 0 else 1)
        diff = (theirs - moment).total_seconds()
    minutes = round(abs(diff) / 60)
    ours = f"Bei mir ist es {g.clock_digital(moment)}"
    if minutes == 0:
        return say(f"{ours} – deine Uhr geht genau richtig.")
    return say(
        f"{ours} – deine Uhr geht etwa {g.plural(minutes, 'Minute', 'Minuten')} {'vor' if diff > 0 else 'nach'}."
    )

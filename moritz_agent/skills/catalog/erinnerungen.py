# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Reminders: "erinnere mich morgen um 8 an den Zahnarzt" (docs/plan/14 §11, SKILL-24).

The skill only understands the sentence; the chat channel keeps the reminder (database, survives a
restart) and delivers it where it was asked. On the telephone there is no callback (PHONE-10).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.catalog.common import say
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.slots.when import find_when

GROUP = "helfer"
MAX_AHEAD = timedelta(days=366)
_LEAD = re.compile(
    r"\b(?:erinner\w*|bitte|doch|mal|kannst du|könntest du|kann ich|könnte ich)\b", re.IGNORECASE
)
_PREFIX = re.compile(r"^(?:mich|uns|mir)\s+", re.IGNORECASE)
_WHEN_PARTS = (
    r"\bin (?:\d+|einer|einem|anderthalb|eineinhalb|einer halben|einer viertel|drei viertel) "
    r"(?:minuten?|stunden?|tagen?|wochen?|monaten?)\b",
    r"\b(?:heute|morgen|übermorgen)(?: (?:früh|morgen|vormittag|mittag|nachmittag|abend|nacht))?\b",
    r"\b(?:am )?(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag)\b",
    r"\bnächste[nrms]? (?:woche|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b",
    r"\b(?:um|gegen|ab) \d{1,2}(?:[:.]\d{2})?(?: uhr(?: \d{1,2})?)?\b",
    r"\b\d{1,2}(?:[:.]\d{2})? uhr(?: \d{1,2})?\b",
    r"\bam \d{1,2}\.(?: ?\d{1,2}\.?| (?:januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember))(?: ?\d{2,4})?",
)


def _body(raw: str) -> str:
    """What to remind of: the sentence without "erinnere mich" and without the time words.

    "an den Zahnarzt" keeps its "an" (the answer reads "ich erinnere dich … an den Zahnarzt")."""
    text = raw
    for pattern in _WHEN_PARTS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = _LEAD.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.:;!?-")
    text = _PREFIX.sub("", text)
    text = re.sub(r"\s+(?:an|daran|zu)$", "", text, flags=re.IGNORECASE).strip(" ,.:;!?-")
    return text[:200]


def _connected(body: str) -> bool:
    return bool(re.match(r"(?:an|daran|dass)\b", body, flags=re.IGNORECASE))


def _due(req: Request) -> tuple[datetime, bool] | None:
    """When, and whether the user named a clock time (then the answer repeats it)."""
    when = find_when(req.text, req.now)
    if when is None or not when.explicit:
        return None
    if re.search(_WHEN_PARTS[0], req.text):  # "in 2 Stunden" is told back the same way
        return (when.start, False) if when.start > req.now else None
    if when.clock is not None:
        return (when.start, True) if when.start > req.now else None
    if when.granularity in {"now", "hour"}:
        return (when.start, False) if when.start > req.now else None
    if when.granularity == "day":  # a day without a time: eight in the morning
        eight = when.start.replace(hour=8, minute=0, second=0, microsecond=0)
        return (eight if eight > req.now else when.start), True
    return when.start, when.granularity == "daypart"


def _described(due: datetime, now: datetime, clock: bool) -> str:
    if not clock and due - now < timedelta(hours=6):
        return "in " + g.duration(due - now, seconds=False)
    return f"{g.day_label(due.date(), now.date())} um {g.clock_digital(due)}"


async def _remind(req: Request) -> SkillResult | None:
    if req.surface == "spoken":
        return say(
            "Erinnerungen schicke ich dir auf Discord. Am Telefon kann ich dich nicht zurückrufen.",
            serious=True,
        )
    parsed = _due(req)
    if parsed is None:
        return say(
            "Wann soll ich dich erinnern? Sag zum Beispiel: in zwei Stunden oder morgen um 8."
        )
    due, clock = parsed
    if due - req.now > MAX_AHEAD:
        return say("So weit im Voraus erinnere ich nicht, höchstens ein Jahr.", serious=True)
    body = _body(req.utt.raw) or "Erinnerung"
    when = _described(due, req.now, clock)
    if _connected(body):
        text = f"Okay, ich erinnere dich {when} {body}"
    else:
        body = body[:1].upper() + body[1:]
        text = f"Okay, ich erinnere dich {when}: {body}"
    return say(g.sentence(text), reminder=(due, body))


skill(
    "remind.add",
    group=GROUP,
    priority="M",
    max_words=24,
    help="Erinnerungen",
    examples=(
        "Erinnere mich morgen um 8 an den Zahnarzt",
        "Erinner mich in 2 Stunden an die Wäsche",
    ),
    patterns=(
        (r"^(?:.*\s)?erinner\w*\s+(?:mich|uns)\b.*$", 1.0),
        (r"^(?:.*\s)?(?:kannst|könntest) du mich\b.*\berinner\w*\b.*$", 1.0),
    ),
)(_remind)


async def _list(req: Request) -> SkillResult | None:
    if req.surface == "spoken" or req.svc.db is None:
        return None
    from moritz_agent.storage.discord import DiscordStore, parse_iso

    reminders = DiscordStore(req.svc.db).open_reminders(req.ctx.user_id)
    if not reminders:
        return say("Du hast keine offenen Erinnerungen.")
    tz = req.now.tzinfo
    lines = []
    for item in reminders[:8]:
        due = parse_iso(item["due_at"]).astimezone(tz)
        lines.append(f"{_described(due, req.now, True)}: {item['text']}")
    return say(g.sentence("Deine Erinnerungen: " + "; ".join(lines)))


skill(
    "remind.list",
    group=GROUP,
    priority="S",
    max_words=10,
    chat_only=True,
    examples=("Welche Erinnerungen habe ich?",),
    patterns=(
        (r"^(?:.*\s)?(?:welche|was für|zeig\w*|lies\w*) (?:\w+ )?erinnerungen\b.*$", 1.0),
        (r"^(?:.*\s)?meine erinnerungen\b.*$", 1.0),
    ),
)(_list)

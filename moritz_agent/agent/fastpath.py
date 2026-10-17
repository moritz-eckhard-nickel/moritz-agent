# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Fast paths: clear, simple questions answered without the language model (AGENT-10, ADR-025).

Only unmistakable patterns match; anything else goes to the normal agent. The clock is read when
the answer is built – immediately before it is spoken – so the time is never made up (PHONE-24).
This is the first slice of docs/plan/12-fast-paths.md (time, date, weekday, calendar week,
tomorrow/yesterday, identity, help, goodbye); the rest follows with the agent core (P1-09).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from moritz_agent.tools.time_tool import (
    DEFAULT_TIMEZONE,
    WEEKDAYS_DE,
    format_calendar_week_de,
    format_date_de,
    format_time_de,
    format_weekday_de,
    now,
)

# Words that turn a time question into something else ("Um wie viel Uhr fährt der Zug?").
_NOT_THE_CLOCK = re.compile(
    r"\b(fährt|fahren|abfahrt|ankunft|öffnet|öffnen|schließt|schließen|beginnt|beginn|startet|"
    r"anfang|kommt|zug|bus|bahn|flug|film|termin|treffen|spiel|konzert|laden|geschäft|sendung|"
    r"ab wann|bis wann|wann|sonnenaufgang|sonnenuntergang|zeitzone|new york|london|tokio)\b"
)
_TIME = re.compile(
    r"\b(wie viel uhr|wieviel uhr|wie spät|wie spaet|welche uhrzeit|uhrzeit|sag mir die uhrzeit|"
    r"kannst du mir die uhrzeit sagen)\b"
)
_DATETIME = re.compile(r"\b(datum und uhrzeit|uhrzeit und datum)\b")
_DATE = re.compile(
    r"\b(welches datum|der wievielte|den wievielten|datum heute|heutiges datum|welches datum haben wir)\b"
)
_WEEKDAY = re.compile(
    r"\b(welcher tag ist heute|welcher wochentag|was für ein tag ist heute|was fuer ein tag ist heute|welchen wochentag|welcher tag haben wir)\b"
)
_WEEK = re.compile(r"\b(welche kalenderwoche|welche kw|kalenderwoche|in welcher woche)\b")
_TOMORROW = re.compile(
    r"\b(welcher tag ist morgen|welches datum ist morgen|was ist morgen für ein tag|welcher wochentag ist morgen)\b"
)
_YESTERDAY = re.compile(
    r"\b(welcher tag war gestern|welches datum war gestern|welcher wochentag war gestern)\b"
)
_IDENTITY = re.compile(
    r"\b(wer bist du|wie heißt du|wie heisst du|wie ist dein name|wie war dein name|stell dich vor)\b"
)
_HELP = re.compile(
    r"\b(was kannst du|hilfe|was kannst du alles|wobei kannst du helfen|was machst du)\b"
)
_GOODBYE = re.compile(
    r"\b(tschüss|tschüs|tschau|ciao|auf wiederhören|auf wiedersehen|wiederhören|mach's gut|mach es gut|"
    r"bis bald|bis später|das war's|das wars|das war es|auflegen|danke das war alles|ich lege jetzt auf)\b"
)
_REPEAT = re.compile(
    r"\b(was hast du gesagt|wiederhol das|nochmal bitte|noch einmal bitte|kannst du das wiederholen|bitte wiederholen)\b"
)


@dataclass(frozen=True)
class FastPathResult:
    intent: str
    text: str | None = None  # spoken with the voice
    prompt: str | None = None  # or a pre-recorded announcement
    hangup: bool = False


def normalize(utterance: str) -> str:
    """Lower case, no punctuation, single spaces."""
    cleaned = re.sub(r"[^\w\s'äöüß]", " ", utterance.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def classify(utterance: str) -> str | None:
    """Name of the fast path that matches, or None (long or compound requests never match)."""
    text = normalize(utterance)
    if not text or len(text.split()) > 12:
        return None
    if _GOODBYE.search(text) and len(text.split()) <= 6:
        return "goodbye"
    if _REPEAT.search(text):
        return "repeat"
    if _DATETIME.search(text):
        return "datetime"
    if _WEEK.search(text):
        return "calendar_week"
    if _TOMORROW.search(text):
        return "tomorrow"
    if _YESTERDAY.search(text):
        return "yesterday"
    if _WEEKDAY.search(text):
        return "weekday"
    if _DATE.search(text):
        return "date"
    if _TIME.search(text) and not _NOT_THE_CLOCK.search(text):
        return "time"
    if _IDENTITY.search(text):
        return "identity"
    if _HELP.search(text):
        return "help"
    return None


def _day_phrase(moment: datetime, label: str) -> str:
    months = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    return f"{label} ist {WEEKDAYS_DE[moment.weekday()]}, der {moment.day}. {months[moment.month - 1]}."


def answer(
    utterance: str,
    assistant_name: str = "Nikita",
    last_reply: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> FastPathResult | None:
    """Answer ``utterance`` if a fast path applies."""
    intent = classify(utterance)
    if intent is None:
        return None
    moment = now(timezone)
    if intent == "time":
        return FastPathResult(intent, format_time_de(moment))
    if intent == "date":
        return FastPathResult(intent, format_date_de(moment))
    if intent == "weekday":
        return FastPathResult(intent, format_weekday_de(moment))
    if intent == "datetime":
        return FastPathResult(
            intent,
            f"{format_date_de(moment)[:-1]}, und {format_time_de(moment)[0].lower()}{format_time_de(moment)[1:]}",
        )
    if intent == "calendar_week":
        return FastPathResult(intent, format_calendar_week_de(moment))
    if intent == "tomorrow":
        return FastPathResult(intent, _day_phrase(moment + timedelta(days=1), "Morgen"))
    if intent == "yesterday":
        return FastPathResult(
            intent, _day_phrase(moment - timedelta(days=1), "Gestern war").replace("war ist", "war")
        )
    if intent == "identity":
        return FastPathResult(intent, f"Ich bin {assistant_name}, Moritz’ Telefonassistent.")
    if intent == "help":
        return FastPathResult(
            intent,
            "Ich kann dir die Uhrzeit und das Datum sagen. Frag mich einfach, zum Beispiel: Wie viel Uhr ist es?",
        )
    if intent == "goodbye":
        return FastPathResult(intent, prompt="goodbye", hangup=True)
    if intent == "repeat":
        return FastPathResult(
            intent, last_reply or "Ich habe noch nichts gesagt, das ich wiederholen könnte."
        )
    return None

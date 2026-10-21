# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Guards against invented facts: clock times (AGENT-06) and weather values (AGENT-11).

A language model that "knows" the time or the weather is guessing. When an answer contains such a
value although the matching tool did not run in this turn, the loop discards the answer and runs the
tool itself (see ``AgentLoop``).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

_NUMBER_WORDS = (
    "ein|eins|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|dreizehn|vierzehn|"
    "fünfzehn|sechzehn|siebzehn|achtzehn|neunzehn|zwanzig"
)
CLOCK_TIME = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b"
    r"|\b(?:[01]?\d|2[0-3])\.[0-5]\d\s*uhr\b"
    r"|\b(?:[01]?\d|2[0-4])\s*uhr(?:\s*[0-5]?\d)?\b"
    rf"|\b(?:viertel|dreiviertel|kurz|fünf|zehn|zwanzig)\s+(?:nach|vor)\s+(?:{_NUMBER_WORDS})\b"
    rf"|\bhalb\s+(?:{_NUMBER_WORDS})\b",
    re.IGNORECASE,
)
TIME_QUESTION = re.compile(
    r"\b(?:wie spät|wieviel uhr|wie viel uhr|uhrzeit|wie spät ist es|welche zeit)\b", re.IGNORECASE
)
WEATHER_VALUE = re.compile(
    r"-?\d+(?:[.,]\d+)?\s?(?:°|grad\b)"
    r"|\b\d+(?:[.,]\d+)?\s?(?:prozent|%)\s+(?:regen|niederschlag|wahrscheinlichkeit)"
    r"|\b\d+(?:[.,]\d+)?\s?(?:km/h|kilometer pro stunde|m/s|mm\b)"
    r"|\b\d+(?:[.,]\d+)?\s?(?:hektopascal|hpa)\b",
    re.IGNORECASE,
)
WEATHER_WORDS = re.compile(
    r"\b(?:wetter|regen|regnet|schnee|schneit|gewitter|sturm|wind|böen|frost|bewölkt|sonnig|"
    r"temperatur|vorhersage|niederschlag|nebel|hagel|schauer|luftdruck|luftfeuchtigkeit|"
    r"hitze|kälte|wolken|wolkig)\b",
    re.IGNORECASE,
)
# "warm", "kalt" … only mean the weather when the question is about now or here ("Wie heiß ist
# Lava?" is not)
WEATHER_WEAK = re.compile(r"\b(?:warm|kalt|heiß|kühl|schirm|jacke)\b", re.IGNORECASE)
WEATHER_CONTEXT = re.compile(
    r"\b(?:draußen|heute|morgen|gerade|jetzt|hier|abend|nacht|nachts|wochenende|später)\b",
    re.IGNORECASE,
)


def _weather_context(answer: str, user_text: str) -> bool:
    return bool(
        WEATHER_WORDS.search(answer)
        or WEATHER_WORDS.search(user_text)
        or (WEATHER_WEAK.search(user_text) and WEATHER_CONTEXT.search(user_text))
    )


FAREWELL = re.compile(
    r"\b(?:tschüss|tschüs|tschau|ciao|auf wiedersehen|wiederhören|bis dann|bis bald|"
    r"mach's gut|mach es gut|schönen tag noch|das war's|das wars)\b",
    re.IGNORECASE,
)

TIME_TOOLS = frozenset({"get_current_time"})
WEATHER_TOOLS = frozenset({"get_weather", "get_warnings", "everyday_advice"})


@dataclass(frozen=True)
class Violation:
    kind: str  # "time" | "weather"
    tool: str  # the tool that must answer instead
    reason: str


_NUMBER = r"\d+(?:[.,]\d+)?"
_VALUE_UNIT = re.compile(
    rf"(?P<a>{_NUMBER})(?:\s?(?:bis|und|oder|–|-)\s?(?P<b>{_NUMBER}))?\s?"
    r"(?P<u>°\s?c?|grad|prozent|%|km/h|kilometer pro stunde|m/s|millimeter|mm|"
    r"liter pro quadratmeter|hektopascal|hpa)",
    re.IGNORECASE,
)
_UNITS = {
    "°": "grad", "°c": "grad", "grad": "grad", "prozent": "prozent", "%": "prozent",
    "km/h": "kmh", "kilometer pro stunde": "kmh", "m/s": "ms", "mm": "mm",
    "millimeter": "mm", "liter pro quadratmeter": "mm", "hektopascal": "hpa", "hpa": "hpa",
}  # fmt: skip


def _plain(number: str) -> str:
    number = number.replace(".", ",")
    return number.rstrip("0").rstrip(",") if "," in number else number


def weather_values(text: str) -> set[tuple[str, str]]:
    """(number, unit) pairs of a text, ranges counted for both ends: "8 bis 13 Grad" → 8 and 13 °."""
    found = set()
    for match in _VALUE_UNIT.finditer(text):
        unit = _UNITS[
            re.sub(r"\s", "", match.group("u").lower())
            if "°" in match.group("u")
            else match.group("u").lower()
        ]
        for part in ("a", "b"):
            if match.group(part):
                found.add((_plain(match.group(part)), unit))
    return found


def check(
    user_text: str,
    answer: str,
    called: Collection[str],
    supported: set[tuple[str, str]] | None = None,
) -> Violation | None:
    """``called`` are the tools that ran successfully in this turn; ``supported`` the values (see
    ``weather_values``) their weather results contained – when given, every weather value of the
    answer must be one of them."""
    called = set(called)
    # the time: asked for, or stated, without the clock tool
    if not called & TIME_TOOLS:
        if TIME_QUESTION.search(user_text) and (
            CLOCK_TIME.search(answer) or re.search(r"\d", answer)
        ):
            return Violation("time", "get_current_time", "time asked, tool not used")
        if CLOCK_TIME.search(answer) and not called:
            return Violation("time", "get_current_time", "clock time without any tool")
    # weather values without a weather tool (but "Wasser kocht bei 100 Grad" is no weather report)
    if (
        not called & WEATHER_TOOLS
        and WEATHER_VALUE.search(answer)
        and _weather_context(answer, user_text)
    ):
        return Violation("weather", "get_weather", "weather values without a weather tool")
    if called & WEATHER_TOOLS and supported is not None and weather_values(answer) - supported:
        return Violation(
            "weather_mismatch", "get_weather", "weather value is not in the tool result"
        )
    return None


def is_farewell(text: str) -> bool:
    """The caller says goodbye (PHONE-36): short sentence with a farewell word."""
    return bool(FAREWELL.search(text)) and len(text.split()) <= 8

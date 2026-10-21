# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""German number words → digits, ordinals, clock phrases and spoken postal codes (docs/plan/13 §4.1).

Whisper writes numbers as digits most of the time, but "fünfunddreißig sieben einundachtzig" or
"drei fünf sieben acht eins" still occur on a bad line. Everything here works on already
lower-cased, punctuation-free text.
"""

from __future__ import annotations

import re

UNITS = {
    "null": 0, "eins": 1, "zwei": 2, "zwo": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13,
    "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
    "neunzehn": 19,
}  # fmt: skip
TENS = {
    "zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
    "siebzig": 70, "achtzig": 80, "neunzig": 90,
}  # fmt: skip
# "ein" in all its forms is also the article: only converted inside compounds ("einundzwanzig").
ARTICLES = {"ein", "eine", "einen", "einem", "einer", "eines"}
MONTHS = [
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
]
_DATIVE = {"am", "vom", "zum", "bis", "ab", "seit", "den", "dem", "der", "des", "vor", "nach"}

_ORDINAL_SPECIAL = {
    "erst": 1, "zweit": 2, "dritt": 3, "viert": 4, "fünft": 5, "sechst": 6, "siebt": 7,
    "siebent": 7, "acht": 8, "neunt": 9, "zehnt": 10, "elft": 11, "zwölft": 12,
}  # fmt: skip


def _below_hundred(word: str) -> int | None:
    if word in UNITS:
        return UNITS[word]
    if word == "ein":
        return 1
    if word in TENS:
        return TENS[word]
    if "und" in word:
        unit, _, tens = word.partition("und")
        if tens in TENS and (unit == "ein" or (unit in UNITS and 0 < UNITS[unit] < 10)):
            return TENS[tens] + (1 if unit == "ein" else UNITS[unit])
    return None


def _below_thousand(word: str, *, years: bool = False) -> int | None:
    """Value below 1000; with ``years`` also "neunzehnhundertneunzig" (1990) style years."""
    if not word:
        return None
    if "hundert" in word:
        left, _, right = word.partition("hundert")
        multiplier = 1 if not left else _below_hundred(left)
        if multiplier is None or not (1 <= multiplier <= 9 or (years and 11 <= multiplier <= 99)):
            return None
        rest = 0 if not right else _below_hundred(right)
        return None if rest is None else multiplier * 100 + rest
    return _below_hundred(word)


def parse_cardinal(word: str) -> int | None:
    """Value of a German number word (compound words included), or None.

    Articles ("ein", "eine", …) are not numbers on their own.
    """
    word = word.lower().replace("ß", "ß")
    if not word or word in ARTICLES:
        return None
    if "tausend" in word:
        left, _, right = word.partition("tausend")
        multiplier = 1 if not left else _below_thousand(left)
        if multiplier is None or not 1 <= multiplier <= 999:
            return None
        rest = 0 if not right else _below_thousand(right)
        return None if rest is None else multiplier * 1000 + rest
    return _below_thousand(word, years=True)


def parse_ordinal(word: str) -> int | None:
    """ "vierundzwanzigsten" → 24, "ersten" → 1, "dritte" → 3 (any case ending), or None."""
    match = re.fullmatch(r"(.+?)(?:e|en|er|es|em)", word)
    if not match:
        return None
    stem = match.group(1)
    if stem in _ORDINAL_SPECIAL:
        return _ORDINAL_SPECIAL[stem]
    if stem.endswith("st"):  # zwanzigst, einundzwanzigst, hundertst …
        value = parse_cardinal(stem[:-2])
        if value is not None and value >= 20:
            return value
    if stem.endswith(
        "t"
    ):  # dreizehnt, vierzehnt, … neunzehnt; "…und" + special: "dreiundzwanzigst"
        value = parse_cardinal(stem[:-1])
        if value is not None and 13 <= value <= 19:
            return value
    return None


_SPOKEN_DECIMAL = re.compile(r"(?<![\d.,])(-?\d+) komma (\d+)\b(?![.,]\d)")


def words_to_digits(text: str) -> str:
    """Replace number words by digits ("zwei tausend" is not joined; compound words are).

    A spoken decimal ("zwei komma fünf") becomes "2,5".
    """
    return _SPOKEN_DECIMAL.sub(r"\1,\2", _words_to_digits(text))


def _words_to_digits(text: str) -> str:
    tokens = text.split()
    out: list[str] = []
    for index, token in enumerate(tokens):
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
        prev = tokens[index - 1] if index else ""
        value = parse_cardinal(token)
        if value is not None:
            # "eins" in "eins zu eins" is fine; "acht geben" / "sich in acht nehmen" are rare enough.
            out.append(str(value))
            continue
        ordinal = parse_ordinal(token)
        if ordinal is not None and (nxt in MONTHS or (prev in _DATIVE and nxt in MONTHS)):
            out.append(f"{ordinal}.")
            continue
        if ordinal is not None and prev in {"am", "zum", "vom", "bis"} and ordinal >= 4:
            out.append(f"{ordinal}.")
            continue
        out.append(token)
    return " ".join(out)


def clock_phrases(text: str, *, quarter_dialect: bool = True) -> str:
    """ "halb vier" → "3:30", "viertel nach drei" → "3:15", "viertel vier" → "3:15" (text has digits)."""

    def hh(hour: str) -> int:
        return int(hour)

    def sub_halb(match: re.Match[str]) -> str:
        hour = (hh(match.group(1)) - 1) % 24
        return f"{hour}:30"

    def sub_after(match: re.Match[str]) -> str:
        return f"{hh(match.group(1))}:15"

    def sub_before(match: re.Match[str]) -> str:
        return f"{(hh(match.group(1)) - 1) % 24}:45"

    text = re.sub(r"\bviertel nach (\d{1,2})\b", sub_after, text)
    text = re.sub(r"\bviertel vor (\d{1,2})\b", sub_before, text)
    text = re.sub(r"\bhalb (\d{1,2})\b(?! uhr)", sub_halb, text)
    if quarter_dialect:
        text = re.sub(
            r"\bdrei ?viertel (\d{1,2})\b", lambda m: f"{(hh(m.group(1)) - 1) % 24}:45", text
        )
        text = re.sub(r"\b3 viertel (\d{1,2})\b", lambda m: f"{(hh(m.group(1)) - 1) % 24}:45", text)
        text = re.sub(r"\bviertel (\d{1,2})\b", lambda m: f"{(hh(m.group(1)) - 1) % 24}:15", text)
    return text


def postcode_candidates(text: str) -> list[str]:
    """Five-digit numbers hidden in runs of number tokens: "3 5 7 8 1" / "35 781" → "35781"."""
    tokens = [t.strip(".,") for t in text.split()]
    found: list[str] = []
    for start in range(len(tokens)):
        digits = ""
        for token in tokens[start : start + 5]:
            if not token.isdigit():
                break
            digits += token
            if len(digits) == 5:
                found.append(digits)
                break
            if len(digits) > 5:
                break
    return list(dict.fromkeys(found))

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""German text normalization for speech output.

CosyVoice's built-in text frontend only knows Chinese and English: digits would be read in
English. Everything that reaches the TTS is therefore turned into plain German words first
(numbers, times, dates, percent, units, abbreviations) and stripped of markdown, links and
emoji. The result contains no digits.
"""

from __future__ import annotations

import re
import unicodedata

_ONES = [
    "null", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
    "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn",
]  # fmt: skip
_TENS = {
    2: "zwanzig",
    3: "dreißig",
    4: "vierzig",
    5: "fünfzig",
    6: "sechzig",
    7: "siebzig",
    8: "achtzig",
    9: "neunzig",
}
_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember",
]  # fmt: skip
_ORDINAL_SPECIAL = {1: "erste", 3: "dritte", 7: "siebte", 8: "achte"}
_DATIVE_WORDS = {"am", "vom", "zum", "im", "bis", "seit", "den", "dem", "vor", "nach", "ab", "um"}

_ABBREVIATIONS = (
    (r"\bz\.\s?B\.", "zum Beispiel"),
    (r"\bd\.\s?h\.", "das heißt"),
    (r"\bu\.\s?a\.", "unter anderem"),
    (r"\bv\.\s?a\.", "vor allem"),
    (r"\bu\.\s?s\.\s?w\.", "und so weiter"),
    (r"\busw\.", "und so weiter"),
    (r"\bggf\.", "gegebenenfalls"),
    (r"\bca\.", "circa"),
    (r"\bbzw\.", "beziehungsweise"),
    (r"\bevtl\.", "eventuell"),
    (r"\bNr\.", "Nummer"),
    (r"\bDr\.", "Doktor"),
    (r"\bProf\.", "Professor"),
    (r"\bTel\.", "Telefon"),
    (r"\bStr\.", "Straße"),
    (r"\binkl\.", "inklusive"),
    (r"\bMio\.", "Millionen"),
    (r"\bMrd\.", "Milliarden"),
)
_UNITS = (
    (r"°\s?C\b", " Grad Celsius"),
    (r"°", " Grad"),
    (r"\s?%", " Prozent"),
    (r"\s?€", " Euro"),
    (r"\s?\$", " Dollar"),
    (r"(?<=\d)\s?km/h\b", " Kilometer pro Stunde"),
    (r"(?<=\d)\s?km\b", " Kilometer"),
    (r"(?<=\d)\s?cm\b", " Zentimeter"),
    (r"(?<=\d)\s?mm\b", " Millimeter"),
    (r"(?<=\d)\s?kg\b", " Kilogramm"),
    (r"(?<=\d)\s?GB\b", " Gigabyte"),
    (r"(?<=\d)\s?MB\b", " Megabyte"),
    (r"(?<=\d)\s?m\b", " Meter"),
    (r"(?<=\d)\s?g\b", " Gramm"),
    (r"(?<=\d)\s?l\b", " Liter"),
    (r"(?<=\d)\s?min\b", " Minuten"),
)


def cardinal(n: int, *, eins: bool = True) -> str:
    """Spell out an integer (0 … 999 999 999) in German; ``eins=False`` gives the attributive "ein"."""
    if n < 0:
        return "minus " + cardinal(-n, eins=eins)
    if n >= 1_000_000_000:
        return " ".join(cardinal(int(d)) for d in str(n))  # too large: digit by digit
    if n < 20:
        if n == 1:
            return "eins" if eins else "ein"
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return _TENS[tens]
        return f"{cardinal(ones, eins=False)}und{_TENS[tens]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = "hundert" if hundreds == 1 else f"{cardinal(hundreds, eins=False)}hundert"
        return head + (cardinal(rest, eins=eins) if rest else "")
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = "tausend" if thousands == 1 else f"{cardinal(thousands, eins=False)}tausend"
        return head + (cardinal(rest, eins=eins) if rest else "")
    millions, rest = divmod(n, 1_000_000)
    noun = "eine Million" if millions == 1 else f"{cardinal(millions, eins=False)} Millionen"
    return noun + (" " + cardinal(rest, eins=eins) if rest else "")


def _year(n: int) -> str:
    """Years 1100–1999 are read in hundreds ("neunzehnhundertneunzig")."""
    if 1100 <= n <= 1999:
        hundreds, rest = divmod(n, 100)
        return f"{cardinal(hundreds, eins=False)}hundert" + (cardinal(rest) if rest else "")
    return cardinal(n)


def ordinal(n: int, ending: str = "e") -> str:
    """Ordinal stem for days of the month and similar (1 … 31 and beyond)."""
    if n in _ORDINAL_SPECIAL:
        stem = _ORDINAL_SPECIAL[n]
    elif n < 20:
        stem = cardinal(n, eins=False) + "te"
    else:
        stem = cardinal(n, eins=False) + "ste"
    return stem[:-1] + ending


def _strip_noise(text: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[`*_#>|~]+", " ", text)  # markdown markers
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    cleaned = []
    for char in text:
        category = unicodedata.category(char)
        if char != "°" and (category.startswith("So") or category in ("Cs", "Co", "Cn")):
            continue  # emoji and pictographs
        if category.startswith("C") and char not in "\n\t":
            continue
        cleaned.append(char)
    return "".join(cleaned)


def _expand_dates_and_times(text: str) -> str:
    def date_numeric(match: re.Match[str]) -> str:
        day, month, year = int(match[1]), int(match[2]), match[3]
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return match[0]
        ending = "en" if _preceded_by_dative(text, match.start()) else "e"
        spoken = f"{ordinal(day, ending)} {_MONTHS[month - 1]}"
        if year:
            spoken += " " + _year(int(year) if len(year) == 4 else 2000 + int(year))
        return spoken

    def date_month(match: re.Match[str]) -> str:
        day = int(match[1])
        ending = "en" if _preceded_by_dative(text, match.start()) else "e"
        return f"{ordinal(day, ending)} {match[2]}"

    def clock(match: re.Match[str]) -> str:
        hours, minutes = int(match[1]), int(match[2])
        if hours > 24 or minutes > 59:
            return match[0]
        spoken = f"{cardinal(hours, eins=False)} Uhr"
        return spoken + (f" {cardinal(minutes)}" if minutes else "")

    text = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?(?!\d)", date_numeric, text)
    month_names = "|".join(_MONTHS)
    text = re.sub(rf"\b(\d{{1,2}})\.\s?({month_names})\b", date_month, text)
    text = re.sub(r"\b(\d{1,2})[:.](\d{2})(?:\s?Uhr)?\b(?!\d)", clock, text)
    return text


def _preceded_by_dative(text: str, position: int) -> bool:
    words = re.findall(r"[A-Za-zÄÖÜäöüß]+", text[max(0, position - 20) : position])
    return bool(words) and words[-1].lower() in _DATIVE_WORDS


def _expand_euro_cents(text: str) -> str:
    def euro_cents(match: re.Match[str]) -> str:
        euros, cents = int(match[1]), int(match[2])
        spoken = f"{cardinal(euros, eins=False)} Euro"
        return spoken + (f" {cardinal(cents)}" if cents else "")

    return re.sub(r"\b(\d+),(\d{2})\s?€", euro_cents, text)


def _expand_numbers(text: str) -> str:
    def decimal(match: re.Match[str]) -> str:
        whole = cardinal(int(match[1]))
        digits = " ".join(cardinal(int(d)) for d in match[2])
        return f"{whole} Komma {digits}"

    def integer(match: re.Match[str]) -> str:
        raw = match[0].replace(".", "")
        value = int(raw)
        after = text[match.end() : match.end() + 14].lstrip()
        before = text[max(0, match.start() - 12) : match.start()].lower()
        if 1100 <= value <= 1999 and re.search(
            r"(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember|jahr\w*|seit|im)\s*$",
            before,
        ):
            return _year(value)
        if value == 1 and after.lower().startswith("million"):
            return "eine"
        if value == 1 and after.lower().startswith(("uhr", "mal", "euro", "grad")):
            return "ein"
        if value == 1 and after.lower().startswith(
            ("prozent", "kilo", "meter", "liter", "gramm", "minute", "stunde", "tag")
        ):
            return "ein"
        return cardinal(value)

    text = re.sub(r"\b(\d+),(\d{1,3})\b", decimal, text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+\b", integer, text)
    return text


def normalize_for_tts(text: str) -> str:
    """Return plain German words for ``text`` (no digits, no markup)."""
    text = _strip_noise(text)
    for pattern, replacement in _ABBREVIATIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE if "usw" in pattern else 0)
    text = _expand_dates_and_times(text)
    text = _expand_euro_cents(text)
    for pattern, replacement in _UNITS:
        text = re.sub(pattern, replacement, text)
    text = _expand_numbers(text)
    text = text.replace("&", " und ").replace("+", " plus ").replace("=", " gleich ")
    text = re.sub(r"[\"“”„«»()\[\]{}<>/\\]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", ". ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.strip()


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ„\"])")


def split_sentences(text: str, max_chars: int = 220) -> list[str]:
    """Split into sentences for sentence-by-sentence synthesis; long ones are cut at commas."""
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            cut = sentence.rfind(",", 0, max_chars)
            cut = cut if cut > 40 else sentence.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            pieces.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentence:
            pieces.append(sentence)
    return pieces

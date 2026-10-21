# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""German text normalization for speech output (docs/plan/13 §9.3).

Piper (and the emergency voice espeak-ng) read digits and abbreviations unreliably, so everything
that reaches the voice is turned into plain German words first: numbers (with the right "ein/eine/
eins"), times, dates, minus signs and ranges, units ("l/m²", "hPa", "µg/m³", "ct/kWh" …), money,
postcodes digit by digit, wind directions, and the pronunciation list
``assets/data/sprache/aussprache.toml``; markdown, links and emoji are removed. The result contains no
digits.
"""

from __future__ import annotations

import functools
import re
import tomllib
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PRONUNCIATION_FILE = (
    Path(__file__).resolve().parents[3] / "assets" / "data" / "sprache" / "aussprache.toml"
)

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
    (r"(?<=\d)\s?l/m²", " Liter pro Quadratmeter"),
    (r"(?<=\d)\s?mm/h\b", " Millimeter pro Stunde"),
    (r"(?<=\d)\s?m/s\b", " Meter pro Sekunde"),
    (r"(?<=\d)\s?µg/m³", " Mikrogramm pro Kubikmeter"),
    (r"(?<=\d)\s?mg/m³", " Milligramm pro Kubikmeter"),
    (r"(?<=\d)\s?ct/kWh\b", " Cent pro Kilowattstunde"),
    (r"(?<=\d)\s?€/kWh\b", " Euro pro Kilowattstunde"),
    (r"(?<=\d)\s?kWh\b", " Kilowattstunden"),
    (r"(?<=\d)\s?hPa\b", " Hektopascal"),
    (r"(?<=\d)\s?km²", " Quadratkilometer"),
    (r"(?<=\d)\s?m²", " Quadratmeter"),
    (r"(?<=\d)\s?m³", " Kubikmeter"),
    (r"(?<=\d)\s?kW\b", " Kilowatt"),
    (r"(?<=\d)\s?ct\b", " Cent"),
    (r"\bBft\s?(?=\d)", "Windstärke "),
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


@functools.cache
def _pronunciations(path: Path = PRONUNCIATION_FILE) -> tuple[tuple[re.Pattern[str], str], ...]:
    """The replacements of ``aussprache.toml`` as compiled patterns (empty if the file is missing)."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    rules: list[tuple[re.Pattern[str], str]] = []
    words: dict[str, str] = dict(data.get("woerter", {}))
    for word in data.get("buchstaben", {}).get("words", []):
        words[word] = " ".join(word)
    for word, spoken in sorted(words.items(), key=lambda item: -len(item[0])):
        rules.append((re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])"), spoken))
    for pattern, spoken in data.get("ausdruecke", {}).items():
        rules.append((re.compile(pattern, re.IGNORECASE), spoken))
    return tuple(rules)


def _pronounce(text: str) -> str:
    for pattern, spoken in _pronunciations():
        text = pattern.sub(spoken, text)
    return text


_DIRECTIONS = {
    "NNO": "Nordnordost", "NNW": "Nordnordwest", "SSO": "Südsüdost", "SSW": "Südsüdwest",
    "ONO": "Ostnordost", "OSO": "Ostsüdost", "WNW": "Westnordwest", "WSW": "Westsüdwest",
    "NO": "Nordost", "NW": "Nordwest", "SO": "Südost", "SW": "Südwest",
}  # fmt: skip
_FEMININE = {
    "minute", "minuten", "stunde", "stunden", "sekunde", "sekunden", "woche", "wochen", "tonne",
    "flasche", "packung", "dose", "tasse", "tüte", "scheibe", "portion", "seite", "million",
}  # fmt: skip
_MASCULINE_E = {"name", "käse", "gedanke", "buchstabe", "friede", "glaube", "wille", "funke"}
_HALF_UNITS = r"(?:Liter|Meter|Kilometer|Kilogramm|Stunden|Tage|Wochen|Jahre|Monate)"


_FRACTIONS = {
    "1/2": "ein halb",
    "1/3": "ein Drittel",
    "2/3": "zwei Drittel",
    "1/4": "ein Viertel",
    "3/4": "drei Viertel",
    "1/8": "ein Achtel",
    "3/8": "drei Achtel",
}


def _prepare_numbers(text: str) -> str:
    """Before everything else: ISO dates as German dates, thousands dots out ("1.234,56" →
    "1234,56", so the money/decimal/unit rules see one number), common fractions as words."""
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\3.\2.\1", text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})+(?![\d.])", lambda m: m[0].replace(".", ""), text)
    return re.sub(
        r"(?<![\d/])([1-3])/([2348])(?![\d/])", lambda m: _FRACTIONS.get(m[0], m[0]), text
    )


def _expand_signs_and_ranges(text: str) -> str:
    """ "−3" → "minus 3", "12–15" → "12 bis 15" (also times: "12:30–13:00")."""
    # a range that ends below zero: "-5–-2 °C" → "-5 bis -2 °C" (the signs follow below)
    text = re.sub(r"(\d)\s?[–−]\s?(?=[−-]\d)", r"\1 bis ", text)
    number = r"(\d{1,2}[:.]\d{2}|\d{1,4}(?:,\d+)?)"
    text = re.sub(rf"(?<![\d\w,.:-]){number}\s?[–−-]\s?{number}(?![\d-])", r"\1 bis \2", text)
    return re.sub(r"(?<![\w.,:])[−–-]\s?(?=\d)", "minus ", text)


def _digits(code: str) -> str:
    return " ".join(cardinal(int(d)) for d in code)


def _expand_postcodes_and_directions(text: str) -> str:
    text = re.sub(
        r"\b(?:Postleitzahl|PLZ)\s*(\d{5})\b", lambda m: "Postleitzahl " + _digits(m[1]), text
    )
    text = re.sub(
        r"\b(in|für|bei|aus|nach|von)\s+(\d{5})\b(?=\s+[A-ZÄÖÜ])",
        lambda m: f"{m[1]} {_digits(m[2])}",
        text,
    )
    pattern = r"\b(" + "|".join(sorted(_DIRECTIONS, key=len, reverse=True)) + r")\b"
    return re.sub(pattern, lambda m: _DIRECTIONS[m[1]], text)


def _half(match: re.Match[str]) -> str:
    whole = int(match[1])
    if whole == 0:
        return f"null Komma fünf {match[2]}"
    return (
        ("eineinhalb" if whole == 1 else f"{cardinal(whole, eins=False)}einhalb") + " " + match[2]
    )


def _expand_meters(text: str) -> str:
    """ "1,42 m" (a river level) → "ein Meter zweiundvierzig"."""

    def meters(match: re.Match[str]) -> str:
        whole, centi = int(match[1]), int(match[2])
        spoken = f"{cardinal(whole, eins=False)} Meter"
        return spoken + (f" {cardinal(centi)}" if centi else "")

    return re.sub(r"\b(\d+),(\d{2})\s?m\b(?![²³/])", meters, text)


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
        amount = Decimal(f"{match[1]}.{match[2]}").quantize(Decimal("0.01"), ROUND_HALF_UP)
        euros, cents = int(amount), int((amount - int(amount)) * 100)
        spoken = f"{cardinal(euros, eins=False)} Euro"
        return spoken + (f" {cardinal(cents)}" if cents else "")

    # "1,729 €" (fuel prices) is rounded to cents; "1,5 €" is one euro fifty
    return re.sub(r"\b(\d+),(\d{1,4})\s?€", euro_cents, text)


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
        if value == 1:
            word = re.match(r"[A-Za-zÄÖÜäöüß]+", after)
            noun = word[0] if word else ""
            low = noun.lower()
            if low.startswith("million"):
                return "eine"
            if noun[
                :1
            ].isupper():  # a noun follows: its gender decides ("eine Minute", "ein Pfund")
                feminine = low in _FEMININE or (low.endswith("e") and low not in _MASCULINE_E)
                return "eine" if feminine else "ein"
            if low in {"mal", "uhr"}:
                return "ein"
        return cardinal(value)

    text = re.sub(r"\b(\d+),(\d+)\b", decimal, text)
    text = re.sub(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+\b", integer, text)
    return text


def normalize_for_tts(text: str) -> str:
    """Return plain German words for ``text`` (no digits, no markup)."""
    text = _strip_noise(text)
    text = _pronounce(text)
    text = _prepare_numbers(text)
    for pattern, replacement in _ABBREVIATIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE if "usw" in pattern else 0)
    text = _expand_postcodes_and_directions(text)
    text = _expand_signs_and_ranges(text)
    text = _expand_dates_and_times(text)
    text = _expand_euro_cents(text)
    text = _expand_meters(text)
    for pattern, replacement in _UNITS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(rf"\b(\d+),5\s+({_HALF_UNITS})\b", _half, text)
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

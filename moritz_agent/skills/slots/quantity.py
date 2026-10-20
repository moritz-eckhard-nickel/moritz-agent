# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Numbers, arithmetic expressions and units (docs/plan/13 §6.11).

The arithmetic parser is a small recursive-descent parser over a closed set of tokens (numbers,
``+ - * / ^ ( )`` and ``sqrt``) – never ``eval`` – with limits on the exponent and the result.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from moritz_agent.skills.data import load_toml

MAX_EXPONENT = 100
MAX_RESULT = 1e15


class CalcError(ValueError):
    """The expression cannot be evaluated; the message is speakable."""


# -- numbers -------------------------------------------------------------------------------
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


def parse_number(text: str) -> float:
    """ "1.234,5" → 1234.5, "19,90" → 19.9, "3.5" → 3.5, "1.234" → 1234."""
    text = text.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", text):
        text = text.replace(".", "")
    return float(text.replace(",", "."))


def find_numbers(text: str) -> list[float]:
    return [parse_number(m.group(0)) for m in _NUMBER.finditer(text)]


# -- arithmetic ----------------------------------------------------------------------------
_WORD_OPS = (
    (r"\bgeteilt durch\b|\bdividiert durch\b|\bdurch\b", " / "),
    (r"\bmultipliziert mit\b|\bmal\b", " * "),
    (r"\bplus\b", " + "),
    (r"\bminus\b", " - "),
    (r"\bhoch\b", " ^ "),
    (r"\bzum quadrat\b", " ^ 2 "),
    (r"\bzur dritten\b|\bin der dritten potenz\b", " ^ 3 "),
    (r"\bwurzel aus\b|\bquadratwurzel aus\b|\bdie wurzel von\b|\bwurzel von\b", " sqrt "),
    (r"\bklammer auf\b", " ( "),
    (r"\bklammer zu\b", " ) "),
)
_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)|(?P<op>[-+*/^()×÷])|(?P<fn>sqrt))"
)


def to_expression(text: str) -> str:
    """Spoken arithmetic → symbols ("17 mal 23" → "17 * 23")."""
    for pattern, symbol in _WORD_OPS:
        text = re.sub(pattern, symbol, text)
    text = re.sub(r"(?<=\d) ?[x×] ?(?=\d)", " * ", text)
    text = text.replace("÷", " / ").replace("×", " * ")
    return re.sub(r"\s+", " ", text).strip()


def extract_expression(text: str) -> str | None:
    """The arithmetic part of a sentence, or None if there is no calculation in it."""
    expr = to_expression(text)
    best = ""
    for m in re.finditer(r"(?:-\s*)?(?:sqrt\s*)?[\d(](?:[\d\s.,+\-*/^()sqrt]*[\d)])?", expr):
        chunk = m.group(0).strip()
        if len(chunk) > len(best) and re.search(r"[-+*/^]|sqrt", chunk):
            best = chunk
    return best or None


@dataclass
class _Parser:
    tokens: list[tuple[str, str]]
    pos: int = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expr(self) -> float:
        value = self.term()
        while (t := self.peek()) in {("op", "+"), ("op", "-")}:
            assert t is not None
            self.take()
            right = self.term()
            value = value + right if t[1] == "+" else value - right
            _check(value)
        return value

    def term(self) -> float:
        value = self.power()
        while (t := self.peek()) and t[0] == "op" and t[1] in "*/":
            self.take()
            right = self.power()
            if t[1] == "*":
                value *= right
            else:
                if right == 0:
                    raise CalcError("Durch null kann man nicht teilen.")
                value /= right
            _check(value)
        return value

    def power(self) -> float:
        base = self.unary()
        if self.peek() == ("op", "^"):
            self.take()
            exponent = self.power()
            if abs(exponent) > MAX_EXPONENT:
                raise CalcError("Die Hochzahl ist mir zu groß.")
            try:
                base = base**exponent
            except (OverflowError, ZeroDivisionError):
                raise CalcError("Das Ergebnis ist zu groß für mich.") from None
            if isinstance(base, complex):
                raise CalcError("Daraus gibt es kein reelles Ergebnis.")
            _check(base)
        return base

    def unary(self) -> float:
        t = self.peek()
        if t == ("op", "-"):
            self.take()
            return -self.unary()
        if t == ("op", "+"):
            self.take()
            return self.unary()
        if t == ("fn", "sqrt"):
            self.take()
            value = self.unary()
            if value < 0:
                raise CalcError("Aus einer negativen Zahl gibt es keine reelle Wurzel.")
            return math.sqrt(value)
        return self.atom()

    def atom(self) -> float:
        if not self.peek():
            raise CalcError("Die Rechnung ist unvollständig.")
        kind, value = self.take()
        if kind == "num":
            return parse_number(value)
        if (kind, value) == ("op", "("):
            inner = self.expr()
            if self.peek() != ("op", ")"):
                raise CalcError("Es fehlt eine Klammer.")
            self.take()
            return inner
        raise CalcError("Das verstehe ich als Rechnung nicht.")


def _check(value: float) -> None:
    if abs(value) > MAX_RESULT:
        raise CalcError("Das Ergebnis ist größer als eine Billiarde – das ist mir zu groß.")


def evaluate(expression: str) -> float:
    """Evaluate a prepared expression; raises :class:`CalcError` with a speakable message."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    expression = expression.strip()
    while pos < len(expression):
        m = _TOKEN.match(expression, pos)
        if not m or m.end() == pos:
            if expression[pos:].strip() == "":
                break
            raise CalcError("Das verstehe ich als Rechnung nicht.")
        for kind in ("num", "op", "fn"):
            if m.group(kind) is not None:
                value = m.group(kind)
                tokens.append((kind, {"×": "*", "÷": "/"}.get(value, value)))
        pos = m.end()
    if not tokens or len(tokens) > 60:
        raise CalcError("Das verstehe ich als Rechnung nicht.")
    parser = _Parser(tokens)
    result = parser.expr()
    if parser.pos != len(tokens):
        raise CalcError("Das verstehe ich als Rechnung nicht.")
    return result


def format_result(value: float) -> tuple[str, bool]:
    """Speakable number and whether it had to be rounded ("etwa")."""
    from moritz_agent.skills.render.german import number

    if abs(value - round(value)) < 1e-9:
        return number(round(value), 0), False
    rounded = round(value, 4)
    return number(rounded, 4), abs(rounded - value) > 1e-12


# -- units ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class Unit:
    key: str
    name: str  # singular German name
    plural: str
    category: str
    factor: float  # to the base unit of the category
    offset: float = 0.0  # temperature: base = (value + offset) * factor


@lru_cache(maxsize=1)
def _units() -> tuple[dict[str, Unit], list[str]]:
    data = load_toml("einheiten.toml")
    table: dict[str, Unit] = {}
    for category, entries in data["kategorie"].items():
        for key, spec in entries.items():
            unit = Unit(
                key=key,
                name=spec["name"],
                plural=spec.get("plural", spec["name"]),
                category=category,
                factor=float(spec["faktor"]),
                offset=float(spec.get("offset", 0.0)),
            )
            for alias in (
                key,
                spec["name"].lower(),
                spec.get("plural", spec["name"]).lower(),
                *spec.get("alias", []),
            ):
                table[alias.lower()] = unit
    names = sorted(table, key=len, reverse=True)
    return table, names


def find_unit(text: str) -> Unit | None:
    """The unit named by ``text`` (exact alias match), or None."""
    table, _ = _units()
    return table.get(text.strip().lower())


def unit_names() -> list[str]:
    return _units()[1]


def convert(value: float, source: Unit, target: Unit) -> float:
    if source.category != target.category:
        raise CalcError("Das passt nicht zusammen – das sind verschiedene Größen.")
    if source.category == "verbrauch":
        liters_per_100km = _to_l100(value, source)
        return _from_l100(liters_per_100km, target)
    base = (value + source.offset) * source.factor
    return base / target.factor - target.offset


def _to_l100(value: float, unit: Unit) -> float:
    if unit.key == "l/100km":
        return value
    if value == 0:
        raise CalcError("Null Verbrauch kann ich nicht umrechnen.")
    return unit.factor / value  # mpg (US/UK): l/100 km = factor / mpg


def _from_l100(value: float, unit: Unit) -> float:
    if unit.key == "l/100km":
        return value
    if value == 0:
        raise CalcError("Null Verbrauch kann ich nicht umrechnen.")
    return unit.factor / value

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Calculating and converting (docs/plan/13 §6.11) – offline, never ``eval``."""

from __future__ import annotations

import re

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.catalog.common import say
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.slots.quantity import (
    CalcError,
    Unit,
    convert,
    evaluate,
    extract_expression,
    find_numbers,
    find_unit,
    format_result,
    parse_number,
    unit_names,
)

_NUM = r"(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_PCT = rf"(?P<p>{_NUM}) ?(?:prozent|%)"
_AMOUNT = rf"(?P<a>{_NUM})(?: ?(?:euro|€|eur))?"


def _fmt(value: float) -> str:
    text, rounded = format_result(value)
    return f"etwa {text}" if rounded else text


def _money(value: float) -> str:
    return g.euro(value)


_CENTS_AFTER = (
    r"(?!\s*(?:[.,]\d|prozent|%|euro|€|personen|leute|leuten|mann|freunde|kollegen|stück|mal|"
    r"minuten?|stunden?|tage?n?|wochen?|monate?n?|jahre?n?)\b)"
)


def _join_cents(text: str) -> str:
    """ "3 euro 50" → "3,50 euro" (how prices are spoken)."""
    return re.sub(
        rf"\b(\d+) ?(?:euro|€) (\d{{1,2}})\b{_CENTS_AFTER}",
        lambda m: f"{m.group(1)},{int(m.group(2)):02d} euro",
        text,
    )


# A bare "5-7", "24/7" or "0171-1234567" is a range, a house number, a score or a phone number –
# only a calculation if the sentence asks for one or consists of little else.
_CALC_CUE = re.compile(
    r"\b(?:was (?:ist|sind|ergibt|ergeben|macht|gibt)|wie ?viel (?:ist|sind|macht|ergibt|ergeben|gibt)|"
    r"rechne\w*|berechne\w*|ausrechnen|ergibt|ergeben)\b"
)
_STRONG_OP = re.compile(
    r"\b(?:plus|minus|mal|geteilt|durch|hoch|multipliziert|dividiert|wurzel|quadrat|klammer)\b"
    r"|[+*^×÷]|\d ?x ?\d|\s[-/]|[-/]\s"
)


def _loose_calculation(text: str, expr: str) -> bool:
    """True if ``expr`` only rests on an unspaced ``-`` or ``/`` that is likely not arithmetic."""
    if _STRONG_OP.search(text) or not re.search(r"\d[-/]\d", text):
        return False
    if _CALC_CUE.search(text):
        return False
    if re.search(r"(?<![\d.,])0\d", expr):  # leading zero: a phone or area code
        return True
    rest = re.sub(r"[\d.,/()-]+", " ", text).split()
    return len(rest) > 0


# ---------------------------------------------------------------------------------------------
@skill(
    "calc.arith",
    group="rechnen",
    priority="M",
    help="Rechnen",
    examples=("Was ist 17 mal 23?", "144 geteilt durch 12", "2 hoch 10", "Wurzel aus 144"),
    max_words=14,
    patterns=(
        r"\d ?(?:plus|minus|mal|geteilt durch|durch|hoch|multipliziert mit|dividiert durch|[+*/^×÷-]) ?\(?\d",
        r"\bwurzel (?:aus|von) \d",
        r"\b\d+(?:[.,]\d+)? zum quadrat\b",
        r"\bwas ist \d[\d\s.,]* (?:plus|minus|mal|geteilt durch)\b",
        r"\b(?:rechne|berechne|rechne mal)\b.*\d",
    ),
    exclude=(
        r"\b(?:prozent|%|euro|€|trinkgeld|mehrwertsteuer|mwst|brutto|netto)\b",
        r"\b(?:uhr|tage?n?|wochen|monate?n?|jahre?n?) ?(?:bis|seit|zwischen)\b",
        r"\d{1,2}\.\d{1,2}\.",
        r"\b(?:wie alt|wann|datum|kw)\b",
    ),
)
async def calc_arith(req: Request) -> SkillResult | None:
    expr = extract_expression(req.text)
    if not expr or _loose_calculation(req.text, expr):
        return None
    try:
        value = evaluate(expr)
    except CalcError as exc:
        if str(exc).startswith("Das verstehe"):
            return None
        return say(str(exc))
    spoken_expr = _speak_expression(req.text, expr)
    return say(f"{spoken_expr} ist {_fmt(value)}.", data={"expression": expr, "value": value})


def _speak_expression(text: str, expr: str) -> str:
    """Repeat the calculation in words: "17 mal 23"."""
    words = {
        "+": "plus",
        "-": "minus",
        "*": "mal",
        "/": "geteilt durch",
        "^": "hoch",
        "(": "Klammer auf",
        ")": "Klammer zu",
    }
    out = []
    for token in re.findall(r"sqrt|\d[\d.,]*|[-+*/^()]", expr):
        if token == "sqrt":
            out.append("die Wurzel aus")
        elif token in words:
            out.append(words[token])
        else:
            out.append(token)
    spoken = " ".join(out)
    spoken = re.sub(r"hoch 2\b", "zum Quadrat", spoken)
    return spoken[0].upper() + spoken[1:]


@skill(
    "calc.percent",
    group="rechnen",
    priority="M",
    help="Prozentrechnung",
    examples=("Was sind 19 Prozent von 249?", "Wie viel Prozent sind 30 von 120?"),
    patterns=(
        rf"{_PCT} von {_AMOUNT}",
        rf"\bwie ?viel prozent (?:sind|ist|wären) (?P<x>{_NUM})(?: euro)? von (?P<y>{_NUM})",
        rf"\b(?P<x2>{_NUM})(?: euro)? (?:sind|ist) wie ?viel prozent von (?P<y2>{_NUM})",
        rf"\b{_PCT} (?:mehr|weniger) (?:auf|als|von)\b",
    ),
    exclude=(r"\b(?:mehrwertsteuer|mwst|umsatzsteuer|brutto|netto|trinkgeld|zinsen?)\b",),
)
async def calc_percent(req: Request) -> SkillResult | None:
    text = _join_cents(req.text)
    m = re.search(
        rf"\bwie ?viel prozent (?:sind|ist|wären) ({_NUM})(?: euro)? von ({_NUM})", text
    ) or re.search(rf"\b({_NUM})(?: euro)? (?:sind|ist) wie ?viel prozent von ({_NUM})", text)
    if m:
        x, y = parse_number(m.group(1)), parse_number(m.group(2))
        if y == 0:
            return say("Durch null kann man nicht teilen.")
        return say(f"{_fmt(x)} von {_fmt(y)} sind {_fmt(x / y * 100)} Prozent.")
    m = re.search(rf"({_NUM}) ?(?:prozent|%) von ({_NUM})(?: ?(?:euro|€|eur))?", text)
    if m:
        p, amount = parse_number(m.group(1)), parse_number(m.group(2))
        result = amount * p / 100
        unit = " Euro" if re.search(r"euro|€|eur", text) else ""
        if unit:
            return say(f"{_fmt(p)} Prozent von {_money(amount)} sind {_money(result)}.")
        return say(f"{_fmt(p)} Prozent von {_fmt(amount)} sind {_fmt(result)}.")
    m = re.search(
        rf"({_NUM})(?: euro)? (plus|mit|und|minus) ({_NUM}) ?(?:prozent|%)", text
    ) or re.search(
        rf"({_NUM}) ?(?:prozent|%) (mehr|weniger|aufschlag|rabatt|abschlag) (?:auf|als|von) ({_NUM})",
        text,
    )
    if m:
        if m.group(2) in {"plus", "mit", "und", "minus"}:
            base, op, p = parse_number(m.group(1)), m.group(2), parse_number(m.group(3))
            sign = -1 if op == "minus" else 1
        else:
            p, op, base = parse_number(m.group(1)), m.group(2), parse_number(m.group(3))
            sign = -1 if op in {"weniger", "rabatt", "abschlag"} else 1
        result = base * (1 + sign * p / 100)
        word = "plus" if sign > 0 else "minus"
        if re.search(r"euro|€|eur", text):
            return say(f"{_money(base)} {word} {_fmt(p)} Prozent sind {_money(result)}.")
        return say(f"{_fmt(base)} {word} {_fmt(p)} Prozent sind {_fmt(result)}.")
    return None


@skill(
    "calc.vat",
    group="rechnen",
    priority="S",
    help="Mehrwertsteuer",
    examples=("Was sind 100 Euro netto brutto?", "Wie viel Mehrwertsteuer ist in 59,90 Euro?"),
    patterns=(r"\b(?:mehrwertsteuer|mwst|umsatzsteuer|ust)\b", r"\bbrutto\b", r"\bnetto\b"),
    exclude=(r"\b(?:gehalt|lohn|einkommen|rente)\b",),
)
async def calc_vat(req: Request) -> SkillResult | None:
    text = _join_cents(req.text)
    amounts = find_numbers(re.sub(rf"{_NUM} ?(?:prozent|%)", "", text))
    if not amounts:
        return None
    amount = amounts[0]
    rate_m = re.search(rf"({_NUM}) ?(?:prozent|%)", text)
    if rate_m:
        rate = parse_number(rate_m.group(1))
    else:
        rate = 7.0 if re.search(r"\b(?:ermäßigt\w*|sieben prozent)\b", text) else 19.0
    tax_word = r"(?:mehrwertsteuer|mwst|umsatzsteuer|ust)"
    pct = f"{_fmt(rate)} Prozent"
    # "19 Prozent Mehrwertsteuer von 100 Euro", "Mehrwertsteuer auf 50 Euro": the tax on a net price
    if re.search(rf"\b{tax_word} (?:von|auf|für|bei) (?:den |dem |einem )?{_NUM}", text):
        tax = amount * rate / 100
        return say(
            f"{pct} Mehrwertsteuer auf {_money(amount)} sind {_money(tax)} – "
            f"zusammen {_money(amount + tax)}."
        )
    # "100 Euro plus / mit / zuzüglich Mehrwertsteuer": add the tax
    if re.search(
        rf"\b(?:plus|mit|zuzüglich|zzgl|und)(?: {_NUM} ?(?:prozent|%))? (?:der |die )?{tax_word}\b"
        rf"|\b{tax_word} (?:drauf|dazu|draufrechnen|draufgerechnet|aufschlagen|aufgeschlagen)\b",
        text,
    ):
        gross = amount * (1 + rate / 100)
        return say(
            f"{_money(amount)} plus {pct} Mehrwertsteuer sind {_money(gross)} – "
            f"davon {_money(gross - amount)} Steuer."
        )
    has_tax_word = re.search(rf"\b{tax_word}\b", text) is not None
    extract = re.search(
        r"\b(?:in|enthalten\w*|inklusive|inkl|stecken|steckt|drin|drinnen|abziehen|herausrechnen|raus)\b",
        text,
    )
    if has_tax_word and (extract or ("netto" not in text and "brutto" not in text)):
        tax = amount - amount / (1 + rate / 100)
        return say(f"In {_money(amount)} stecken {_money(tax)} Mehrwertsteuer bei {pct}.")
    net_pos, gross_pos = text.find("netto"), text.find("brutto")
    if net_pos >= 0 and (gross_pos < 0 or net_pos < gross_pos):
        gross = amount * (1 + rate / 100)
        return say(f"{_money(amount)} netto sind {_money(gross)} brutto bei {pct} Mehrwertsteuer.")
    net = amount / (1 + rate / 100)
    return say(f"{_money(amount)} brutto sind {_money(net)} netto bei {pct} Mehrwertsteuer.")


@skill(
    "calc.tip",
    group="rechnen",
    priority="S",
    help="Trinkgeld",
    examples=("10 Prozent Trinkgeld auf 43 Euro?",),
    patterns=(r"\btrinkgeld\b",),
)
async def calc_tip(req: Request) -> SkillResult | None:
    text = _join_cents(req.text)
    pct_m = re.search(rf"({_NUM}) ?(?:prozent|%)", text)
    percent = parse_number(pct_m.group(1)) if pct_m else 10.0
    rest = find_numbers(re.sub(rf"{_NUM} ?(?:prozent|%)", "", text))
    if not rest:
        return None
    amount = rest[0]
    tip = amount * percent / 100
    total = amount + tip
    rounded = float(int(total) + (1 if total % 1 else 0))
    return say(
        f"{_fmt(percent)} Prozent Trinkgeld auf {_money(amount)} sind {_money(tip)}, zusammen {_money(total)} – "
        f"aufgerundet {_money(rounded)}."
    )


@skill(
    "calc.split",
    group="rechnen",
    priority="S",
    help="Rechnung aufteilen",
    examples=("86 Euro durch 3 Personen?",),
    patterns=(
        rf"{_AMOUNT} (?:geteilt )?durch (?P<n>\d+) (?:personen|leute|leuten|mann|freunde|kollegen)",
        rf"\b(?:teilen|aufteilen|aufgeteilt|teilt)\b.*\b(?:{_NUM}).*\b(?:\d+) (?:personen|leute|leuten)\b",
        rf"{_NUM}(?: euro)? (?:unter|auf|für) \d+ (?:personen|leute|leuten)",
    ),
)
async def calc_split(req: Request) -> SkillResult | None:
    m = re.search(
        rf"({_NUM})(?: ?(?:euro|€))?.*?(\d+) (?:personen|leute|leuten|mann|freunde|kollegen)",
        _join_cents(req.text),
    )
    if not m:
        return None
    amount, people = parse_number(m.group(1)), int(m.group(2))
    if people <= 0:
        return say("Durch null Personen kann ich nicht teilen.")
    share = amount / people
    return say(
        f"Jeder zahlt {_money(share)}."
        + (
            " Das geht nicht ganz glatt auf."
            if round(share * people, 2) != round(amount, 2)
            else ""
        )
    )


_FRACTIONS = {
    "halb": 2,
    "hälfte": 2,
    "drittel": 3,
    "viertel": 4,
    "fünftel": 5,
    "sechstel": 6,
    "achtel": 8,
    "zehntel": 10,
}


@skill(
    "calc.fraction",
    group="rechnen",
    priority="S",
    examples=("Was ist ein Drittel von 90?", "Die Hälfte von 150?"),
    patterns=(
        rf"\b(?:(?P<n>\d+|ein|eine|zwei|drei) )?(?:halb\w*|hälfte|drittel|viertel|fünftel|sechstel|achtel|zehntel) von {_NUM}",
        rf"\banderthalb mal {_NUM}",
    ),
)
async def calc_fraction(req: Request) -> SkillResult | None:
    m = re.search(
        rf"\b(?:(\d+|ein|eine|zwei|drei) )?(halb\w*|hälfte|drittel|viertel|fünftel|sechstel|achtel|zehntel) von ({_NUM})",
        req.text,
    )
    if not m:
        return None
    count = {"ein": 1, "eine": 1, "zwei": 2, "drei": 3}.get(m.group(1) or "")
    count = int(m.group(1)) if count is None and m.group(1) else (count or 1)
    word = "halb" if m.group(2).startswith("halb") else m.group(2)
    denom = _FRACTIONS[word]
    base = parse_number(m.group(3))
    result = base * count / denom
    label = {"halb": "Die Hälfte", "hälfte": "Die Hälfte"}.get(word)
    if label and count == 1:
        return say(f"{label} von {_fmt(base)} ist {_fmt(result)}.")
    lead = "Ein" if count == 1 else _fmt(count)
    return say(f"{lead} {word.capitalize()} von {_fmt(base)} ist {_fmt(result)}.")


@skill(
    "calc.discount",
    group="rechnen",
    priority="S",
    examples=("Was kostet 80 Euro minus 25 Prozent?", "80 Euro mit 25 Prozent Rabatt"),
    patterns=(
        rf"{_NUM}(?: ?euro| ?€)? (?:mit|minus|plus|abzüglich|zuzüglich) {_NUM} ?(?:prozent|%)(?: rabatt| aufschlag)?",
        r"\brabatt\b.*\d",
        r"\breduziert\b.*\d",
        r"\baufschlag\b.*\d",
    ),
    exclude=(r"\b(?:mehrwertsteuer|mwst|brutto|netto|trinkgeld)\b",),
)
async def calc_discount(req: Request) -> SkillResult | None:
    text = _join_cents(req.text)
    nums = find_numbers(re.sub(r"(?<=\d) ?(?:prozent|%)", " P", text))
    if len(nums) < 2:
        return None
    price, percent = nums[0], nums[1]
    up = bool(re.search(r"\b(?:plus|zuzüglich|aufschlag|erhöht\w*|teurer)\b", text))
    result = price * (1 + percent / 100) if up else price * (1 - percent / 100)
    money = bool(re.search(r"euro|€|eur|kostet|preis", text))
    word = "plus" if up else "minus"
    fmt = _money if money else _fmt
    tail = "" if up else (f" – du sparst {_money(price - result)}." if money else ".")
    return say(
        f"{fmt(price)} {word} {_fmt(percent)} Prozent sind {fmt(result)}{tail}"
        + ("." if not tail and not up else "." if up else "")
    )


@skill(
    "calc.round",
    group="rechnen",
    priority="K",
    examples=("Runde 3,14159 auf zwei Stellen",),
    patterns=(r"\brunde?\b.*\d", r"\bgerundet\b.*\d", r"\d.*\bgerundet\b"),
)
async def calc_round(req: Request) -> SkillResult | None:
    nums = find_numbers(req.text)
    if not nums:
        return None
    digits = 0
    m = re.search(
        r"auf (\d+|keine|eine|null|ganze) (?:nachkomma)?(?:stellen?|nachkommastellen?)", req.text
    )
    if m and m.group(1).isdigit():
        digits = int(m.group(1))
    elif m and m.group(1) == "eine":
        digits = 1
    value = float(g.round_half_up(nums[0], digits))
    return say(f"Gerundet sind das {g.number(value, digits)}.")


# ---------------------------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------------------------
def _unit_regex() -> str:
    return "|".join(re.escape(n) for n in unit_names() if n and not n.isspace())


def _say_conversion(value: float, source: Unit, target: Unit) -> str:
    result = convert(value, source, target)
    magnitude = abs(result)
    if abs(result - round(result)) < 1e-7 * max(1.0, magnitude):
        spoken, approx = g.number(round(result), 0), False
    else:
        digits = 0 if magnitude >= 100 else 1 if magnitude >= 10 else 2 if magnitude >= 1 else 3
        shown = float(g.round_half_up(result, digits))
        spoken, approx = g.number(shown, digits), abs(shown - result) > 1e-7 * max(1.0, magnitude)
    src = source.name if value == 1 else source.plural
    dst = target.name if abs(result) == 1 else target.plural
    in_words = g.number(value, 3)
    in_words = in_words[0].upper() + in_words[1:]
    return f"{in_words} {src} {'sind' if value != 1 else 'ist'} {'etwa ' if approx else ''}{spoken} {dst}."


@skill(
    "convert.units",
    group="rechnen",
    priority="S",
    help="Einheiten umrechnen",
    examples=(
        "Wie viel sind 5 Meilen in Kilometer?",
        "100 Fahrenheit in Celsius",
        "Wie viele Gramm sind ein Pfund?",
        "3 Esslöffel in Milliliter",
    ),
    patterns=(
        r"\b\d+(?:[.,]\d+)? ?[a-zäöüß°²³/%\"]+(?: [a-zäöüß]+){0,2} (?:in|zu|nach|auf)\b",
        r"\bwie ?viele? [a-zäöüß/²³ ]+ (?:sind|ist|hat|haben|ergeben|entsprechen)\b.*\b(?:\d+|ein|eine|einen|zwei)\b",
        r"\bumrechn\w*\b",
        r"\bwas sind \d+(?:[.,]\d+)? [a-zäöüß°/]+ in\b",
    ),
    exclude=(
        r"\b(?:prozent|%|euro|€|dollar|franken|pfund sterling|kurs)\b",
        r"\b(?:uhr|zeitzone)\b",
    ),
)
async def convert_units(req: Request) -> SkillResult | None:
    text = req.text
    names = _unit_regex()
    number = rf"(?:(?P<neg>(?<![\d.,])-|\bminus ) ?)?(?P<n>{_NUM}|ein|eine|einen|einem|zwei)"

    def num_value(m: re.Match[str]) -> float:
        raw = m.group("n")
        value = {"ein": 1.0, "eine": 1.0, "einen": 1.0, "einem": 1.0, "zwei": 2.0}.get(
            raw
        ) or parse_number(raw)
        return -value if m.group("neg") else value

    m = re.search(
        rf"{number} ?(?P<src>{names})\b (?:in|zu|nach|auf|zu den)\s+(?P<dst>{names})\b", text
    )
    if m:
        source, target = find_unit(m.group("src")), find_unit(m.group("dst"))
        if source and target:
            try:
                return say(_say_conversion(num_value(m), source, target))
            except CalcError as exc:
                return say(str(exc))
    m = re.search(
        rf"wie ?viele? (?P<dst>{names})\b (?:sind|ist|hat|haben|ergeben|entsprechen|sind es|hat ein|hat eine)\s+{number} ?(?P<src>{names})\b",
        text,
    )
    if m:
        source, target = find_unit(m.group("src")), find_unit(m.group("dst"))
        if source and target:
            try:
                return say(_say_conversion(num_value(m), source, target))
            except CalcError as exc:
                return say(str(exc))
    m = re.search(
        rf"wie ?viele? (?P<dst>{names})\b (?:hat|haben) (?:ein|eine|einen|1) (?P<src>{names})\b",
        text,
    )
    if m:
        source, target = find_unit(m.group("src")), find_unit(m.group("dst"))
        if source and target and source.category == target.category:
            return say(_say_conversion(1.0, source, target))
    return None


@skill(
    "convert.numeral",
    group="rechnen",
    priority="K",
    examples=("Was ist 2026 in römischen Zahlen?", "42 in binär?"),
    patterns=(r"\b(?:römisch\w*|binär\w*|hexadezimal\w*|dual\w*)\b",),
)
async def convert_numeral(req: Request) -> SkillResult | None:
    m = re.search(r"\b(\d{1,7})\b", req.text)
    if not m:
        return None
    n = int(m.group(1))
    if "römisch" in req.text:
        if not 1 <= n <= 3999:
            return say("Römische Zahlen gehen bei mir von 1 bis 3999.")
        pairs = (
            (1000, "M"),
            (900, "CM"),
            (500, "D"),
            (400, "CD"),
            (100, "C"),
            (90, "XC"),
            (50, "L"),
            (40, "XL"),
            (10, "X"),
            (9, "IX"),
            (5, "V"),
            (4, "IV"),
            (1, "I"),
        )
        rest, out = n, ""
        for value, letters in pairs:
            while rest >= value:
                out += letters
                rest -= value
        return say(f"{n} ist in römischen Zahlen {' '.join(out)}.")
    if "hex" in req.text:
        return say(f"{n} ist hexadezimal {' '.join(format(n, 'X'))}.")
    return say(f"{n} ist binär {' '.join(format(n, 'b'))}.")

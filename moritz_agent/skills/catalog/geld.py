# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Money and prices: exchange rates, electricity, fuel (docs/plan/13 §6.12)."""

from __future__ import annotations

import re
from datetime import timedelta

from moritz_agent.skills.base import (
    Clarification,
    Option,
    Request,
    SkillResult,
    Source,
)
from moritz_agent.skills.data import load_toml
from moritz_agent.skills.providers import Providers, ProviderUnavailable
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g
from moritz_agent.skills.router import followup_state
from moritz_agent.skills.slots.where import home_place
from moritz_agent.skills.weather.frame import unavailable
from moritz_agent.tools.time_tool import WEEKDAYS_DE

GROUP = "geld"
ECB_SOURCE = Source("Europäische Zentralbank, Referenzkurse", "https://www.ecb.europa.eu/", "")
ENERGY_SOURCE = Source("Energy-Charts (Fraunhofer ISE)", "https://energy-charts.info/", "CC BY 4.0")
FUEL_SOURCE = Source("Tankerkönig / MTS-K", "https://creativecommons.tankerkoenig.de/", "CC BY 4.0")


def _line(*alternatives: str) -> str:
    return rf"^(?:.*\s)?(?:{'|'.join(alternatives)})(?:\s.*)?$"


def _providers(req: Request) -> Providers | None:
    providers = req.svc.providers
    return providers if isinstance(providers, Providers) else None


# -- currencies ---------------------------------------------------------------------------------------
def _currencies() -> dict[str, dict]:
    return load_toml("waehrungen.de.toml")["currencies"]


def _alias_table() -> list[tuple[str, str]]:
    table = [
        (alias, code)
        for code, info in _currencies().items()
        for alias in (*info["aliases"], info["name"].lower())
    ]
    return sorted(table, key=lambda item: -len(item[0]))


def find_currencies(text: str) -> list[tuple[int, int, str]]:
    """(start, end, code) of every currency named in ``text``, in spoken order."""
    found: list[tuple[int, int, str]] = []
    for alias, code in _alias_table():
        pattern = (
            rf"(?<![\wäöüß]){re.escape(alias)}(?:kurs|s)?(?![\wäöüß])"
            if alias.isalnum() or " " in alias
            else re.escape(alias)
        )
        for match in re.finditer(pattern, text):
            if not any(match.start() < e and s < match.end() for s, e, _ in found):
                found.append((match.start(), match.end(), code))
    return sorted(found)


def _ambiguous(text: str) -> list[str] | None:
    table = load_toml("waehrungen.de.toml")["ambiguous"]
    for word, codes in table.items():
        if re.search(rf"\b{word}\b", text) and not any(
            re.search(rf"\b{a}\b", text)
            for a in ("schwedische", "norwegische", "dänische", "tschechische")
        ):
            return list(codes)
    return None


def _name(code: str) -> str:
    return _currencies()[code]["name"]


def _amount_before(text: str, position: int) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*$", text[:position])
    if not match:
        return None
    raw = match.group(1)
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    return float(raw)


def _money(value: float, code: str) -> str:
    if code == "EUR":
        return g.euro(value)
    digits = 0 if value >= 100 else 2
    return f"{g.number(round(value, digits), digits)} {_name(code)}"


def _rates_day(rates_day, today) -> str:
    delta = (today - rates_day).days
    if delta == 0:
        return "von heute"
    if delta == 1:
        return "von gestern"
    if 0 < delta < 7:
        return f"vom {WEEKDAYS_DE[rates_day.weekday()]}"
    return f"vom {g.date_plain(rates_day)}"


async def _fx(req: Request) -> SkillResult | None:
    source_text = req.overrides.get("text", req.text)
    chosen: str | None = req.overrides.get("code")
    amount: float | None = req.overrides.get("amount")
    if chosen is None:
        options = _ambiguous(source_text)
        if options:
            amount_match = re.search(r"(\d+(?:[.,]\d+)?)", source_text)
            amount_value = float(amount_match.group(1).replace(",", ".")) if amount_match else None
            names = ["schwedische", "norwegische", "dänische", "tschechische"]
            question = "Welche Krone meinst du – die " + " oder ".join(names[: len(options)]) + "?"
            return SkillResult(
                text=question,
                clarify=Clarification(
                    question,
                    tuple(
                        Option(
                            label=names[i],
                            params={"code": code, "amount": amount_value, "text": source_text},
                            aliases=(names[i][:-1], _name(code).split()[0].lower()),
                        )
                        for i, code in enumerate(options)
                    ),
                    "money.fx",
                ),
            )
    mentions = find_currencies(source_text)
    codes = [c for _, _, c in mentions]
    if chosen is not None:
        codes = [chosen, *codes]
        mentions = [(0, 0, chosen), *mentions]
    if not codes:
        return None
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("ecb", "offline"), "Kursdaten")
    try:
        fetched = await providers.exchange_rates()
    except ProviderUnavailable as exc:
        return unavailable(exc, "Kursdaten")
    rates = fetched.data
    asks_rate = bool(
        re.search(r"\b(?:kurs|steht|steht der|wert)\b", source_text)
    ) and not re.search(r"\d", source_text)
    if len(codes) == 1:
        source, target = (codes[0], "EUR") if codes[0] != "EUR" else ("EUR", "USD")
    else:
        source, target = codes[0], codes[1]
        if source == target:
            return SkillResult(text="Das ist dieselbe Währung.")
    if asks_rate or (amount is None and not re.search(r"\d", source_text) and len(codes) == 1):
        base = codes[0] if codes[0] != "EUR" else target
        per_euro = rates.per_euro(base)
        if per_euro is None:
            return SkillResult(text=f"Den Kurs für {_name(base)} habe ich nicht.", serious=True)
        value = g.number(round(per_euro, 4 if per_euro < 10 else 2), 4 if per_euro < 10 else 2)
        label = _rates_day(rates.day, req.now.date())
        return SkillResult(
            text=g.sentence(f"Ein Euro kostet {value} {_name(base)} – EZB-Referenzkurs {label}"),
            sources=(ECB_SOURCE,),
            data={"rate": per_euro, "currency": base},
            followup=followup_state("money.fx", code=base),
        )
    if amount is None:
        first_start = mentions[0][0]
        amount = _amount_before(source_text, first_start)
        if amount is None:
            match = re.search(r"(\d+(?:[.,]\d+)?)", source_text)
            amount = float(match.group(1).replace(",", ".")) if match else None
    if amount is None:
        amount = 1.0
    result = rates.convert(amount, source, target)
    if result is None:
        missing = source if rates.per_euro(source) is None else target
        return SkillResult(
            text=f"Für {_name(missing)} gibt es keinen Referenzkurs der EZB.", serious=True
        )
    label = _rates_day(rates.day, req.now.date())
    verb = "ist" if amount == 1.0 else "sind"
    text = (
        f"{_money(amount, source)} {verb} etwa {_money(result, target)} – EZB-Referenzkurs {label}"
    )
    return SkillResult(
        text=g.sentence(text),
        sources=(ECB_SOURCE,),
        data={"amount": amount, "from": source, "to": target, "result": round(result, 4)},
        followup=followup_state("money.fx", code=source),
    )


_FX_WORDS = (
    r"dollar\w*", r"franken", r"pfund", r"yen", r"yuan", r"zloty", r"kron\w+", r"forint", r"lira",
    r"rupie\w*", r"peso\w*", r"baht", r"wechselkurs", r"devisen\w*", r"umrechnen", r"euro",
)  # fmt: skip

skill(
    "money.fx",
    group=GROUP,
    online=True,
    priority="S",
    max_words=12,
    help="Wechselkurse",
    examples=("Wie viel sind 100 Dollar in Euro?", "Wie steht der Franken?", "Euro in Pfund?"),
    patterns=(
        (rf"^(?:.*\s)?(?:{'|'.join(_FX_WORDS)})\b.*\b(?:in|zu|nach|kurs|steht|wert)\b.*$", 0.95),
        (r"^(?:.*\s)?(?:wechselkurs|dollarkurs|eurokurs|frankenkurs|pfundkurs|yenkurs)\b.*$", 1.0),
        (
            r"^(?:.*\s)?wie (?:steht|ist) (?:der |die |das )?(?:dollar|franken|pfund|yen|euro)\w*\b.*$",
            1.0,
        ),
    ),
    exclude=(
        r"\b(?:brutto|netto)\b",
        r"\b(?:wetter|temperatur|grad)\b",
        r"\b(?:kilo|liter|meter|gramm|kilometer|zoll)\b",
        r"\b(?:prozent|mehrwertsteuer|trinkgeld)\b",
    ),
)(_fx)


# -- electricity ---------------------------------------------------------------------------------------
async def _power(req: Request) -> SkillResult | None:
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("energy", "offline"), "Strompreise")
    now = req.now
    tomorrow = bool(re.search(r"\bmorgen\b", req.text))
    day = now.date() + timedelta(days=1 if tomorrow else 0)
    try:
        fetched = await providers.power_prices(day)
    except ProviderUnavailable as exc:
        return unavailable(exc, "Strompreise")
    from moritz_agent.skills.providers import energy_charts

    points = [p for p in fetched.data if p.start.date() == day]
    if not points:
        return SkillResult(
            text="Die Börsenpreise für morgen gibt es erst am Nachmittag."
            if tomorrow
            else "Dazu habe ich gerade keine Preise.",
            serious=True,
        )
    if re.search(r"\b(?:billigsten|günstigsten|billig|günstig|am besten)\b", req.text):
        future = (
            [p for p in points if p.start + timedelta(hours=1) > now] if not tomorrow else points
        )
        window = energy_charts.cheapest_window(future, 2)
        if window is None:
            return SkillResult(text="Dazu habe ich gerade keine Preise.", serious=True)
        start, end, price = window
        label = "morgen" if tomorrow else "heute"
        text = (
            f"Am günstigsten {label} zwischen {start.hour} und {end.hour} Uhr, an der Börse etwa "
            f"{g.number(round(price, 1), 1)} Cent pro Kilowattstunde ohne Steuern und Netzentgelte"
        )
    else:
        current = next(
            (p for p in points if p.start <= now < p.start + timedelta(hours=1)), points[0]
        )
        text = (
            f"{'Morgen früh' if tomorrow else 'Gerade'} kostet Strom an der Börse etwa "
            f"{g.number(round(current.ct_per_kwh, 1), 1)} Cent pro Kilowattstunde, ohne Steuern und Netzentgelte"
        )
    return SkillResult(
        text=g.sentence(text),
        sources=(ENERGY_SOURCE,),
        detail="Der Endkundenpreis ist deutlich höher, weil Netzentgelte, Steuern und Abgaben dazukommen.",
    )


skill(
    "money.power_price",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Wann ist Strom heute am billigsten?", "Was kostet Strom an der Börse?"),
    patterns=(
        (
            r"^(?:.*\s)?strom(?:preis\w*)?\b.*\b(?:billig\w*|günstig\w*|teuer\w*|börse|preis\w*|kostet)\b.*$",
            1.0,
        ),
        (_line(r"börsenstrompreis", r"strompreis\w*", r"strombörse"), 1.0),
        (r"^(?:.*\s)?wie teuer ist (?:der |gerade )?strom\b.*$", 1.0),
    ),
)(_power)


# -- fuel -----------------------------------------------------------------------------------------------
async def _fuel(req: Request) -> SkillResult | None:
    providers = _providers(req)
    if providers is None:
        return unavailable(ProviderUnavailable("fuel", "offline"), "Spritpreise")
    if not req.svc.cfg.money.fuel:
        return SkillResult(text="Spritpreise sind bei mir ausgeschaltet.", serious=True)
    place = home_place(req.svc, req.ctx)
    try:
        fetched = await providers.fuel(place)
    except ProviderUnavailable as exc:
        if exc.reason == "nokey":
            return SkillResult(
                text="Für Spritpreise fehlt mir der Tankerkönig-Schlüssel in der Datei passwords.txt.",
                serious=True,
            )
        return unavailable(exc, "Spritpreise")
    stations = fetched.data
    fuel = req.svc.cfg.money.fuel_type.upper()
    if not stations:
        return SkillResult(
            text=f"Im Umkreis von {g.number(req.svc.cfg.money.fuel_radius_km)} Kilometern hat gerade keine Tankstelle mit {fuel} geöffnet.",
            serious=True,
        )
    best = stations[0]
    where = f" in {best.place}" if best.place else ""
    text = f"Am günstigsten ist {fuel} gerade bei {best.name}{where} für etwa {g.euro(best.price)}"
    if len(stations) > 1:
        text += f", die zweitgünstigste verlangt {g.euro(stations[1].price)}"
    return SkillResult(text=g.sentence(text), sources=(FUEL_SOURCE,), data={"price": best.price})


skill(
    "money.fuel",
    group=GROUP,
    online=True,
    priority="K",
    max_words=12,
    examples=("Was kostet E10 gerade?", "Wo tanke ich am billigsten?"),
    patterns=(
        (
            r"^(?:.*\s)?(?:e10|e5|super|diesel\w*|benzin\w*|sprit\w*)\b.*\b(?:kostet|kosten|preis\w*|teuer\w*|billig\w*|günstig\w*|tanken)\b.*$",
            1.0,
        ),
        (
            r"^(?:.*\s)?(?:kostet|kosten|preis\w*|wie teuer ist|wie billig ist)\b.*\b(?:e10|e5|super|diesel\w*|benzin\w*|sprit\w*)\b.*$",
            1.0,
        ),
        (r"^(?:.*\s)?(?:spritpreis\w*|benzinpreis\w*|dieselpreis\w*)\b.*$", 1.0),
        (r"^(?:.*\s)?wo (?:tanke|tank) ich\b.*$", 1.0),
    ),
    exclude=(r"\b(?:motor|verbrauch|tankvolumen|funktioniert)\b",),
)(_fuel)

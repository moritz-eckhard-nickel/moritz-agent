# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Small helpers: spelling, dice, coin, jokes, counting, timer (docs/plan/13 §6.14)."""

from __future__ import annotations

import re
from datetime import timedelta

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.catalog.common import say
from moritz_agent.skills.data import load_toml
from moritz_agent.skills.registry import skill
from moritz_agent.skills.render import german as g

_SPELL_FILLER = {"man", "mir", "uns", "das", "wort", "mal", "doch", "den", "namen"}
_DICE_WORDS = {"einen": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6}


# ---------------------------------------------------------------------------------------------
@skill(
    "spell.word",
    group="helfer",
    priority="S",
    help="Wörter buchstabieren",
    examples=("Buchstabier Weilburg", "Wie buchstabiert man Lahn?"),
    patterns=(r"\bbuchstabier\w*\b", r"\bbuchstabiert man\b"),
    exclude=(r"\bwie heißt\b.*\bbuchstabiertafel\b",),
)
async def spell_word(req: Request) -> SkillResult | None:
    m = re.search(r"\bbuchstabiert man (.+)$", req.text) or re.search(
        r"\bbuchstabier\w* (.+)$", req.text
    )
    if not m:
        return None
    tokens = [
        t for t in re.sub(r"[^a-zäöüß0-9 ]", "", m.group(1)).split() if t not in _SPELL_FILLER
    ]
    if not tokens:
        return None
    word = "".join(tokens) if all(len(token) == 1 for token in tokens) else tokens[0]
    table = load_toml("buchstabiertafel.toml")[req.svc.cfg.spelling.alphabet]
    parts = []
    for ch in word[:20]:
        if ch.isdigit():
            parts.append(ch)
        elif ch in table:
            parts.append(f"{ch.upper()} wie {table[ch]}" if ch != "ß" else "Eszett")
    if not parts:
        return None
    more = " Weiter buchstabiere ich nicht." if len(word) > 20 else ""
    return say(f"{word.capitalize()}: {', '.join(parts)}.{more}")


@skill(
    "spell.letter",
    group="helfer",
    priority="K",
    examples=("Wie heißt A in der Buchstabiertafel?",),
    patterns=(r"\bbuchstabiertafel\b",),
)
async def spell_letter(req: Request) -> SkillResult | None:
    m = re.search(
        r"\b(?:buchstabe |der buchstabe )?([a-zäöüß])\b(?: in der buchstabiertafel| bei der buchstabiertafel)",
        req.text,
    )
    if not m:
        return None
    table = load_toml("buchstabiertafel.toml")[req.svc.cfg.spelling.alphabet]
    ch = m.group(1)
    if ch not in table:
        return None
    return say(f"{ch.upper()} wie {table[ch]}.")


# ---------------------------------------------------------------------------------------------
@skill(
    "random.coin",
    group="helfer",
    priority="S",
    help="eine Münze werfen",
    examples=("Wirf eine Münze", "Kopf oder Zahl?"),
    patterns=(r"\bmünze\b", r"\bkopf oder zahl\b", r"\bmünzwurf\b"),
)
async def random_coin(req: Request) -> SkillResult:
    return say(req.ctx.rng.choice(("Kopf.", "Zahl.")))


@skill(
    "random.dice",
    group="helfer",
    priority="S",
    help="würfeln",
    examples=("Würfel mal", "Wirf zwei Würfel", "Würfel einen W20"),
    patterns=(r"\bwürfel\w*\b", r"\bw(?:4|6|8|10|12|20|100)\b"),
)
async def random_dice(req: Request) -> SkillResult | None:
    sides = 6
    m = re.search(r"\bw(\d+)\b", req.text) or re.search(r"\b(\d+)(?:er)?[ -]?seitig\w*\b", req.text)
    if m:
        sides = int(m.group(1))
    if not 2 <= sides <= 1000:
        return say("So einen Würfel habe ich nicht.")
    count = 1
    c = re.search(r"\b(\d+|zwei|drei|vier|fünf|sechs) würfel\b", req.text)
    if c:
        count = int(c.group(1)) if c.group(1).isdigit() else _DICE_WORDS[c.group(1)]
    count = min(count, 6)
    rolls = [req.ctx.rng.randint(1, sides) for _ in range(count)]
    if count == 1:
        return say(f"Eine {rolls[0]}." if sides == 6 else f"{rolls[0]}.", data={"rolls": rolls})
    return say(
        f"{g.join_and([str(r) for r in rolls])}, zusammen {sum(rolls)}.", data={"rolls": rolls}
    )


@skill(
    "random.number",
    group="helfer",
    priority="S",
    examples=("Nenn mir eine Zahl zwischen 1 und 100",),
    patterns=(
        r"\bzufallszahl\b",
        r"\b(?:zahl|nummer) zwischen \d+ und \d+\b",
        r"\beine zahl von \d+ bis \d+\b",
    ),
)
async def random_number(req: Request) -> SkillResult:
    m = re.search(r"\b(\d+) (?:und|bis) (\d+)\b", req.text)
    low, high = (int(m.group(1)), int(m.group(2))) if m else (1, 100)
    if low > high:
        low, high = high, low
    return say(f"{req.ctx.rng.randint(low, high)}.")


@skill(
    "random.choice",
    group="helfer",
    priority="K",
    examples=("Entscheide: Pizza oder Döner?",),
    patterns=(
        r"\b(?:entscheide|entscheid|such aus|wähle|wähl|lass das zufall entscheiden)\b.*\boder\b",
    ),
)
async def random_choice(req: Request) -> SkillResult | None:
    body = re.sub(r"^.*?\b(?:entscheide|entscheid|such aus|wähle|wähl)\b[: ]*", "", req.text)
    options = [o.strip() for o in re.split(r"\boder\b|,", body) if o.strip()]
    if len(options) < 2:
        return None
    return say(f"{req.ctx.rng.choice(options).capitalize()}.")


@skill(
    "random.rps",
    group="helfer",
    priority="K",
    examples=("Schere, Stein, Papier – Stein!",),
    patterns=(r"\bschere\b.*\b(?:stein|papier)\b", r"\bstein\b.*\bpapier\b"),
)
async def random_rps(req: Request) -> SkillResult:
    beats = {"schere": "papier", "papier": "stein", "stein": "schere"}  # key beats value
    verbs = {"schere": "schneidet", "papier": "wickelt", "stein": "schleift"}
    mine = req.ctx.rng.choice(tuple(beats))
    yours = next((w for w in beats if re.search(rf"\b{w}\b[!.]*$", req.text)), None)
    if yours is None:
        return say(f"Ich nehme {mine.capitalize()}. Und du?")
    if yours == mine:
        return say(f"Ich nehme auch {mine.capitalize()} – unentschieden.")
    winner, loser, outcome = (
        (mine, yours, "ich gewinne") if beats[mine] == yours else (yours, mine, "du gewinnst")
    )
    tail = " ein" if winner == "papier" else ""
    return say(
        f"Ich nehme {mine.capitalize()} – {winner.capitalize()} {verbs[winner]} {loser.capitalize()}{tail}, {outcome}."
    )


# ---------------------------------------------------------------------------------------------
@skill(
    "fun.joke",
    group="fun",
    priority="K",
    help="Witze",
    examples=("Erzähl einen Witz",),
    patterns=(
        r"\bwitz\b",
        r"\bwas lustiges\b",
        r"\bbring mich zum lachen\b",
        r"\bheitere mich auf\b",
    ),
)
async def fun_joke(req: Request) -> SkillResult | None:
    if not req.svc.cfg.fun.enabled:
        return None
    jokes = load_toml("sprueche.de.toml")["witze"]
    fresh = [j for j in jokes if j not in req.ctx.used] or jokes
    joke = req.ctx.rng.choice(fresh)
    req.ctx.used.add(joke)
    return say(joke)


@skill(
    "fun.hessian",
    group="fun",
    priority="K",
    examples=("Sag was auf Hessisch", "Was heißt Guude?"),
    patterns=(
        r"\bauf hessisch\b",
        r"\bwas (?:heißt|bedeutet|ist) (?:guude|ebbelwoi|äppler|schobbe|babbeln|gebabbel|handkäs|grie soß|dribbdebach|ei gude wie)\b",
        r"\bhessisch(?:e)? wörter\b",
    ),
)
async def fun_hessian(req: Request) -> SkillResult | None:
    if not req.svc.cfg.fun.enabled:
        return None
    data = load_toml("sprueche.de.toml")["hessisch"]
    for term, text in data["begriffe"].items():
        if re.search(rf"(?<![\wäöüß]){re.escape(term)}(?![\wäöüß])", req.text):
            return say(text)
    return say(req.ctx.rng.choice(data["sprueche"]))


@skill(
    "count.down",
    group="helfer",
    priority="K",
    examples=("Zähl von 10 runter",),
    patterns=(r"\bzähl\w* (?:von \d+ )?(?:runter|rückwärts|bis \d+)\b", r"\bzähl\w* bis \d+\b"),
)
async def count_down(req: Request) -> SkillResult | None:
    m = re.search(r"\bvon (\d+)\b", req.text)
    if m:
        start = min(int(m.group(1)), 20)
        return say(", ".join(str(n) for n in range(start, -1, -1)) + ".")
    m = re.search(r"\bbis (\d+)\b", req.text)
    if m:
        end = min(int(m.group(1)), 20)
        return say(", ".join(str(n) for n in range(1, end + 1)) + ".")
    return None


# ---------------------------------------------------------------------------------------------
def _duration_seconds(text: str) -> float | None:
    total, found = 0.0, False
    for amount, unit in re.findall(
        r"(\d+(?:[.,]\d+)?|eine halbe|eine viertel|anderthalb|eine|einer|ein) ?(sekunden?|minuten?|stunden?|stunde)\b",
        text,
    ):
        value = {
            "eine halbe": 0.5,
            "eine viertel": 0.25,
            "anderthalb": 1.5,
            "eine": 1,
            "einer": 1,
            "ein": 1,
        }.get(amount)
        value = float(amount.replace(",", ".")) if value is None else value
        total += value * (1 if unit.startswith("sek") else 60 if unit.startswith("min") else 3600)
        found = True
    if re.search(r"\bviertelstunde\b", text):
        total, found = total + 900, True
    if re.search(r"\bdreiviertelstunde\b", text):
        total, found = total + 2700, True
    if re.search(r"\bhalbe stunde\b", text) and not found:
        total, found = 1800, True
    return total if found and total > 0 else None


@skill(
    "timer.start",
    group="helfer",
    priority="S",
    help="Timer und Eieruhr",
    examples=("Stell einen Timer auf 3 Minuten", "Eieruhr 7 Minuten"),
    patterns=(r"\btimer\b", r"\beieruhr\b", r"\bwecker (?:in|auf|für)\b", r"\bstoppuhr\b"),
)
async def timer_start(req: Request) -> SkillResult | None:
    if not req.svc.cfg.timer.enabled:
        return None
    seconds = _duration_seconds(req.text)
    if seconds is None:
        return say("Auf wie viele Minuten soll ich den Timer stellen?")
    limit = req.svc.cfg.timer.max_minutes * 60
    if req.surface == "spoken" and seconds > limit:
        return say(
            f"So lange kann ich am Telefon nicht mitzählen – höchstens {req.svc.cfg.timer.max_minutes} Minuten."
        )
    label = g.duration(timedelta(seconds=seconds), seconds=seconds < 120)
    tail = " Ich melde mich, solange wir telefonieren." if req.surface == "spoken" else ""
    return say(f"Okay, {label} ab jetzt.{tail}", start_timer=(seconds, label))


@skill(
    "timer.left",
    group="helfer",
    priority="S",
    examples=("Wie lange noch?",),
    patterns=(r"\bwie lange noch\b", r"\bnoch wie lange\b", r"\bwie viel zeit (?:ist )?noch\b"),
    exclude=(r"\bbis\b",),
)
async def timer_left(req: Request) -> SkillResult | None:
    now = req.svc.clock.monotonic()
    pending = [(d - now, label) for d, label in req.ctx.timers if d > now]
    if not pending:
        return None
    left, _ = min(pending)
    return say(f"Noch {g.duration(timedelta(seconds=left), seconds=left < 120)}.")

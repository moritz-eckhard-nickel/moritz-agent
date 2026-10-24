# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Talking to Anton: greeting, thanks, help, repeat, speed, goodbye, status (docs/plan/13 §6.15)."""

from __future__ import annotations

import re
from datetime import timedelta

from moritz_agent.skills.base import Request, SkillResult
from moritz_agent.skills.calendar import holidays as hol
from moritz_agent.skills.calendar import school
from moritz_agent.skills.catalog.common import briefing_part, briefing_parts, say
from moritz_agent.skills.registry import groups, skill
from moritz_agent.skills.render import german as g

_RANK = {"M": 0, "S": 1, "K": 2}
_HELP_GROUPS = (
    ("zeit", "die Uhrzeit sagen"),
    ("wetter", "das Wetter vorhersagen"),
    ("kalender", "Datum, Feiertage und Ferien nennen"),
    ("warnungen", "vor Unwettern warnen"),
    ("rechnen", "rechnen und umrechnen"),
    ("himmel", "Sonne und Mond erklären"),
    ("helfer", "Wörter buchstabieren oder würfeln"),
    ("region", "den Lahn-Pegel und die Müllabfuhr nennen"),
    ("geld", "Wechselkurse und Preise nennen"),
    ("fun", "Witze erzählen"),
)
_GOODBYE_WORDS = (
    r"tschüss|tschüs|tschau|ciao|auf wiederhören|auf wiedersehen|wiederhören|bis bald|bis später|"
    r"mach's gut|mach es gut|das war's|das war es|das wars|ich lege (?:jetzt )?auf|bis dann|bis zum nächsten mal"
)
# "Leg auf" only when the whole sentence asks Anton to hang up (Moritz, 21.10.2026: "dass man das
# wirklich meint") – not "wie leg ich den Hörer auf", "leg nicht auf" or "soll ich auflegen".
_NOW = r"(?:(?:jetzt|ruhig|einfach|gleich|dann|schon|bitte|mal|doch) )*"
# Phone things answered in a text chat (Moritz, 21.10.2026: "Sachen, die telefonspezifisch sind,
# sollen nur am Telefon gehen").
ONLY_SPOKEN = "{what} geht nur, wenn wir telefonieren oder im Sprachkanal reden."
_HANG_UP = re.compile(
    r"^(?:(?:okay|ok|gut|so|alles klar|danke|jo|ja|na dann|dann|anton)[ ,]+)*"
    rf"(?:(?:du kannst|kannst du|du darfst|würdest du|könntest du) )?{_NOW}"
    rf"(?:auflegen|leg(?:e)? {_NOW}auf|häng(?:e)? {_NOW}auf)"
    r"(?:[ ,]+(?:jetzt|danke|tschüss|tschüs|anton|bis dann|bis bald))*$"
)


@skill(
    "talk.goodbye",
    group="gespraech",
    priority="M",
    help="Verabschiedung",
    examples=("Tschüss", "Danke, das war's", "Gute Nacht"),
    max_words=7,
    patterns=(
        rf"\b(?:{_GOODBYE_WORDS})\b",
        _HANG_UP.pattern,
        r"\bgute nacht\b",
        r"\bdanke,? (?:das war alles|das reicht|mehr brauche ich nicht)\b",
    ),
)
async def talk_goodbye(req: Request) -> SkillResult:
    if re.search(r"\bgute nacht\b", req.text):
        return say("Gute Nacht, Moritz! Schlaf gut.", hangup=True)
    if _HANG_UP.match(req.text):  # "Leg auf": politely, then the line goes dead
        if (
            req.surface == "chat"
        ):  # only in a call (Moritz, 21.10.2026: "das sollte nur im Call gehen")
            return say(ONLY_SPOKEN.format(what="Auflegen"))
        return say("Alles klar, ich lege auf. Tschüss, Moritz – bis bald!", hangup=True)
    return SkillResult(prompt="goodbye", hangup=True)


@skill(
    "talk.greeting",
    group="gespraech",
    priority="M",
    help="Begrüßung",
    examples=("Guude!", "Hallo", "Moin"),
    max_words=4,
    patterns=(
        r"^(?:ei )?(?:guude|gude|hallo|hi|hey|moin|moin moin|servus|grüß dich|grüß gott|hallöchen|huhu|na)(?: anton)?$",
        r"^guten (?:tag|abend)$",
        r"^guten tag anton$",
        r"^anton$",
    ),
)
async def talk_greeting(req: Request) -> SkillResult:
    hour = req.now.hour
    if "abend" in req.text:
        hello = "Guten Abend!"
    elif hour >= 18:
        hello = req.pick(("Guten Abend!", "Guude!"))
    else:
        hello = req.pick(("Guude!", "Hallo!", "Guude, Moritz!"))
    return say(f"{hello} Was kann ich für dich tun?")


@skill(
    "talk.thanks",
    group="gespraech",
    priority="M",
    help="Danke",
    examples=("Danke", "Vielen Dank", "Super, danke"),
    max_words=6,
    patterns=(r"\b(?:danke|dankeschön|vielen dank|merci|danke dir|besten dank|danke schön)\b",),
    exclude=(rf"\b(?:{_GOODBYE_WORDS})\b",),
)
async def talk_thanks(req: Request) -> SkillResult:
    return say(req.pick(("Gerne!", "Gern geschehen!", "Immer gern!", "Kein Problem!")))


@skill(
    "talk.how_are_you",
    group="gespraech",
    priority="M",
    help="wie es mir geht",
    examples=("Wie geht's dir?", "Alles klar bei dir?"),
    max_words=7,
    patterns=(
        r"\bwie geht es dir\b",
        r"\bwie geht es\b$",
        r"\bwie läuft(?:'s| es)?\b$",
        r"\balles klar bei dir\b",
        r"\bwie gehts\b",
        r"\bwie ist die lage\b",
    ),
)
async def talk_how_are_you(req: Request) -> SkillResult:
    status = req.svc.status_fn() if req.svc.status_fn else {}
    problems = [name for name, value in status.items() if value in {"failed", "degraded"}]
    if problems:
        return say(f"Mir geht’s ganz gut, aber {g.join_and(problems)} macht gerade Probleme.")
    return say(
        req.pick(
            (
                "Mir geht’s gut, danke! Alle Systeme laufen.",
                "Bestens, danke der Nachfrage! Alles läuft.",
            )
        )
    )


@skill(
    "talk.identity",
    group="gespraech",
    priority="M",
    help="wer ich bin",
    examples=("Wer bist du?", "Wie heißt du?", "Bist du ein Mensch?"),
    max_words=8,
    patterns=(
        r"\bwer bist du\b",
        r"\bwie heißt du\b",
        r"\bwie ist dein name\b",
        r"\bstell dich vor\b",
        r"\bbist du (?:ein |eine )?(?:mensch|roboter|computer|ki|programm|echt)\b",
        r"\bbist du (?:der |die )?anton\b",
    ),
)
async def talk_identity(req: Request) -> SkillResult:
    name = req.svc.assistant_name
    if re.search(
        r"\bbist du (?:ein |eine )?(?:mensch|roboter|computer|ki|programm|echt)\b", req.text
    ):
        return say(f"Ich bin {name}, ein Computerprogramm – kein Mensch, aber ich gebe mir Mühe.")
    return say(f"Ich bin {name}, Moritz’ Telefonassistent – ein Computerprogramm, kein Mensch.")


@skill(
    "talk.help",
    group="gespraech",
    priority="M",
    help="Hilfe",
    examples=("Was kannst du?", "Hilfe", "Was kann ich dich fragen?"),
    max_words=8,
    patterns=(
        r"\bwas kannst du\b",
        r"^hilfe$",
        r"\bwobei kannst du (?:mir )?helfen\b",
        r"\bwas machst du\b",
        r"\bwas kann ich dich fragen\b",
        r"\bwas kann man (?:dich|bei dir) (?:fragen|machen)\b",
    ),
)
async def talk_help(req: Request) -> SkillResult:
    cfg = req.svc.cfg
    offered: list[tuple[str, str]] = []  # (what I can do, an example question)
    present = groups()
    for group, phrase in _HELP_GROUPS:
        items = [
            s
            for s in present.get(group, [])
            if s.id not in cfg.disabled and group not in cfg.disabled
        ]
        if not items or (not cfg.online and all(s.online for s in items)):
            continue
        examples = [
            s.examples[0]
            for s in sorted(items, key=lambda s: (_RANK.get(s.priority, 1), s.id))
            if s.examples
        ]
        offered.append((phrase, examples[0] if examples else ""))
    if not offered:
        return say("Ich kann dir die Uhrzeit sagen.")
    first, rest = offered[:3], offered[3:]
    example = next((e for _, e in offered if e), "Wie viel Uhr ist es?")
    wetter = next((e for p, e in offered if "Wetter" in p and e), None)
    text = f"Ich kann dir {g.join_and([p for p, _ in first])}. Frag mich zum Beispiel: {wetter or example}"
    detail = None
    if rest:
        detail = "Außerdem kann ich dir " + g.join_and([p for p, _ in rest]) + "."
    return say(text, detail=detail)


@skill(
    "talk.repeat",
    group="gespraech",
    priority="M",
    help="das Letzte wiederholen",
    examples=("Was hast du gesagt?", "Nochmal bitte", "Kannst du das wiederholen?"),
    max_words=7,
    patterns=(
        r"\bwas hast du gesagt\b",
        r"\bwiederhol\w*\b",
        r"\bnochmal\b",
        r"\bnoch einmal\b",
        r"\bwie bitte\b",
        r"\bwas war das\b",
        r"\bhab ich nicht verstanden\b",
        r"^(?:wie|was|hä)$",
    ),
    exclude=(r"\d",),
)
async def talk_repeat(req: Request) -> SkillResult:
    if not req.ctx.last_text:
        return say("Ich habe noch nichts gesagt, das ich wiederholen könnte.")
    return say(req.ctx.last_text)


@skill(
    "talk.details",
    group="gespraech",
    priority="M",
    examples=("Mehr Details", "Genauer", "Was noch?"),
    max_words=5,
    patterns=(
        r"\bmehr details\b",
        r"^genauer$",
        r"\bnoch genauer\b",
        r"^was noch$",
        r"^mehr$",
        r"\bmehr dazu\b",
        r"\bdetails\b",
    ),
)
async def talk_details(req: Request) -> SkillResult | None:
    if not req.ctx.last_detail:
        return None
    detail, req.ctx.last_detail = req.ctx.last_detail, None
    return say(detail)


@skill(
    "talk.source",
    group="gespraech",
    priority="M",
    examples=("Woher weißt du das?", "Welcher Wetterdienst?"),
    max_words=7,
    patterns=(
        r"\bwoher (?:weißt|hast) du das\b",
        r"\bwoher das\b",
        r"\bwelcher wetterdienst\b",
        r"\bwas ist deine quelle\b",
        r"\bquelle\b",
    ),
)
async def talk_source(req: Request) -> SkillResult | None:
    sources = req.ctx.last_sources
    if not sources:
        return (
            say("Das habe ich aus meiner eigenen Uhr und meinen Kalenderdaten.")
            if req.ctx.last_text
            else None
        )
    names = g.join_and(sorted({s.name for s in sources}))
    return say(f"Das kommt von {names}.")


@skill(
    "talk.discord",
    group="gespraech",
    priority="S",
    help="das Letzte auf Discord schicken",
    examples=("Schick mir das auf Discord", "Schreib mir das auf Discord"),
    max_words=9,
    patterns=(
        r"\b(?:schick|schreib|send)\w* (?:mir |uns )?(?:das |es |die antwort )?(?:bitte )?(?:auch )?"
        r"(?:auf|an|per|über) (?:mein |meinen )?discord\b",
        r"\bauf discord (?:schicken|schreiben|senden)\b",
        r"\b(?:schick|schreib)\w* (?:mir )?(?:das |es )?(?:bitte )?aufs handy\b",
    ),
)
async def talk_discord(req: Request) -> SkillResult:
    """On the phone: the last answer goes to the caller's Discord as a direct message (docs/plan/14 §12)."""
    if req.surface == "chat":
        return say("Du bist doch schon auf Discord – hier steht es ja.")
    if not req.svc.settings.discord.enabled:
        return say("Discord ist bei mir nicht eingerichtet.")
    if not req.ctx.last_text:
        return say("Ich habe noch nichts gesagt, das ich dir schicken könnte.")
    return SkillResult(
        text="Okay, ich habe es dir auf Discord geschickt.",
        forward=("Von Anton (Telefon)", req.ctx.last_text),
    )


@skill(
    "talk.slower",
    group="gespraech",
    priority="S",
    help="langsamer oder schneller sprechen",
    examples=("Sprich langsamer", "Etwas schneller bitte"),
    max_words=6,
    patterns=(
        r"\b(?:sprich|sprechen|red|rede)\w* (?:bitte )?(?:etwas |ein bisschen |bisschen )?(?:langsamer|schneller)\b",
        r"\b(?:etwas |bisschen )?(?:langsamer|schneller)(?: bitte)?\b",
    ),
)
async def talk_tempo(req: Request) -> SkillResult:
    slower = "langsamer" in req.text
    if req.surface == "chat":
        return say(
            ONLY_SPOKEN.format(what="Langsamer sprechen" if slower else "Schneller sprechen")
        )
    tempo = max(0.7, min(1.4, req.ctx.tempo * (0.85 if slower else 1.15)))
    if tempo == req.ctx.tempo:
        return say("Langsamer geht es nicht mehr." if slower else "Schneller geht es nicht mehr.")
    return say(
        "Okay, ich sage es etwas langsamer." if slower else "Okay, ich sage es etwas schneller.",
        tempo=tempo,
    )


@skill(
    "talk.louder",
    group="gespraech",
    priority="K",
    examples=("Lauter bitte", "Leiser"),
    max_words=5,
    patterns=(
        r"\b(?:lauter|leiser)(?: bitte)?\b",
        r"\b(?:sprich|sprechen) (?:bitte )?(?:lauter|leiser)\b",
    ),
)
async def talk_loudness(req: Request) -> SkillResult:
    louder = "lauter" in req.text
    if req.surface == "chat":
        return say(ONLY_SPOKEN.format(what="Lauter" if louder else "Leiser"))
    db = max(-8.0, min(8.0, req.ctx.loudness_db + (3.0 if louder else -3.0)))
    if db == req.ctx.loudness_db:
        return say("Lauter geht es nicht mehr." if louder else "Leiser geht es nicht mehr.")
    return say("Ist das besser?", loudness_db=db)


@skill(
    "talk.call_duration",
    group="gespraech",
    priority="S",
    examples=("Wie lange telefonieren wir schon?",),
    patterns=(
        r"\bwie lange (?:telefonieren|reden|sprechen|quatschen) wir (?:schon|jetzt)\b",
        r"\bwie lange dauert (?:das|unser) (?:gespräch|telefonat)\b",
    ),
)
async def talk_call_duration(req: Request) -> SkillResult:
    if req.surface == "chat":
        return say("Wir telefonieren doch gerade gar nicht ^^")
    seconds = max(0.0, req.svc.clock.monotonic() - req.ctx.started)
    return say(f"Seit {g.duration(timedelta(seconds=seconds), seconds=seconds < 600)}.")


@skill(
    "talk.last_question",
    group="gespraech",
    priority="K",
    examples=("Was habe ich dich gerade gefragt?",),
    patterns=(
        r"\bwas habe? ich (?:dich )?(?:gerade|eben|zuletzt) gefragt\b",
        r"\bwas war meine letzte frage\b",
    ),
)
async def talk_last_question(req: Request) -> SkillResult | None:
    previous = req.ctx.heard[:-1]
    if not previous:
        return say("Du hast mich noch nichts gefragt.")
    return say(f"Du hast gesagt: {previous[-1].strip().rstrip('?.!')}.")


@skill(
    "talk.hear_me",
    group="gespraech",
    priority="S",
    examples=("Hörst du mich?", "Bist du noch da?"),
    max_words=6,
    patterns=(
        r"\bhörst du mich\b",
        r"\bbist du (?:noch )?da\b",
        r"\bkannst du mich hören\b",
        r"\bhallo\? ?hörst\b",
        r"\bkannst du mich (?:verstehen|verstehen)\b",
    ),
)
async def talk_hear_me(req: Request) -> SkillResult:
    return say("Ja, ich höre dich gut.")


@skill(
    "talk.privacy",
    group="gespraech",
    priority="M",
    help="Datenschutz",
    examples=("Speicherst du das?", "Nimmst du das auf?"),
    max_words=8,
    patterns=(
        r"\bspeicherst du (?:das|alles|mich)\b",
        r"\bnimmst du (?:das|mich|alles) auf\b",
        r"\bwird das (?:aufgezeichnet|gespeichert|aufgenommen)\b",
        r"\bspeicherst du\b",
        r"\bhörst du (?:mir )?(?:immer |ständig |dauernd )?zu\b",
        r"\bdatenschutz\b",
    ),
)
async def talk_privacy(req: Request) -> SkillResult:
    storage = req.svc.settings.storage
    if storage.store_transcripts:
        return say(
            f"Ich nehme kein Audio auf. Den erkannten Text speichere ich {g.plural(storage.transcript_retention_hours, 'Stunde', 'Stunden')}, dann wird er gelöscht."
        )
    return say("Ich nehme kein Audio auf und speichere auch keinen Text.")


@skill(
    "talk.version",
    group="gespraech",
    priority="S",
    examples=("Welche Version hast du?", "Wie lange läufst du schon?"),
    patterns=(
        r"\bwelche version\b",
        r"\bversionsnummer\b",
        r"\bwie lange läufst du schon\b",
        r"\bwie alt bist du\b",
    ),
)
async def talk_version(req: Request) -> SkillResult:
    uptime = timedelta(seconds=max(0.0, req.svc.clock.monotonic() - req.svc.started_at))
    version = req.svc.version or "unbekannt"
    if uptime < timedelta(minutes=1):
        return say(f"Ich bin moritz-agent, Version {version}, und gerade erst gestartet.")
    return say(f"Ich bin moritz-agent, Version {version}, und laufe seit {g.duration(uptime)}.")


@skill(
    "talk.status",
    group="gespraech",
    priority="S",
    examples=("Läuft alles?", "Systemstatus?"),
    patterns=(
        r"\bläuft alles\b",
        r"\bsystemstatus\b",
        r"\bfunktioniert alles\b",
        r"\bfunktionierst du (?:richtig|noch|gut)\b",
        r"\balles in ordnung bei dir\b",
        r"\bwie ist dein status\b",
    ),
)
async def talk_status(req: Request) -> SkillResult:
    status = req.svc.status_fn() if req.svc.status_fn else {}
    if not status:
        return say("Ich bin bereit und höre dir zu.")
    bad = {k: v for k, v in status.items() if v not in {"ready", "bereit", "ok", True}}
    if not bad:
        return say("Ja, alles läuft: Telefon, Spracherkennung und Stimme sind bereit.")
    return say(
        "Fast alles läuft. Probleme gibt es bei " + g.join_and(sorted(bad)) + ".", serious=True
    )


@skill(
    "talk.cancel",
    group="gespraech",
    priority="S",
    examples=("Vergiss es", "Abbrechen"),
    max_words=5,
    patterns=(r"\bvergiss es\b", r"^abbrechen$", r"^egal$", r"\blass gut sein\b", r"\bschon gut\b"),
)
async def talk_cancel(req: Request) -> SkillResult:
    return say("Alles klar.")


@skill(
    "talk.compliment",
    group="gespraech",
    priority="K",
    examples=("Du bist toll",),
    max_words=6,
    patterns=(
        r"\bdu bist (?:toll|super|klasse|großartig|cool|gut|prima|der beste)\b",
        r"\bgut gemacht\b",
    ),
)
async def talk_compliment(req: Request) -> SkillResult:
    return say("Danke, das freut mich!")


@skill(
    "talk.insult",
    group="gespraech",
    priority="K",
    examples=("Du bist doof",),
    max_words=6,
    patterns=(
        r"\bdu bist (?:doof|dumm|blöd|schlecht|nutzlos|scheiße|ein idiot)\b",
        r"^du nervst$",
    ),
)
async def talk_insult(req: Request) -> SkillResult:
    return say("Okay. Kann ich dir sonst irgendwie helfen?")


# -- morning overview -----------------------------------------------------------------------
@briefing_part(10)
async def _briefing_date(req: Request) -> str | None:
    return f"Heute ist {g.date_long(req.now.date())}."


@briefing_part(20)
async def _briefing_calendar(req: Request) -> str | None:
    today = req.now.date()
    state = req.svc.cfg.home.state
    parts = []
    holiday = hol.holiday_on(today, state)
    if holiday:
        parts.append(f"Heute ist {holiday.name} – ein Feiertag.")
    elif (nxt := hol.holiday_on(today + timedelta(days=1), state)) is not None:
        parts.append(f"Morgen ist {nxt.name}.")
    vacation = school.current(today)
    if vacation:
        parts.append(f"Gerade sind {vacation.name} in Hessen.")
    return " ".join(parts) or None


@skill(
    "briefing",
    group="gespraech",
    priority="S",
    help="den Tagesüberblick",
    examples=("Guten Morgen", "Was steht heute an?", "Gib mir einen Überblick"),
    max_words=7,
    patterns=(
        r"^guten morgen(?: anton)?$",
        r"\bwas steht (?:heute )?an\b",
        r"\b(?:gib|gibt|mach) (?:mir )?(?:bitte )?(?:einen |den )?(?:überblick|tagesüberblick)\b",
        r"\btagesüberblick\b",
        r"\bmorgenbriefing\b",
        r"\bwas gibt(?:'s| es) heute\b",
    ),
    exclude=(r"\b(?:fernsehen|fernseher|tv|kino|essen|mittag\w*|abendessen|nachrichten)\b",),
)
async def briefing(req: Request) -> SkillResult:
    sentences: list[str] = []
    for part in briefing_parts():
        try:
            piece = await part(req)
        except Exception:
            continue
        if piece:
            sentences.append(piece)
    lead = (
        "Guten Morgen!"
        if "morgen" in req.text and "guten" in req.text
        else "Hier ist dein Überblick."
    )
    body = " ".join(sentences)
    return say(f"{lead} {body}".strip(), detail=None)

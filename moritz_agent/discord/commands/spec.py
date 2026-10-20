# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The slash commands as data (docs/plan/14 §7): name, options, who may use them, what they ask.

A command that asks the core ("say") turns its options into a plain German sentence, so the same
router answers it as on the phone and in the text chat. Commands whose function is not active are not
registered (``Features``). Nothing here knows discord.py, so the table is tested on its own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from moritz_agent.config.settings import Settings
from moritz_agent.discord.access import CommandRule

Values = Mapping[str, Any]


@dataclass(frozen=True)
class Opt:
    name: str
    description: str
    kind: str = "str"  # str | int
    required: bool = False
    choices: tuple[tuple[str, str], ...] = ()  # (label, value)
    autocomplete: str = ""  # "place"
    low: int | None = None
    high: int | None = None


@dataclass(frozen=True)
class Spec:
    name: str
    description: str
    options: tuple[Opt, ...] = ()
    rule: CommandRule = field(default_factory=CommandRule)
    say: Callable[[Values], str] | None = None  # None: handled by the worker itself
    feature: str = ""  # the feature this needs; "" = always
    ephemeral: bool = False  # the answer is only for the caller
    group: str = ""  # subcommand group name (for /admin …)
    subcommands: tuple[Spec, ...] = field(default=())

    @property
    def local(self) -> bool:
        return self.say is None


# -- helpers for the sentences ----------------------------------------------------------------------------
def _v(values: Values, key: str, default: str = "") -> str:
    value = values.get(key)
    return str(value).strip() if value not in (None, "") else default


def _in(values: Values, key: str = "ort") -> str:
    place = _v(values, key)
    return f" in {place}" if place else ""


def _when(values: Values, key: str = "wann", default: str = "heute") -> str:
    return _v(values, key, default)


def _weather(values: Values) -> str:
    when, where = _when(values), _in(values)
    detail = _v(values, "detail")
    if detail == "regen":
        return f"Regnet es {when}{where}"
    if detail == "wind":
        return f"Wie windig ist es {when}{where}"
    if detail == "temperatur":
        return f"Wie warm wird es {when}{where}"
    if detail == "frost":
        return f"Gibt es {when}{where} Frost"
    return f"Wie wird das Wetter {when}{where}"


def _sun(values: Values) -> str:
    when, where = _when(values, "datum"), _in(values)
    return f"Wann ist Sonnenuntergang {when}{where}"


def _moon(values: Values) -> str:
    when = _when(values, "datum")
    return f"Wie ist die Mondphase {when}"


def _date(values: Values) -> str:
    expression = _v(values, "ausdruck", "heute")
    if expression[:1].isdigit() and "." in expression:
        return f"Welcher Wochentag ist der {expression}"
    return f"Welcher Tag ist {expression}"


def _holidays(values: Values) -> str:
    year, state = _v(values, "jahr"), _v(values, "bundesland")
    if year:
        return f"Welche Feiertage gibt es {year}" + (f" in {state}" if state else "")
    return "Wann ist der nächste Feiertag" + (f" in {state}" if state else "")


def _holidays_school(values: Values) -> str:
    state = _v(values, "bundesland")
    return "Wann sind die nächsten Schulferien" + (f" in {state}" if state else "")


def _fx(values: Values) -> str:
    amount, currency = _v(values, "betrag", "1"), _v(values, "waehrung", "Dollar")
    return f"Wie viel sind {amount} {currency} in Euro"


def _fuel(values: Values) -> str:
    kind = _v(values, "sorte")
    return "Wo ist der Sprit am günstigsten" + (f" für {kind}" if kind else "")


def _dice(values: Values) -> str:
    count, sides = _v(values, "anzahl", "1"), _v(values, "seiten", "6")
    if count == "1" and sides == "6":
        return "Würfle mit einem Würfel"
    return f"Würfle mit {count} Würfeln mit {sides} Seiten"


def _notes(values: Values) -> str:
    action, text = _v(values, "aktion", "zeigen"), _v(values, "text")
    if action == "hinzu" and text:
        return f"Notiere {text}"
    if action == "loeschen":
        return "Lösche meine Notizen"
    return "Was steht in meinen Notizen"


def _shopping(values: Values) -> str:
    action, text = _v(values, "aktion", "zeigen"), _v(values, "text")
    if action == "hinzu" and text:
        return f"Setze {text} auf die Einkaufsliste"
    if action == "loeschen":
        return "Lösche die Einkaufsliste"
    return "Was steht auf der Einkaufsliste"


WHEN = Opt(
    "wann",
    "Wann? (heute, morgen, am Wochenende …)",
    choices=(
        ("heute", "heute"),
        ("morgen", "morgen"),
        ("übermorgen", "übermorgen"),
        ("am Wochenende", "am Wochenende"),
    ),
)
PLACE = Opt("ort", "Ort oder Postleitzahl (leer = zu Hause)", autocomplete="place")
EVERYONE = CommandRule("OVG", "S DM U")
TRUSTED = CommandRule("OV", "S DM U")
OWNER_DM = CommandRule("O", "DM")
PRIVATE = CommandRule("OV", "DM U")
STATE = Opt("bundesland", "Bundesland (leer = Hessen)")

SPECS: tuple[Spec, ...] = (
    Spec(
        "frag",
        "Frag Nikita etwas",
        (Opt("text", "Deine Frage", required=True),),
        TRUSTED,
        lambda v: _v(v, "text"),
    ),
    Spec(
        "wetter",
        "Wie wird das Wetter?",
        (
            PLACE,
            WHEN,
            Opt(
                "detail",
                "Nur ein Detail",
                choices=(
                    ("Regen", "regen"),
                    ("Wind", "wind"),
                    ("Temperatur", "temperatur"),
                    ("Frost", "frost"),
                ),
            ),
        ),
        EVERYONE,
        _weather,
        "skills",
    ),
    Spec(
        "warnungen",
        "Gibt es Unwetterwarnungen?",
        (PLACE,),
        EVERYONE,
        lambda v: "Gibt es Unwetterwarnungen" + _in(v),
        "skills",
    ),
    Spec(
        "pollen",
        "Wie ist der Pollenflug?",
        (PLACE, WHEN),
        EVERYONE,
        lambda v: f"Wie ist der Pollenflug {_when(v)}{_in(v)}",
        "pollen",
    ),
    Spec(
        "luft",
        "Wie ist die Luftqualität?",
        (PLACE,),
        EVERYONE,
        lambda v: "Wie ist die Luftqualität" + _in(v),
        "skills",
    ),
    Spec(
        "sonne",
        "Wann geht die Sonne auf und unter?",
        (PLACE, Opt("datum", "Tag (heute, morgen, 24.12. …)")),
        EVERYONE,
        _sun,
        "skills",
    ),
    Spec(
        "mond",
        "Wie ist die Mondphase?",
        (Opt("datum", "Tag (heute, morgen, 24.12. …)"),),
        EVERYONE,
        _moon,
        "skills",
    ),
    Spec(
        "zeit",
        "Wie spät ist es?",
        (Opt("ort", "Ort für die Weltzeit (leer = hier)", autocomplete="place"),),
        EVERYONE,
        lambda v: "Wie spät ist es" + _in(v),
    ),
    Spec(
        "datum",
        "Welcher Tag ist wann?",
        (Opt("ausdruck", "zum Beispiel „in 3 Wochen“ oder „24.12.“"),),
        EVERYONE,
        _date,
        "skills",
    ),
    Spec(
        "feiertage",
        "Feiertage",
        (Opt("jahr", "Jahr", "int", low=1900, high=2200), STATE),
        EVERYONE,
        _holidays,
        "skills",
    ),
    Spec("ferien", "Schulferien", (STATE,), EVERYONE, _holidays_school, "skills"),
    Spec(
        "rechne",
        "Rechnen",
        (Opt("ausdruck", "zum Beispiel „17 mal 23“", required=True),),
        EVERYONE,
        lambda v: f"Was ist {_v(v, 'ausdruck')}",
        "skills",
    ),
    Spec(
        "umrechnen",
        "Einheiten umrechnen",
        (Opt("ausdruck", "zum Beispiel „5 Meilen in Kilometer“", required=True),),
        EVERYONE,
        lambda v: f"Was sind {_v(v, 'ausdruck')}",
        "skills",
    ),
    Spec(
        "kurs",
        "Währungskurs",
        (Opt("betrag", "Betrag"), Opt("waehrung", "Währung, zum Beispiel Dollar")),
        TRUSTED,
        _fx,
        "fx",
    ),
    Spec(
        "strompreis",
        "Wie teuer ist der Strom gerade?",
        (),
        TRUSTED,
        lambda v: "Wie hoch ist der Strompreis",
        "power",
    ),
    Spec(
        "sprit",
        "Wo ist der Sprit am günstigsten?",
        (
            Opt(
                "sorte",
                "Sorte",
                choices=(("E5", "E5"), ("E10", "E10"), ("Diesel", "Diesel")),
            ),
        ),
        TRUSTED,
        _fuel,
        "fuel",
    ),
    Spec(
        "pegel",
        "Wie hoch ist die Lahn?",
        (),
        TRUSTED,
        lambda v: "Wie hoch ist der Pegel der Lahn",
        "water",
    ),
    Spec(
        "muell",
        "Welche Tonne kommt als Nächstes?",
        (),
        TRUSTED,
        lambda v: "Welche Tonne kommt als Nächstes",
        "waste",
    ),
    Spec(
        "fussball",
        "Wie hat die Eintracht gespielt?",
        (),
        TRUSTED,
        lambda v: "Wie hat Eintracht Frankfurt gespielt",
        "football",
    ),
    Spec("nachrichten", "Was gibt es Neues?", (), TRUSTED, lambda v: "Was gibt es Neues", "news"),
    Spec(
        "buchstabiere",
        "Ein Wort buchstabieren",
        (Opt("wort", "Das Wort", required=True),),
        EVERYONE,
        lambda v: f"Buchstabiere {_v(v, 'wort')}",
    ),
    Spec(
        "wuerfel",
        "Würfeln",
        (
            Opt("anzahl", "Wie viele Würfel", "int", low=1, high=20),
            Opt("seiten", "Wie viele Seiten", "int", low=2, high=1000),
        ),
        EVERYONE,
        _dice,
    ),
    Spec("muenze", "Münze werfen", (), EVERYONE, lambda v: "Wirf eine Münze"),
    Spec(
        "zufall",
        "Zufallszahl",
        (
            Opt("von", "von", "int", True, low=-1_000_000, high=1_000_000),
            Opt("bis", "bis", "int", True, low=-1_000_000, high=1_000_000),
        ),
        EVERYONE,
        lambda v: f"Zufallszahl zwischen {_v(v, 'von', '1')} und {_v(v, 'bis', '100')}",
    ),
    Spec(
        "timer",
        "Einen Timer stellen",
        (Opt("dauer", "zum Beispiel „10 Minuten“", required=True),),
        TRUSTED,
        lambda v: f"Stelle einen Timer auf {_v(v, 'dauer')}",
        "skills",
    ),
    Spec(
        "erinnere",
        "Erinnere mich an etwas",
        (
            Opt("wann", "Wann? (morgen um 8 Uhr, in 2 Stunden …)", required=True),
            Opt("was", "Woran?", required=True),
        ),
        TRUSTED,
        lambda v: f"Erinnere mich {_v(v, 'wann')} an {_v(v, 'was')}",
        "skills",
    ),
    Spec(
        "notiz",
        "Notizen",
        (
            Opt(
                "aktion",
                "Was tun?",
                choices=(("zeigen", "zeigen"), ("hinzufügen", "hinzu"), ("löschen", "loeschen")),
            ),
            Opt("text", "Text zum Hinzufügen"),
        ),
        CommandRule("O", "DM U"),
        _notes,
        "notes",
        True,
    ),
    Spec(
        "einkauf",
        "Einkaufsliste",
        (
            Opt(
                "aktion",
                "Was tun?",
                choices=(("zeigen", "zeigen"), ("hinzufügen", "hinzu"), ("löschen", "loeschen")),
            ),
            Opt("text", "Was soll auf die Liste?"),
        ),
        CommandRule("O", "DM U"),
        _shopping,
        "notes",
        True,
    ),
    Spec("briefing", "Der Tagesüberblick", (), TRUSTED, lambda v: "Morgenbriefing", "skills"),
    Spec(
        "suche",
        "Im Internet suchen",
        (Opt("text", "Wonach?", required=True),),
        TRUSTED,
        lambda v: f"Suche im Internet nach {_v(v, 'text')}",
        "search",
    ),
    # -- handled by the worker itself ----------------------------------------------------------------
    Spec(
        "abo",
        "Nachrichten, die Nikita dir von sich aus schickt",
        (
            Opt(
                "was",
                "Welches Abo?",
                required=True,
                choices=(
                    ("Unwetterwarnungen", "warnungen"),
                    ("Morgenbriefing", "briefing"),
                    ("Müllabfuhr", "muell"),
                    ("Anrufhinweise", "anrufe"),
                    ("Systemhinweise", "system"),
                ),
            ),
            Opt(
                "einstellung",
                "an / aus / Stufe 1–4 (Warnungen) / Uhrzeit HH:MM (Briefing)",
                required=True,
            ),
        ),
        PRIVATE,
        None,
        ephemeral=True,
    ),
    Spec(
        "einstellungen",
        "Deine persönlichen Einstellungen",
        (
            Opt("heimatort", "Dein Ort oder deine Postleitzahl", autocomplete="place"),
            Opt("ruhezeit", "Ruhezeit HH:MM-HH:MM (leer = Standard, „aus“ = keine)"),
            Opt(
                "sprachantwort",
                "Antworten auf Sprachnachrichten",
                choices=(("spiegeln", "mirror"), ("immer", "always"), ("nie", "never")),
            ),
        ),
        PRIVATE,
        None,
        ephemeral=True,
    ),
    Spec(
        "erinnerungen",
        "Deine offenen Erinnerungen",
        (Opt("loeschen", "Nummer der Erinnerung, die weg soll", "int", low=1, high=1_000_000),),
        PRIVATE,
        None,
        ephemeral=True,
    ),
    Spec(
        "aktivitaet",
        "Was Nikita gerade so treibt",
        (
            Opt(
                "aktion",
                "Was tun?",
                required=True,
                choices=(
                    ("neu", "neu"),
                    ("aus", "aus"),
                    ("an", "an"),
                    ("Vorschlag", "vorschlag"),
                ),
            ),
            Opt("text", "Eigener Spruch (bei „Vorschlag“)"),
            Opt(
                "art",
                "Art (bei „Vorschlag“)",
                choices=(
                    ("Spielt", "playing"),
                    ("Hört", "listening"),
                    ("Schaut", "watching"),
                    ("Tritt an in", "competing"),
                    ("Freier Status", "custom"),
                ),
            ),
        ),
        CommandRule("O", "S DM"),
        None,
        "activities",
        True,
    ),
    Spec(
        "anrufe",
        "Telefon-Status und letzte Anrufe",
        (),
        CommandRule("O", "DM U"),
        None,
        ephemeral=True,
    ),
    Spec(
        "hilfe",
        "Was Nikita kann",
        (
            Opt(
                "thema",
                "Thema",
                choices=(
                    ("Befehle", "befehle"),
                    ("Datenschutz", "datenschutz"),
                    ("Sprache", "sprache"),
                    ("Admin", "admin"),
                ),
            ),
        ),
        EVERYONE,
        None,
        ephemeral=True,
    ),
    Spec(
        "joinvc",
        "Nikita kommt in den Sprachkanal",
        (Opt("kanal", "Sprachkanal (leer = der, in dem du gerade bist)", "channel"),),
        CommandRule("OV", "S"),
        None,
        "voice",
    ),
    Spec("leavevc", "Nikita verlässt den Sprachkanal", (), CommandRule("OV", "S"), None, "voice"),
    Spec(
        "admin",
        "Verwaltung (nur Owner)",
        (),
        OWNER_DM,
        None,
        ephemeral=True,
        subcommands=(
            Spec("status", "Wie geht es dem System?", (), OWNER_DM, None, ephemeral=True),
            Spec("version", "Version", (), OWNER_DM, None, ephemeral=True),
            Spec(
                "logs",
                "Die letzten Logzeilen (redigiert)",
                (
                    Opt("kategorie", "z. B. Phone, System, Discord, Inference, Search"),
                    Opt("zeilen", "Wie viele (höchstens 200)", "int", low=10, high=200),
                ),
                OWNER_DM,
                None,
                ephemeral=True,
            ),
            Spec("neu-laden", "Konfiguration neu laden", (), OWNER_DM, None, ephemeral=True),
            Spec(
                "wartung",
                "Wartungsmodus",
                (
                    Opt(
                        "modus",
                        "an oder aus",
                        required=True,
                        choices=(("an", "an"), ("aus", "aus")),
                    ),
                ),
                OWNER_DM,
                None,
                ephemeral=True,
            ),
            Spec("neustart", "Dienst neu starten", (), OWNER_DM, None, ephemeral=True),
        ),
    ),
)

# context menus (right click on a message → Apps); name → (description for /hilfe, feature)
MENUS: tuple[tuple[str, str, str], ...] = (
    ("Nikita fragen", "Die Nachricht als Frage an Nikita", ""),
    ("Vorlesen", "Nikita liest die Nachricht vor", "speech"),
)


# -- which commands exist right now ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Features:
    """Which functions are active; a command of an inactive one is not registered."""

    on: frozenset[str]

    @classmethod
    def from_settings(
        cls, settings: Settings, *, voice: bool = False, speech: bool = False
    ) -> Features:
        skills, money = settings.skills, settings.skills.money
        flags = {
            "skills": skills.enabled,
            "pollen": skills.enabled and skills.pollen.enabled,
            "fx": skills.enabled and skills.online and money.currency,
            "power": skills.enabled and skills.online and money.electricity,
            "fuel": skills.enabled and skills.online and money.fuel,
            "water": skills.enabled and skills.online and skills.water.enabled,
            "waste": skills.enabled and skills.waste.enabled,
            "football": skills.enabled and skills.online and skills.football.enabled,
            "news": skills.enabled and skills.online and skills.news.enabled,
            "notes": skills.enabled and skills.notes.enabled,
            "search": settings.search.enabled and settings.inference.enabled,
            "activities": settings.discord.activities.enabled,
            "voice": voice and settings.discord.voice.enabled,
            "speech": speech,
        }
        return cls(frozenset(name for name, active in flags.items() if active))

    def has(self, feature: str) -> bool:
        return not feature or feature in self.on


def active_specs(features: Features, specs: tuple[Spec, ...] = SPECS) -> list[Spec]:
    return [spec for spec in specs if features.has(spec.feature)]


def active_menus(features: Features) -> list[tuple[str, str, str]]:
    return [menu for menu in MENUS if features.has(menu[2])]


def find(name: str, group: str = "") -> Spec | None:
    """The spec of ``/name`` or ``/group name``."""
    for spec in SPECS:
        if group and spec.name == group:
            return next((sub for sub in spec.subcommands if sub.name == name), None)
        if not group and spec.name == name:
            return spec
    return None


def sentence(spec: Spec, values: Values) -> str:
    """The German sentence a command asks the core."""
    assert spec.say is not None
    return spec.say(values).strip()


def digest(payloads: list[dict[str, Any]]) -> str:
    """Fingerprint of the registered commands: only a change registers them again."""
    blob = json.dumps(payloads, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:24]

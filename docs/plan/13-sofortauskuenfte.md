# 13 – Sofortauskünfte: Uhrzeit, Datum, Wetter & Co. ohne Sprachmodell

Stand: 18.10.2026 (Umsetzungsstand und Abweichungen: [04 Anhang C](04-part1-umsetzung.md#anhang-c--umsetzungsstand-und-abweichungen-stand-21102026)) · Tickets: [04 Block S](04-part1-umsetzung.md#block-s--sofortauskünfte-vor-dem-sprachmodell)
(P1-19 … P1-30) · Anforderungen: [01 §6a](01-anforderungen.md#6a-sofortauskünfte-skill) (SKILL-01 … SKILL-35) ·
Entscheidungen: ADR-029 … ADR-032 ([03](03-entscheidungen.md)).

> Moritz, 18.10.2026: „Plane nun bitte, bevor wir LLM und richtige Agent-Instanzen machen, dass ich
> Nikita nach Uhrzeit, Datum und simplen Sachen wie dem Wetter in der Region fragen kann. Standard
> ist 35781 Weilburg als Wetter, außer PLZ oder was anderes wird gesagt. Mache dafür den
> detailliertesten Plan ever mit wirklich so vielen Funktionen wie möglich.“

**Ziel:** Nikita beantwortet am Telefon – noch **ohne Sprachmodell** – alles, was sich aus Uhr,
Kalender, Rechnung, mitgelieferten Daten oder einem offenen Datendienst eindeutig bestimmen lässt:
Uhrzeit, Datum, Feiertage, Ferien, **Wetter für Weilburg (35781) oder jeden genannten Ort/jede
genannte PLZ**, Warnungen, Pollen, Sonne und Mond, Rechnen, Umrechnen, Lahn-Pegel, Müllabfuhr und
viele kleine Helfer. Diese „Sofortauskünfte“ (im Code: **Skills**) ersetzen und erweitern die
Fast-Paths aus [12-fast-paths.md](12-fast-paths.md) und werden später unverändert als Werkzeuge
des Sprachmodells weiterverwendet (ADR-029).

Inhalt: [1 Leitlinien](#1-leitlinien) · [2 So klingt das](#2-so-klingt-das-beispielanruf) ·
[3 Architektur](#3-architektur) · [4 Verstehen: Absicht und Angaben](#4-verstehen-absicht-und-angaben) ·
[5 Heimatort Weilburg](#5-heimatort-weilburg-35781) · [6 Katalog](#6-katalog-aller-sofortauskünfte) ·
[7 Wetter im Detail](#7-wetter-im-detail) · [8 Zeit und Kalender im Detail](#8-zeit-und-kalender-im-detail) ·
[9 Sprache: Erkennung und Ausgabe](#9-sprache-erkennung-und-ausgabe) · [10 Konfiguration](#10-konfiguration) ·
[11 Daten im Repository](#11-daten-im-repository) · [12 Datenschutz und Sicherheit](#12-datenschutz-und-sicherheit) ·
[13 Beobachtbarkeit](#13-beobachtbarkeit) · [14 Tests](#14-tests) · [15 Latenzbudget](#15-latenzbudget) ·
[16 Umsetzungswellen](#16-umsetzungswellen) · [17 Abnahme](#17-abnahme-am-telefon) ·
[18 Ideenspeicher](#18-ideenspeicher-später-oder-bewusst-nicht) · [19 Offene Fragen](#19-offene-fragen-an-moritz)

---

## 1. Leitlinien

1. **Deterministisch statt geraten.** Jede Zahl, jedes Datum, jede Wetterangabe stammt aus der
   Systemuhr, einer Rechnung, einer mitgelieferten Datei oder einem Datenabruf – nie aus einem
   Sprachmodell, nie „ungefähr erfunden“ (SKILL-02). Fehlt etwas, sagt Nikita das ehrlich.
2. **Nur bei eindeutiger Erkennung.** Ein Skill antwortet nur, wenn Absicht und Angaben sicher
   erkannt sind. Sonst: kurze Rückfrage (wenn genau eine Angabe fehlt oder mehrdeutig ist) oder
   Weitergabe – heute an den Testmodus („Ich habe verstanden: …“), später an den Agenten (SKILL-01).
3. **Heimatort ist Weilburg.** Jede ortsbezogene Frage ohne Ort meint **35781 Weilburg**. Eine
   gesprochene Postleitzahl oder ein Ortsname ersetzt ihn – für diese Frage und Folgefragen im selben
   Anruf (SKILL-03, SKILL-04, SKILL-07).
4. **Offline zuerst.** Alles, was ohne Internet geht (Zeit, Kalender, Feiertage, Ferien, Sonne,
   Mond, Rechnen, Einheiten, Orte, Buchstabieren), geht ohne Internet. Online-Daten (Wetter,
   Warnungen, Pollen, Pegel, Kurse) kommen aus einem Cache, der für den Heimatort vorab gefüllt
   wird (SKILL-13, SKILL-26).
5. **Kurz und sprechbar.** Telefon-Antworten: höchstens drei kurze Sätze, wichtigste Angabe zuerst,
   keine Abkürzungen, Zahlen gerundet wie ein Mensch sie sagt („um die 12 Grad“), auf Nachfrage mehr
   („Mehr Details“, „Und der Wind?“) (SKILL-22).
6. **Ehrlich über Unsicherheit.** Vorhersagen werden als Vorhersagen formuliert („soll“, „laut
   Vorhersage“), ab Tag 7 als Tendenz; Datenalter über einer Stunde wird genannt; zu weit Entferntes
   wird abgelehnt statt geraten.
7. **Keine Seiteneffekte.** Skills lesen nur. Einzige Ausnahme: lokale Notizen/Einkaufsliste in
   moritz-agent selbst, mit gesprochener Bestätigung (SKILL-24). Nikita schaltet nichts, ruft
   niemanden an (PHONE-10) und schickt nichts weg.
8. **Datensparsam.** An Datendienste gehen nur gerundete Koordinaten, Postleitzahlen/Ortsnamen und
   fachliche Kennungen (Warnzelle, Pegel, Währung) – nie Transkripte, Rufnummern oder Zugangsdaten
   (SKILL-25, ADR-032).
9. **Ein Code für Telefon und Sprachmodell.** Jeder Skill ist zugleich ein Tool mit JSON-Schema
   (P1-07). Das spätere LLM ruft `get_weather` auf statt im Internet nach dem Wetter zu suchen; eine
   LLM-Antwort mit Wetterwerten ohne Tool-Aufruf wird verworfen (**Wetter-Garantie**, SKILL-23,
   analog zur Uhrzeit-Garantie AGENT-06).
10. **Messbar.** Jede Auskunft wird mit Skill, Quelle, Cache-Treffer und Dauer protokolliert;
    nicht erkannte Fragen werden (24 h, nur mit Transkriptspeicherung) gesammelt, damit Moritz’
    eigene Formulierungen nachgetragen werden können (SKILL-28).
11. **Wetter nur Open Source und kostenlos.** Wetter-, Warn-, Pollen- und Luftdaten kommen nur von
    Open-Source-Diensten (Open-Meteo, Bright Sky) und amtlichen offenen Daten (DWD, BBK) – ohne Konto,
    ohne Schlüssel, ohne Kosten; beide Dienste sind bei Bedarf selbst betreibbar (SKILL-35, §7.1).

## 2. So klingt das (Beispielanruf)

```text
Nikita:  Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?
         Übrigens: Für Weilburg gilt bis heute 22 Uhr eine Unwetterwarnung vor Sturmböen.   (nur bei Warnung ≥ Stufe 3)
Moritz:  Wie isses Wedder?
Nikita:  In Weilburg sind es gerade 11 Grad, stark bewölkt, Wind aus Südwest mit Böen bis 70 Kilometer pro Stunde.
Moritz:  Und morsche?
Nikita:  Morgen, Montag, wird es in Weilburg wechselhaft bei 8 bis 13 Grad. Vormittags Schauer, nachmittags trockener.
Moritz:  Brauch isch en Schirm?
Nikita:  Morgen früh ja, bis etwa 11 Uhr sind Schauer wahrscheinlich. Am Nachmittag eher nicht.
Moritz:  Wie wird's am Wochenende in sechs null drei eins eins?
Nikita:  Für 60311, das ist Frankfurt am Main: Samstag sonnig bis 16 Grad, Sonntag Regen bei höchstens 12 Grad.
Moritz:  Und in Limburg?
Nikita:  In Limburg an der Lahn am Wochenende: Samstag sonnig bis 15 Grad, Sonntag Regen bei 11 Grad.
Moritz:  Wann geht morgen die Sonne auf?
Nikita:  Morgen geht in Weilburg die Sonne um 7 Uhr 58 auf und um 18 Uhr 19 unter.
Moritz:  Wie viele Tage noch bis Weihnachten?
Nikita:  Noch 67 Tage bis Heiligabend.
Moritz:  Wann sind die nächsten Ferien?
Nikita:  Die Weihnachtsferien in Hessen beginnen am Montag, 21. Dezember.   (aus der gepflegten Ferientabelle)
Moritz:  Was sind 19 Prozent von 249 Euro?
Nikita:  19 Prozent von 249 Euro sind 47 Euro 31.
Moritz:  Wie hoch steht die Lahn?
Nikita:  Die Lahn am Pegel Leun steht bei 1 Meter 42, leicht steigend, etwas über dem mittleren Wasserstand.
Moritz:  Danke, tschüss.
Nikita:  Gerne! Bis bald.                                                        (legt auf)
```

Werte in diesem Beispiel sind erfunden und dienen nur der Form – die echten Antworten kommen aus
den Quellen in §7; Pegelname und Ferientermine werden im jeweiligen Ticket geprüft.

## 3. Architektur

### 3.1 Einordnung

```text
Telefon ─► VAD ─► Whisper (STT) ─► Transcript(text, avg_logprob)
                                        │
                                        ▼
                         SkillResponder.respond(text, TurnContext)          (ersetzt TestResponder, P1-19)
                                        │
            ┌───────────────────────────┼───────────────────────────────┐
            ▼                           ▼                               ▼
    1. Vorverarbeitung          2. Erkennung                    3. Dialogkontext
    normalize → Dialekt →       Intent-Regeln + Gewichte        Folgefrage? offene Rückfrage?
    Zahlwörter → Ziffern        → Kandidaten mit Score          Ort/Zeit aus letzter Auskunft
            └───────────────────────────┬───────────────────────────────┘
                                        ▼
                              4. Angaben (Slots) auflösen
                       Zeit (WhenParser) · Ort (Gazetteer) · Zahl/Einheit/Währung
                                        │
                     eindeutig? ──nein──► Rückfrage („Welches Frankfurt?“) / Weitergabe
                                        │ ja
                                        ▼
                              5. Skill ausführen (async, Zeitbudget)
                    Offline-Rechnung  oder  Provider ─► Cache ─► HTTP (Allowlist, Timeout)
                                        │
                                        ▼
                              6. Antwort formulieren (Renderer, Vorlagen, Rundung, Variation)
                                        │
                                        ▼
                    Reply(text | prompt, hangup, sources, data)  ─► textnorm ─► Piper ─► Telefon
                                        │
                                        └─► Protokoll: [Skill] id, Quelle, Cache, Dauer (ohne Transkript)
```

Kein Treffer → heute die bekannte Testantwort, ab P1-09 der Agent-Loop (der dieselben Skills als
Tools nutzt). Die Reihenfolge ist fest: **erst Skills, dann LLM** – das LLM sieht nur, was kein
Skill eindeutig beantworten kann.

### 3.2 Module

```text
moritz_agent/skills/
├── __init__.py
├── base.py            Skill-Protokoll, SkillRequest, SkillResult, Fehlerklassen
├── registry.py        alle Skills, Aktivierung per Konfiguration, Hilfe-Text aus aktiven Skills
├── responder.py       SkillResponder (Responder-Protokoll aus phone/responder.py)
├── router.py          Kandidaten finden, bewerten, Konflikte lösen, Schwellwerte
├── context.py         SkillContext je Anruf: letzte Auskunft, offene Rückfrage, Ablauf
├── clock.py           Clock-Protokoll (Systemuhr; in Tests feste Uhr)
├── text/
│   ├── normalize.py   Kleinschreibung, Satzzeichen, Füllwörter („äh“, „mal“, „bitte“)
│   ├── dialect.py     Hessisch/Umgangssprache → Standard (Wörterbuch aus assets/data)
│   ├── numbers.py     Zahlwörter → Ziffern („fünfunddreißig“, „drei fünf sieben acht eins“)
│   └── phonetic.py    Kölner Phonetik für unscharfe Ortsnamen
├── slots/
│   ├── when.py        Zeitausdrücke → Zeitraum (Start, Ende, Auflösung, Tagesteil)
│   ├── where.py       Ort/PLZ → Place (Name, Kreis, Land, lat/lon, Zeitzone) oder Mehrdeutigkeit
│   └── quantity.py    Zahl + Einheit/Währung, Rechenausdrücke
├── geo/
│   ├── gazetteer.py   PLZ- und Ortsverzeichnis DE + Weltstädte (offline, assets/data/geo)
│   ├── geocode.py     Online-Rückfall (Open-Meteo Geocoding) nur für unbekannte Orte
│   └── distance.py    Luftlinie (Haversine), Himmelsrichtung
├── providers/         ein Modul je Datendienst, alle mit Cache, Timeout, Plausibilitätsprüfung
│   ├── http.py        gemeinsamer httpx-Client: Allowlist, Timeouts, User-Agent, Größenlimit, Backoff
│   ├── cache.py       RAM + Datei-Cache (data/cache/skills/), TTL, Stale-Regeln
│   ├── open_meteo.py  Vorhersage, aktuelles Wetter, Luftqualität, Geocoding
│   ├── brightsky.py   DWD-Warnungen, Messwerte, Rückfall-Vorhersage
│   ├── dwd.py         Pollenflug-Gefahrenindex, UV, Biowetter (DWD Open Data)
│   ├── nina.py        Bevölkerungswarnungen (BBK)
│   ├── pegelonline.py Wasserstände (WSV)
│   ├── ecb.py         Euro-Referenzkurse (EZB)
│   ├── energy_charts.py Börsenstrompreis (Fraunhofer ISE)
│   ├── tankerkoenig.py  Spritpreise (MTS-K, Schlüssel nötig)
│   ├── openligadb.py  Fußball
│   ├── news.py        Schlagzeilen (optional)
│   └── ics.py         Abfallkalender (iCal-Datei/-Link)
├── astro/             Sonne, Mond, Jahreszeiten (eigene Rechnung nach NOAA/Meeus, kein `astral`)
├── calendar/          Feiertage DE/Länder, Schulferien HE, Arbeits-/Brückentage, Sonderdaten
├── render/            deutsche Formulierungen: Wetter, Zeiträume, Listen, Rundung, Variation
├── catalog/           die Skills selbst, gruppiert wie §6 (time.py, calendar.py, weather.py, …)
├── tools.py           Skill → Tool-Adapter (JSON-Schema) für P1-07
└── __main__.py        CLI: ask, explain, misses, providers, prefetch, corpus
```

`moritz_agent/agent/fastpath.py` bleibt als dünne Fassade erhalten (`answer()` ruft den Router), bis
alle Aufrufer umgestellt sind; die bestehenden Tests laufen unverändert weiter.

### 3.3 Schnittstellen

```python
class Skill(Protocol):
    id: str                                  # z. B. "weather.forecast"
    group: str                               # "zeit", "kalender", "wetter", … (Hilfe-Text, Statistik)
    online: bool                             # braucht Netz?
    examples: tuple[str, ...]                # für Hilfe, Tests und Tool-Beschreibung

    def match(self, utt: Utterance, ctx: SkillContext) -> Match | None: ...
    async def run(self, req: SkillRequest, ctx: SkillContext) -> SkillResult: ...

@dataclass(frozen=True)
class Match:
    skill_id: str
    score: float                             # 0 … 1, siehe §4.2
    slots: Slots                             # erkannte Angaben (Zeit, Ort, Zahl, …), evtl. unvollständig
    missing: tuple[str, ...] = ()            # z. B. ("place",) → Rückfrage statt Antwort

@dataclass(frozen=True)
class SkillResult:
    text: str | None                         # gesprochener Text (vor textnorm), ≤ 3 Sätze
    prompt: str | None = None                # oder vorgefertigte Ansage
    hangup: bool = False
    data: dict | None = None                 # strukturierte Werte (Tool-Ergebnis fürs LLM, WebUI)
    sources: tuple[Source, ...] = ()         # Datendienst, Abrufzeit, Lizenzhinweis
    followup: FollowupState | None = None    # was eine Folgefrage erben darf
    detail: str | None = None                # Antwort auf „Mehr Details“
    stale_s: int | None = None               # Datenalter, falls aus altem Cache
    markdown: str | None = None              # geschriebene Form für Discord/WebUI (ab P1-31, 14 §4.1)
    card: Card | None = None                 # strukturierte Karte (Titel, Felder, Farbe, Quelle) → Embed
    actions: tuple[Action, ...] = ()         # Folgeaktionen („Morgen“, „Wochenende“) → Knöpfe
```

`SkillResponder.respond()` liefert das bestehende `Reply` (Text, Ansage, Auflegen) – die
Telefonseite bleibt unverändert. `TurnContext` bekommt ein Feld `skills: SkillContext`.

### 3.4 Skills als Tools (für P1-07/P1-09)

`tools.py` erzeugt aus jedem Skill ein Tool im Format von P1-07 (`{ok, data|error, sources?,
speakable?}`). Beispiel:

```json
{
  "name": "get_weather",
  "description": "Wetter für einen Ort und Zeitraum. Ohne Ort: Heimatort Weilburg (35781).",
  "parameters": {
    "type": "object",
    "properties": {
      "place":  {"type": "string", "description": "Ortsname oder fünfstellige Postleitzahl"},
      "when":   {"type": "string", "description": "z. B. jetzt, heute, heute Abend, morgen, Samstag, Wochenende, 2026-10-24, 15 Uhr"},
      "aspect": {"type": "string", "enum": ["overview", "rain", "temperature", "wind", "snow", "frost", "thunder", "uv", "sun", "humidity", "pressure"]}
    }
  }
}
```

Das Tool-Ergebnis enthält `data` (Zahlen) **und** `speakable` (fertiger Satz). Das Phone-Profil des
LLM bekommt die lesenden Skill-Tools frei (PHONE-45 geändert); Systemprompt-Zeile: „Für Wetter,
Warnungen, Pollen, Sonne und Mond rufst du immer das passende Werkzeug auf, nie die Websuche.“
**Wetter-Garantie (Guard):** Enthält eine LLM-Antwort Temperatur-, Regen- oder Windangaben
(`\b-?\d+\s?(°|grad)\b`, „Prozent Regen“, „km/h“) ohne Wetter-Tool-Aufruf im selben Turn, wird sie
verworfen und über das Tool neu beantwortet.

### 3.5 Nebenläufigkeit und Zeitbudget

- Alles läuft im asyncio-Loop des Phone-Workers (bis zum Supervisor, P1-04, danach im Main-Prozess
  hinter `/internal/phone/turn`). Rechenarbeit ist klein (< 10 ms); Gazetteer-Laden einmal beim
  Start (≈ 50–150 ms, Hintergrund-Thread, Status „laden“).
- Jeder Online-Skill hat ein **Budget**: Cache-Antwort sofort; sonst HTTP mit Verbindungsaufbau
  1,5 s, gesamt 3 s; danach Stale-Cache (falls ≤ `max_stale_hours`) mit Altersangabe, sonst ehrliche
  Absage. Die bestehende Zwischenansage („Moment, ich schaue nach.“, PHONE-35, nach 2,5 s) deckt
  langsame Abrufe ab; für Wetter gibt es die passendere Ansage `thinking_weather` („Moment, ich
  schaue nach dem Wetter.“), die der Skill sofort anfordert, wenn kein Cache-Treffer vorliegt.
- Auflegen bricht laufende Abrufe ab (PHONE-28); ein begonnener Abruf darf im Hintergrund zu Ende
  laufen und den Cache füllen (nicht für den Anruf, nur für den nächsten).
- **Vorabruf:** Ein Hintergrund-Task holt für den Heimatort alle `prefetch_interval_minutes`
  (Standard 30) Wetter, alle 10 min Warnungen und morgens Pollen – nur wenn `skills.online = true`.
  So ist „Wie wird das Wetter?“ fast immer ein Cache-Treffer (≤ 50 ms).

### 3.6 Cache

| Daten | Schlüssel | TTL frisch | Stale erlaubt bis | Speicher |
| --- | --- | --- | --- | --- |
| Wetterpaket (aktuell + stündlich + täglich) | Provider, lat/lon (2 Nachkommastellen), Modell | 10 min aktuell / 30 min Vorhersage | 6 h (mit Altersangabe) | RAM + `data/cache/skills/weather/*.json` |
| Warnungen DWD/NINA | Warnzelle bzw. Kreis-ARS | 10 min | 30 min, danach „kann ich gerade nicht prüfen“ | RAM + Datei |
| Pollen DWD | Teilregion | bis zur nächsten Ausgabe (täglich ~11 Uhr) | 24 h | RAM + Datei |
| Luftqualität | lat/lon | 60 min | 6 h | RAM |
| Pegel | Station | 15 min | 2 h | RAM |
| EZB-Kurse | Tag | bis 16:30 des nächsten Arbeitstags | 4 Tage (Wochenende/Feiertag) | Datei |
| Strompreis | Gebotszone, Tag | bis 14 Uhr (Day-Ahead) | 24 h | Datei |
| Geocoding online | Suchtext | 30 Tage | – | Datei |
| Abfallkalender | Quelle | 24 h | 30 Tage | Datei |

Dateien werden atomar geschrieben (tmp + rename, UPD-06), nie mit Personenbezug; `data/cache/` darf
jederzeit gelöscht werden. Der Updater sichert den Cache nicht.

### 3.7 Fehlerverhalten

| Situation | Antwort (Beispiel) |
| --- | --- |
| Netz/Datendienst nicht erreichbar, frischer Cache | normale Antwort |
| nicht erreichbar, Cache 1–6 h alt | „Ich komme gerade nicht an neue Wetterdaten. Stand von vor zwei Stunden: …“ |
| nicht erreichbar, kein brauchbarer Cache | „Ich komme gerade nicht an die Wetterdaten. Versuch es bitte gleich noch einmal.“ (Ansage `skills_offline`) |
| `skills.online = false` | „Wetterabfragen sind bei mir gerade ausgeschaltet.“ |
| Antwort unplausibel (Schema, Wertebereich, z. B. 70 °C) | verwerfen, Rückfallquelle, sonst wie „nicht erreichbar“; Log `[Skill] implausible` |
| Rückfallquelle springt ein | normale Antwort; auf Nachfrage „Woher?“ wird die tatsächliche Quelle genannt |
| Ort unbekannt | „Den Ort ‚Weilborg‘ kenne ich nicht. Meinst du Weilburg?“ |
| Zeitraum außerhalb der Vorhersage | „So weit im Voraus gibt es keine verlässliche Vorhersage – höchstens 16 Tage, und ab etwa einer Woche nur als grobe Tendenz.“ |
| Daten für den Ort nicht verfügbar (z. B. DWD-Warnungen im Ausland) | „Amtliche Warnungen habe ich nur für Deutschland.“ |
| Skill wirft eine Ausnahme | Log mit Stacktrace (ohne Transkript), Antwort „Das kann ich gerade nicht beantworten.“; der Anruf läuft weiter |

## 4. Verstehen: Absicht und Angaben

### 4.1 Vorverarbeitung (Reihenfolge fest)

1. **Normalisieren:** Kleinschreibung, Satzzeichen weg (Ziffern-Punkte in Datumsangaben bleiben:
   „24.12.“), Mehrfach-Leerzeichen, Füllwörter am Rand („äh“, „ähm“, „also“, „mal“, „bitte“, „sag
   mal“, „kannst du mir sagen“, „weißt du“, „hey Nikita“).
2. **Dialekt/Umgangssprache → Standard** (Wörterbuch §9.1, ganze Wörter, Groß-/Kleinschreibung egal):
   „wedder“ → „wetter“, „morsche“ → „morgen“, „heit“ → „heute“, „isses“ → „ist es“, „hammer“ → „haben
   wir“ …
3. **Zahlwörter → Ziffern:** „fünfunddreißig“ → 35, „zweitausendsiebenundzwanzig“ → 2027, „halb“,
   „viertel“, „anderthalb“ → Brüche; Ziffernfolgen („drei fünf sieben acht eins“, „35 781“,
   „fünfunddreißig sieben einundachtzig“) werden zu **einer** Zahl zusammengefasst, wenn sie zusammen
   genau 5 Stellen ergeben und vor/nach ihnen ein PLZ-Signal steht („Postleitzahl“, „PLZ“, „in“,
   „für“) oder die Zahl im Gazetteer existiert.
4. Ergebnis: `Utterance(raw, text, tokens, numbers, stt_confidence)`.

### 4.2 Absicht erkennen

- Jeder Skill hat **Muster** (reguläre Ausdrücke über `text`) mit Gewicht und **Schlüsselwörter**
  (z. B. „wetter“, „regen“, „schirm“, „grad“, „warm“, „kalt“, „sonne“). Score = bestes Muster ×
  Abdeckung (Anteil erkannter Wörter) × Slot-Vollständigkeit.
- **Ausschlusslisten** je Skill (wie heute `_NOT_THE_CLOCK`): „Um wie viel Uhr fährt der Zug?“ ist
  keine Uhrzeitfrage, „Das Wetter ist mir egal“ keine Wetterfrage, „Ich hab keine Zeit“ keine
  Zeitfrage, „Wie war das Wetter im Urlaub?“ keine Wetterfrage (kein Ort/Zeitraum bestimmbar →
  Weitergabe).
- **Schwellwerte:** Score ≥ 0,75 → antworten; 0,5–0,75 und genau ein Kandidat → antworten, wenn
  alle Pflichtangaben eindeutig sind, sonst Rückfrage; < 0,5 → Weitergabe. Zwei Kandidaten mit
  Abstand < 0,1 → Weitergabe (später LLM), außer sie sind kombinierbar (siehe unten).
- **Lange oder zusammengesetzte Sätze** (> 18 Wörter, oder „und dann“, „außerdem“, „weil“) gehen
  nie an einen Skill, außer die Kombination ist vorgesehen: „Wie spät ist es und wie wird das
  Wetter?“ → Zeit + Wetter in einer Antwort (max. zwei Skills).
- **Konfidenz der Spracherkennung:** Ist `avg_logprob` niedrig (< −0,8) **und** hängt die Antwort an
  einer Zahl/PLZ/einem Ortsnamen, wird die erkannte Angabe in der Antwort wiederholt („Für 60311,
  das ist Frankfurt am Main: …“) – bei sehr niedriger Konfidenz (< −1,0) vorher kurz nachgefragt
  („Meinst du die Postleitzahl 60311?“).

### 4.3 Zeitangaben (`slots/when.py`)

Ergebnis: `When(start, end, granularity: now|hour|daypart|day|days|week|month|year, label)`; `label`
ist die gesprochene Form für die Antwort („morgen früh“, „am Samstag“, „am Wochenende“).

| Ausdruck | Bedeutung (Beispiel: heute = Sonntag, 18.10.2026, 19:12) |
| --- | --- |
| *(nichts)* bei Wetter | jetzt + Rest des Tages; nach 18 Uhr: heute Abend/Nacht + Hinweis auf morgen |
| jetzt, gerade, im Moment, aktuell, draußen | aktueller Wert (`current`) |
| heute | heute 00–24 (bei Wetter: ab jetzt bis Mitternacht, Tageswerte heute) |
| heute früh / heute Morgen | 05–09 (liegt es in der Vergangenheit: Rückblick aus Messwerten, sonst Hinweis „Das ist vorbei.“) |
| vormittags · mittags · nachmittags · abends · nachts | 09–12 · 12–14 · 14–18 · 18–22 · 22–05 |
| heute Nacht / heute Abend | 22 heute – 06 morgen · 18–22 heute |
| in der Nacht zu Dienstag | Montag 22 – Dienstag 06 |
| morgen · übermorgen · gestern · vorgestern | Tag + 1 · + 2 · − 1 · − 2 |
| morgen früh · morgen Abend · morgen Mittag | Tagesteil des Folgetags |
| Montag … Sonntag, „am Freitag“ | nächster solcher Tag **ab heute** (heute Freitag → heute); in der Antwort mit Datum |
| nächsten Freitag | nächster solcher Tag **nach** heute; Antwort nennt immer das Datum („am Freitag, dem 23. Oktober“) |
| (am) Wochenende, dieses Wochenende | Samstag + Sonntag dieser Woche; samstags/sonntags: der Rest davon |
| nächstes Wochenende | Wochenende der nächsten Kalenderwoche (sonntags: das kommende) |
| diese Woche · nächste Woche · die nächsten Tage | Rest bis Sonntag · Mo–So nächste KW · heute + 1 … + 5 |
| in X Minuten/Stunden · in einer halben Stunde · in anderthalb Stunden | Zeitpunkt jetzt + Dauer |
| in X Tagen/Wochen/Monaten/Jahren | Datum + Dauer (Kalenderarithmetik, Monatsende sauber: 31.01. + 1 Monat = 28./29.02.) |
| um 15 Uhr, um 15:30, um drei | Uhrzeit; „um drei“ ohne Tagesteil → nächster zukünftiger Zeitpunkt von 3:00/15:00 zwischen 6 und 22 Uhr |
| halb vier · viertel nach drei · viertel vor vier | 3:30/15:30 · 3:15 · 3:45 (Regel wie oben) |
| viertel vier · dreiviertel vier (hessisch/ostdeutsch) | 3:15 · 3:45 (`skills.time.quarter_dialect`) |
| am 24. Dezember, am 24.12., am vierundzwanzigsten | Datum; ohne Jahr → nächstes Vorkommen ab heute |
| Anfang/Mitte/Ende (nächster) Woche/Monat | Mo–Di / Mi–Do / Fr–So bzw. 1.–10. / 11.–20. / 21.–Ende |
| Sonderdaten: Heiligabend, Weihnachten, Silvester, Neujahr, Ostern, Pfingsten, Himmelfahrt/Vatertag, Fronleichnam, Muttertag, Erntedank, 1. Advent … 4. Advent, Nikolaus, Valentinstag, Halloween, Rosenmontag, Fastnacht, Aschermittwoch, Buß- und Bettag, Totensonntag, Sommer-/Winterzeit, Frühlings-/Sommer-/Herbst-/Winteranfang | Datum aus `calendar/` (§8) |
| letztes Jahr an diesem Tag, vor einer Woche | Vergangenheit (Wetter-Rückblick: KANN, §6.4) |

Mehrdeutig („am Ersten“ ohne Monat, „nach Weihnachten“) → Rückfrage nur, wenn die Antwort davon
abhängt; sonst plausibelste Deutung **mit Nennung** in der Antwort.

### 4.4 Ortsangaben (`slots/where.py`)

1. **Heimat-Wörter:** „hier“, „bei mir“, „bei uns“, „zu Hause“, „daheim“, „draußen“, „in Weilburg“
   → Heimatort. „In der Region“, „im Landkreis“, „in der Gegend“, „im Umkreis“ → Regionsüberblick
   (Heimatort + `skills.home.region_places`).
2. **Postleitzahl:** fünf Ziffern (nach §4.1/3) → Gazetteer. Mehrere Orte je PLZ (z. B. eine PLZ für
   mehrere Gemeinden) → Hauptort (größte Einwohnerzahl), Antwort nennt ihn. Existiert die PLZ nicht →
   „Die Postleitzahl 35791 kenne ich nicht.“ (+ nächstliegende ähnliche, falls genau eine Ziffer
   abweicht: „Meinst du 35781, Weilburg?“).
3. **Ortsname:** Kandidaten-Fenster nach Signalwörtern („in“, „für“, „bei“, „nach“, „rund um“,
   „Wetter …“) bis zum nächsten Zeitwort/Satzende, längste Übereinstimmung zuerst (max. 5 Wörter:
   „Frankfurt am Main“, „Limburg an der Lahn“, „Bad Homburg vor der Höhe“).
   - Abgleich in dieser Reihenfolge: exakt → ohne Zusätze („an der Lahn“, „a. d. Lahn“, „(Lahn)“,
     „Bad“, „Sankt/St.“, „im Taunus“) → Ortsteile (GeoNames-Ortsteile, z. B. „Kubach“ → Weilburg-Kubach)
     → **unscharf** (`difflib` ≥ 0,88; kein `rapidfuzz`) → **phonetisch** (Kölner Phonetik gleich und Länge ± 2).
   - Unscharfe/phonetische Treffer werden **nie** stillschweigend genommen: Antwort mit Nennung
     („Ich nehme an, du meinst Weilburg: …“) oder Rückfrage, wenn mehrere ähnlich gut sind.
4. **Mehrdeutige Namen** (Frankfurt, Neustadt, Kirchheim, Limburg …): Score = Namensgleichheit ×
   log(Einwohner) × Nähe-Faktor (nah am Heimatort bevorzugt). Klarer Sieger (Abstand > 30 %) →
   nehmen und in der Antwort präzisieren („Frankfurt am Main“); sonst Rückfrage mit höchstens zwei
   Optionen: „Welches Neustadt meinst du – Neustadt in Hessen oder Neustadt an der Weinstraße?“ Die
   Antwort („das in Hessen“, „das erste“, „Weinstraße“) wird im Kontext aufgelöst.
5. **Ausland:** Weltstädte-Tabelle (deutsche Namen, z. B. „Mailand“, „Rom“, „Mallorca“ → Palma,
   „New York“), sonst Open-Meteo-Geocoding online (Sprache `de`, Treffer mit Land nennen).
   Länder ohne Stadt („Wetter in Spanien“) → Rückfrage nach der Stadt bzw. Hauptstadt mit Nennung.
6. Ergebnis: `Place(name, display_name, postal_codes, district, state, country, lat, lon, tz,
   population, source, confidence)`.

### 4.5 Dialogkontext und Folgefragen (`context.py`)

- `SkillContext` hält je Anruf: letzte Auskunft (Skill, Ort, Zeitraum, Aspekt), offene Rückfrage
  (Optionen + erwarteter Typ), „Mehr Details“-Text, Sprechtempo, laufende Eieruhr. Ablauf: drei
  Runden oder zwei Minuten nach der letzten Auskunft.
- **Ellipsen:** „Und morgen?“, „Und am Wochenende?“, „Und um 18 Uhr?“ (neuer Zeitraum, alter Ort und
  Skill) · „Und in Limburg?“, „Und in 60311?“, „Und dort?“ (neuer Ort, alter Skill/Zeitraum) · „Und der
  Wind?“, „Wie warm?“, „Regnet es?“ (neuer Aspekt) · „Mehr Details“, „Genauer?“, „Was noch?“
  (Detail-Text) · „Woher weißt du das?“ (Quelle der letzten Auskunft).
- **Rückfragen:** höchstens eine pro Auskunft; versteht Nikita die Antwort nicht, nimmt sie die
  plausibelste Option **mit Nennung** statt ein zweites Mal zu fragen.
- Ein Ortswechsel gilt nur für den laufenden Anruf; der Heimatort ändert sich nie per Sprache.

## 5. Heimatort Weilburg (35781)

| Wert | Inhalt | Herkunft / Prüfung |
| --- | --- | --- |
| Postleitzahl | **35781** | Vorgabe Moritz (`skills.home.postal_code`) |
| Ort | Weilburg, Landkreis Limburg-Weilburg, Regierungsbezirk Gießen, Hessen | Gazetteer |
| Koordinaten | ≈ 50,48° N, 8,26° E (Kernstadt an der Lahn) | Gazetteer; Überschreiben mit `skills.home.latitude/longitude` |
| Amtlicher Gemeindeschlüssel | 06 5 33 017 (laut Postleitzahl-Verzeichnissen; in P1-21 gegen das Destatis-Gemeindeverzeichnis prüfen) | – |
| NINA-Regionalschlüssel (Kreisebene) | 065330000000 (Landkreis Limburg-Weilburg; die NINA-Übersicht erwartet Kreis-ARS mit Nullen) | P1-23 prüfen |
| DWD-Warnzelle | wird beim ersten Abruf aus der Bright-Sky-Antwort (`/alerts?lat=…&lon=…`, Feld `warn_cell_id`) übernommen und gecacht | P1-23 |
| DWD-Pollenregion | Hessen, Teilregion **„Nordhessen und hessische Mittelgebirge“** (Weilburg liegt zwischen Westerwald und Taunus); Alternative „Rhein-Main“ | Kennungen (laut Fremdquellen 91/92) in P1-23 gegen die aktuelle DWD-Datei prüfen; F-20 |
| Lahn-Pegel | nächstgelegener PEGELONLINE-Pegel an der Lahn (Kandidat: Leun oberhalb von Weilburg) | `stations.json?waters=LAHN` in P1-27, F-23 |
| Zeitzone | Europe/Berlin | `general.timezone` |
| Feiertage/Ferien | Hessen (`skills.home.state = "HE"`, ersetzt `fastpaths.state`) | §8 |
| Regionsüberblick | Weilburg + Limburg an der Lahn + Wetzlar (`skills.home.region_places`) | F-24 |
| Ortsteile (Beispiele) | Ahausen, Bermbach, Drommershausen, Gaudernbach, Hasselbach, Hirschhausen, Kirschhofen, Kubach, Odersbach, Waldhausen | Gazetteer (Ortsteile → Weilburg); Liste in P1-21 gegen die Stadt prüfen |

Der Installer fragt den Heimatort **nicht** ab (Standard ist gesetzt); Änderung über
`config/moritz-agent.toml`. Die Statusseite (P1-14) zeigt den aufgelösten Heimatort mit Koordinaten,
damit ein Tippfehler sofort auffällt.

## 6. Katalog aller Sofortauskünfte

Spalten: **ID** · **Beispiele** (inkl. Umgangssprache) · **Antwort** (Form) · **Quelle** · **W** =
Umsetzungswelle (§16) · **P** = Priorität (M = MUSS, S = SOLL, K = KANN). Alle Beispielwerte sind
Platzhalter.

### 6.1 Uhrzeit

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `time.now` | „Wie viel Uhr ist es?“, „Wie spät isses?“, „Wie viel Uhr hammer?“, „Uhrzeit?“ | „Es ist 19 Uhr 12.“ (optional umgangssprachlich: „Es ist Viertel nach sieben.“ nur bei glatten Vierteln) | Systemuhr, Europe/Berlin | A | M |
| `time.datetime` | „Datum und Uhrzeit?“ | „Heute ist Sonntag, der 18. Oktober 2026, und es ist 19 Uhr 12.“ | Systemuhr | A | M |
| `time.world` | „Wie spät ist es in New York?“, „Uhrzeit in Tokio?“ | „In New York ist es jetzt 13 Uhr 12, sechs Stunden früher als hier.“ | zoneinfo + Weltstädte | A | S |
| `time.offset` | „Wie viel Zeitunterschied ist es nach Sydney?“ | „Sydney ist uns gerade neun Stunden voraus.“ (Sommerzeit beider Orte beachtet) | zoneinfo | A | S |
| `time.in_duration` | „Wie spät ist es in drei Stunden?“, „Wann ist es in 90 Minuten?“ | „In drei Stunden ist es 22 Uhr 12.“ | Uhr | A | S |
| `time.until` | „Wie lange noch bis 22 Uhr?“, „Wie lange ist es noch bis Mitternacht?“ | „Noch 2 Stunden und 48 Minuten.“ | Uhr | A | S |
| `time.dst_now` | „Haben wir gerade Sommerzeit?“ | „Ja, noch bis Sonntag, 25. Oktober – dann wird die Uhr eine Stunde zurückgestellt.“ | zoneinfo | A | S |
| `time.dst_next` | „Wann wird die Uhr umgestellt?“, „Zeitumstellung?“ | „Am Sonntag, 25. Oktober, um 3 Uhr wird die Uhr auf 2 Uhr zurückgestellt – eine Stunde länger schlafen.“ | zoneinfo-Übergänge | A | M |
| `time.timestamp_talk` | „Sag mir die genaue Uhrzeit“ | „Es ist 19 Uhr 12 und 30 Sekunden.“ | Uhr (Sekunden **direkt vor** der Ausgabe gelesen, TTS-Vorlauf eingerechnet) | A | K |
| `time.clock_check` | „Geht meine Uhr richtig? Bei mir ist es 19:15.“ | „Bei mir ist es 19 Uhr 12 – deine geht etwa 3 Minuten vor.“ | Uhr (NTP-synchron, Status zeigt Synchronität) | A | K |

### 6.2 Datum und Kalender

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `date.today` | „Welches Datum ist heute?“, „Der Wievielte ist heute?“, „Was hammer heit fürn Datum?“ | „Heute ist Sonntag, der 18. Oktober 2026.“ | Uhr | A | M |
| `date.weekday` | „Welcher Tag ist heute?“, „Was ist heute für ein Tag?“ | „Heute ist Sonntag.“ + Sonderdatum, falls vorhanden („… und Erntedank ist vorbei, nächster Feiertag …“ nur bei echtem Anlass) | Uhr + Kalender | A | M |
| `date.relative` | „Welcher Tag ist morgen/übermorgen/war gestern/vorgestern?“ | „Übermorgen ist Dienstag, der 20. Oktober.“ | Uhr | A | M |
| `date.weekday_of` | „Was für ein Tag ist der 24. Dezember?“, „Welcher Wochentag war der 3. Oktober 1990?“ | „Der 24. Dezember 2026 ist ein Donnerstag.“ | proleptischer Gregorianischer Kalender (Jahre 1583–9999) | A | M |
| `date.offset` | „Welches Datum ist in drei Wochen?“, „Was ist heute in 100 Tagen?“ | „In drei Wochen ist Sonntag, der 8. November.“ | Kalenderarithmetik | A | S |
| `date.days_until` | „Wie viele Tage bis Weihnachten / Silvester / zum 1. März / bis zum Wochenende / bis Ostern?“ | „Noch 67 Tage bis Heiligabend.“ (Ziel heute → „Heute ist Heiligabend!“) | Kalender | A | M |
| `date.days_since` | „Wie viele Tage sind seit Neujahr vergangen?“, „Wie lange ist der 1. Mai her?“ | „Seit Neujahr sind 290 Tage vergangen.“ | Kalender | A | S |
| `date.between` | „Wie viele Tage liegen zwischen dem 1. März und dem 15. April?“ | „45 Tage.“ (+ „6 Wochen und 3 Tage“) | Kalender | A | S |
| `date.calendar_week` | „Welche KW haben wir?“, „In welcher Kalenderwoche ist der 24.12.?“ | „Wir haben Kalenderwoche 42.“ | ISO 8601 | A | M |
| `date.week_range` | „Wann ist KW 50?“ | „Kalenderwoche 50 geht von Montag, 7. Dezember, bis Sonntag, 13. Dezember.“ | ISO 8601 | A | S |
| `date.day_of_year` | „Der wievielte Tag des Jahres ist heute?“, „Wie viele Tage hat das Jahr noch?“ | „Heute ist der 291. Tag des Jahres, es bleiben noch 74.“ | Kalender | A | S |
| `date.month_info` | „Wie viele Tage hat der Februar 2028?“ | „Der Februar 2028 hat 29 Tage – 2028 ist ein Schaltjahr.“ | Kalender | A | S |
| `date.leap_year` | „Ist 2028 ein Schaltjahr?“ | „Ja, 2028 ist ein Schaltjahr.“ | Kalender | A | S |
| `date.age` | „Wie alt ist jemand, der am 12. Mai 1990 geboren ist?“, „Wie alt bin ich, wenn ich 1995 geboren bin?“ | „36 Jahre.“ (ohne Tag: „35 oder 36, je nachdem, ob der Geburtstag schon war.“) | Kalender | A | S |
| `date.weeks_in_year` | „Wie viele Kalenderwochen hat 2026?“ | „2026 hat 53 Kalenderwochen.“ | ISO 8601 | A | K |
| `date.year_progress` | „Wie viel vom Jahr ist schon rum?“ | „Fast 80 Prozent – 291 von 365 Tagen.“ | Kalender | A | K |
| `date.zodiac` | „Welches Sternzeichen hat der 12. Mai?“ | „Wer am 12. Mai geboren ist, hat das Sternzeichen Stier.“ (nur die Datumsgrenzen, keine Horoskope) | feste Tabelle | A | K |
| `date.special` | „Wann ist Muttertag?“, „Wann ist der erste Advent?“, „Wann ist Rosenmontag 2027?“, „Wann ist Ostern 2027?“ | „Der erste Advent ist am Sonntag, 29. November.“ | §8.2 | A | M |

### 6.3 Feiertage, Ferien, Arbeitstage

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `holiday.next` | „Wann ist der nächste Feiertag?“ | „Der nächste Feiertag in Hessen ist der 1. Weihnachtstag, am Freitag, 25. Dezember.“ | §8.1 | A | M |
| `holiday.is` | „Ist morgen ein Feiertag?“, „Ist der 31. Oktober in Hessen ein Feiertag?“ | „Nein, der Reformationstag ist in Hessen kein gesetzlicher Feiertag – in Niedersachsen zum Beispiel schon.“ | §8.1 (alle Länder) | A | M |
| `holiday.list` | „Welche Feiertage gibt es im Dezember?“, „Feiertage 2027?“ | max. 4 nennen, Rest auf Nachfrage | §8.1 | A | S |
| `holiday.other_state` | „Ist Fronleichnam in Bayern ein Feiertag?“, „Ist morgen in NRW Feiertag?“ | „Ja, Fronleichnam ist in Bayern ein Feiertag.“ (regionale Sonderfälle wie Augsburger Friedensfest/Mariä Himmelfahrt mit „in Teilen von Bayern“) | §8.1 | A | S |
| `holiday.long_weekend` | „Wann ist das nächste lange Wochenende?“, „Brückentage?“ | „Mit einem Brückentag am Freitag, 7. Mai, nach Christi Himmelfahrt hast du vier Tage frei.“ | §8.3 | A | S |
| `holiday.workdays` | „Wie viele Arbeitstage hat der November?“, „Arbeitstage bis Weihnachten?“ | „Der November 2026 hat 21 Arbeitstage in Hessen.“ | §8.3 | A | S |
| `school.next` | „Wann sind die nächsten Ferien?“, „Wann sind Sommerferien?“ | „Die Weihnachtsferien in Hessen gehen vom … bis …“ | §8.4 (gepflegte Tabelle) | A | S |
| `school.now` | „Sind gerade Ferien?“, „Wie lange gehen die Herbstferien noch?“ | „Ja, in Hessen sind Herbstferien, noch bis Freitag, 23. Oktober.“ | §8.4 | A | S |
| `school.other_state` | „Wann sind in Bayern Sommerferien?“ | nur, wenn die Tabelle das Land enthält (Standard: nur Hessen) – sonst ehrlich | §8.4 | D | K |

### 6.4 Wetter – Überblick und Vorhersage

Alle Wetter-Skills: Ort optional (Standard **Weilburg**), Zeitraum optional (§4.3), Quelle Open-Meteo
(Rückfall Bright Sky), Formulierung nach §7.4. Ein Abruf liefert ein **Wetterpaket**, aus dem alle
Skills antworten (kein Abruf je Frage).

| ID | Beispiele | Antwort | W | P |
| --- | --- | --- | --- | --- |
| `weather.now` | „Wie ist das Wetter?“, „Wie isses Wedder drauße?“, „Wie warm ist es?“, „Wie viel Grad hat es?“ | „In Weilburg sind es gerade 11 Grad, stark bewölkt, schwacher Wind aus Südwest.“ (+ „gefühlt 7 Grad“ bei ≥ 3 K Unterschied) | B | M |
| `weather.today` | „Wie wird das Wetter heute?“, „Wie werd's heit?“ | „Heute in Weilburg bis 15 Grad, vormittags trocken, ab dem Nachmittag Schauer.“ (nach 18 Uhr: Abend/Nacht + Hinweis auf morgen) | B | M |
| `weather.daypart` | „Wie wird es heute Abend?“, „Und heute Nacht?“, „Wie ist es morgen früh?“ | „Heute Nacht wird es klar und kalt, bis 2 Grad, gegen Morgen Bodenfrost möglich.“ | B | M |
| `weather.day` | „Wie wird das Wetter morgen / übermorgen / am Samstag / am 24.12.?“ | „Morgen, Montag, wird es wechselhaft bei 8 bis 13 Grad, vormittags Schauer.“ | B | M |
| `weather.weekend` | „Wie wird das Wetter am Wochenende?“ | „Samstag sonnig bis 16 Grad, Sonntag Regen bei höchstens 12 Grad.“ | B | M |
| `weather.week` | „Wie wird die Woche?“, „Die nächsten Tage?“, „Wetter für die nächsten 7 Tage?“ | Trend in ≤ 3 Abschnitten: „Bis Mittwoch trocken und mild um 15 Grad, ab Donnerstag kühler mit Regen.“ | B | M |
| `weather.hour` | „Wie ist das Wetter um 15 Uhr?“, „Wie wird es in zwei Stunden?“ | „Um 15 Uhr sollen es 14 Grad sein, bewölkt, Regenrisiko 20 Prozent.“ | B | M |
| `weather.long_range` | „Wie wird das Wetter in zwei Wochen?“, „Wird es an Weihnachten schneien?“ (außerhalb 16 Tage) | Tendenz bis Tag 16 („nur eine grobe Tendenz“), darüber ehrliche Absage | B | S |
| `weather.place` | „Wie ist das Wetter in Berlin?“, „Wetter in 60311?“, „Wie wird's morgen in Limburg?“ | wie oben, mit Ortsnennung („Für 60311, das ist Frankfurt am Main: …“) | B | M |
| `weather.region` | „Wie ist das Wetter in der Region?“, „Im Landkreis?“ | „In Weilburg 11, in Limburg 12 und in Wetzlar 10 Grad, überall bewölkt und trocken.“ | B | S |
| `weather.compare` | „Wird es morgen wärmer als heute?“, „Ist es in Frankfurt wärmer als hier?“ | „Ja, morgen wird es mit 16 Grad drei Grad wärmer als heute.“ | C | S |
| `weather.extremes` | „Wann ist es heute am wärmsten?“, „Welcher Tag wird diese Woche am schönsten?“ | „Am wärmsten wird es heute gegen 15 Uhr mit 14 Grad.“ / „Am schönsten wird der Donnerstag: sonnig bis 17 Grad.“ | C | S |
| `weather.when_change` | „Wann wird es wieder warm/sonnig/trocken?“, „Wann kommt der nächste Frost?“ | „Laut Vorhersage ab Freitag, dann bis zu 18 Grad.“ (Suche im Vorhersagezeitraum, sonst ehrlich) | C | S |
| `weather.yesterday` | „Wie war das Wetter gestern?“, „Wie viel hat es gestern geregnet?“ | „Gestern war es in Weilburg bis 14 Grad, es hat 3 Liter pro Quadratmeter geregnet.“ | C | S |
| `weather.history` | „Wie warm war es letztes Jahr an diesem Tag?“ | aus Open-Meteo-Archiv (Reanalyse), als „laut Wetterdaten“ | D | K |
| `weather.observed` | „Wie warm ist es wirklich gerade?“, „Was misst die Wetterstation?“ | „Die DWD-Station Weilburg … misst gerade 10,8 Grad.“ (Bright Sky, nächste Station mit Name und Entfernung) | C | K |
| `weather.summary_brief` | Teil von `briefing` (§6.15) | ein Satz Tagesüberblick | C | S |

### 6.5 Wetter – Einzelheiten

| ID | Beispiele | Antwort | W | P |
| --- | --- | --- | --- | --- |
| `weather.rain` | „Regnet es heute?“, „Gibt's Regen?“, „Wird's nass?“ | „Ja, ab etwa 15 Uhr sind Schauer wahrscheinlich, bis zum Abend.“ / „Nein, heute bleibt es trocken.“ | B | M |
| `weather.rain_when` | „Wann fängt es an zu regnen?“, „Wann hört der Regen auf?“, „Wie lange regnet es noch?“ | „Der Regen soll gegen 17 Uhr aufhören.“ (15-Minuten-Daten, wo verfügbar) | B | M |
| `weather.rain_now` | „Regnet es gerade?“ | „Laut Messung und Vorhersage regnet es in Weilburg gerade leicht.“ (Modell + Station; Radar = K) | C | S |
| `weather.rain_amount` | „Wie viel Regen kommt?“, „Wie viel hat es geregnet?“ | „Bis morgen früh sollen 8 Liter pro Quadratmeter fallen.“ | C | S |
| `weather.umbrella` | „Brauche ich einen Schirm?“, „Brauch isch en Schermche?“ | Ratschlag nach §7.7 mit Begründung | B | M |
| `weather.snow` | „Schneit es morgen?“, „Bleibt der Schnee liegen?“, „Gibt es weiße Weihnachten?“ | „Morgen früh kann es schneien, liegen bleiben soll kaum etwas.“ | B | M |
| `weather.frost` | „Gibt es heute Nacht Frost?“, „Muss ich morgen kratzen?“, „Wird es glatt?“ | „Ja, heute Nacht bis minus 2 Grad – morgen früh musst du wohl kratzen.“ (Glätte bei gefrierendem Regen/Niesel immer zuerst) | B | M |
| `weather.wind` | „Wie windig ist es?“, „Gibt es Sturm?“, „Wie stark sind die Böen?“ | „Mäßiger Wind aus West, Böen bis 50 Kilometer pro Stunde.“ (Beaufort-Wort, §7.4) | B | M |
| `weather.thunder` | „Gibt es Gewitter?“, „Wird's heute gewittrig?“ | „Am späten Nachmittag sind Gewitter möglich, örtlich mit Starkregen.“ | B | M |
| `weather.fog` | „Ist es neblig?“, „Gibt es morgen früh Nebel?“ | „Morgen früh ist im Lahntal Nebel möglich.“ (Code 45/48, Sicht < 1 km) | C | S |
| `weather.temperature` | „Wie warm wird es heute?“, „Wie kalt wird es heute Nacht?“, „Höchsttemperatur morgen?“ | „Heute bis 15, heute Nacht bis 6 Grad.“ | B | M |
| `weather.feels_like` | „Wie kalt fühlt es sich an?“ | „Gefühlt sind es wegen des Windes nur 4 Grad.“ | C | S |
| `weather.humidity` | „Wie hoch ist die Luftfeuchtigkeit?“, „Ist es schwül?“ | „Die Luftfeuchtigkeit liegt bei 85 Prozent.“ / schwül = Taupunkt ≥ 16 °C | C | S |
| `weather.pressure` | „Wie ist der Luftdruck?“, „Steigt oder fällt der Luftdruck?“ | „1.012 Hektopascal, in den letzten drei Stunden leicht fallend.“ | C | K |
| `weather.sunshine` | „Scheint heute die Sonne?“, „Wie viele Sonnenstunden?“ | „Heute sind etwa 4 Sonnenstunden drin, am meisten über Mittag.“ | C | S |
| `weather.clouds` | „Ist es bewölkt?“, „Wird es heute Nacht klar?“ (Sternegucken) | „Heute Nacht wird es überwiegend klar.“ | C | K |
| `weather.uv` | „Wie hoch ist der UV-Index?“, „Brauche ich Sonnencreme?“ | „UV-Index heute bis 6 – hoch; Sonnencreme ist sinnvoll.“ | C | S |
| `weather.visibility` | „Wie ist die Sicht?“ | „Die Sicht beträgt etwa 300 Meter – Nebel.“ | C | K |
| `weather.source` | „Woher hast du das?“, „Welcher Wetterdienst?“ | „Von Open-Meteo, berechnet mit dem Modell des Deutschen Wetterdienstes.“ | B | M |
| `weather.details` | „Mehr Details“, „Genauer“ | nächste Prioritätsstufe der Fakten (§7.5) | B | M |

### 6.6 Warnungen

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `warn.weather` | „Gibt es Unwetterwarnungen?“, „Gibt's Warnungen für Weilburg?“ | „Ja, der Deutsche Wetterdienst warnt bis heute 22 Uhr vor Sturmböen bis 80 Kilometer pro Stunde.“ / „Nein, für Weilburg gibt es gerade keine Wetterwarnung.“ | DWD über Bright Sky | C | S |
| `warn.weather_detail` | „Was genau?“, „Was soll ich tun?“ | Überschrift + Handlungsempfehlung des DWD, bereinigt, max. 2 Sätze | DWD | C | S |
| `warn.civil` | „Gibt es Warnungen im Landkreis?“, „Ist was mit Hochwasser?“, „Gibt es eine Katastrophenwarnung?“ | NINA-Meldungen (MoWaS/KATWARN/BIWAPP/Hochwasser) für den Kreis: Titel + Gültigkeit | BBK (NINA) | C | S |
| `warn.greeting` | *(automatisch)* | nach der Begrüßung ein Satz, wenn eine Warnung ≥ `announce_on_greeting` für den Heimatort gilt (Standard: ab Stufe 3 „Unwetter“) | DWD + NINA | C | S |
| `warn.place` | „Gibt es in Berlin Warnungen?“ | wie `warn.weather` für den genannten deutschen Ort | DWD | C | K |

### 6.7 Gesundheit und Umwelt

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `pollen.today` | „Wie ist der Pollenflug?“, „Fliegen heute Pollen?“, „Wie sieht's mit Birke aus?“ | „Heute fliegen in Mittelhessen Gräserpollen mäßig, alles andere kaum.“ (nur Stufen ≥ gering; mit `allergens` nur diese) | DWD-Pollenflug-Gefahrenindex | C | S |
| `pollen.forecast` | „Und morgen?“, „Wie wird der Pollenflug übermorgen?“ | heute/morgen/übermorgen (mehr liefert der DWD nicht) | DWD | C | S |
| `pollen.place` | „Pollen in Berlin?“ | DWD-Region des Ortes; im Ausland CAMS (Open-Meteo Luftqualität) mit Hinweis | DWD / CAMS | C | K |
| `air.quality` | „Wie ist die Luft?“, „Wie ist die Luftqualität?“, „Feinstaub?“ | „Die Luftqualität ist gut, europäischer Index 18.“ (Feinstaub/Ozon nur bei mäßig oder schlechter) | Open-Meteo Luftqualität (CAMS) | C | S |
| `air.ozone` | „Wie hoch ist das Ozon?“ | „Ozon heute Nachmittag bis 140 Mikrogramm pro Kubikmeter – mäßig.“ | CAMS | C | K |
| `bio.weather` | „Wie ist das Biowetter?“, „Ist Kopfschmerzwetter?“ | DWD-Biowetter-Einschätzung, ohne medizinischen Rat | DWD (Datei im Ticket bestimmen) | D | K |
| `uv.index` | siehe `weather.uv` | – | Open-Meteo / DWD-UV | C | S |

### 6.8 Alltagsratschläge (feste Regeln, §7.7)

| ID | Beispiele | Antwort (Beispiel) | W | P |
| --- | --- | --- | --- | --- |
| `advice.umbrella` | „Brauche ich einen Schirm?“ | „Ja, am Nachmittag sind Schauer wahrscheinlich.“ | B | M |
| `advice.jacket` | „Brauche ich eine Jacke?“, „Was soll ich anziehen?“ | „Ja, eine dicke Jacke – morgens nur 3 Grad.“ | C | S |
| `advice.laundry` | „Kann ich Wäsche draußen aufhängen?“ | „Heute gut: trocken, sonnig und etwas Wind.“ | C | S |
| `advice.bbq` | „Ist heute Grillwetter?“ | „Heute Abend ja: trocken und um die 20 Grad.“ | C | S |
| `advice.bike` | „Ist Fahrradwetter?“, „Kann ich mit dem Rad fahren?“ | „Bis 16 Uhr trocken, danach Schauer – lieber vorher los.“ | C | S |
| `advice.run` | „Kann ich joggen gehen?“, „Wann ist heute die beste Zeit zum Laufen?“ | „Am besten zwischen 17 und 19 Uhr, trocken und 14 Grad.“ | C | K |
| `advice.garden_water` | „Muss ich den Garten gießen?“ | „Eher ja: in den letzten drei Tagen kaum Regen, und es kommt keiner.“ (Niederschlag vs. Verdunstung) | C | S |
| `advice.mow` | „Kann ich Rasen mähen?“ | „Lieber morgen – heute ist der Rasen nach dem Regen noch nass.“ | C | K |
| `advice.scrape` | „Muss ich morgen Scheibe kratzen?“ | wie `weather.frost` | B | M |
| `advice.sunscreen` | „Brauche ich Sonnencreme?“ | wie `weather.uv` | C | S |
| `advice.ventilate` | „Soll ich lüften?“, „Fenster auflassen heute Nacht?“ | „Heute Nacht ja, es bleibt trocken.“ / Sturm-/Regenhinweis | C | K |
| `advice.car_wash` | „Lohnt sich Autowaschen?“ | „Eher nicht, ab morgen Mittag soll es regnen.“ | C | K |
| `advice.swim` | „Ist Badewetter?“ | „Mit 27 Grad und Sonne ja.“ | C | K |
| `advice.hike` | „Wie ist das Wetter zum Wandern am Samstag?“ | Tagesvorhersage + Gewitter-/Hitze-/Glättehinweis | C | K |
| `advice.plants_frost` | „Muss ich die Pflanzen reinholen?“ | „Ja, heute Nacht ist Bodenfrost möglich.“ | C | K |
| `advice.heating` | „Wird es kalt genug zum Heizen?“ | Tagesmittel < 15 °C → „Heiztag“ | C | K |

### 6.9 Sonne, Mond, Himmel (offline)

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `sun.rise_set` | „Wann geht die Sonne auf/unter?“, „Wann ist morgen Sonnenaufgang in Berlin?“ | „Heute geht in Weilburg die Sonne um 18 Uhr 21 unter.“ | astral, Heimat-/Ortskoordinaten | C | M |
| `sun.dark` | „Wann wird es dunkel/hell?“, „Ist es draußen noch hell?“ | „Richtig dunkel ist es ab etwa 18 Uhr 55.“ (bürgerliche Dämmerung) | astral | C | S |
| `sun.daylength` | „Wie lange ist es heute hell?“, „Wie viel kürzer werden die Tage?“ | „Heute ist es 10 Stunden und 28 Minuten hell, 3 Minuten weniger als gestern.“ | astral | C | S |
| `sun.noon` | „Wann steht die Sonne am höchsten?“ | „Gegen 13 Uhr 12, knapp 30 Grad über dem Horizont.“ | astral | C | K |
| `sun.golden_hour` | „Wann ist die goldene Stunde?“ | Zeitraum vor Sonnenuntergang (Sonne < 6°) | astral | C | K |
| `sun.solstice` | „Ab wann werden die Tage wieder länger?“ | „Ab dem 21. Dezember, der Wintersonnenwende.“ | Meeus | C | S |
| `moon.phase` | „Welche Mondphase haben wir?“, „Ist heute Vollmond?“ | „Zunehmender Halbmond; Vollmond ist am Montag, 26. Oktober.“ | Meeus Kap. 49 | C | S |
| `moon.next` | „Wann ist der nächste Vollmond / Neumond?“ | „Der nächste Vollmond ist am …, um … Uhr.“ | Meeus | C | S |
| `moon.rise_set` | „Wann geht der Mond auf?“ | „Heute um 15 Uhr 40, unter geht er nach Mitternacht.“ | astral | C | K |
| `season.start` | „Wann ist Frühlingsanfang?“, „Wann beginnt der Winter?“ | „Astronomisch am 21. Dezember um … Uhr, meteorologisch schon am 1. Dezember.“ | Meeus Kap. 27 + feste Daten | C | S |
| `sky.stars` | „Kann man heute Nacht Sterne sehen?“ | Bewölkung nachts + Mondphase („klar, aber fast Vollmond“) | Wetter + Mond | C | K |

### 6.10 Orte und Entfernungen (offline)

| ID | Beispiele | Antwort | W | P |
| --- | --- | --- | --- | --- |
| `geo.plz_to_place` | „Wo ist 35781?“, „Welcher Ort hat die Postleitzahl 65549?“ | „35781 ist Weilburg im Landkreis Limburg-Weilburg, Hessen.“ | B | S |
| `geo.place_to_plz` | „Welche Postleitzahl hat Limburg?“ | „Limburg an der Lahn hat die Postleitzahlen 65549 bis 65556.“ (zusammenhängende Bereiche zusammengefasst, sonst max. 3) | B | S |
| `geo.distance` | „Wie weit ist es nach Frankfurt?“, „Entfernung Weilburg Gießen?“ | „Luftlinie etwa 50 Kilometer, Richtung Südosten.“ (ausdrücklich Luftlinie, keine Straßenkilometer) | B | S |
| `geo.region_of` | „In welchem Bundesland liegt Wetzlar?“, „Zu welchem Kreis gehört Runkel?“ | „Runkel gehört zum Landkreis Limburg-Weilburg in Hessen.“ | B | S |
| `geo.home` | „Wo bin ich?“, „Was ist mein Standort?“, „Für welchen Ort sagst du das Wetter?“ | „Dein Heimatort ist Weilburg, 35781.“ | B | M |
| `geo.timezone` | „Welche Zeitzone hat Bangkok?“ | „Bangkok liegt in der Zeitzone UTC plus 7, fünf Stunden vor uns.“ | A | K |
| `geo.dialing_code` | „Welche Vorwahl hat Weilburg?“ | aus der Ortsnetz-Liste der Bundesnetzagentur (Datei, Nutzungsbedingungen prüfen) | D | K |

### 6.11 Rechnen und Umrechnen (offline)

| ID | Beispiele | Antwort | W | P |
| --- | --- | --- | --- | --- |
| `calc.arith` | „Was ist 17 mal 23?“, „144 geteilt durch 12“, „2 hoch 10“, „Wurzel aus 2“ | „17 mal 23 ist 391.“ (max. 4 Nachkommastellen, „ungefähr“ bei Rundung) | A | M |
| `calc.percent` | „Was sind 19 Prozent von 249?“, „Wie viel Prozent sind 30 von 120?“ | „30 von 120 sind 25 Prozent.“ | A | M |
| `calc.vat` | „Was ist 100 Euro netto brutto?“, „Wie viel Mehrwertsteuer ist in 59,90?“ | „In 59 Euro 90 stecken 9 Euro 56 Mehrwertsteuer bei 19 Prozent.“ (7 % auf Nachfrage/bei „ermäßigt“) | A | S |
| `calc.tip` | „10 Prozent Trinkgeld auf 43 Euro?“ | „4 Euro 30, zusammen 47 Euro 30 – aufgerundet 48.“ | A | S |
| `calc.split` | „86 Euro durch 3 Personen?“ | „Jeder zahlt 28 Euro 67.“ | A | S |
| `calc.fraction` | „Was ist ein Drittel von 90?“, „Anderthalb mal 12?“ | „30.“ | A | S |
| `calc.discount` | „Was kostet 80 Euro minus 25 Prozent?“ | „60 Euro.“ | A | S |
| `calc.round` | „Runde 3,14159 auf zwei Stellen“ | „3 Komma 14.“ | A | K |
| `convert.units` | „Wie viel sind 5 Meilen in Kilometer?“, „100 Fahrenheit in Celsius“, „Wie viele Gramm sind ein Pfund?“, „3 Esslöffel in Milliliter“ | „5 Meilen sind etwa 8 Kilometer.“ („Pfund“ = 500 g; „englisches Pfund“ = 453,6 g) | A | S |
| `convert.speed` | „50 Knoten in km/h?“ | „Gut 90 Kilometer pro Stunde.“ | A | S |
| `convert.time` | „Wie viele Sekunden hat ein Tag?“, „Wie viele Stunden sind 3 Tage?“ | „86.400 Sekunden.“ | A | S |
| `convert.data` | „Wie viele Megabyte sind 2 Gigabyte?“ | dezimal (2.000) + Hinweis auf binär (2.048 Mebibyte) | A | K |
| `convert.numeral` | „Was ist 2026 in römischen Zahlen?“, „42 in binär?“ | „MMXXVI.“ (buchstabiert ausgegeben) | A | K |
| `convert.fuel` | „Was sind 6 Liter auf 100 Kilometer in Meilen pro Gallone?“ | „Etwa 39 Meilen pro US-Gallone.“ | A | K |
| `convert.cooking` | „Wie viele Gramm Butter sind ein Stück?“ | nur feste Tabelle (250 g Stück) – sonst Weitergabe | A | K |

Rechnen: eigener rekursiver Parser über Tokens („plus“, „minus“, „mal“, „geteilt durch“, „durch“,
„hoch“, „Wurzel aus“, „Prozent von“, „Klammer auf/zu“, „Komma“), **kein `eval`**, Grenzen: Exponent
≤ 100, Ergebnis ≤ 10^15 sonst wissenschaftlich gesprochen, Division durch null → „Durch null kann man
nicht teilen.“ Einheiten aus `assets/data/einheiten.toml` (Faktor + Offset für Temperatur).

### 6.12 Geld und Preise

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `money.fx` | „Wie viel sind 100 Dollar in Euro?“, „Wie steht der Franken?“, „Euro in Pfund?“ | „100 US-Dollar sind etwa 92 Euro – EZB-Referenzkurs von heute.“ („Kronen“ → Rückfrage, welche) | EZB-Referenzkurse (täglich, ca. 16 Uhr) | D | S |
| `money.fx_rate` | „Wie ist der Dollarkurs?“ | „Ein Euro kostet 1,09 US-Dollar.“ | EZB | D | S |
| `money.power_price` | „Wann ist Strom heute am billigsten?“, „Was kostet Strom an der Börse?“ | „Am günstigsten heute zwischen 13 und 15 Uhr, an der Börse etwa 4 Cent pro Kilowattstunde ohne Steuern und Netzentgelte.“ | Energy-Charts (Fraunhofer ISE), Day-Ahead DE-LU | D | K |
| `money.fuel` | „Was kostet E10 gerade?“, „Wo tanke ich am billigsten?“ | „Am günstigsten ist E10 gerade bei … in Weilburg für etwa 1 Euro 73.“ (nur geöffnete Stationen im Radius) | Tankerkönig (Schlüssel in `passwords.txt`) | D | K |
| `money.crypto` | „Was kostet Bitcoin?“ | keine verlässliche offene Quelle im Plan → ehrlich bzw. später `web_search` | – | – | – |

### 6.13 Region und Alltag

| ID | Beispiele | Antwort | Quelle | W | P |
| --- | --- | --- | --- | --- | --- |
| `water.level` | „Wie hoch steht die Lahn?“, „Wasserstand Lahn?“, „Steigt die Lahn?“ | „Die Lahn am Pegel Leun steht bei 1 Meter 42, leicht steigend, etwas über dem mittleren Wasserstand.“ | PEGELONLINE (WSV): Wert, Trend aus letzten Messungen, Kennwerte MW/MHW | D | S |
| `water.flood` | „Gibt es Hochwasser?“ | Pegel über MHW → „deutlich erhöht“; NINA-Hochwassermeldungen | PEGELONLINE + NINA | D | S |
| `waste.next` | „Welche Tonne kommt morgen?“, „Wann kommt die gelbe Tonne?“, „Wann ist Sperrmüll?“ | „Morgen wird die Biotonne abgeholt.“ / „Die nächste Papiertonne kommt am Donnerstag, 22. Oktober.“ | Abfallkalender als iCal (AWB Limburg-Weilburg, Link/Datei von Moritz, F-21) | D | S |
| `waste.week` | „Was wird diese Woche abgeholt?“ | Liste der Woche | iCal | D | K |
| `football.last` | „Wie hat die Eintracht gespielt?“ | „Eintracht Frankfurt hat am Samstag 2 zu 1 gegen … gewonnen.“ | OpenLigaDB (Nutzung im Ticket prüfen) | D | K |
| `football.next` | „Wann spielt die Eintracht?“ | „Das nächste Spiel ist am Sonntag um 17 Uhr 30 gegen …“ | OpenLigaDB | D | K |
| `football.table` | „Auf welchem Platz steht die Eintracht?“ | „Auf Platz 5 mit 14 Punkten.“ | OpenLigaDB | D | K |
| `news.headlines` | „Was gibt's Neues?“, „Nachrichten?“ | drei Schlagzeilen, nur Titel, Quelle genannt | Tagesschau-API o. Ä. (Bedingungen prüfen; Standard aus) | D | K |
| `notes.add` | „Schreib Milch auf die Einkaufsliste.“, „Notiz: Reifen wechseln.“ | „Ich habe Milch auf die Einkaufsliste geschrieben.“ | lokal (SQLite/Datei) | D | K |
| `notes.read` | „Was steht auf der Einkaufsliste?“ | „Auf der Liste stehen Milch, Eier und Kaffee.“ | lokal | D | K |
| `notes.clear` | „Lösch die Einkaufsliste.“ | Rückfrage „Wirklich alles löschen?“ → „Ja“ | lokal | D | K |

### 6.14 Kleine Helfer

| ID | Beispiele | Antwort | W | P |
| --- | --- | --- | --- | --- |
| `spell.word` | „Buchstabier Weilburg“, „Wie buchstabiert man Lahn?“ | „W wie Wuppertal, E wie Essen, I wie Ingelheim, L wie Leipzig, B wie Berlin, U wie Unna, R wie Rostock, G wie Goslar.“ (DIN 5009:2022; „traditionell“: Anton, Berta …) – buchstabiert wird, was die Spracherkennung verstanden hat | A | S |
| `spell.letter` | „Wie heißt A in der Buchstabiertafel?“ | „A wie Aachen.“ | A | K |
| `random.coin` | „Wirf eine Münze“, „Kopf oder Zahl?“ | „Kopf.“ | A | S |
| `random.dice` | „Würfel mal“, „Wirf zwei Würfel“, „Würfel einen W20“ | „Eine Vier.“ / „Drei und fünf, zusammen acht.“ | A | S |
| `random.number` | „Nenn mir eine Zahl zwischen 1 und 100“ | „Siebenundvierzig.“ | A | S |
| `random.choice` | „Pizza oder Döner?“, „Entscheide: Kino oder Couch?“ | „Döner.“ | A | K |
| `random.rps` | „Schere, Stein, Papier – Stein!“ | „Ich nehme Papier – Papier wickelt Stein ein, ich gewinne.“ | A | K |
| `fun.joke` | „Erzähl einen Witz“, „Sag was Lustiges“ | eigener Witz aus `assets/data/sprueche.de.toml`, im Anruf ohne Wiederholung | A | K |
| `fun.hessian` | „Sag was auf Hessisch“, „Was heißt Guude?“ | eigener Spruch / kurze Erklärung | A | K |
| `timer.start` | „Stell einen Timer auf 3 Minuten“, „Eieruhr 7 Minuten“ | „Okay, 3 Minuten ab jetzt. Ich melde mich, solange wir telefonieren.“ – nach Ablauf Ton + „Die 3 Minuten sind um.“ (nur im laufenden Anruf, max. 15 min, Stille-Auflegen pausiert) | C | K |
| `timer.left` | „Wie lange noch?“ (bei laufendem Timer) | „Noch 1 Minute 20.“ | C | K |
| `count.down` | „Zähl von 10 runter“ | „Zehn, neun, …, null.“ | A | K |

### 6.15 Gespräch und Nikita

| ID | Beispiele | Antwort | W | P |
| --- | --- | --- | --- | --- |
| `talk.greeting` | „Guude!“, „Hallo“, „Moin“, „Servus“ | „Guude! Was kann ich für dich tun?“ | A | M |
| `talk.thanks` | „Danke“, „Merci“, „Super, danke“ | „Gerne!“ (ohne Auflegen; „Danke, das war’s“ = Abschied) | A | M |
| `talk.how_are_you` | „Wie geht’s dir?“, „Alles klar bei dir?“ | „Mir geht’s gut, danke! Alles läuft.“ bzw. ehrliche Störung (Datendienst/Stimme) | A | M |
| `talk.identity` | „Wer bist du?“, „Wie heißt du?“, „Bist du ein Mensch?“ | „Ich bin Nikita, Moritz’ Telefonassistent – ein Computerprogramm, kein Mensch.“ | A | M |
| `talk.help` | „Was kannst du?“, „Hilfe“, „Was kann ich dich fragen?“ | aus aktiven Skills erzeugt, max. 3 Beispiele + „Frag zum Beispiel: Wie wird das Wetter morgen?“; „Mehr“ → nächste Gruppe | A | M |
| `talk.repeat` | „Was hast du gesagt?“, „Nochmal bitte“ | letzte Antwort (aus RAM-Cache) | A | M |
| `talk.slower` / `talk.faster` | „Sprich langsamer“, „Etwas schneller bitte“ | Sprechtempo für den Rest des Anrufs (Piper `length_scale` ± 15 %, Grenzen 0,8–1,4) + Bestätigung im neuen Tempo | A | S |
| `talk.louder` / `talk.quieter` | „Lauter bitte“, „Leiser“ | Lautheit ± 3 dB (Grenzen −26 … −12 dBFS), nur dieser Anruf | A | K |
| `talk.call_duration` | „Wie lange telefonieren wir schon?“ | „Seit 4 Minuten und 10 Sekunden.“ | A | S |
| `talk.last_question` | „Was hab ich dich gerade gefragt?“ | „Du hast gefragt: Wie wird das Wetter morgen?“ (nur im Anruf, RAM) | A | K |
| `talk.hear_me` | „Hörst du mich?“, „Bist du noch da?“ | „Ja, ich höre dich gut.“ | A | S |
| `talk.privacy` | „Speicherst du das?“, „Nimmst du das auf?“ | ehrliche Antwort aus der Konfiguration („Ich nehme kein Audio auf. Den Text speichere ich 24 Stunden.“) | A | M |
| `talk.version` | „Welche Version hast du?“, „Wie lange läufst du schon?“ | „Ich bin moritz-agent 0.1.0 und laufe seit 3 Tagen.“ | A | S |
| `talk.status` | „Läuft alles?“, „Systemstatus?“ | „Telefon, Spracherkennung und Stimme laufen; die Wetterdaten sind 12 Minuten alt.“ | A | S |
| `talk.goodbye` | „Tschüss“, „Ade“, „Gute Nacht“, „Bis später“, „Danke, das war’s“ | Ansage `goodbye` (bzw. „Gute Nacht, Moritz!“) + Auflegen | A | M |
| `talk.cancel` | „Vergiss es“, „Abbrechen“, „Egal“ | „Alles klar.“ (offene Rückfrage/Timer verworfen) | A | S |
| `briefing` | „Guten Morgen“, „Was steht heute an?“, „Gib mir einen Überblick“ | „Guten Morgen! Heute ist Montag, der 19. Oktober. In Weilburg bewölkt bis 13 Grad, ab Mittag Regen. Morgen wird die Biotonne abgeholt.“ (Datum + Wetter + Warnung + Müll + Feiertag/Ferien in ≤ 3 Sätzen) | C | S |
| `talk.compliment` | „Du bist toll“ | „Danke, das freut mich!“ | A | K |
| `talk.insult` | Beleidigungen | ruhig, kurz („Okay. Kann ich dir sonst helfen?“) | A | K |

Katalog-Umfang: rund **180 Skill-IDs** in 15 Gruppen; davon MUSS 44, SOLL 81, KANN 56 (eine Zeile
bewusst ohne Umsetzung: Kryptokurse).

## 7. Wetter im Detail

### 7.1 Datenquellen und Lizenzen

**Grundsatz (Moritz, 18.10.2026: „Wetter bitte Open Source, free if possible“):** Wetter, Warnungen,
Pollen und Luft kommen **nur** aus Diensten, deren Software Open Source ist oder die amtliche offene
Daten liefern – kostenlos, ohne Konto, ohne API-Schlüssel, Daten unter freier Lizenz (CC BY 4.0).
Proprietäre Wetter-APIs werden nicht eingebaut, auch nicht als Rückfall. Weil Open-Meteo (AGPL-3.0) und
Bright Sky (MIT) Open Source sind, lassen sie sich bei Bedarf **selbst betreiben**; die Adressen sind
dafür konfigurierbar (`skills.weather.open_meteo_url`, `brightsky_url`, §10). Standard bleiben die
öffentlichen, kostenlosen Instanzen.

| Quelle | Wofür | Zugang | Software / Lizenz / Bedingungen | Rolle |
| --- | --- | --- | --- | --- |
| **Open-Meteo** Forecast-API (`api.open-meteo.com/v1/forecast`) | aktuell, 15-Minuten-, Stunden-, Tageswerte, bis 16 Tage, Rückblick `past_days` | kostenlos, ohne Schlüssel | Software **Open Source (AGPL-3.0)**, selbst hostbar; Daten **CC BY 4.0**; öffentliche API kostenlos für nicht kommerzielle Nutzung, < 10.000 Aufrufe/Tag, < 5.000/h, < 600/min; Namensnennung „Wetterdaten: Open-Meteo.com“ | **Hauptquelle** (Deutschland: DWD-ICON-Modelle, `models=best_match` oder `icon_seamless`) |
| Open-Meteo Luftqualität (`air-quality-api.open-meteo.com/v1/air-quality`) | Europäischer AQI, PM10/2,5, Ozon, NO₂; Pollen (CAMS) Europa | ohne Schlüssel | CC BY 4.0 + Copernicus-Bedingungen | Luft; Pollen außerhalb Deutschlands |
| Open-Meteo Geocoding (`geocoding-api.open-meteo.com/v1/search`) | Orte, die der Gazetteer nicht kennt | ohne Schlüssel | CC BY 4.0 (GeoNames-basiert) | Rückfall |
| **Bright Sky** (`api.brightsky.dev`) | DWD-Warnungen (`/alerts`), Stationsmessungen (`/current_weather`), MOSMIX-Vorhersage (`/weather`) | kostenlos, ohne Schlüssel | Software **Open Source (MIT)**, selbst hostbar; Daten DWD Open Data, **CC BY 4.0**, Quelle „Deutscher Wetterdienst“ | Warnungen; Rückfall-Vorhersage; Messwerte |
| **DWD Open Data** (`opendata.dwd.de/climate_environment/health/alerts/`) | Pollenflug-Gefahrenindex `s31fg.json` (heute/morgen/übermorgen, täglich), UV- und Biowetter-Dateien | kostenlos, ohne Schlüssel | amtliche offene Daten, CC BY 4.0 (DWD, Stand Mai 2024) | Pollen (Hauptquelle), UV/Biowetter |
| **NINA** (BBK, `warnung.bund.de/api31/dashboard/<ARS>.json`) | Bevölkerungswarnungen: MoWaS, KATWARN, BIWAPP, DWD, Hochwasser | kostenlos, ohne Schlüssel | amtliche offene Daten; Nutzungsbedingungen in P1-23 prüfen | Katastrophen-/Hochwasserwarnungen |
| GeoNames (Download, im Repo) | PLZ ↔ Ort ↔ Koordinaten, Orte DE, Weltstädte | einmalig, per Skript | CC BY 4.0 | Ortsauflösung (ADR-031) |

**Verworfen:** OpenWeatherMap/Weatherbit/Tomorrow.io/AccuWeather (proprietär, Schlüssel, Kontingente,
Kosten – widerspricht dem Grundsatz), Scraping von wetter.com/wetteronline/kachelmannwetter (AGB,
bricht ständig), DWD-MOSMIX-KMZ selbst parsen (macht Bright Sky bereits, als Open Source), Wetter per
`web_search` (langsam, unzuverlässig, halluzinationsanfällig – genau das ersetzt dieser Plan).
**Später möglich:** eigener Open-Meteo- oder Bright-Sky-Server im Homelab (beides Open Source; kostet
Platz und Rechenzeit für die Modelldaten bzw. eine Datenbank) – nur nötig, falls die öffentlichen
Instanzen wegfallen oder ihre Bedingungen ändern (R20). Umstellen = Adresse in der Konfiguration ändern.

### 7.2 Abruf (ein Wetterpaket je Ort)

```text
GET https://api.open-meteo.com/v1/forecast
  ?latitude=50.48&longitude=8.26            (2 Nachkommastellen ≈ 1 km, Datensparsamkeit)
  &timezone=Europe%2FBerlin &models=best_match &wind_speed_unit=kmh
  &past_days=3 &forecast_days=10            (Rückblick für Gießen-Ratschlag/„gestern“; bis 16 möglich)
  &current=temperature_2m,apparent_temperature,relative_humidity_2m,is_day,precipitation,rain,showers,
           snowfall,weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m
  &minutely_15=precipitation,rain,snowfall,weather_code          (Mitteleuropa: echte 15-min-Daten, ICON-D2)
  &hourly=temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,precipitation_probability,
          precipitation,rain,showers,snowfall,snow_depth,weather_code,cloud_cover,visibility,pressure_msl,
          wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,is_day,sunshine_duration,cape,
          soil_temperature_0cm
  &daily=weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,
         sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,precipitation_sum,rain_sum,
         showers_sum,snowfall_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,
         wind_gusts_10m_max,wind_direction_10m_dominant,et0_fao_evapotranspiration
```

- Abrufe/Tag: Vorabruf Heimatort alle 30 min = 48, plus Fragen zu anderen Orten (Cache 30 min) –
  weit unter den Grenzen. Rate-Limit-Antwort (HTTP 429) → Backoff bis 15 min, Cache weiter nutzen.
- **Prüfung jeder Antwort** (pydantic): Pflichtfelder, gleiche Länge der Reihen, Wertebereiche
  (Temperatur −60 … +60 °C, Wind 0 … 400 km/h, Wahrscheinlichkeit 0 … 100, Niederschlag 0 … 500 mm/h),
  Zeitzone `Europe/Berlin`, erste Stunde nicht in der Zukunft. Verstöße → Rückfallquelle.
- Welche Felder fehlen dürfen (Modelle liefern nicht alles, z. B. `minutely_15` außerhalb
  Mitteleuropas oder `cape`), ist je Skill festgelegt; fehlt ein Pflichtfeld, sagt der Skill nur das,
  was da ist.
- **Rückfall Bright Sky:** `/current_weather?lat&lon` und `/weather?lat&lon&date&last_date` (MOSMIX,
  stündlich, etwa 10 Tage); fehlende Felder (UV, Pollen, 15-min) → diese Skills sagen ehrlich ab.

### 7.3 Wettercodes (WMO) → Deutsch

| Code | Tag | Nacht | Klasse |
| --- | --- | --- | --- |
| 0 | sonnig | klar | trocken |
| 1 | überwiegend sonnig | überwiegend klar | trocken |
| 2 | teils bewölkt | teils bewölkt | trocken |
| 3 | bedeckt | bedeckt | trocken |
| 45 / 48 | Nebel / gefrierender Nebel (Reif) | dto. | Nebel |
| 51 / 53 / 55 | leichter / mäßiger / starker Nieselregen | dto. | Regen |
| 56 / 57 | leichter / starker gefrierender Niesel – **Glätte** | dto. | Glätte |
| 61 / 63 / 65 | leichter Regen / Regen / starker Regen | dto. | Regen |
| 66 / 67 | leichter / starker gefrierender Regen – **Glatteis** | dto. | Glätte |
| 71 / 73 / 75 | leichter Schneefall / Schneefall / starker Schneefall | dto. | Schnee |
| 77 | Schneegriesel | dto. | Schnee |
| 80 / 81 / 82 | leichte Schauer / Regenschauer / heftige Schauer | dto. | Schauer |
| 85 / 86 | leichte / kräftige Schneeschauer | dto. | Schnee |
| 95 | Gewitter | dto. | Gewitter |
| 96 / 99 | Gewitter mit Hagel / mit starkem Hagel | dto. | Gewitter |

Tabelle als Datei `assets/data/wetter/wmo-codes.de.toml` (Tag/Nacht nach `is_day` bzw. Sonnenstand).

### 7.4 Formulierungsregeln

- **Temperatur:** ganze Grad; −0,4 → „null Grad“ (nie „minus null“); Spanne „zwischen 8 und 14
  Grad“ bzw. „8 bis 14 Grad“; gefühlt nennen bei |gefühlt − gemessen| ≥ 3 K; Wörter: ≥ 30 heiß,
  ≥ 25 sommerlich, 15–24 mild/angenehm, 5–14 kühl, 0–4 kalt, < 0 Frost, Höchstwert < 0 „Dauerfrost“,
  Tiefstwert ≥ 20 „tropische Nacht“.
- **Niederschlag:** Wahrscheinlichkeit gerundet auf 10 %; Wörter: < 10 % „trocken“, 10–29 % „kaum
  Regen“, 30–59 % „Schauer möglich“, 60–79 % „wahrscheinlich Regen“, ≥ 80 % „Regen“; Menge: < 0,2 mm
  „ein paar Tropfen“, 0,2–2 „etwas“, 2–10 „Regen“, > 10 mm/Tag „viel Regen“, ≥ 15 mm/h „Starkregen“;
  Einheit gesprochen „Liter pro Quadratmeter“.
- **Wind (Beaufort):** 0–5 km/h windstill/leiser Zug, 6–19 schwacher Wind, 20–28 mäßig, 29–38
  frisch, 39–49 stark, 50–61 steif, 62–74 stürmisch, 75–88 Sturm, 89–102 schwerer Sturm, 103–117
  orkanartig, ≥ 118 Orkan; Böen nennen ab 40 km/h oder 20 km/h über dem Mittelwind, gerundet auf 5;
  Richtung in 8 Wörtern („aus Südwest“).
- **Tagesverlauf:** je Tagesteil (früh, vormittags, mittags, nachmittags, abends, nachts) Klasse
  aus Wettercode + Regenwahrscheinlichkeit; gleiche Nachbarn verschmelzen → höchstens zwei Abschnitte
  („vormittags trocken, ab dem Nachmittag Schauer“).
- **Mehrtagestrend:** Tagesklasse (sonnig, freundlich, wolkig, wechselhaft, Regen, Schnee,
  Gewitter) + Höchstwert; gleiche Folgetage zusammenfassen („bis Mittwoch“, „ab Donnerstag“), max.
  drei Abschnitte; ab Tag 7 „Tendenz“.
- **Zeiten:** „gegen 15 Uhr“ (volle Stunde), „ab etwa 17 Uhr“ (15-Minuten-Raster, gerundet auf
  Viertelstunde); vergangene Tagesteile werden weggelassen.
- **Ort:** Heimatort wird genannt, solange der Anruf ihn nicht schon zweimal genannt hat (danach
  „hier“); fremder Ort immer.
- **Quelle:** am Telefon nur auf Nachfrage (`weather.source`), Datenalter > 1 h immer.

### 7.5 Antwortaufbau (Faktenprioritäten)

Jede Wetterantwort wird aus **Fakten** zusammengesetzt, sortiert nach Priorität; aufgenommen wird,
was ins Wortbudget (Standard ≈ 35 Wörter, Details ≈ 70) passt:

1. Warnung (DWD ≥ Stufe 2 für den gefragten Zeitraum) oder Glätte/Gewitter
2. Antwort auf den gefragten Aspekt (bei „Regnet es?“ zuerst Regen)
3. Temperatur (aktuell bzw. Spanne)
4. Himmel/Niederschlag (Code-Klasse, Verlauf)
5. Wind, wenn bemerkenswert (Böen ≥ 40 km/h)
6. gefühlte Temperatur, UV ≥ 6, Nebel, Schwüle
7. Sonnenstunden, Luftfeuchte, Druck (nur Details)

„Mehr Details“ liefert die nächsten Prioritäten. Vorlagen je Antworttyp gibt es in 2–4 Varianten;
die Wahl ist deterministisch aus `(call_id, turn)` (Tests: fester Startwert).

### 7.6 Warnungen

- **DWD-Stufen:** 1 Wetterwarnung (gelb), 2 markantes Wetter (orange), 3 Unwetter (rot), 4 extremes
  Unwetter (violett) – CAP-Schwere minor/moderate/severe/extreme. Gesprochen: Ereignis (`event_de`,
  Großbuchstaben → normal: „Sturmböen“, „Frost“, „Starkregen“), Gültigkeit („bis heute 22 Uhr“,
  „ab morgen 6 Uhr“), bei Stufe ≥ 3 die Stufe („Unwetterwarnung“).
- **Freitext** (Überschrift, Beschreibung, Handlungsempfehlung) nur auf Nachfrage, bereinigt
  (Steuerzeichen, URLs, Großbuchstaben), max. 300 Zeichen – nie automatisch, nie ungeprüft an ein LLM
  (T20).
- **Hinweis bei Anrufbeginn** (`warn.greeting`): Hintergrundabruf alle 10 min; gilt beim Abnehmen
  eine Warnung ≥ `announce_on_greeting` für den Heimatort, folgt der Begrüßung (gecachte Ansage) ein
  live gesprochener Satz. Ohne aktuelle Warnungsdaten (> 30 min alt) entfällt der Hinweis still.
- **NINA:** Kreis-ARS des Heimatorts; Meldungen der Quelle DWD werden nicht doppelt genannt.

### 7.7 Ratschlagsregeln

Feste, dokumentierte Schwellwerte (`moritz_agent/skills/catalog/advice.py`, Tabelle hier ist die
Spezifikation; Antworten nennen immer den Grund):

| Ratschlag | „Ja“, wenn … | „Nein/Eher nicht“, wenn … |
| --- | --- | --- |
| Schirm | im Zeitraum (Standard: ab jetzt bis 22 Uhr) Wahrscheinlichkeit ≥ 50 % oder Menge ≥ 0,5 mm | sonst; 30–49 % → „Ein kleiner Schirm schadet nicht.“ |
| Jacke | gefühlt < 15 °C oder Regen ≥ 50 % | gefühlt ≥ 20 °C und trocken |
| Wäsche draußen | 4 h trocken (≤ 20 %), Luftfeuchte < 75 %, Temperatur ≥ 10 °C, Wind ≥ 5 km/h | Regen ≥ 30 %, Nebel, Frost |
| Grillwetter | Abend trocken (≤ 20 %), ≥ 15 °C, Böen < 40 km/h | Regen/Gewitter, < 10 °C |
| Fahrrad | Zeitraum trocken (≤ 30 %), Böen < 50 km/h, kein Glatteis, ≥ 0 °C | Gewitter, Glätte, Sturm |
| Laufen | trocken, 5–25 °C, kein Gewitter, Ozon nicht schlecht; beste Stunde = kleinster Strafwert | Hitze ≥ 30 °C mittags, Gewitter |
| Gießen | Regen letzte 3 Tage − Verdunstung (ET0) < −5 mm **und** nächste 24 h < 2 mm | Regen ≥ 5 mm erwartet oder gefallen |
| Rasen mähen | letzte 6 h und nächste 3 h trocken, Luftfeuchte < 85 % | nass, Regen erwartet |
| Scheibe kratzen | Tiefstwert nachts ≤ 0 °C (Luft) oder Bodentemperatur ≤ 0 °C bei klarem Himmel | sonst |
| Sonnencreme | UV-Index ≥ 3 im Zeitraum | UV < 3 |
| Lüften/Fenster | kein Regen ≥ 50 %, Böen < 50 km/h | Sturm, Starkregen |
| Auto waschen | 48 h trocken | Regen in 48 h |
| Badewetter | ≥ 25 °C, sonnig/freundlich, kein Gewitter | sonst |
| Pflanzen rein | Tiefstwert ≤ 2 °C oder Bodenfrost | sonst |
| Heiztag | Tagesmittel < 15 °C | sonst |

Keine medizinischen oder sicherheitskritischen Ratschläge über diese Tabelle hinaus; bei Warnungen
≥ Stufe 3 wird immer zuerst auf die Warnung verwiesen.

### 7.8 Datenalter, Ausfall, offline

- Frisch: keine Angabe. 1–6 h: „Stand von vor zwei Stunden“. > 6 h: wird nicht gesprochen.
- Beginn eines Ausfalls → Status `degraded` (Statusdatei, später Statusseite), Log einmalig, nicht
  je Frage; Rückkehr → `ready`.
- `skills.online = false`: Online-Skills antworten mit einer festen Ansage, Vorabruf aus.
- Der Anruf wartet nie länger als das Budget auf einen Datendienst (§3.5).

## 8. Zeit und Kalender im Detail

### 8.1 Feiertage

- **Hessen** (Hessisches Feiertagsgesetz): Tabelle aus [12 §4](12-fast-paths.md#4-feiertage-hessen-f-15) –
  Neujahr, Karfreitag, Ostermontag, 1. Mai, Christi Himmelfahrt, Pfingstmontag, Fronleichnam,
  3. Oktober, 1. und 2. Weihnachtstag; Oster- und Pfingstsonntag (Sonntage, in Hessen genannt).
- **Alle Länder** (für `holiday.is`/`other_state`): bundesweit + Heilige Drei Könige (BW, BY, ST),
  Internationaler Frauentag (BE, MV), Fronleichnam (BW, BY, HE, NW, RP, SL; teilweise SN/TH),
  Augsburger Friedensfest (nur Stadt Augsburg), Mariä Himmelfahrt (SL; BY in Gemeinden mit
  überwiegend katholischer Bevölkerung), Weltkindertag (TH), Reformationstag (BB, HB, HH, MV, NI, SN,
  ST, SH, TH), Allerheiligen (BW, BY, NW, RP, SL), Buß- und Bettag (SN). Datei
  `assets/data/kalender/feiertage-de.toml` (Regel + Länder + Hinweis), mit Tests gegen die Jahre
  2026–2030 aus einer amtlichen Quelle; Änderungen (neue Feiertage) per PR.
- Ostern: Gaußsche Osterformel (Gregorianisch), bewegliche Tage als Abstand zu Ostern.

### 8.2 Sonderdaten (keine Feiertage)

Heiligabend 24.12., Silvester 31.12., Valentinstag 14.2., Weiberfastnacht (Ostern − 52),
Rosenmontag (− 48), Fastnacht/Faschingsdienstag (− 47), Aschermittwoch (− 46), Gründonnerstag (− 3),
Muttertag (2. Sonntag im Mai), Vatertag = Himmelfahrt, Erntedank (1. Sonntag im Oktober),
Halloween 31.10., Martinstag 11.11., Volkstrauertag (2 Sonntage vor dem 1. Advent),
Buß- und Bettag (Mittwoch vor dem 23.11.), Totensonntag (Sonntag vor dem 1. Advent),
1.–4. Advent (4. Advent = letzter Sonntag vor dem 25.12.), Nikolaus 6.12., Beginn/Ende der
Sommerzeit (zoneinfo), Jahreszeiten (§8.5).

### 8.3 Arbeitstage und Brückentage

- Arbeitstag = Montag–Freitag (`skills.calendar.workdays`, änderbar) ohne gesetzlichen Feiertag des
  Heimat-Bundeslands; Heiligabend und Silvester zählen als Arbeitstag mit Hinweis „halber Tag“ nur auf
  Nachfrage.
- Brückentag = einzelner Arbeitstag zwischen Feiertag und Wochenende (Feiertag am Dienstag → Montag,
  am Donnerstag → Freitag); „langes Wochenende“ = ≥ 3 freie Tage am Stück ohne Urlaubstag.

### 8.4 Schulferien Hessen

- Datei `assets/data/kalender/schulferien-he.toml`: je Schuljahr Herbst-, Weihnachts-, Oster- und
  Sommerferien (Start, Ende), Quelle Hessisches Kultusministerium mit Abrufdatum. Bewegliche
  Ferientage einzelner Schulen sind nicht enthalten (wird so gesagt).
- Fehlt ein Jahr: „Für 2031 habe ich noch keine Ferientermine.“ Der Selbsttest warnt, wenn die Tabelle
  weniger als 12 Monate in die Zukunft reicht (Status `degraded` für `school.*`).
- Andere Länder: KANN, nur wenn jemand die Tabelle pflegt (Standard nein).

### 8.5 Astronomie

- **Sonne:** eigene Rechnung nach NOAA (statt `astral`, siehe 04 Anhang C.2): Dämmerung (bürgerlich), Auf-/Untergang, Mittag, Höhe, goldene
  Stunde; Polarfälle („Dort geht die Sonne heute nicht unter.“).
- **Mond:** Phasen-Zeitpunkte nach Meeus, *Astronomical Algorithms*, Kap. 49 (Genauigkeit wenige
  Minuten), Phasenname aus dem Alter; Auf-/Untergang wie bei der Sonne.
- **Jahreszeiten:** Tagundnachtgleichen/Sonnenwenden nach Meeus Kap. 27 (Genauigkeit ≈ 1 min);
  meteorologische Jahreszeiten fest (1.3., 1.6., 1.9., 1.12.).
- Tests gegen veröffentlichte Werte (Sonnenzeiten Weilburg/Frankfurt für 12 Daten, Mondphasen und
  Jahreszeiten 2026–2028) mit Toleranz ± 2 min.

### 8.6 Uhrzeit-Garantie bleibt

Die Uhr wird für jede Zeitantwort **unmittelbar vor der Ausgabe** gelesen (PHONE-24, ADR-017); bei
`time.timestamp_talk` wird die erwartete TTS-Vorlaufzeit addiert. Status zeigt, ob die Systemuhr per
NTP synchron ist (`timedatectl show -p NTPSynchronized`); unsynchron → Zeitantworten mit Zusatz
„laut meiner Uhr, die gerade nicht abgeglichen ist“.

## 9. Sprache: Erkennung und Ausgabe

### 9.1 Hessisch und Umgangssprache (Auszug, Datei `assets/data/sprache/hessisch.toml`)

| gehört (Whisper-Ausgabe) | Standard |
| --- | --- |
| wedder, weder | wetter |
| morsche, morje, morn | morgen |
| heit, heut | heute |
| gestern, gesdern | gestern |
| isses, iss es | ist es |
| hammer, hamma, ham mer | haben wir |
| werds, wirds, werd's | wird es |
| drauße, draus | draußen |
| isch, ich | ich |
| brauch isch | brauche ich |
| en, e (Artikel) | einen / ein |
| schermche, schirmche, knirps | regenschirm |
| kald, kalt | kalt |
| warm, wärm | warm |
| ebbes | etwas |
| net, nit | nicht |
| gell, gelle, odder | *(Füllwort, entfernt)* |
| guude, gude, ei gude wie | *(Gruß → `talk.greeting`)* |
| ade, adschö, tschö, machs gut | *(Abschied)* |
| wie spät isses | wie spät ist es |
| wieviel uhr hammer | wie viel uhr haben wir |
| was isn | was ist denn |
| des | das |
| mer (= wir) | wir |
| viertel acht, dreiviertel acht | 7:15, 7:45 (§4.3) |

Erweiterung mit Moritz’ echten Formulierungen über die Liste nicht erkannter Fragen (§13).
Mindestens 50 Einträge zum Start (SKILL-21); jeder Eintrag hat einen Test.

### 9.2 Spracherkennung auf Orte und Zahlen trimmen

- `phone.stt.initial_prompt` (heute „Nikita, Moritz, Hessen, Frankfurt.“) wird um Heimatort und
  Fachwörter erweitert: „Nikita, Moritz, Weilburg, Limburg, Lahn, Wetzlar, Hessen, Wetter,
  Postleitzahl, Grad.“ – **gemessen** mit `./test-1.sh bench` und dem Satzkorpus, weil ein langer
  Prompt Halluzinationen fördern kann. faster-whisper kennt zusätzlich `hotwords`; Vergleich beider
  Varianten in P1-29, Gewinner wird Standard.
- PLZ-Varianten im Korpus: „35781“, „35 781“, „3 5 7 8 1“, „drei fünf sieben acht eins“,
  „fünfunddreißig sieben einundachtzig“, „fünfunddreißigtausendsiebenhunderteinundachtzig“,
  „Postleitzahl 35781“.
- Ortsnamen-Varianten: „Weil Burg“, „Weilborg“, „Weilburg an der Lahn“, „Limburg a. d. Lahn“,
  „Limburg Lahn“, „Wetzler“, „Gießen“/„Giesen“.

### 9.3 Aussprache (textnorm-Erweiterungen, P1-29)

| Text | gesprochen |
| --- | --- |
| −3 °C, -3 Grad (Minuszeichen U+2212 und Bindestrich) | minus drei Grad |
| 12–15 °C, 12 bis 15 Grad | zwölf bis fünfzehn Grad |
| 2,5 l/m², 2,5 mm | zweieinhalb Liter pro Quadratmeter |
| 1012 hPa | tausendzwölf Hektopascal |
| 70 km/h, Bft 7 | siebzig Kilometer pro Stunde, Windstärke sieben |
| 18 µg/m³ | achtzehn Mikrogramm pro Kubikmeter |
| 4,2 ct/kWh | vier Komma zwei Cent pro Kilowattstunde |
| 1,729 € (Sprit) | ein Euro dreiundsiebzig (auf Cent gerundet) |
| 06:12 Uhr, 6.12 Uhr | sechs Uhr zwölf |
| 1,42 m (Pegel) | ein Meter zweiundvierzig |
| UV-Index 6 | U-V-Index sechs |
| PLZ 35781 | Postleitzahl drei fünf sieben acht eins (Renderer schreibt Ziffern aus) |
| DWD | Deutscher Wetterdienst (nie als Abkürzung ausgeben) |
| NNW, SW | Nordnordwest, Südwest (Renderer schreibt aus) |

Ausspracheliste `assets/data/sprache/aussprache.toml` (Textersetzungen vor Piper, z. B. „Open-Meteo“
→ „Open Meteo“, „Böen“ prüfen), festgelegt per Hörtest mit 30 Testsätzen (`./test-1.sh speak`).
Die veraltete Bemerkung über CosyVoice im Modulkopf von `textnorm.py` wird dabei korrigiert.

### 9.4 Länge, Variation, Sprechtempo

- Standard ≤ 3 Sätze, ≈ 35 Wörter; Listen max. 3 Elemente, Rest auf Nachfrage („Soll ich weitere
  nennen?“ nur bei > 3).
- 2–4 Formulierungsvarianten je Antworttyp (deterministisch je Anruf/Runde).
- Sprechtempo/Lautheit je Anruf (`talk.slower` …) gelten für alle folgenden Live-Sätze; gecachte
  Ansagen bleiben unverändert.

## 10. Konfiguration

Neue Sektion `[skills]` in `config/moritz-agent.example.toml` (dokumentiert, Defaults = Plan). Die
bisherige Sektion `[fastpaths]` wird weiter gelesen (`enabled` → `skills.enabled`, `state` →
`skills.home.state`) und beim Start mit einem Hinweis im Log gemeldet; entfernt wird sie frühestens
mit 1.0.

```toml
[skills]
enabled = true                      # false: nur die Grundfunktionen (Uhrzeit, Datum, Abschied)
disabled = []                       # einzelne Skills/Gruppen abschalten, z. B. ["news", "fuel", "fun"]
online = true                       # false: keine Netzabrufe; Online-Skills sagen ehrlich ab
http_connect_timeout_s = 1.5
http_timeout_s = 3.0
cache_dir = "data/cache/skills"
max_sentences = 3
answer_variation = true             # leicht wechselnde Formulierungen
store_misses = true                 # nicht erkannte Fragen 24 h merken (nur wenn storage.store_transcripts)

[skills.home]
postal_code = "35781"
name = "Weilburg"
state = "HE"                        # Feiertage/Ferien (ersetzt fastpaths.state)
# latitude = 50.48                  # nur zum Überschreiben des Gazetteer-Werts
# longitude = 8.26
region_places = ["Limburg an der Lahn", "Wetzlar"]

[skills.time]
spoken_style = "digital"            # "digital" = „19 Uhr 12“, "umgangssprachlich" = „Viertel nach sieben“ (nur glatte Viertel)
quarter_dialect = true              # „viertel acht“ = 7:15 verstehen

[skills.calendar]
workdays = [1, 2, 3, 4, 5]          # ISO-Wochentage

[skills.weather]
provider = "open-meteo"             # nur Open-Source-Dienste mit freien Daten (§7.1)
fallback_provider = "brightsky"     # "" = kein Rückfall
open_meteo_url = "https://api.open-meteo.com"     # eigene Open-Meteo-Instanz möglich (AGPL-3.0)
brightsky_url = "https://api.brightsky.dev"       # eigene Bright-Sky-Instanz möglich (MIT)
model = "best_match"                # oder "icon_seamless"
forecast_days = 10                  # 1 … 16
past_days = 3
coordinate_decimals = 2             # ≈ 1 km
cache_current_minutes = 10
cache_forecast_minutes = 30
max_stale_hours = 6
prefetch_home = true
prefetch_interval_minutes = 30
mention_source = "on_request"       # "always" | "first" | "on_request"

[skills.warnings]
enabled = true
sources = ["dwd", "nina"]
announce_on_greeting = "severe"     # "off" | "moderate" | "severe" | "extreme"
refresh_minutes = 10

[skills.pollen]
enabled = true
dwd_partregion = "Nordhessen und hessische Mittelgebirge"   # oder "Rhein-Main"
allergens = []                      # z. B. ["Birke", "Gräser"]: nur diese nennen

[skills.air]
enabled = true

[skills.advice]
enabled = true

[skills.water]
enabled = true
river = "LAHN"
station = "auto"                    # PEGELONLINE-Name/UUID oder "auto" (nächster Pegel)

[skills.waste]
enabled = false
ics_url = ""                        # iCal-Link des Abfallkalenders (nur https)
ics_file = ""                       # oder Datei unter data/

[skills.money]
currency = true                     # EZB-Kurse
electricity = true                  # Börsenstrompreis
bidding_zone = "DE-LU"
fuel = false                        # braucht tankerkoenig_api_key in passwords.txt [optional_services]
fuel_type = "e10"                   # "e5" | "e10" | "diesel"
fuel_radius_km = 5

[skills.football]
enabled = false
team = "Eintracht Frankfurt"
league = "bl1"

[skills.news]
enabled = false
max_headlines = 3

[skills.notes]
enabled = false
retention_days = 30

[skills.spelling]
alphabet = "din5009"                # oder "traditionell"

[skills.fun]
enabled = true

[skills.timer]
enabled = true
max_minutes = 15
```

Neuer optionaler Schlüssel in `passwords.txt`, Abschnitt `[optional_services]` (nur zeilenweise
angehängt, CFG-09): `tankerkoenig_api_key`. Er wird nie geloggt; da Tankerkönig ihn als URL-Parameter
erwartet, protokolliert der HTTP-Client grundsätzlich **keine Query-Strings** (LOG-02).

## 11. Daten im Repository

| Datei | Inhalt | Quelle / Lizenz | Größe (Schätzung) | Erzeugung |
| --- | --- | --- | --- | --- |
| `assets/data/geo/de-postcodes.tsv` | PLZ, Ort, Land, Kreis, lat, lon | GeoNames Postal Codes DE, CC BY 4.0 | ≈ 1 MB | `scripts/build_geodata.py` |
| `assets/data/geo/de-places.tsv` | bewohnte Orte DE mit Einwohnern, Ortsteil → Gemeinde, Kölner Phonetik | GeoNames DE, CC BY 4.0 | ≈ 3–4 MB | dto. |
| `assets/data/geo/world-cities.tsv` | Städte ≥ 15.000 Einwohner, deutscher Name, Land, Zeitzone, lat, lon | GeoNames cities15000, CC BY 4.0 | ≈ 2 MB | dto. |
| `assets/data/geo/aliases.de.toml` | eigene Aliasse („Malle“ → Palma, „Mainhattan“ → Frankfurt am Main, Länder → Hauptstadt; die Antwort nennt dann den Ort: „In Paris …“) | eigen | klein | Hand |
| `assets/data/kalender/feiertage-de.toml` | Feiertagsregeln je Land | eigen (aus Gesetzen) | klein | Hand + Tests |
| `assets/data/kalender/schulferien-he.toml` | Ferien Hessen | Hessisches Kultusministerium | klein | Hand, jährlich |
| `assets/data/wetter/wmo-codes.de.toml` | Wettercodes → Deutsch | eigen | klein | Hand |
| `assets/data/sprache/hessisch.toml`, `aussprache.toml` | Dialekt, Aussprache | eigen | klein | Hand |
| `assets/data/buchstabiertafel.toml` | DIN 5009:2022 + traditionell | Namen aus der Norm (Liste der Städte, keine Normtexte) | klein | Hand |
| `assets/data/einheiten.toml`, `waehrungen.de.toml` | Einheiten, Währungsnamen | eigen | klein | Hand |
| `assets/data/sprueche.de.toml` | eigene Witze/Sprüche | eigen (MSOL) | klein | Hand |

- GeoNames-Dateien sind **mitgelieferte Fremddaten** wie `assets/models/`: nicht von Hand ändern,
  nur per Skript neu erzeugen; Herkunft, Datum und SHA-256 der Rohdaten in `third_party/VENDORED.md`,
  Lizenz in `THIRD_PARTY_NOTICES.md` und `LICENSING.md`, Namensnennung auf der Über-Seite (Part 2).
  CLAUDE.md nennt `assets/data/geo/` dann bei den Fremdkomponenten (P1-21).
- Eigene Datendateien bekommen eine Kopfzeile `# SPDX-License-Identifier: LicenseRef-MSOL-1.1`.
- Neue Python-Pakete (ADR-019, `requirements/core.in` + Lock mit Hashes, Lizenz in
  `THIRD_PARTY_NOTICES.md`): **keine** – `astral`, `rapidfuzz` und `icalendar` sind durch eigenen Code
  ersetzt (siehe [04 Anhang C.2](04-part1-umsetzung.md#c2-abweichungen-vom-plan-und-warum)).
- RAM: Gazetteer + Indizes ≈ 40–80 MB (in 06 §2.2 nachgetragen, gemessen in P1-21).

## 12. Datenschutz und Sicherheit

Kurzfassung, Details in [08](08-sicherheit.md) (T19–T24):

- **Was das Haus verlässt:** gerundete Koordinaten (Heimatort ≈ 1 km genau), PLZ/Ortsnamen bei
  Online-Geocoding, Warnzelle/ARS, Pegelname, Währungscodes, Mannschaft. **Nie:** Transkripte,
  Anrufer, Uhrzeit des Anrufs als Bezug, Zugangsdaten (außer dem Schlüssel des jeweiligen Dienstes).
- **Nur HTTPS** an eine feste Liste von Hosts (Allowlist im HTTP-Client, ADR-032); Weiterleitungen nur
  innerhalb der Liste; Antwortgröße max. 2 MB; konfigurierbare URLs (iCal) nur `https://` und nie auf
  private/lokale Adressen (Schutz vor SSRF). Ausnahme: eine **selbst betriebene** Open-Meteo- oder
  Bright-Sky-Instanz, die der Admin ausdrücklich als `open_meteo_url`/`brightsky_url` einträgt, darf im
  LAN liegen (auch `http://` nur dann, wenn ausdrücklich so eingetragen).
- **Antworten von außen sind Daten:** Schema- und Plausibilitätsprüfung, Freitext bereinigt und
  gekürzt, nie als Anweisung an ein LLM (spätere Tool-Ergebnisse in `<tool_result>`-Blöcken, T6).
- **Notizen/Einkaufsliste** (Standard aus): jeder, der intern 999 anruft, kann sie lesen – Hinweis
  in der Doku; Löschen nur nach Rückfrage; Aufbewahrung `retention_days`.
- **Kein neuer eingehender Port**, keine neuen Rechte; Skills laufen im bestehenden Dienst.

## 13. Beobachtbarkeit

- **Log** je Auskunft (Kategorie `[Skill]`, ohne Transkript): `skill=weather.day place=home
  when=2026-10-19 source=open-meteo cache=hit age_s=420 ms=14 score=0.91`.
- **Statusdatei** `data/run/phone-status.json` bekommt `skills`: je Datendienst `state`
  (`ready|degraded|disabled`), `last_ok`, `age_s`, `last_error` (ohne URL-Parameter); Heimatort
  (Name, PLZ, Koordinaten).
- **Nicht erkannte Fragen** (`store_misses`, nur wenn Transkripte gespeichert werden, 24 h):
  `./test-1.sh misses` / `python -m moritz_agent.skills misses` zeigt sie mit dem besten Kandidaten
  und Score – Grundlage für neue Muster und Dialektwörter.
- **Statistik** (ab DB, P1-06): `tool_calls.tool = "skill:<id>"`, Trefferquote, Cache-Quote,
  Latenz je Skill; Statusseite (P1-14) zeigt die letzten 20 Auskünfte ohne Text.
- **CLI für Moritz:** `./test-1.sh ask "wie isses wedder morsche"` (Antwort als Text + optional
  `--play`), `./test-1.sh ask --explain …` (erkannte Absicht, Angaben, Score, Quelle),
  `./test-1.sh providers` (alle Datendienste einmal abrufen, Status), `./test-1.sh prefetch`.

## 14. Tests

| Ebene | Inhalt | CI |
| --- | --- | --- |
| Unit: Text | normalize, Dialekt, Zahlwörter → Ziffern (≥ 150 Fälle inkl. PLZ-Varianten), Kölner Phonetik | ja |
| Unit: Zeit/Kalender | `when.py` gegen Tabelle §4.3 mit fester Uhr; Feiertage aller Länder 2026–2030; Ostern 1900–2100 gegen Referenzliste; Arbeits-/Brückentage; Sommerzeit-Grenzen (25.10.2026 2:00–3:00 doppelt, 28.03.2027 Lücke); Silvester/Neujahr, 29.02.2028 | ja |
| Unit: Orte | Gazetteer (35781 → Weilburg, 60311 → Frankfurt am Main, Ortsteile, mehrdeutige Namen, unscharf/phonetisch, unbekannte PLZ) | ja |
| Unit: Rechnen | Parser (Vorrang, Klammern, Grenzen, Division durch null, keine Codeausführung), Prozent, MwSt, Einheiten | ja |
| Unit: Astronomie | Sonne/Mond/Jahreszeiten gegen Referenzwerte ± 2 min | ja |
| Router-Korpus | `tests/moritz_agent/data/skills.de.jsonl`: **≥ 800 Äußerungen** (je MUSS-Skill ≥ 15, je SOLL ≥ 8, ≥ 150 Negativbeispiele, ≥ 100 Dialekt, ≥ 80 STT-Varianten) mit erwarteter Absicht und Angaben; Trefferquote MUSS-Skills 100 %, Fehlzuordnungen bei Negativbeispielen 0 | ja |
| Golden-Antworten | `skills_golden.de.jsonl`: Äußerung + feste Uhr + Fixture → exakter Antworttext (Variation mit festem Startwert) | ja |
| Provider | aufgezeichnete Antworten (`tests/moritz_agent/data/http/…`) für drei Wetterlagen (Sommer/Gewitter, Herbst/Regen-Sturm, Winter/Frost-Schnee) + Fehlerfälle (Timeout, 429, 500, kaputtes JSON, fehlende Felder, unplausible Werte) über `httpx.MockTransport` – keine neue Test-Abhängigkeit | ja |
| Dialog | Folgefragen, Rückfragen, Kontextablauf, „Mehr Details“, Abbruch beim Auflegen | ja |
| Latenz | Router + Offline-Skill p95 ≤ 20 ms über den Korpus; Gazetteer-Laden ≤ 300 ms | ja |
| Netz (Schema-Wächter) | echte Abrufe aller Dienste, prüfen nur Schema/Plausibilität (`@pytest.mark.network`) | nein (manuell/wöchentlich) |
| Telefon Ende-zu-Ende | `./test-1.sh call --fixtures tests/…/http "Wie wird das Wetter morgen?" "Und in Limburg?" …` | nein |
| Hörtest | 30 typische Antworten rendern und anhören (Zahlen, Minusgrade, Ortsnamen, Fachwörter) | nein |

Uhr in Tests über das `Clock`-Protokoll (keine neue Abhängigkeit wie freezegun). Testdaten enthalten
keine echten Transkripte von Moritz (personenbezogen) – nur nachgestellte Sätze.

## 15. Latenzbudget

| Schritt | Ziel |
| --- | --- |
| Sprechende → Transkript (vorhanden, Whisper small) | ≈ 0,5–1,5 s (Messung `bench`) |
| Vorverarbeitung + Router + Slots | ≤ 20 ms |
| Offline-Skill / Wetter aus Cache | ≤ 30 ms |
| Wetter frisch aus dem Netz | typisch 0,3–0,8 s, Abbruch 3 s |
| Text → erster Ton (Piper, erster Satz) | ≈ 0,2–0,5 s (Messung `bench`) |
| **Gesamt Sprechende → Antwortbeginn** | **≤ 2 s** aus Cache, **≤ 3 s** mit Netzabruf (NFR-03 ohne LLM) |

## 16. Umsetzungswellen

| Welle | Inhalt | Tickets | Ergebnis am Telefon |
| --- | --- | --- | --- |
| **A – Offline-Grundlage** | Framework, Responder, Vorverarbeitung, Dialekt, Kontext; Zeit, Kalender, Feiertage, Ferien; Rechnen/Umrechnen; kleine Helfer; Gesprächsfunktionen | P1-19, P1-20, P1-26 (offline), P1-28 | „Wie viele Tage bis Weihnachten?“, „Was sind 19 Prozent von 249?“, „Sprich langsamer“, „Buchstabier Weilburg“ |
| **B – Wetter für Weilburg** | Gazetteer + Heimatort; Open-Meteo-Kern mit Cache/Vorabruf; Wetter-Skills (MUSS); Aussprache | P1-21, P1-22, P1-29 (Teil) | „Wie wird das Wetter morgen?“ = Weilburg; „…in 60311?“, „Und in Limburg?“ |
| **C – Wetter komplett** | Warnungen (DWD/NINA) + Hinweis nach Begrüßung, Pollen, Luft, UV, Ratschläge, Sonne/Mond/Jahreszeiten, Tagesüberblick, Eieruhr | P1-23, P1-24, P1-25 | „Brauch isch en Schirm?“, „Gibt's Unwetter?“, „Wann geht die Sonne unter?“, „Guten Morgen“ |
| **D – Region und Alltag** | EZB, Strompreis, Lahn-Pegel, Müllabfuhr, Fußball, Sprit, Schlagzeilen, Notizen | P1-26 (online), P1-27 | „Wie hoch steht die Lahn?“, „Welche Tonne kommt morgen?“ |
| **E – Abnahme** | Korpus vollständig, Messungen, Testanruf-Protokoll | P1-29, P1-30 | Abnahme §17 |

Danach (oder parallel ab Welle B) geht es mit dem Sprachmodell weiter (P1-02, P1-05, P1-07, P1-09):
P1-07 übernimmt `skills/tools.py` als erste Tools, P1-09 baut den Agenten **hinter** den Skills ein.

## 17. Abnahme am Telefon

Protokoll `docs/abnahme/sofortauskuenfte-<datum>.md`, Anruf an 999 über die echte Anlage:

| # | Prüfung | Erwartung |
| --- | --- | --- |
| 1 | „Wie viel Uhr ist es?“ / „Welches Datum?“ / „Welche KW?“ | Systemzeit ± 1 min, Datum/KW korrekt |
| 2 | „Wie wird das Wetter?“ (ohne Ort) | Antwort für **Weilburg**, Werte = Open-Meteo-Abruf (gegengeprüft per `./test-1.sh ask --explain`) |
| 3 | „Wie wird das Wetter morgen in sechs null drei eins eins?“ | „Für 60311, das ist Frankfurt am Main: …“ |
| 4 | Folgefragen „Und am Wochenende?“, „Und in Limburg?“, „Mehr Details“ | Kontext korrekt übernommen |
| 5 | Mehrdeutig „Wetter in Neustadt“ | eine Rückfrage, Antwort nach Auswahl |
| 6 | Hessisch: „Wie isses Wedder morsche?“, „Brauch isch en Schirm?“ | richtig erkannt |
| 7 | Netz trennen (Firewall-Regel) → „Wie wird das Wetter?“ | Antwort aus Cache mit Altersangabe bzw. ehrliche Absage, kein Hänger > 3 s |
| 8 | Warnung (Test mit Fixture oder echter Lage) | Hinweis nach der Begrüßung, Details auf Nachfrage |
| 9 | Feiertag/Ferien/Brückentag-Fragen | stimmen mit Tabelle/Gesetz |
| 10 | Sonne/Mond | ± 2 min gegenüber Referenz |
| 11 | Rechnen/Prozent/MwSt/Einheiten | korrekt, sprechbar |
| 12 | 30 Fragen aus dem Korpus am Stück | ≥ 28 richtig, keine falsche Zahl, Latenzen protokolliert |
| 13 | Negativfragen („Um wie viel Uhr fährt der Zug?“, „Das Wetter ist mir egal“) | keine Sofortauskunft, Weitergabe |
| 14 | Log/Status | `[Skill]`-Zeilen ohne Transkript, Statusdatei mit Datendiensten, keine Schlüssel in Logs |

## 18. Ideenspeicher (später oder bewusst nicht)

| Idee | Entscheidung |
| --- | --- |
| Bus/Bahn (RMV, DB) | später mit Schlüssel und Haltestellen von Moritz (Part 7+), eigener Plan |
| Kalender/Termine (CalDAV) | Part 8+ („Tools später: calendar“, 05) |
| Erinnerung/Weckruf per Rückruf | **nein** ohne eigene Freigabe: Nikita ruft nie selbst an (PHONE-10) – **auf Discord als Direktnachricht: ja** ([14 §11](14-discord.md#11-proaktive-nachrichten-und-erinnerungen)) |
| Smart Home („Mach das Licht an“) | **nein** per Telefon (PHONE-46, Caller-ID ist keine Berechtigung) |
| Regenradar „regnet es in 10 Minuten?“ | KANN: Bright-Sky-Radar (DWD RADOLAN) als Nowcasting, nach Welle C |
| Wetterkarte, Diagramme | WebUI (Part 2) aus denselben Wetterpaketen |
| Morgen-Anruf mit Wetter | nein (ausgehend); stattdessen `briefing` bei „Guten Morgen“ und als abonnierbares Morgenbriefing auf Discord (14 §11) |
| Namenstage, Horoskope | Horoskope nein (unseriös); Namenstage KANN mit gepflegter Liste |
| Persönliche Orte („bei Oma“, „im Büro“) | Part 8 (Memory), mit Bestätigung |
| Geburtstage („Wann hat Lisa Geburtstag?“) | Part 8 (Memory) |
| Kino, Öffnungszeiten, Veranstaltungen | später über `web_search`/LLM, kein Skill (keine verlässliche offene Quelle) |
| Wissen („Wie hoch ist der Feldberg?“) | LLM + Websuche (P1-09), kein Skill |
| Eigene Wetterstation/Home Assistant als Quelle | später als Provider-Plugin (lesend) |

## 19. Offene Fragen an Moritz

Bis zur Antwort gilt der Default (eingetragen in [10 §3](10-risiken-offene-fragen.md#3-offene-fragen--neu)):

| # | Frage | Default |
| --- | --- | --- |
| F-18 | Soll Nikita nach der Begrüßung von selbst auf Warnungen hinweisen – ab welcher Stufe? | ja, ab „Unwetter“ (Stufe 3) |
| F-19 | Uhrzeit lieber „19 Uhr 12“ oder umgangssprachlich („Viertel nach sieben“)? | „19 Uhr 12“ |
| F-20 | Pollen: hast du Allergien (nur diese nennen)? Pollenregion Mittelgebirge oder Rhein-Main? | alle Arten, Mittelgebirge |
| F-21 | Müllabfuhr: Link zum Abfallkalender (AWB Limburg-Weilburg) für deine Straße/deinen Stadtteil? | aus |
| F-22 | Fußball: welcher Verein (Eintracht Frankfurt?) – oder gar nicht? | aus |
| F-23 | Lahn-Pegel: welcher Pegel interessiert dich (nächster automatisch)? | automatisch |
| F-24 | „Wetter in der Region“: welche Nachbarorte? | Limburg an der Lahn, Wetzlar |
| F-25 | Spritpreise: willst du einen Tankerkönig-Schlüssel (kostenlos) eintragen? Welche Sorte? | aus, E10 |
| F-26 | Nachrichten-Schlagzeilen am Telefon gewünscht? Welche Quelle? | aus |
| F-27 | Einkaufsliste/Notizen per Telefon gewünscht (jeder interne Anrufer kann sie hören)? | aus |
| F-28 | Soll Nikita die Wetterquelle von sich aus nennen oder nur auf Nachfrage? | nur auf Nachfrage |

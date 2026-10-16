# 12 – Fast-Paths: vordefinierte einfache Infos (F-13)

Moritz: „jaja auf jeden Fall, simple Infos, alle predefined paths.“ Fast-Paths beantworten
eindeutige, einfache Fragen **deterministisch ohne LLM** – schneller (kein Modellaufruf),
und nicht halluzinierbar. Alles, was nicht eindeutig erkannt wird, geht an den normalen
Agent-Loop (AGENT-06, AGENT-10, ADR-025).

## 1. Regeln

1. Erkennung über normalisierten Text (klein, ohne Satzzeichen, Zahlwörter → Ziffern) und
   Muster-Listen pro Fast-Path. Bei Mehrdeutigkeit (zwei Fast-Paths oder Zusatzinhalt wie
   „Um wie viel Uhr fährt der Zug?“) **kein** Fast-Path.
2. Jeder Fast-Path ist ein Tool-Aufruf im Log/DB (`path = fast_path_<id>`), damit er in der
   Statistik sichtbar ist.
3. Werte werden **unmittelbar vor der Sprachausgabe** berechnet (Zeit, Datum).
4. Neue Fast-Paths: Muster + Antwort-Template + Tests (positive und negative Beispiele) in
   `tests/moritz_agent/data/fastpaths.de.jsonl`.

## 2. Katalog Part 1

| ID | Beispiele | Antwort (Template) | Quelle |
| --- | --- | --- | --- |
| `time` | „Wie viel Uhr haben wir?“, „Wie spät ist es?“, „Uhrzeit?“ | „Es ist 19 Uhr 12.“ | Systemuhr, Europe/Berlin |
| `date` | „Welches Datum ist heute?“, „Der Wievielte ist heute?“ | „Heute ist Freitag, der 16. Oktober 2026.“ | Systemuhr |
| `weekday` | „Welcher Tag ist heute?“, „Was für ein Wochentag?“ | „Heute ist Freitag.“ | Systemuhr |
| `datetime` | „Datum und Uhrzeit?“ | „Heute ist Freitag, der 16. Oktober 2026, es ist 19 Uhr 12.“ | Systemuhr |
| `calendar_week` | „Welche Kalenderwoche haben wir?“, „Welche KW?“ | „Wir haben Kalenderwoche 42.“ | ISO-8601-Woche |
| `tomorrow` / `yesterday` | „Welcher Tag ist morgen?“ | „Morgen ist Samstag, der 17. Oktober.“ | Systemuhr |
| `days_until` | „Wie viele Tage bis Weihnachten / Silvester / Neujahr / Wochenende?“ | „Noch 69 Tage bis Heiligabend.“ | Kalender (feste + bewegliche Feiertage, Ostern per Gauß) |
| `holiday_next` | „Wann ist der nächste Feiertag?“, „Ist morgen ein Feiertag?“ | „Der nächste Feiertag in Hessen ist Weihnachten, am Freitag, 25. Dezember.“ | Feiertage **Hessen** (`fastpaths.state = "HE"`, F-15), siehe §4 |
| `daylight_saving` | „Wann wird die Uhr umgestellt?“ | „Die Uhr wird am Sonntag, 25. Oktober, um 3 Uhr auf 2 Uhr zurückgestellt.“ | zoneinfo |
| `calculator` | „Was ist 17 mal 23?“, „Wurzel aus 144“, „20 Prozent von 80“ | „17 mal 23 ist 391.“ | sicherer Ausdrucks-Parser (kein `eval`) |
| `identity` | „Wer bist du?“, „Wie heißt du?“ | „Ich bin Nikita, Moritz’ Telefonassistentin.“ | fest |
| `capabilities` | „Was kannst du?“, „Hilfe“ | „Ich kann dir die Uhrzeit und das Datum sagen, rechnen und im Internet nachschauen …“ | fest, aus aktivierten Tools generiert |
| `status` | „Wie geht’s dir?“, „Läufst du?“ | „Mir geht’s gut. Alle Systeme laufen.“ bzw. ehrliche Störung | Komponentenstatus |
| `goodbye` | „Tschüss“, „Danke, das war’s“, „Auflegen“ | Ansage `goodbye` + Auflegen | PHONE-36 |
| `repeat` | „Was hast du gesagt?“, „Nochmal bitte“ | letzte Antwort erneut abspielen (aus Cache) | Gesprächsverlauf |

## 3. Bewusst **nicht** als Fast-Path

- Wetter, Nachrichten, Preise, Sportergebnisse → `web_search` (aktuelle Daten nötig).
- Sonnenauf-/-untergang → erst mit konfiguriertem Standort (`fastpaths.location`, Part 7).
- Alles mit Seiteneffekten (Licht, Geräte, Anrufe) → nie per Fast-Path (PHONE-46).

## 4. Feiertage Hessen (F-15)

Gesetzliche Feiertage nach dem Hessischen Feiertagsgesetz, berechnet je Jahr (Ostern nach der
Gaußschen Osterformel):

| Feiertag | Datum |
| --- | --- |
| Neujahr | 1. Januar |
| Karfreitag | Ostersonntag − 2 Tage |
| Ostersonntag | beweglich (fällt immer auf einen Sonntag) |
| Ostermontag | Ostersonntag + 1 |
| Tag der Arbeit | 1. Mai |
| Christi Himmelfahrt | Ostersonntag + 39 |
| Pfingstsonntag | Ostersonntag + 49 (Sonntag) |
| Pfingstmontag | Ostersonntag + 50 |
| Fronleichnam | Ostersonntag + 60 (in Hessen gesetzlicher Feiertag) |
| Tag der Deutschen Einheit | 3. Oktober |
| 1. Weihnachtstag | 25. Dezember |
| 2. Weihnachtstag | 26. Dezember |

Heiligabend und Silvester sind keine gesetzlichen Feiertage, werden aber bei `days_until` als
Ziel erkannt. Die Liste wird in P1-09 mit Tests gegen bekannte Jahre (z. B. 2026, 2027)
abgesichert; vor Inbetriebnahme gegen den offiziellen Feiertagskalender des Landes Hessen prüfen.

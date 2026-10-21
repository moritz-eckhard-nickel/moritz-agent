# Abnahmeprotokoll P1-30: Sofortauskünfte am Telefon

Vorlage – für die Abnahme nach `sofortauskuenfte-<datum>.md` kopieren und ausfüllen. Maßgeblich ist
[Plan 13 §17](../plan/13-sofortauskuenfte.md#17-abnahme-am-telefon); die Messung der Latenzen
folgt [09 §4](../plan/09-tests-abnahme.md).

Stand der Entwicklung: **offen** – alle Ergebnisse unten stehen aus. Was die automatischen Tests schon
belegen, steht in der Spalte „Automatisch belegt“; das ersetzt den Anruf nicht, es erklärt nur, wo bei
einem Fehler zuerst zu suchen ist.

## Vorbereitung

1. Stand: `python -m moritz_agent --version`, Commit, Datum, Wer, Maschine (Sophie-1 oder anderer Host).
2. `./test-1.sh check` – SIP-Registrierung und Stimme ✔; Internet erreichbar (für Zeilen 2–5, 8–10).
3. Ortsdaten: `ls assets/data/geo/de-places.tsv` – vorhanden? (Installer-Phase `geodata`; sonst nur die
   Grundmenge, dann können Zeilen 3 und 5 scheitern.)
4. Textpfad zum Gegenprüfen: `./test-1.sh ask --explain "Wie wird das Wetter?"` (zeigt Skill, Slots, Quelle).
5. Netzwächter laufen lassen: `pytest -m network tests/moritz_agent/test_skills_network.py` – alle Dienste
   antworten in der erwarteten Form.

## Prüfungen (Anruf an 999 über die echte Anlage)

| # | Prüfung | Erwartung | Automatisch belegt | Ergebnis | Datum / Wer |
| --- | --- | --- | --- | --- | --- |
| 1 | „Wie viel Uhr ist es?“ / „Welches Datum?“ / „Welche KW?“ | Systemzeit ± 1 min, Datum/KW korrekt | `test_skills_when`, `test_skills_router` (Korpus) | offen | |
| 2 | „Wie wird das Wetter?“ (ohne Ort) | Antwort für **Weilburg**, Werte = Open-Meteo-Abruf (gegengeprüft mit `ask --explain`) | `test_skills_weather` (Fixtures) | offen | |
| 3 | „Wie wird das Wetter morgen in sechs null drei eins eins?“ | „Für 60311, das ist Frankfurt am Main: …“ | `test_skills_places`, `test_skills_router` (Korpus) | offen | |
| 4 | „Und am Wochenende?“, „Und in Limburg?“, „Mehr Details“ | Kontext korrekt übernommen | `test_skills_weather` (Folgefragen) | offen | |
| 5 | Mehrdeutig „Wetter in Neustadt“ | eine Rückfrage, Antwort nach Auswahl | `test_skills_places` | offen | |
| 6 | Hessisch: „Wie isses Wedder morsche?“, „Brauch isch en Schirm?“ | richtig erkannt (Whisper!) | `test_skills_router` (Korpus, nur Text), `test_textnorm` | offen | |
| 7 | Netz trennen (Firewall-Regel) → „Wie wird das Wetter?“ | Antwort aus Cache mit Altersangabe bzw. ehrliche Absage, kein Hänger > 3 s | `test_skills_weather`, `test_skills_providers` (Cache, Ausfall) | offen | |
| 8 | Warnung (Fixture `tests/moritz_agent/data/` oder echte Lage) | Hinweis nach der Begrüßung, Details auf Nachfrage | `test_skills_health` | offen | |
| 9 | Feiertag/Ferien/Brückentag-Fragen | stimmen mit Tabelle/Gesetz | `test_skills_calendar` | offen | |
| 10 | Sonne/Mond | ± 2 min gegenüber Referenz (z. B. DWD, timeanddate.de) | `test_skills_astro` (bekannte Werte) | offen | |
| 11 | Rechnen/Prozent/MwSt/Einheiten | korrekt, **sprechbar** (Hörtest der Aussprache-Liste!) | `test_skills_catalog`, `test_textnorm` | offen | |
| 12 | 30 Fragen aus dem Korpus am Stück | ≥ 28 richtig, keine falsche Zahl, Latenzen protokolliert | `test_skills_router::test_corpus` (803 Äußerungen als Text) | offen | |
| 13 | Negativfragen („Um wie viel Uhr fährt der Zug?“, „Das Wetter ist mir egal“) | keine Sofortauskunft, Weitergabe | `test_skills_router` (Korpus, Negativfälle) | offen | |
| 14 | Log/Status | `[Skill]`-Zeilen ohne Transkript, Statusdatei mit Datendiensten, keine Schlüssel in Logs | `test_redaction`, `test_skills_router` | offen | |
| 15 | Eieruhr: „Stell einen Timer auf eine Minute“ | nach 60 s Signalton und „Die Zeit ist um!“ | `test_state_machine`, `test_dialogue` | offen | |

## Offene Messungen aus P1-29

| Punkt | Wie | Ergebnis |
| --- | --- | --- |
| Whisper `initial_prompt` gegen `hotwords` | dieselben 30 Sätze (Hessisch, Orte, Zahlen) mit beiden Einstellungen aufnehmen, Wortfehlerrate vergleichen | offen |
| Aussprache-Liste (`assets/data/sprache/aussprache.toml`) | Hörtest: Einheiten, Währungen, Abkürzungen, PLZ, „ein/eine“; Einträge nachbessern | offen |
| Gesamtlatenz Sprechende → Antwortbeginn | siehe Tabelle unten | offen |

## Latenz ([09 §4](../plan/09-tests-abnahme.md))

Ziel aus [13 §15](../plan/13-sofortauskuenfte.md#15-latenzbudget): ≤ 2 s aus dem Cache, ≤ 3 s mit Netzabruf.
**Ungemessen** – die Werte kommen aus den `[Skill]`-/Turn-Logzeilen (LOG-03).

| Turn | Pfad | VAD-Ende→STT fertig | Skill | TTS-Anlauf | Gesamt |
| --- | --- | --- | --- | --- | --- |
| 1 | skill:time.now | | | | |
| 1a | skill:weather.day (Cache) | | | | |
| 1b | skill:weather.day (Netzabruf) | | | | |

## Fazit

Abgenommen: ☐ ja ☐ mit Auflagen ☐ nein – Auflagen/Fehler:

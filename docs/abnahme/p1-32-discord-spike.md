# Abnahmeprotokoll P1-32: Discord-Spike (Bot, Befehle, DAVE)

Dieses Protokoll gehört zu [Plan 14 §9.5](../plan/14-discord.md#95-dave-und-rückfallwege-adr-036) und
[ADR-036](../plan/03-entscheidungen.md). Es braucht ein echtes Discord-Konto, einen privaten Test-Server
und Sprachkanal-Verkehr – das lässt sich **nicht** in der Entwicklungsumgebung ohne Netz prüfen. Der
gesamte Code ist so gebaut, dass beide Ausgänge funktionieren (Empfang oder „nur sprechen“); dieses
Protokoll entscheidet, welcher gilt.

Stand der Entwicklung (24.10.2026): **Kandidat gewählt, Live-Test offen.**

- Kandidat ist `zacker150/discord-ext-voice-recv` (Commit `dcf543a`) mit seinem discord.py-Fork, in der
  eigenen Umgebung `runtime/discord-venv` (`scripts/setup-discord-voice.sh`, ADR-036 Stand 24.10.2026).
- Auf PyPI gibt es keine Alternative. Die `libdave`-Bindung ist überflüssig: `davey` entschlüsselt selbst.
- Die Live-Punkte stehen in `./test-3.sh run` → `runtime/test-3/abnahme.md`. Die Tabelle unten bleibt für
  die Detailwerte.

## Vorbereitung

1. Bot nach [../discord-einrichtung.md](../discord-einrichtung.md) einrichten, Server mit einem Textkanal und
   einem Sprachkanal, Moritz als Owner.
2. `./test-1.sh discord check` – alle Zeilen ✔.
3. Kandidaten für den Empfang installieren (immer in eine **Wegwerf-Umgebung**, nicht in `runtime/venv`):
   * `discord-ext-voice-recv` von PyPI (derzeit nur eine Alpha-Fassung) und jeder Fork/PR mit
     DAVE-Entschlüsselung;
   * Python-Bindung an Discords `libdave`, falls vorhanden.

## Kriterien und Ergebnisse

| # | Prüfung | Soll | Ergebnis | Datum / Wer |
| --- | --- | --- | --- | --- |
| 1 | Gateway, Intents, Slash-Befehle, Benutzer-Installation (discord.py ≥ 2.7) | Befehle erscheinen, Antworten kommen, Message Content lesbar | offen | |
| 2 | Sprache **senden** mit DAVE (`davey`) | `/joinvc`, Begrüßung klar hörbar, 10 Min ohne Aussetzer | offen | |
| 3 | Sprache **empfangen** mit DAVE – Kandidat: ______ | Moritz spricht, Whisper erkennt den Satz (Wort-Fehlerrate wie am Telefon) | offen | |
| 4 | … 60 Minuten ohne Abbruch | keine Ausnahmen im Log, Latenz konstant | offen | |
| 5 | … Sprecherwechsel (zweite freigegebene Person spricht) | Audio je Person getrennt zugeordnet | offen | |
| 6 | … Schlüsselwechsel (jemand betritt/verlässt den Kanal) | Gespräch läuft weiter | offen | |
| 7 | … Reconnect (WLAN kurz weg, Sprachserver wechselt) | Anton verbindet sich neu, Sitzung bleibt | offen | |
| 8 | … CPU-Last des Discord-Workers im Gespräch | < 1 Kern im Schnitt; Telefon-Latenz unverändert | offen | |
| 9 | Barge-in: über Antons Antwort sprechen | Anton verstummt ≤ 300 ms, versteht den Satz | offen | |
| 10 | Dürfen Bots echte Sprachnachrichten senden (Flag, Wellenform, Dauer)? | ja/nein; heute senden wir eine OGG-Audiodatei | offen | |
| 11 | Upload-Grenze ohne Boost | tatsächliche Größe notieren (Plan: ≈ 10 MB) | offen | |
| 12 | Wheels für Python 3.12–3.14 (`davey`, PyNaCl) | `pip install --require-hashes -r requirements/discord.lock` ohne Compiler | offen | |
| 13 | RAM während einer Sprachsitzung | Messung (Plan: + ≈ 1–1,5 GB) | offen | |
| 14 | Erste Antwort nach Sprachende | Messung „Sprachende → erster Ton“ im Log (`Runde N: …`) | offen | |

## Entscheidung (nach dem Ausfüllen)

* **A – Empfang stabil:** Kandidat in `requirements/discord.in`/`discord.lock` aufnehmen (PyPI) oder als
  Fremdkomponente `third_party/discord-ext-voice-recv/` mit `VENDORED.md`-Eintrag (ADR-021); die Datei
  `moritz_agent/discord/voice/receive.py` benutzt ihn automatisch. ADR-036 auf „bestätigt“ setzen.
* **B – nicht stabil:** nichts tun – der Sprachkanal läuft im Modus „nur sprechen“ (Text im Chat des
  Sprachkanals und Sprachnachrichten rein, gesprochene Antwort raus). ADR-036 um das Ergebnis ergänzen,
  Spike nach neuen Bibliotheksfassungen wiederholen.

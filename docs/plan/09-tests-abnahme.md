# 09 – Teststrategie und Abnahme

## 1. Testebenen

| Ebene | Werkzeug | Läuft in CI | Inhalt |
| --- | --- | --- | --- |
| Unit | pytest | ja | Config/Secrets, Zeitformat, Fast-Path, Guard, Speakable, Zustandsautomat, Queue, Tool-Validierung, Setup-Helfer |
| Komponenten | pytest + Fakes | ja | Inference-Client gegen Fake-OpenAI-Server, SearXNG-Client gegen Fixture, API mit TestClient, Supervisor mit Fake-Children |
| Integration lokal | pytest `-m integration` | nein | echter KoboldCPP mit kleinem Testmodell, echter SearXNG |
| Audio-Benchmark | `scripts/bench_audio.py` | nein | WER/Latenz STT, TTFA/RTF TTS |
| LLM-Benchmark | `scripts/bench_llm.py` | nein | 40 Fragen, Tool-Call-Validität, Latenz |
| SIP-Spike | `scripts/sip_spike.py` | nein | Registrierung, Audio beidseitig |
| Abnahme | manuell, Protokoll | nein | §3 |
| Shell | shellcheck | ja | `moritz-agent`, `install.sh`, `update.sh`, `moritz-*.sh` |
| Lint/Format | ruff | ja | `moritz_agent/`, `tests/moritz_agent/`, `scripts/` |

CI-Workflow: `.github/workflows/moritz-ci.yaml` (Python 3.12 und 3.13). Die Upstream-
KoboldCPP-Workflows bleiben `workflow_dispatch`-only und laufen nicht automatisch.

Skripte (`install.sh`, `update.sh`, `moritz-install.sh`, `moritz-update.sh`, `test-1.sh`, `scripts/*.sh`, `deploy/lib/*.sh`) sind `shellcheck`-sauber; ihr Verhalten prüfen `tests/moritz_agent/test_installers.py` (echte Läufe gegen einen Fake-Baum mit aufzeichnenden Systembefehlen) und `tests/moritz_agent/test_host_scripts.py` (simulierter Proxmox-Host, siehe `fake_proxmox.py`).

## 2. Testdaten

- `tests/moritz_agent/data/phone_questions.de.jsonl` – Telefonfragen mit erwartetem Pfad
  (`fast_path_time`, `tool:web_search`, `llm_only`, `goodbye`).
- Testsätze Audio: Aufnahme über das echte Telefon (Moritz spricht 30 Sätze, inkl. Zahlen,
  Namen, Umgebungsgeräusch) – Dateien **nicht** ins Repo (Stimme = personenbezogen), nur
  Transkript-Referenzen.
- Test-Secrets: ausschließlich offensichtliche Platzhalter.

## 3. Abnahmeprotokoll Part 1 (= Originalplan §41)

Durchführung auf Sophie-1, Ergebnis in `docs/abnahme/part1-<datum>.md`.

| # | Prüfung | Erwartung | Messwerte | OK |
| --- | --- | --- | --- | --- |
| 1 | LXC + CUDA | `nvidia-smi` im LXC, Modell läuft auf GPU | VRAM belegt, Tokens/s | ☐ |
| 2a | Eigenständigkeit | SearXNG startet aus `third_party/searxng` als Worker von moritz-agent (kein separater Dienst), PJSIP baut aus `third_party/pjproject`; aus dem Netz kommen nur PyPI-Pakete, CUDA-Toolchain, Modelle | – | ☐ |
| 2 | Installer | Ersteinrichtung mit SIP-Vorgaben, Web-Login, Sandbox „später“; zweiter Lauf erhält angepasste Daten (Diff der TXT leer) | Dauer | ☐ |
| 3 | SIP + Routing | REGISTER ok **und** Anruf an 999 klingelt beim Agent (REGISTER allein reicht nicht) | Codec | ☐ |
| 4 | Begrüßung + Audio | Annahme, Begrüßung sofort, Audio beidseitig verständlich | Zeit Abheben → Begrüßung | ☐ |
| 5 | Uhrzeit | Antwort = Systemzeit Europe/Berlin (±1 min), Datum/Sommerzeit korrekt; im Log Tool-Aufruf sichtbar | Latenz | ☐ |
| 6 | Mehrere Runden + Sonderfälle | ≥ 3 Runden im selben Anruf; unverständliche Sprache → Rückfrage; Stille → Nachfrage → Auflegen; Auflegen während Antwort → sauberer Abbruch (Log: Tasks gecancelt); zweiter Anruf → besetzt | alle Turn-Latenzen | ☐ |
| 7 | Websuche | aktuelle Frage → Suchaufruf + Quellen im Log, kurze gesprochene Antwort; SearXNG gestoppt → ehrliche Fehlermeldung | Latenz mit Suche | ☐ |
| 8 | Last + Speicher | LLM, STT, TTS, SearXNG, SIP gemeinsam: kein OOM, kein dauerhafter Swap; RAM/VRAM-Tabelle in 06 §2.2 ausfüllen | RAM, VRAM, Swap | ☐ |
| 9 | SIP-Änderung | Passwort/Registrar in TXT ändern → Reload → Neuregistrierung erst nach Gesprächsende; danach konsistent zurücksetzen | – | ☐ |
| 10 | Update | Update mit eigenen Zugangsdaten: Werte bleiben, neue Felder ergänzt, Dienst + Registrierung wieder oben; keine Secrets in Web/Logs (grep über Logs nach allen Secret-Werten ≥ 8 Zeichen) | Dauer | ☐ |
| 11 | Ohne Sandbox | Sandbox-VM aus → Telefon voll funktionsfähig | – | ☐ |
| 12 | Dauerlauf | 30 Anrufe in Folge, kein Neustart nötig (NFR-04) | Fehlerquote | ☐ |

## 4. Latenz-Messprotokoll (je Turn, aus LOG-03)

| Turn | Pfad | VAD-Ende→STT fertig | LLM erster Token | LLM gesamt | Tools | TTS-Anlauf | Gesamt (Sprechende→Antwortbeginn) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | fast_path_time | | – | – | | | |
| 2 | agent | | | | – | | |
| 3 | agent + web_search | | | | | | |

Feste Geschwindigkeitsversprechen gibt es nicht; die Ziele aus NFR-03 dienen der Bewertung.

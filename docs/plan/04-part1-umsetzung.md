# 04 – Part 1 / v0.1: Umsetzungsplan (Tickets)

Ziel von Part 1: **Ein echter interner Anruf an 999** mit Begrüßung, mehreren
Gesprächsrunden, Uhrzeit-Tool und einfacher Websuche – installiert per `moritz-install.sh`,
aktualisierbar per `moritz-update.sh`, beobachtbar über eine minimale Statusseite.

## Arbeitsweise

- **Risiko zuerst:** Die zwei größten Unbekannten (SIP/Audio mit PJSUA2 und CPU-STT/TTS-
  Latenz) werden als **Spikes** vor dem eigentlichen Ausbau geklärt.
- **Ein Ticket = ein PR** gegen `agent` (Ausnahme: sehr kleine zusammengehörige Tickets).
  PR-Titel: `P1-xx: <Kurzbeschreibung>`.
- **Definition of Done (für jedes Ticket):**
  1. Anforderungs-IDs aus [`01-anforderungen.md`](01-anforderungen.md) im PR genannt und erfüllt.
  2. `ruff check`, `ruff format --check`, `pytest` grün; Shell-Skripte `shellcheck`-sauber.
  3. Neue Konfigurationsschlüssel in `config/moritz-agent.example.toml` dokumentiert.
  4. Keine Secrets in Code, Tests, Logs, Fixtures (Test-Secrets nur offensichtlich falsch,
     z. B. `test-password-123`).
  5. Abweichungen vom Plan → Plan-Dokument im selben PR aktualisiert.
  6. **Kanal-Parität** (ADR-034, DISCORD-12): Eine neue Anton-Funktion ist im selben PR auf allen
     Kanälen nutzbar (Telefon, Discord, später WebUI) – oder die Ausnahme ist in der Matrix
     [14 §6](14-discord.md#6-funktionsumfang-alle-funktionen-auf-allen-kanälen) begründet.
- **Testskript je Ausbaustufe:** Eine große Erweiterung bringt ein neues `test-N.sh` mit `setup` und
  `run`, das alles Bisherige mit testet, ohne Ja/Nein-Fragen ([09 §5](09-tests-abnahme.md#5-testskripte-je-ausbaustufe-test-nsh)).
- Hardware-abhängige Schritte (GPU, SIP-Anlage) werden mit einem **Testprotokoll** im PR
  belegt (Vorlage: [`09-tests-abnahme.md`](09-tests-abnahme.md)).

## Reihenfolge & Abhängigkeiten

```text
P1-00 Repo-Grundlage (dieser PR) ──┬─► P1-03 Config/Secrets ─► P1-04 Supervisor/Logging ─┐
                                    │                                                     │
P1-01 Infrastruktur (manuell) ──────┼─► P1-02 KoboldCPP-Build + Modellwahl ─► P1-05 Inference-Client
                                    │                                                     │
                                    ├─► P1-11 SIP-Spike (PJSUA2) ─────────┐               │
                                    ├─► P1-10 Audio-Spike (VAD/STT/TTS) ──┼─► P1-12 Phone-Worker ◄─┤
                                    │                                     │       ▲               │
                                    └─► P1-08 SearXNG ─► P1-07 Tools ─► P1-09 Agent (Phone-Profil)
P1-06 Storage ─────────────────────────────────────────────────────────────────┘
P1-13 Ansagen ◄─ P1-10            P1-14 API + Status-UI ◄─ P1-04, P1-06
P1-15 Installer ◄─ alle Komponenten   P1-16 Updater ◄─ P1-15   P1-17 systemd/Launcher
P1-18 Abnahme auf Sophie-1 ◄─ alles
```

Empfohlene Abfolge in Wochen-Blöcken (ohne Zeitversprechen):

1. **Block A – Fundament & Spikes:** P1-01, P1-03, P1-11, P1-10, P1-02 (parallel möglich).
2. **Block B – Kernpfad:** P1-04, P1-05, P1-06, P1-08, P1-07, P1-09.
3. **Block C – Telefon komplett:** P1-13, P1-12, P1-14.
4. **Block D – Betrieb:** P1-17, P1-15, P1-16.
5. **Block E – Abnahme:** P1-18.

**Stand 18.10.2026 und neue Reihenfolge (ADR-029):** Telefon (P1-10 … P1-13) und Betrieb
(P1-15 … P1-17) sind ohne Sprachmodell gebaut und laufen bei Moritz. Bevor das Sprachmodell kommt,
wird **Block S – Sofortauskünfte** umgesetzt (Moritz: „bevor wir LLM und richtige Agent-Instanzen
machen“):

```text
P1-19 Skill-Framework ─┬─► P1-20 Zeit & Kalender ─────────────────────────┐
                       ├─► P1-26 Rechnen/Umrechnen/Geld (offline zuerst)  │
                       ├─► P1-28 Helfer & Gesprächsfunktionen             │
                       └─► P1-21 Orte/Heimatort ─► P1-22 Wetter-Kern ─┬─► P1-23 Warnungen, Pollen, Luft
                                                                      ├─► P1-24 Ratschläge
                                                     P1-25 Sonne/Mond ◄┘   P1-27 Region & Alltag
P1-29 Erkennung, Aussprache, Korpus (begleitend ab P1-19) ─► P1-30 Abnahme Sofortauskünfte
danach: P1-02, P1-05, P1-07 (übernimmt skills/tools.py), P1-09 (Agent hinter den Skills), P1-08, P1-14, P1-18
```

**Block D – Discord (ADR-033 … ADR-037, [14](14-discord.md)):** Anton als Discord-Bot mit allen
Funktionen. Startet nach P1-19 mit dem Kanal-Kern (P1-31) und dem Spike (P1-32) und läuft parallel zu
den späteren Wellen von Block S; LLM-Funktionen kommen mit P1-09 automatisch dazu.

```text
P1-19 ─► P1-31 Kanal-Kern ─► P1-32 Spike ─► P1-33 Worker ─┬─► P1-34 Text + Sofortauskünfte ─┬─► P1-38 Proaktiv/Erinnerungen
                                                          ├─► P1-35 Befehle/Benutzer-App    ├─► P1-39 Telefon ↔ Discord
                                                          ├─► P1-41 Einrichtung             └─► P1-40 Admin
                                                          ├─► P1-36 Sprachkanal (/joinvc wie Anruf), P1-37 Sprachnachrichten (nach Spike)
                                                          └─► P1-43 Persönlichkeit + Aktivitäten
                                                                                 alles ─► P1-42 Abnahme Discord
```

Wellen: **A** P1-19, P1-20, P1-26 (offline), P1-28 · **B** P1-21, P1-22 · **C** P1-23, P1-24, P1-25 ·
**D** P1-26 (online), P1-27 · **E** P1-29, P1-30 ([13 §16](13-sofortauskuenfte.md#16-umsetzungswellen)).
P1-03 (Konfiguration) und P1-06 (Speicher) werden nur so weit vorgezogen, wie Block S sie braucht
(`[skills]`-Sektion, Notizen); Skill-Aufrufe landen bis zur Datenbank im Log.

---

## P1-00 – Repo-Grundlage, Rebranding, Plan *(dieser PR)*

- README auf moritz-agent umgestellt, Upstream-README archiviert, GitHub-Templates,
  `THIRD_PARTY_NOTICES.md`, `.gitignore` (Secrets, Laufzeitdaten), `CLAUDE.md`.
- Vollständiger Plan in `docs/plan/`.
- Gerüst: `pyproject.toml`, Paket `moritz_agent/` mit Modul-Stubs, `config/`-Vorlagen,
  Skript-Skelette, systemd-Unit, CI-Workflow `moritz-ci.yaml`.
- Kleine Referenzimplementierungen mit Tests: `passwords.txt`-Parser inkl. `Secret`-Typ
  (CFG-03, CFG-04), Uhrzeit-Formatierung (PHONE-24/ADR-017), Redaction-Helfer (LOG-02),
  CLI `moritz-agent --version` / `check-config`.
- Installer/Updater: Optionen, Phasenliste, `--dry-run`; Phasen selbst brechen mit
  „noch nicht implementiert“ ab (P1-15/P1-16).

## P1-00b – Antworten von Moritz, Branding, Fremdkomponenten im Repo *(PR 2)*

- Antworten auf R1–R12 / F-01–F-13 in alle Plan-Dokumente eingearbeitet (ADR-002, -005,
  -006, -007, -008, -016, -019 aktualisiert; ADR-020 … -025 neu).
- Logo m-agent mit **Scribbles** (LayerNX-Maskottchen), Branding-Regeln, Generator
  `scripts/build_branding.py`; Icons ersetzt, KoboldCpp-Oberflächen und Screenshots entfernt.
- `third_party/searxng` (fertig gebaut, Start aus dem Repo geprüft), `third_party/pjproject`,
  Silero VAD im Repo; Python-Abhängigkeiten als Lock-Dateien mit Hashes in `requirements/`.
- Neue Dokumente: [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md),
  [11-suchoptionen.md](11-suchoptionen.md), [12-fast-paths.md](12-fast-paths.md).

## P1-01 – Infrastruktur Sophie-1 (manuell, dokumentiert)

- **Ziel:** Agent-LXC (Ubuntu 26.04, 16 GB RAM-Limit, 18 Kerne) mit funktionierendem CUDA.
- **Schritte:** exakt nach [`06-infrastruktur.md`](06-infrastruktur.md) Abschnitt 2–4,
  **inklusive NVIDIA-Treiber-Installation auf dem Proxmox-Host** (noch keiner installiert, F-06).
- **Asterisk:** Konfiguration nach [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md)
  einrichten (Moritz kennt den Ist-Stand nicht, F-01/R7).
- **Ergebnis:** ausgefülltes Inventar (`docs/plan/06-infrastruktur.md` → Tabelle
  „Ist-Werte“ ausfüllen, per PR), `nvidia-smi` im LXC, CUDA-Smoke-Test (`llama-bench` oder
  KoboldCPP-Benchmark mit Testmodell).
- **Anforderungen:** NFR-01, NFR-02, NFR-06, INST-02.
- **DoD:** Inventar ausgefüllt; Asterisk-Checkliste (06, Abschnitt 6) beantwortet.

## P1-02 – KoboldCPP-Build im LXC + Modellauswahl

> Seit 24.10.2026 bare metal auf Sophie-1 statt im LXC (ADR-039). Gebaut ist das mit `scripts/setup-koboldcpp.sh`, `scripts/bench_llm.py` und `./test-3.sh` (Anhang C.8).

- **Aufgaben:**
  1. `./koboldcpp.sh rebuild` im LXC ausführen (ADR-015), Dauer/Plattenbedarf messen.
  2. Modell aus ADR-016 (`Qwen3-30B-A3B-Instruct-2507-UD-Q3_K_XL.gguf`) laden, SHA-256
     notieren; `--moecpu N` so justieren, dass ≈ halb VRAM / halb RAM belegt ist und
     ≥ 0,6 GB VRAM frei bleiben.
  3. Benchmark-Skript `scripts/bench_llm.py` (neu): 40 deutsche Telefonfragen aus
     `tests/moritz_agent/data/phone_questions.de.jsonl` (neu), misst Zeit bis erster Token,
     Tokens/s, Tool-Call-Validität, Antwortlänge; Ergebnisse als Markdown-Tabelle.
  4. VRAM/RAM je Modell bei Kontext 4096 (und 8192 informativ) messen.
  5. Startflags festlegen (`--gpulayers`, `--contextsize`, `--jinja` / Adapter,
     `--flashattention`, KV-Quantisierung optional).
- **Ergebnis:** Messtabelle in ADR-016 (Tokens/s, VRAM, RAM, Zeit bis erster Token je N);
  `config/versions.lock` mit SHA-256 des Modells.
- **Anforderungen:** INF-01…05, NFR-02.

## P1-03 – Konfiguration & Zugangsdaten

- **Dateien:** `moritz_agent/config/{secrets.py,settings.py,validate.py,reload.py}`.
- **Aufgaben:**
  1. `secrets.py` (Gerüst vorhanden) vervollständigen: Rechteprüfung/-korrektur (CFG-06),
     Validierung je Sektion (SIP: Host/IP, Port 1–65535, Transport `udp|tcp|tls`;
     web_login: beide leer oder beide gesetzt; sandbox_ssh: nur prüfen wenn `enabled = true`).
  2. `settings.py`: pydantic-Modelle für `config/moritz-agent.toml`
     (Struktur = `config/moritz-agent.example.toml`), Defaults identisch zur Vorlage.
  3. `reload.py`: atomarer Austausch eines `RuntimeConfig`-Snapshots; ungültig → alter
     Snapshot bleibt, Fehler an Status/Log (CFG-05). Auslöser: `SIGHUP`, `POST /api/system/reload`,
     optional Datei-mtime-Polling (Default aus).
  4. Diff-Ermittlung: welche Sektionen haben sich geändert → Ereignis `sip_changed` an
     Phone-Worker (PHONE-08).
  5. `moritz-agent check-config` CLI: validiert beide Dateien, gibt **keine Werte** aus.
- **Tests:** Sonderzeichen/Prozent (`p%40ss%`, `a;b#c`, Umlaute), leere Werte, fehlende
  Sektionen, unbekannte Schlüssel, falsche Rechte, Reload mit ungültiger Datei.
- **Anforderungen:** CFG-01…10, PHONE-08.

## P1-04 – Supervisor, Prozessverwaltung, Logging

- **Dateien:** `moritz_agent/supervisor.py`, `moritz_agent/logging_setup.py`,
  `moritz_agent/process.py` (neu: `ManagedProcess` mit Backoff).
- **Aufgaben:** Startablauf gemäß 02 §4; `ManagedProcess(name, argv, env, health_check,
  backoff=(2, 60))`; Child-stdout/-stderr zeilenweise in Kategorie-Logger; sauberes
  Herunterfahren (SIGTERM → 10 s → SIGKILL; Phone-Worker zuerst, damit BYE gesendet wird);
  freier Port-Finder für Loopback; internes Token; Logging nach journald (stdout) und
  `data/logs/moritz-agent.log` (rotierend, 10 × 10 MB); Redaction-Filter (LOG-02).
- **Tests:** Fake-Child (Python-Skript, das abstürzt) → Neustart mit Backoff; Shutdown-
  Reihenfolge; Redaction.
- **Anforderungen:** PRD-02, INF-08, LOG-01, LOG-02, NFR-04.

## P1-05 – Inference-Client

- **Dateien:** `moritz_agent/inference/{process.py,client.py,queue.py}`.
- **Aufgaben:** KoboldCPP-Start-Argumente aus Settings bauen (ADR-003); Health über
  `/api/v1/model` + `/api/extra/perf`; async OpenAI-Client (httpx) mit Streaming und
  Tool-Calls; Prioritäts-Queue + Preemption (02 §6) inkl. `genkey` und `/api/extra/abort`;
  Timeouts; Fehlerklassen (`InferenceUnavailable`, `InferenceTimeout`, `InferenceAborted`).
- **Tests:** Fake-OpenAI-Server (pytest-Fixture) für Streaming, Tool-Calls, Abort, Queue-
  Priorisierung.
- **Anforderungen:** INF-01…05, INF-08, PHONE-41.

## P1-06 – Storage

- **Dateien:** `moritz_agent/storage/{db.py,migrations/0001_init.sql,repo.py}`.
- **Aufgaben:** SQLite WAL, `busy_timeout`, Migrationsrunner (versioniert, transaktional),
  Schema gemäß 02 §8, Retention-Job für Transkripte (`storage.transcript_retention_days`),
  Backup-Funktion über `sqlite3.Connection.backup` (für Updater).
- **Anforderungen:** STORE-01, STORE-02, UPD-02, UPD-06.

## P1-07 – Tool-Framework + `get_current_time` + `web_search`

- **Dateien:** `moritz_agent/tools/{registry.py,base.py,time_tool.py,web_search.py}`.
- **Aufgaben:** `Tool`-Protokoll (Name, Beschreibung **deutsch**, JSON-Schema, `async run`),
  Validierung der Argumente (jsonschema/pydantic – *umgesetzt mit einem kleinen eigenen Validator, Anhang C.2*), Ergebnisobjekt
  `{ok, data | error, sources?, speakable?}`, Registry mit Profil-Freigaben (PHONE-45),
  Ausgabe-Größenlimit, Protokollierung in `tool_calls`.
  - `get_current_time(kind: "time"|"date"|"datetime")` → nutzt `time_tool.py` (Gerüst
    vorhanden), Zeitzone aus Settings.
  - `web_search(query: str, max_results: int = 5)` → SearXNG-Client (P1-08), gibt Titel,
    URL, Snippet, Domain, Engines zurück; Fehler → `{ok: false, error: "search_unavailable"}`.
- **Anforderungen:** AGENT-03, PHONE-23…25, PHONE-32, SEARCH-02, SEARCH-03, AGENT-08.

## P1-08 – SearXNG-Integration

- **Dateien:** `moritz_agent/research/{searxng_process.py,searxng_client.py}`,
  `config/searxng/settings.yml` (Gerüst vorhanden).
- **Aufgaben:** Installer-Teil (venv mit `requirements/searxng.lock`, Code aus `third_party/searxng`, `granian`), Start als
  `ManagedProcess` mit `SEARXNG_SETTINGS_PATH`, lokaler `secret_key`, Health-Check
  (`/healthz`), Client mit Timeout 6 s, Deduplizierung nach Domain, Sprache `de-DE`,
  `safesearch=0`; Fallback-Kette SearXNG → KoboldCpp-Websuche → Wikipedia (ADR-020,
  [11-suchoptionen.md](11-suchoptionen.md)).
- **Tests:** Client gegen Fixture-JSON; Fallback bei Timeout/leerem Ergebnis; Integrationstest optional (markiert `@pytest.mark.network`).
- **Anforderungen:** SEARCH-01…03, NFR-07.

## P1-09 – Agent Core (Phone-Profil)

- **Dateien:** `moritz_agent/agent/{loop.py,profiles.py,context.py,fastpath.py,guard.py,speakable.py}`,
  `moritz_agent/agent/prompts/phone.de.md`.
- **Aufgaben:** Agent-Loop mit Tool-Calls (max. 3 Schritte, Deadline), Context Manager mit
  Token-Budget (Token-Zählung über `/api/extra/tokencount` oder Heuristik 3,5 Zeichen/Token
  mit 15 % Reserve), **Fast-Path-Katalog** ([12-fast-paths.md](12-fast-paths.md), AGENT-10),
  Uhrzeit-Guard, `speakable.py` (Markdown/URLs/
  Emojis entfernen, Abkürzungen, Zahlen/Datum sprechbar, max. 3 Sätze), Abschiedserkennung
  (PHONE-36), Cancellation per `call_id`.
- **Systemprompt-Entwurf** (`phone.de.md`):

  ```text
  Du bist „Anton“, der Telefonassistent von Moritz. Du sprichst Deutsch und duzt Moritz.
  Deine Antworten werden vorgelesen: Antworte in höchstens zwei bis drei kurzen Sätzen,
  ohne Aufzählungen, ohne Markdown, ohne Links, ohne Emojis.
  Für die aktuelle Uhrzeit oder das Datum rufst du immer das Werkzeug get_current_time auf.
  Nenne niemals eine Uhrzeit ohne dieses Werkzeug.
  Für Wetter, Unwetterwarnungen, Pollen, Sonne und Mond rufst du immer das passende Werkzeug auf
  (get_weather, get_warnings, get_pollen, get_sun_moon) – nie die Websuche. Ohne Ortsangabe gilt
  Weilburg (35781).
  Für aktuelle Ereignisse, Preise, Nachrichten oder alles, was du nicht sicher weißt,
  rufst du web_search auf. Nenne kurz die Quelle, z. B. „laut tagesschau.de“.
  Wenn die Suche fehlschlägt, sag ehrlich, dass du gerade nichts nachschlagen kannst.
  Erfinde keine Fakten. Wenn du etwas nicht verstanden hast, frag kurz nach.
  Du kannst keine Geräte steuern, keine Befehle ausführen und keine Anrufe tätigen.
  ```
- **Tests:** Fast-Path-Erkennung (positive/negative Beispielsätze, inkl. „Um wie viel Uhr
  fährt der Zug?“ = **kein** Fast-Path), Guard, Speakable-Normalisierung, Loop mit Fake-LLM.
- **Nach Block S (ADR-029):** Fast-Paths sind dann Skills (P1-19); der Agent-Loop läuft **hinter**
  dem `SkillResponder` und bekommt die Skill-Tools aus `skills/tools.py`; zusätzlich Wetter-Guard
  (AGENT-11). `prompts/phone.de.md` bekommt die Wetter-Zeile aus dem Entwurf oben erst, wenn diese
  Tools existieren.
- **Anforderungen:** AGENT-01…08, AGENT-10, AGENT-11, PHONE-23…27, PHONE-32, PHONE-45.

## P1-10 – Audio-Spike + Audio-Komponenten (VAD, STT, TTS, Resampling)

- **Spike-Teil (zuerst):** `scripts/bench_audio.py` (neu): 30 deutsche Testsätze (von Moritz
  über das echte Telefon aufgenommen **oder** synthetisch + G.711-Codec-Simulation),
  misst Whisper small (int8, 8 Threads; Vergleich `base`) WER + Latenz + RAM und je
  TTS-Engine (Piper „Hessisch“, espeak-ng) Time-to-first-audio + Real-Time-Factor. Piper ist
  Hauptstimme, espeak-ng Notstimme (PHONE-37, ADR-027).
  **Umgesetzt als** `./test-1.sh bench` (`python -m moritz_agent.phone bench`) – misst auf dem
  Zielrechner Whisper und die Stimme mit vier Beispielsätzen.
- **Komponenten-Teil:** `moritz_agent/phone/audio/{resample.py,vad.py,stt.py,tts.py,buffers.py}`
  mit Interfaces `SpeechToText.transcribe(pcm16_16k) -> Transcript(text, avg_logprob, no_speech_prob)`,
  `TextToSpeech.synthesize(text) -> Iterator[pcm16_16k_chunk]` (satzweise),
  `VoiceActivityDetector.feed(frame) -> Event` (Silero aus `assets/models/vad/`).
  TTS-Engines `piper` und `espeak` mit Rückfallkette (PHONE-37). Modelle werden einmal geladen, Threads konfigurierbar,
  Self-Test beim Start (`./test-1.sh check`).
- **Stand 18.10.2026 – umgesetzt (ADR-027):** `moritz_agent/phone/audio/` mit `pcm.py`
  (Resampling/Lautheit/WAV), `vad.py` (Silero, 512er Fenster), `stt.py` (faster-whisper small
  int8 + Halluzinationsfilter), `textnorm.py` (Zahlen/Datum/Uhrzeit → deutsche Wörter),
  `tts.py` (`TtsService`: Engine-Kette, Platten-Cache für Ansagen, RAM-Cache für Live-Sätze,
  satzweises Streaming), `tts_piper.py`, `tts_espeak.py`, `models.py` (Modell-Manifest/Download
  mit Größen- und SHA-256-Prüfung), `factory.py`. Test mit Fake-Engines in `tests/moritz_agent/`.
  **Offen:** WER-/Latenzmessung und Hörprobe mit den echten Modellen auf dem Zielrechner (R16, R17).

## P1-11 – SIP-Spike (PJSUA2)

- **Ziel:** Minimalprogramm `scripts/sip_spike.py`: registriert als `agent`, nimmt Anruf an,
  spielt eine WAV, nimmt 10 s Gegenrichtung als WAV auf (nur Spike, nur lokal, danach
  löschen), legt auf. Kein LLM, kein STT.
- **Quelle:** `third_party/pjproject` (2.17, im Repo).
- **Klärt:** Build-Rezept (→ Installer), Thread-Modell, `AudioMediaPort`-
  Callbacks in Python (Frame-Größe, Takt, GIL-Last), ausgehandelter Codec mit der Anlage,
  RTP-Portbereich/Firewall, Verhalten bei zweitem Anruf (486), Re-REGISTER nach
  Passwortänderung, Quell-IP-Filter für INVITEs.
- **Ergebnis:** ADR-005 auf `beschlossen`, Build-Rezept in `07-installation-update.md`,
  Testprotokoll inkl. ausgehandeltem Codec.
- **Stand 17.10.2026 – umgesetzt statt Spike:** `scripts/build-pjsip.sh` baut `third_party/pjproject`
  außerhalb des Baums (Kopie unter `runtime/pjsip-build/`) und installiert das Python-Binding
  in die Umgebung; `moritz_agent/phone/sip.py` ist der vollständige Adapter (ein
  Polling-Thread mit `threadCnt=0`, 16-kHz-Konferenzbrücke ohne Soundgerät, G.722 > PCMA >
  PCMU, Registrierung mit exponentiellem Backoff, Quell-IP-Filter 403, zweiter Anruf 486,
  nie ausgehende Anrufe, Medien-Watchdog über RTP-Paketzähler, Neuanmeldung nur ohne Anruf;
  Klingeln vor dem Abnehmen: 180 Ringing, nach 4–8 s (`phone.ring_seconds_min/max`, zufällig) 200 OK, Auflegen während des
  Klingelns wird sauber abgefangen).
  `scripts/sip_testcall.py` ist ein skriptgesteuerter Anrufer (Direktanruf oder über die
  Telefonanlage). **Getestet** per echtem SIP/RTP-Anruf gegen sich selbst (Begrüßung, drei
  Runden, Verabschiedung, 486, 403, Auflegen während der Begrüßung, sauberes Beenden).
  **Offen:** Test gegen die echte Asterisk-Anlage von Moritz (`docs/asterisk-konfiguration.md`
  ist nicht gegen eine laufende Anlage geprüft).
- **Abbruchkriterium:** Funktionieren Audio-Callbacks nach 3 Arbeitstagen nicht stabil →
  Fallback-Optionen aus ADR-005 mit Moritz besprechen.
- **Anforderungen:** PHONE-01…07, PHONE-09, PHONE-40.

## P1-12 – Phone-Worker (Zustandsautomat, Turns, Cancellation)

- **Dateien:** `moritz_agent/phone/{worker.py,sip_account.py,call.py,state_machine.py,media_port.py,prompts.py}`.
- **Aufgaben:** Zustandsautomat gemäß 02 §5.2 (rein, ohne PJSIP testbar: Ereignisse rein,
  Aktionen raus), PJSUA2-Adapter, ein aktiver Anruf (zweiter → 486), INVITE-Quellfilter,
  Turn-Request an Main mit Deadline, Zwischenansage, Stille-/Reprompt-Logik, Abschied,
  Cleanup bei BYE in jedem Zustand, Status-Events an Main, Re-Registrierung bei
  `sip_changed` nur im Zustand IDLE, Metriken je Turn (LOG-03).
- **Tests:** Zustandsautomat vollständig per Unit-Test (inkl. Auflegen in jedem Zustand,
  Stille, 2× unverständlich, Timeout LLM, Suche fehlgeschlagen, zweiter Anruf).
- **Stand 17.10.2026 – umgesetzt:** `state_machine.py` (rein: Ereignisse rein, Aktionen raus),
  `dialogue.py` (`CallSession`, asyncio; Halbduplex mit Schutzzeit, Stille-Erinnerung und
  -Auflegen, „unverständlich“-Zähler, Medien-Watchdog, Latenzlog je Runde, Störungsansage bei
  fehlender Spracherkennung), `worker.py` (Startreihenfolge: Komponenten → Ansagen → SIP;
  SIGHUP-Reload), `responder.py` (Schnittstelle zum späteren Agenten, `TestResponder`),
  `moritz_agent/agent/fastpath.py` (Uhrzeit/Datum/Wochentag/KW …, ADR-025),
  `phone/__main__.py` (`run`, `check`, `speak`, `prompts`, `bench`). Der LLM-Agent selbst
  (P1-06…P1-09) ist nicht Teil davon: der `TestResponder` antwortet mit Fast-Paths und
  „Ich habe verstanden: …“. Tests: `test_state_machine.py`, `test_dialogue.py`.
- **Anforderungen:** PHONE-20…36, PHONE-40, PHONE-41, PHONE-43, PHONE-44, LOG-03.

## P1-13 – Vorbereitete Ansagen

- **Dateien:** `assets/audio/prompts.de.toml` (Gerüst vorhanden), `moritz_agent/phone/prompts.py`.
- **Aufgaben:** Ansagen aus Textkatalog per TTS erzeugen (Installer + bei Text-/Stimmen-
  änderung), Cache `assets/audio/cache/<voice>/<id>-<hash>.wav` (16 kHz mono), Manifest mit
  Hash von Text+Stimme+TTS-Version; Self-Test „alle Pflichtansagen vorhanden“ (ADR-011).
  Begrüßungstext aus `phone.greeting_text` (Default exakt PHONE-21).
- **Stand 18.10.2026 – umgesetzt (PHONE-48):** `announcements.py` (`AnnouncementStore`:
  Pflichtansagen aus dem Cache laden bzw. rendern; Viertelstunden-Uhrzeiten
  optional mit `prompts --warm-times`). Cache: `assets/audio/cache/<hash>.wav`, Schlüssel =
  sha256(Version | Engine | Stimme | Lautheit | Satz). Katalog: `assets/audio/prompts.de.toml`.
- **Anforderungen:** PHONE-21, PHONE-30…35, ADR-011.

## P1-14 – Backend-API, Auth, Statusseite

- **Dateien:** `moritz_agent/api/{app.py,auth.py,routes_system.py,routes_phone.py,routes_chat.py,internal.py}`,
  `frontend/status/{index.html,status.js,style.css}`; Favicon und Logo aus `assets/branding/`,
  Scribbles auf Login-, Lade- und Fehlerseite (PRD-08).
- **Aufgaben:** Endpunkte gemäß 02 §9; Login (ADR-013), Session-Cookie, Rate-Limit
  (5 Fehlversuche / 5 min / IP), API-02-Startprüfung, Statusseite (UI-01), Text-Testpfad
  `/api/chat` (identische Agent-Pipeline wie Telefon, ohne Audio), Admin-Token-Datei.
- **Tests:** Auth-Flows, Rate-Limit, keine Secrets in Status-JSON (Test sucht nach allen
  Werten aus einer Test-`passwords.txt`), Health ohne Auth minimal.
- **Anforderungen:** API-01…03, API-05, UI-01, CFG-06.

## P1-15 – Installer `moritz-install.sh`

- **Spezifikation:** [`07-installation-update.md`](07-installation-update.md) §2.
- **Aufgaben:** Phasen als Funktionen (Gerüst vorhanden), Python-Helfer
  `python -m moritz_agent.setup …` für alle Datei-Schreibvorgänge, Logfile ohne Secrets,
  `--non-interactive`, `--dry-run`, Exit-Codes gemäß 07 §4.
- **Tests:** `shellcheck`; Installer-Helfer per pytest (Ersteinrichtung vs. Bestand,
  Rechte, idempotent); manueller Lauf im frischen LXC (Protokoll).
- **Stand 18.10.2026 – umgesetzt (ADR-028):** `moritz-install.sh` (Phasen preflight, packages, user_dirs,
  code, python_env, pjsip, models, secrets, config, prompts, service, verify, testcall; KoboldCpp/
  SearXNG/TLS folgen mit ihren Tickets), `install.sh` (Proxmox-Host: LXC anlegen, GPU-Geräte,
  Programm kopieren, Installer starten; lokal oder `--remote`), Bibliotheken `deploy/lib/common.sh`
  und `deploy/lib/host.sh`, Programmliste `deploy/payload.txt`, `scripts/setup-env.sh`. Tests:
  `test_installers.py` (echte Läufe gegen einen Fake-Baum mit aufzeichnenden Systembefehlen) und
  `test_host_scripts.py` (simulierter Proxmox-Host). **Offen:** Lauf auf einem echten Proxmox-Host und
  in einem echten Ubuntu-LXC (Protokoll für P1-18); `moritz_agent.setup` (Web-Login/Sandbox-Abfragen)
  kommt mit P1-03/P1-14.
- **Anforderungen:** INST-01…15, CFG-02, CFG-04, CFG-09.

## P1-16 – Updater `moritz-update.sh`

- **Spezifikation:** [`07-installation-update.md`](07-installation-update.md) §3.
- **Aufgaben:** Drain mit Timeout und Verschieben, Backup, Git-Update, venv-Swap,
  bedingter KoboldCPP-Rebuild, TXT-Feldergänzung, DB-Migration, Neustart, Health-Prüfung,
  Rollback.
- **Tests:** Rollback-Szenario (absichtlich kaputter Health-Check), TXT mit eigenen Werten
  bleibt byte-identisch bis auf angehängte neue Felder.
- **Stand 18.10.2026 – umgesetzt (ADR-028):** `moritz-update.sh` (Wartungsmodus über `data/run/drain`,
  Sicherung, neue venv nur bei geänderten Paketen/PJSIP, Austausch, Start + Prüfung, Rollback mit
  Exit 70/71, Verschieben mit Exit 75), `update.sh` (Proxmox-Snapshot, Programm kopieren, Updater
  starten, Exit-Codes durchreichen, alte Snapshots aufräumen). Getestet: Verschieben bei laufendem
  Gespräch, Rollback bei fehlgeschlagenem Start, Benutzerdaten bleiben unverändert, Wartungsmodus im
  Dienst per echtem SIP-Anruf (486). **Anders als geplant:** Quelle ist der kopierte Programmordner
  statt `git fetch` im Container (kein `--channel`); TXT-Feldergänzung und DB-Migration folgen mit
  `moritz_agent.setup` (P1-03) bzw. der Datenbank (P1-14).
- **Anforderungen:** UPD-01…07.

## P1-17 – systemd-Unit + Launcher

- **Dateien:** `deploy/systemd/moritz-agent.service` (Gerüst vorhanden), `moritz-agent` (vorhanden).
- **Aufgaben:** Härtung (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths=`,
  `PrivateTmp`, `ProtectHome`), GPU-Gerätezugriff (`DeviceAllow=/dev/nvidia* rw`), Limits
  (`MemoryMax` informativ unter LXC-Limit), `TimeoutStopSec=30`, `KillMode=mixed`.
- **Stand 18.10.2026:** Unit angepasst (Programmbaum für den Dienst schreibgeschützt, schreibbar nur
  `data/`, `models/`, `runtime/`, Ansagen-Cache; ohne `DevicePolicy`, das übernimmt der LXC), vom Installer
  mit Installationsverzeichnis und Benutzer eingesetzt; `moritz-agent run` startet den Telefon-Worker.
- **Anforderungen:** INST-08, PRD-01.

## P1-18 – Abnahme auf Sophie-1

- Durchführung exakt nach [`09-tests-abnahme.md`](09-tests-abnahme.md) §3 (Abnahmeprotokoll
  = Originalplan §41, Punkte 1–10). Ergebnisprotokoll als `docs/abnahme/part1-<datum>.md`.
- Erst danach: Tag `v0.1.0`.

---

## Block S – Sofortauskünfte (vor dem Sprachmodell)

Plan: [13-sofortauskuenfte.md](13-sofortauskuenfte.md) · Anforderungen SKILL-01 … SKILL-35, AGENT-11,
PHONE-52 · Entscheidungen ADR-029 … ADR-032. Gemeinsame DoD zusätzlich zur allgemeinen DoD oben:
Korpus-Einträge für jeden neuen Skill (positiv, negativ, Dialekt), Golden-Antworten, `./test-1.sh ask`
beantwortet die Beispiele aus 13 §6, keine Netzabrufe in CI (nur Fixtures), Lizenzeintrag jeder neuen
Datenquelle **vor** dem ersten Abruf.

## P1-19 – Skill-Framework und Sofortauskunft-Responder

- **Dateien:** `moritz_agent/skills/{base,registry,responder,router,context,clock,tools}.py`,
  `skills/text/{normalize,dialect,numbers,phonetic}.py`, `skills/__main__.py`,
  `assets/data/sprache/hessisch.toml`, `moritz_agent/config/settings.py` (Sektion `[skills]`,
  Weiterlesen von `[fastpaths]`), `config/moritz-agent.example.toml`, `test-1.sh` (`ask`, `misses`).
- **Aufgaben:**
  1. Protokolle `Skill`, `Match`, `SkillResult` (13 §3.3); Registry mit Aktivierung/Abschaltung je
     Skill und Gruppe; Hilfe-Text aus aktiven Skills.
  2. Vorverarbeitung (13 §4.1): Normalisieren, Füllwörter, Dialekt-Wörterbuch (≥ 50 Einträge),
     Zahlwörter → Ziffern inkl. Ziffernfolgen/PLZ-Zusammenfassung, Kölner Phonetik.
  3. Router (13 §4.2): Muster + Schlüsselwörter + Ausschlusslisten, Score, Schwellen, Konflikte,
     Kombination von höchstens zwei Skills, STT-Konfidenz-Regel.
  4. `SkillContext` (13 §4.5): Folgefragen, eine Rückfrage, „Mehr Details“, „Woher?“, Ablauf.
  5. `SkillResponder` ersetzt `TestResponder` in `phone/worker.py` (Testantwort bleibt als Rückfall);
     `agent/fastpath.py` wird Fassade auf die Zeit-/Gesprächs-Skills (SKILL-33).
  6. `Clock`-Protokoll; Log `[Skill]` je Auskunft ohne Transkript; Statusdatei-Feld `skills`.
  7. CLI `python -m moritz_agent.skills ask|explain|misses|corpus` und `./test-1.sh ask "…"`
     (`--explain`, `--play`, `--fixtures DIR`).
- **Tests:** Vorverarbeitung (≥ 150 Fälle), Router-Grundkorpus, Kontext/Folgefragen, alle bisherigen
  `test_fastpath.py`-Fälle unverändert grün, Latenz p95 ≤ 20 ms.
- **Anforderungen:** SKILL-01, -02, -07, -20 (Grundgerüst), -21, -27 (Grundstock), -28, -29, -31, -33.

## P1-20 – Zeit- und Kalenderauskünfte

- **Dateien:** `skills/slots/when.py`, `skills/calendar/{holidays,school,workdays,special}.py`,
  `skills/catalog/{time,calendar}.py`, `assets/data/kalender/{feiertage-de,schulferien-he}.toml`,
  `assets/data/geo/aliases.de.toml` (Weltzeit-Städte, falls der Gazetteer noch fehlt).
- **Aufgaben:** Zeitausdrucks-Parser nach 13 §4.3 (inkl. „viertel acht“, Sonderdaten); alle Skills aus
  13 §6.1–6.3 (Uhrzeit, Weltzeit, Zeitumstellung, Datum, Datumsrechnung, KW, Alter, Schaltjahr,
  Sonderdaten, Feiertage aller Länder, Arbeits-/Brückentage, Schulferien Hessen); Ferientabelle aus der
  Quelle des Kultusministeriums mit Abrufdatum; Selbsttest „Ferientabelle reicht < 12 Monate“.
- **Tests:** feste Uhr; Sommerzeit-Grenzen (25.10.2026, 28.03.2027), Jahreswechsel, 29.02.2028;
  Feiertage 2026–2030 gegen amtliche Liste; Ostern 1900–2100; Golden-Antworten.
- **Anforderungen:** SKILL-06, SKILL-15, SKILL-32, PHONE-23, PHONE-24, AGENT-06.

## P1-21 – Orte: Gazetteer, Heimatort, Ortsauflösung

- **Dateien:** `scripts/build_geodata.py`, `assets/data/geo/{de-postcodes,de-places,world-cities}.tsv`,
  `assets/data/geo/aliases.de.toml`, `skills/geo/{gazetteer,geocode,distance}.py`, `skills/slots/where.py`,
  `skills/catalog/geo.py`, `third_party/VENDORED.md`, `THIRD_PARTY_NOTICES.md`, `LICENSING.md`, `CLAUDE.md`.
- **Aufgaben:** GeoNames-Rohdaten mit fester SHA-256 laden und in kompakte TSV umwandeln (reproduzierbar);
  Laden im Hintergrund, Indizes (PLZ, Name, ohne Zusätze, Ortsteil, phonetisch); Auflösung nach 13 §4.4
  (Heimat-Wörter, PLZ, Namen, Mehrdeutigkeit, Ausland, Online-Rückfall über Open-Meteo-Geocoding);
  Heimatort 35781 auflösen und in Status/Log zeigen (13 §5, Gemeindeschlüssel/Ortsteile gegen amtliche
  Quelle prüfen); Skills aus 13 §6.10; neue Abhängigkeit `rapidfuzz` (Lock neu erzeugen, ADR-019). *Umgesetzt ohne `rapidfuzz`: `difflib` + Kölner Phonetik (Anhang C.2).*
- **Tests:** 35781 → Weilburg, 60311 → Frankfurt am Main, unbekannte PLZ, PLZ mit mehreren Orten,
  Ortsteile, „Limburg a. d. Lahn“, „Weilborg“, Frankfurt/Neustadt-Mehrdeutigkeit, Ausland,
  Ladezeit ≤ 300 ms, RAM gemessen (06 §2.2).
- **Anforderungen:** SKILL-03, -04, -05, -30, ADR-031.

## P1-22 – Wetter-Kern (Open-Meteo)

- **Dateien:** `skills/providers/{http,cache,open_meteo}.py`, `skills/render/weather.py`,
  `skills/catalog/weather.py`, `assets/data/wetter/wmo-codes.de.toml`, `assets/audio/prompts.de.toml`
  (`thinking_weather`, `skills_offline`).
- **Aufgaben:** gemeinsamer HTTP-Client nach ADR-032 (Allowlist, Zeitlimits, Größenlimit, User-Agent,
  Backoff, keine Query-Strings im Log); Wetterpaket-Abruf nach 13 §7.2 mit Schema-/Plausibilitätsprüfung;
  RAM- und Datei-Cache mit Stale-Regeln (13 §3.6); Vorabruf für den Heimatort; Renderer nach 13 §7.3–7.5
  (Codes, Rundung, Beaufort, Tagesverlauf, Mehrtagestrend, Faktenprioritäten, Varianten); alle Skills
  aus 13 §6.4/6.5 mit Priorität M; Rückfall-Provider-Schnittstelle (Bright Sky folgt in P1-23);
  Fehlerverhalten 13 §3.7; Quellenangabe auf Nachfrage; Dienst-Adressen `open_meteo_url`/`brightsky_url`
  konfigurierbar (eigene Instanz möglich, SKILL-35).
- **Tests:** Fixtures für drei Wetterlagen + Fehlerfälle über `httpx.MockTransport`; Golden-Antworten
  (Weilburg ohne Ort, PLZ, anderer Ort, Folgefragen, nach 18 Uhr, Tag 8+, Stale-Cache, offline).
- **Anforderungen:** SKILL-02, -03, -08, -13, -14, -22, -25, -26, -34, -35, ADR-030, ADR-032.

## P1-23 – Warnungen, Pollen, Luft, Wetter-Zusatz

- **Dateien:** `skills/providers/{brightsky,dwd,nina}.py`, `skills/catalog/{warnings,health}.py`,
  `moritz_agent/phone/dialogue.py` (Satz nach der Begrüßung).
- **Aufgaben:** Bright Sky (`/alerts` mit Warnzelle, `/current_weather`, `/weather` als Rückfall);
  DWD-Pollenflug-Gefahrenindex (Teilregion aus der aktuellen Datei bestimmen, F-20), UV/Biowetter-Dateien
  bestimmen; NINA-Kreisübersicht (ARS prüfen, Nutzungsbedingungen prüfen); Warnungsstufen und
  Freitext-Bereinigung (13 §7.6); Hinweis nach der Begrüßung (`announce_on_greeting`, PHONE-52);
  restliche Wetter-Skills (S/K) aus 13 §6.5–6.7.
- **Tests:** Fixtures mit Warnungen jeder Stufe, abgelaufenen Warnungen, NINA-Doppelmeldungen,
  Pollen-Stufen inkl. Halbstufen, Rückfall bei Open-Meteo-Ausfall; Dialogtest „Begrüßung + Warnsatz“.
- **Anforderungen:** SKILL-09, -10, -11, -34, PHONE-52.

## P1-24 – Alltagsratschläge

- **Dateien:** `skills/catalog/advice.py`.
- **Aufgaben:** Regeln exakt nach 13 §7.7 (Schwellwerte als Konstanten mit Verweis), Begründung in
  jeder Antwort, Warnung zuerst; Zeitraum-Standard je Ratschlag.
- **Tests:** je Regel Grenzwerte (knapp darüber/darunter) mit synthetischen Wetterpaketen.
- **Anforderungen:** SKILL-12.

## P1-25 – Sonne, Mond, Jahreszeiten

- **Dateien:** `skills/astro/{sun,moon,seasons}.py`, `skills/catalog/astro.py`; neue Abhängigkeit
  `astral` (Apache-2.0). *Umgesetzt als eigene Rechnung in `skills/astro/` (Anhang C.2).*
- **Aufgaben:** Skills aus 13 §6.9; Meeus Kap. 27/49 für Jahreszeiten und Mondphasen; Polarfälle;
  Ort aus P1-21.
- **Tests:** Referenzwerte (12 Daten Weilburg/Frankfurt, Mondphasen und Jahreszeiten 2026–2028, ± 2 min).
- **Anforderungen:** SKILL-16.

## P1-26 – Rechnen, Umrechnen, Geld

- **Dateien:** `skills/slots/quantity.py`, `skills/catalog/{calc,convert,money}.py`,
  `skills/providers/{ecb,energy_charts,tankerkoenig}.py`, `assets/data/{einheiten,waehrungen.de}.toml`.
- **Aufgaben:** sicherer Rechen-Parser (kein `eval`, Grenzen, 13 §6.11); Prozent, MwSt, Trinkgeld,
  Aufteilen, Rabatt; Einheiten-Tabelle („Pfund“ = 500 g); offline zuerst (Welle A). Online (Welle D):
  EZB-Referenzkurse, Börsenstrompreis, Spritpreise nur mit `tankerkoenig_api_key` (zeilenweise in
  `passwords.txt` ergänzbar, nie geloggt).
- **Tests:** Parser-Fuzzing mit festem Startwert (keine Ausnahme, keine Codeausführung), Rundung,
  Einheiten-Rundreisen, Fixtures für EZB/Energy-Charts/Tankerkönig.
- **Anforderungen:** SKILL-17, SKILL-25.

## P1-27 – Region und Alltag

- **Dateien:** `skills/providers/{pegelonline,ics,openligadb,news}.py`, `skills/catalog/{region,notes}.py`;
  neue Abhängigkeit `icalendar` (BSD-2-Clause). *Umgesetzt mit einem kleinen eigenen ICS-Leser (Anhang C.2).*
- **Aufgaben:** Lahn-Pegel (Station aus `stations.json?waters=LAHN` bestimmen, Trend, Kennwerte), Hochwasser
  mit NINA; Abfallkalender (iCal-Link/-Datei, nur `https://`, keine privaten Adressen, Kategorien
  normalisieren); Fußball, Schlagzeilen (Nutzungsbedingungen prüfen, Standard aus); Notizen/Einkaufsliste
  (Standard aus, Bestätigung, Löschen mit Rückfrage, Aufbewahrung).
- **Tests:** Fixtures je Dienst; iCal mit Wiederholungsregeln; SSRF-Schutz (Redirect auf 192.168.x.x
  wird abgelehnt).
- **Anforderungen:** SKILL-18, SKILL-24, SKILL-25.

## P1-28 – Kleine Helfer und Gesprächsfunktionen

- **Dateien:** `skills/catalog/{talk,helpers,fun,timer,briefing}.py`, `assets/data/{buchstabiertafel,sprueche.de}.toml`,
  `moritz_agent/phone/dialogue.py` (Sprechtempo/Lautheit je Anruf, Eieruhr: Stille-Erinnerung pausiert).
- **Aufgaben:** alle Skills aus 13 §6.14/6.15 (Buchstabieren, Zufall, Witze, Eieruhr, Gruß, Danke,
  Tempo, Lautheit, Gesprächsdauer, Datenschutz, Version/Status, Hilfe, Abbrechen, Abschied,
  Tagesüberblick – Wetterteil ab P1-22).
- **Tests:** Zufall mit festem Startwert, Eieruhr mit falscher Uhr, Tempo-Grenzen, Dialogtests.
- **Anforderungen:** SKILL-19, SKILL-20.

## P1-29 – Erkennung, Aussprache, Korpus und Messung

- **Dateien:** `moritz_agent/phone/audio/textnorm.py`, `assets/data/sprache/aussprache.toml`,
  `config/moritz-agent.example.toml` (`phone.stt.initial_prompt`), `tests/moritz_agent/data/skills*.jsonl`,
  `scripts/bench_audio.py`/`./test-1.sh bench`.
- **Aufgaben:** textnorm-Erweiterungen nach 13 §9.3 (Modulkopf korrigieren: CosyVoice ist entfernt);
  Ausspracheliste per Hörtest; Whisper-Bias (`initial_prompt` vs. `hotwords`) mit PLZ-/Ortsnamen-Sätzen
  messen und den Gewinner als Standard setzen; Korpus auf ≥ 800 Äußerungen bringen; Latenzmessung je
  Skill (Cache/Netz) in 09 §4 eintragen.
- **Anforderungen:** SKILL-21, SKILL-22, SKILL-27, NFR-03.

## P1-30 – Abnahme Sofortauskünfte

- Testanruf über die echte Anlage nach [13 §17](13-sofortauskuenfte.md#17-abnahme-am-telefon),
  Protokoll `docs/abnahme/sofortauskuenfte-<datum>.md`; offene Fragen F-18 … F-28 geklärt oder Defaults
  bestätigt; README und `docs/telefon-test-1.md` aktualisiert.

---

## Block D – Discord-Bot

Plan: [14-discord.md](14-discord.md) · Anforderungen DISCORD-01 … DISCORD-47 · Entscheidungen
ADR-033 … ADR-037 · Bedrohungen T25–T32. Gemeinsame DoD zusätzlich: Fake-Discord-Tests ohne Netz,
keine Inhalte/Token im Log (Test sucht den Testtoken), Rollenmatrix getestet, Discord-Ausfall lässt
das Telefon unberührt (Test: Worker beenden während eines Testanrufs).

## P1-31 – Kanal-Kern und Ausgabeprofile

- **Dateien:** `moritz_agent/core/{turn,principal,surface,profiles}.py` (neu), `skills/base.py`
  (`markdown`, `card`, `actions`), `phone/responder.py` (`TurnContext` → Kern-Turn), Storage-Spalte
  `channel` (bzw. Log-Feld bis P1-06).
- **Aufgaben:** Turn-Modell mit `principal`, `channel`, `surface`; Ausgabeprofile `phone`,
  `discord_voice`, `discord_chat`; Skills liefern zusätzlich Markdown, Karte und Folgeaktionen;
  Rückfragen des Kerns als strukturierte Optionen (für Auswahllisten); persönliche Einstellungen je
  Principal (Heimatort-Standard 35781 Weilburg). Telefon verhält sich danach **bit-genau gleich**.
- **Tests:** alle Telefon- und Skill-Tests unverändert grün; Golden-Antworten je Surface.
- **Anforderungen:** DISCORD-12, DISCORD-15, DISCORD-29, ADR-034.

## P1-32 – Discord-Spike (Bot, Befehle, DAVE)

- **Ziel:** auf einem privaten Test-Server klären, bevor gebaut wird: (1) Gateway + Intents +
  Slash-Befehle + Benutzer-Installation mit discord.py ≥ 2.7; (2) **Sprache senden** mit DAVE
  (davey); (3) **Sprache empfangen** mit DAVE – Kandidaten: DAVE-fähige Fassungen von
  `discord-ext-voice-recv`, Python-Bindung an `libdave`; Kriterien: 60 min ohne Abbruch,
  Sprecherwechsel, Schlüsselwechsel (jemand kommt/geht), Reconnect, CPU-Last; (4) dürfen Bots echte
  Sprachnachrichten senden; (5) tatsächliche Upload-Grenze ohne Boost; (6) Wheels für Python 3.12–3.14
  (`davey`, PyNaCl).
- **Ergebnis:** Protokoll im PR, ADR-036 bestätigt oder geändert, Lock-Datei `requirements/discord.lock`.
- **Anforderungen:** DISCORD-23, DISCORD-24, DISCORD-38.

## P1-33 – Discord-Worker: Grundgerüst

- **Dateien:** `moritz_agent/discord/{__main__,worker,client,access,sessions}.py`,
  `moritz_agent/config/{settings,secrets}.py` (`[discord]`), `cli.py` (`moritz-agent run` startet beide
  Worker mit Neustart-Backoff), `config/moritz-agent.example.toml`.
- **Aufgaben:** Verbindung, Wiederverbindung, Intents, Statusdatei `data/run/discord-status.json`,
  Wartungsmodus, Reload mit Token-Wechsel, `nice +5`; Zugriff nach ADR-035 (Rollen, Server-Allowlist mit
  automatischem Verlassen, Unbekannte ignorieren, Rate-Limits); Log `[Discord]` ohne Inhalte;
  Ausgabefilter für Secrets; `allowed_mentions`.
- **Tests:** Rollenmatrix, fremder Server, Bots ignoriert, Rate-Limit, Secret-Filter, Token-Suche in
  Logs/Status, Telefon läuft bei abstürzendem Discord-Worker weiter.
- **Anforderungen:** DISCORD-01, -03, -04, -05, -08, -09, -10, -11, -20, -21, -33, -36.

## P1-34 – Text-Chat und Sofortauskünfte auf Discord

- **Dateien:** `discord/{render,components}.py`, `discord/sessions.py`.
- **Aufgaben:** Antworten in DMs, bei Erwähnung, auf Antworten, in Anton-Threads/-Kanälen und auf
  „Anton, …“; Rendern als Text/Karte mit Quelle, Folgeknöpfe, Auswahllisten für Rückfragen,
  Aufteilen/Datei, Tippanzeige, Reaktionen (✅, 👍/👎-Feedback); ab P1-09: LLM-Antworten gestreamt,
  Websuche mit Quellenlinks, Threads für lange Gespräche; `/hilfe datenschutz`.
- **Anforderungen:** DISCORD-13, -14, -15, -18, -19, -34, -35, -40.

## P1-35 – Slash-Befehle, Kontextmenüs, Autovervollständigung, Benutzer-App

- **Dateien:** `discord/commands/*`, `discord/__main__.py` (`sync-commands`).
- **Aufgaben:** Befehle aus [14 §7](14-discord.md#7-befehle-slash-befehle-kontextmenüs-autovervollständigung)
  für alle aktiven Funktionen, Kontexte (Server/DM/Benutzer-App), Autovervollständigung für Orte aus dem
  Gazetteer, `/joinvc` und `/leavevc`, Kontextmenüs „Anton fragen“ und „Vorlesen“, ephemere Antworten in fremden Servern,
  Registrierung nur bei geändertem Befehlsbaum; `/abo`, `/einstellungen`, `/hilfe`.
- **Tests:** Befehlsbaum gültig (Namen, Längen, Anzahl), nur aktive Funktionen, Interaktion-Fakes.
- **Anforderungen:** DISCORD-02, -16, -17, -29.

## P1-36 – Sprachkanal: `/joinvc` wie ein Anruf

- **Dateien:** `discord/voice/{session,receive,pipeline,playback}.py`; `phone/media.py` (neu:
  Schnittstelle `MediaChannel`), `phone/dialogue.py` und `phone/sip.py` auf `MediaChannel` umgestellt
  (ohne Verhaltensänderung am Telefon); gemeinsame Audio-Bausteine aus `phone/audio/` (VAD, STT, TTS,
  Resampling) als Bibliothek nutzbar.
- **Aufgaben:** `/joinvc`/`/leavevc`, Auto-Join optional, eine Sitzung; Zustände Wartet → Im Gespräch
  → Ruht (14 §9.1): Moritz betritt den Kanal = Anruf angenommen (Begrüßung wie PHONE-21), Verlassen =
  Auflegen, „Tschüss“ = Abschied und gehen, Stille = Ruhe-Modus oder gehen (`on_silence`), Weckwort nur
  zum Aufwecken; keine Sprecherauswahl (Privatserver), Fremde verworfen; Empfang (Ergebnis P1-32) oder
  Modus „nur sprechen“; Barge-in ≤ 300 ms, Zwischenansage, Ansagen aus dem Telefon-Cache; Modelle ab
  `/joinvc` laden, danach entladen; Priorität `VOICE`; RAM- und Latenzmessung (06 §2.2, 09 §4).
- **Tests:** alle `test_dialogue.py`/`test_state_machine.py`-Fälle laufen zusätzlich über einen
  Fake-Sprachkanal (`MediaChannel`); Audio-Kette ohne Netz (Opus ↔ PCM, 48 ↔ 16 kHz, VAD, Unterbrechen);
  Zustandswechsel Betreten/Verlassen/Stille/Ruhe; Live-Protokoll; Telefon parallel unbeeinträchtigt.
- **Anforderungen:** DISCORD-22, -23, -24, -25, -46, ADR-036.

## P1-37 – Sprachnachrichten

- **Dateien:** `discord/voice_messages.py`.
- **Aufgaben:** Empfangen (Grenzen, Dekodieren mit PyAV, Whisper, Transkript sichtbar), Antwort als
  Text und je nach `reply_with_voice` als Sprachnachricht/Audiodatei (OGG/Opus 48 kHz, Wellenform);
  Kontextmenü „Vorlesen“.
- **Anforderungen:** DISCORD-26.

## P1-38 – Proaktive Nachrichten, Erinnerungen, Timer

- **Dateien:** `discord/notify.py`, Planer im Kern (`core/scheduler.py`), Speicher `data/discord/` bzw.
  Tabellen aus 14 §16.
- **Aufgaben:** `/erinnere`, `/timer`, natürliche Sprache („erinnere mich morgen um 8 …“), neustartfest,
  Nachholen ≤ 12 h; Abos Warnungen/Morgenbriefing/Müll/Systemhinweise mit Ruhezeiten und Drosselung;
  Ziel Standardkanal (`notify.target`), Startmeldung im Standardkanal.
- **Tests:** feste Uhr, Sommerzeitwechsel, Neustart dazwischen, Drosselung, Ruhezeit-Ausnahme Unwetter.
- **Anforderungen:** DISCORD-27, -28, -47.

## P1-39 – Telefon ↔ Discord

- **Aufgaben:** `/anrufe` (Status, letzte Anrufe ohne Inhalte), Anrufhinweise per Abo, Themen/Transkript
  nur per `call_summaries`, „schick mir das auf Discord“ am Telefon (Nebenstelle → Discord-ID über
  `phone_extensions`, sonst an den Owner); Präsenz „im Gespräch“.
- **Anforderungen:** DISCORD-30, DISCORD-35.

## P1-40 – Admin-Befehle

- **Dateien:** `discord/admin.py`.
- **Aufgaben:** `/admin status|version|logs|neu-laden|wartung|neustart` nach 14 §13, nur Owner, nur DM/
  ephemeral, Bestätigungsknöpfe, optionale PIN aus `passwords.txt` (`[discord] admin_pin`) mit
  Fehlversuchssperre; Logs redigiert als Datei.
- **Tests:** Owner/Vertraut/Gast, PIN-Sperre, Logs ohne Secrets, Neustart verweigert bei laufendem Anruf.
- **Anforderungen:** DISCORD-31, T30.

## P1-41 – Einrichtung: Installer, `passwords.txt`, `./test-1.sh discord`, Doku

- **Dateien:** `moritz-install.sh` (Phase `discord`), `moritz_agent/setup` (`set-discord-token`,
  `set-discord-channel`, Prüfung gegen die API, App-Infos, Einladungslinks, Kanalauswahl, Avatar/Banner/Bio),
  `config/passwords.template.txt` (`[discord]` mit `bot_token`, `channel_id`, `admin_pin`),
  Updater-`migrate` (Abschnitt/Schlüssel anhängen), `test-1.sh` (`discord token|channel|check|invite|run|say`),
  `scripts/build_branding.py` (Avatar 512 × 512, Banner), `docs/discord-einrichtung.md` (Developer Portal
  Schritt für Schritt, Token-Reset, Datenschutz), `requirements/discord.in`/`.lock`,
  `THIRD_PARTY_NOTICES.md`, `deploy/payload.txt`.
- **Tests:** `test_installers.py`: Phase mit Testtoken über stdin (nie in Argumenten/Log), zweiter Lauf
  unverändert, `--non-interactive` überspringt; Updater hängt `[discord]` an, Bestandswerte
  byte-identisch; shellcheck.
- **Anforderungen:** DISCORD-05, -06, -07, -37, -38, -42, -45, INST-05, CFG-09.

## P1-43 – Antons Discord-Persönlichkeit: süßer Stil und schelmische Aktivitäten

- **Dateien:** `discord/{style,activities}.py`, `assets/data/discord/{stil,aktivitaeten}.de.toml`,
  `discord/commands/` (`/aktivitaet`), LLM-Profil `discord_chat` (Stilzeile, ab P1-09).
- **Aufgaben:** Stil-Renderer nach [14 §8.2](14-discord.md#82-persönlichkeit-anton-ein-bisschen-süß-adr-037)
  mit Ernst-Modus; Aktivitäten nach [14 §8.5](14-discord.md#85-aktivitäten-schelmisch-und-funny-adr-037):
  Grundliste, lagebezogene Aktivitäten (Anruf, Sprachkanal, Nacht, Wetter aus dem Cache, Sonderdaten,
  Wartung, Unwetter), Rotation 7–15 min ohne Wiederholung, Präsenz-Limits, `/aktivitaet neu|aus|an|vorschlag`;
  Bio-Text; `/hilfe datenschutz`-Satz „ich spiele nicht wirklich mit deinen Daten“.
- **Tests:** Stil deterministisch je Nachrichten-ID, nie mehr als 2 Emojis, Zahlen unverändert,
  Ernst-Modus bei Warnungen/Admin/Fehlern; Aktivitäten: Rotation, Vorrang der Lage, keine Wiederholung
  unter 10, Inhaltsprüfung der Liste (keine Vorfall-Wörter wie „hackt“, „gelöscht“, „kaputt“).
- **Anforderungen:** DISCORD-32, -43, -44, ADR-037.

## P1-42 – Abnahme Discord

- Durchführung nach [14 §21](14-discord.md#21-abnahme), Protokoll `docs/abnahme/discord-<datum>.md`;
  offene Fragen F-29 … F-40 geklärt oder Defaults bestätigt; README und `docs/telefon-test-1.md`
  ergänzt.

---

## Anhang A – Ansagenkatalog (Part 1)

| ID | Text | Verwendung |
| --- | --- | --- |
| `greeting` | Hallo Moritz, hier ist Anton. Was kann ich für dich tun? | Anrufbeginn |
| `not_understood` | Entschuldigung, das habe ich nicht verstanden. Kannst du das bitte wiederholen? | Reprompt 1 |
| `not_understood_again` | Ich verstehe dich leider schlecht. Sag zum Beispiel: Wie viel Uhr ist es? | Reprompt 2 |
| `still_there` | Bist du noch da? | Stille |
| `goodbye` | Alles klar, bis bald! | Abschied/Stille-Timeout |
| `thinking` | Moment, ich schaue nach. | Zwischenansage |
| `error_generic` | Ich habe gerade eine technische Störung. Bitte versuch es später noch einmal. | LLM/STT/TTS-Fehler |
| `starting_up` | Ich starte gerade noch. Bitte ruf in einer Minute noch einmal an. | LLM lädt |
| `search_failed` | Die Websuche ist gerade nicht erreichbar, deshalb kann ich das nicht nachschlagen. | optional vorgefertigt |
| `timeout` | Das dauert leider zu lange. Frag mich gern noch einmal. | Deadline überschritten |
| `thinking_weather` | Moment, ich schaue nach dem Wetter. | Wetterabruf ohne Cache-Treffer (P1-22) |
| `skills_offline` | Ich komme gerade nicht an die Daten. Versuch es bitte gleich noch einmal. | Datendienst nicht erreichbar, kein Cache (P1-22) |
| `timer_done` | Die Zeit ist um! | Eieruhr während des Gesprächs (P1-28), davor ein kurzer Ton |
| `voice_join` | Guude, ich bin da. | Anton betritt einen Discord-Sprachkanal, in dem Moritz noch nicht ist (P1-36); kommt Moritz dazu, folgt `greeting` |
| `voice_rest` | Ich bin dann mal still. Sag einfach Anton, wenn du mich brauchst. | Sprachkanal: Ruhe-Modus nach Stille (P1-36) |
| `voice_wake` | Ja? | Sprachkanal: aus dem Ruhe-Modus geweckt (P1-36) |
| `voice_waking` | Einen Moment, ich wache auf. | Sprachmodelle im Discord-Worker werden noch geladen (P1-36) |
| `voice_leave` | Ich bin dann mal weg. Bis bald! | Anton verlässt den Sprachkanal (P1-36) |

## Anhang B – Konfigurationsschlüssel Part 1

Vollständig und kommentiert in [`config/moritz-agent.example.toml`](../../config/moritz-agent.example.toml).

## Anhang C – Umsetzungsstand und Abweichungen (Stand 21.10.2026)

Dieser Anhang ist die Quelle der Wahrheit dafür, was in Part 1 gebaut ist, was davon **nur im Code und
in Tests** belegt ist und was **noch auf echter Hardware oder gegen echte Dienste geprüft** werden muss.
„Gebaut“ heißt: Code und automatische Tests sind grün (`pytest`, `ruff`, `shellcheck`); es heißt nicht,
dass die Abnahme auf Sophie-1 bzw. gegen echte Dienste schon stattgefunden hat.

Letzter Lauf (21.10.2026): `pytest` 2316 bestanden (6 abgewählte Tests brauchen Internet, `-m network`),
`ruff check`, `ruff format --check` und `shellcheck` sauber.

### C.1 Stand je Ticket

| Ticket | Stand | Anmerkung |
| --- | --- | --- |
| P1-00, P1-00b | fertig | Repo-Grundlage, Rebranding, Fremdkomponenten |
| P1-01 | **offen** (manuell) | Sophie-1 bare metal (ADR-039): nur noch der NVIDIA-Treiber von Hand ([`docs/sophie-1-bare-metal.md`](../sophie-1-bare-metal.md)) |
| P1-02 | gebaut, **Messung offen** | `scripts/setup-koboldcpp.sh` (Build), Modelle im Cache `/home/models`, `scripts/bench_llm.py` (`--moecpu` einmessen, 40 Telefonfragen in `tests/moritz_agent/data/phone_questions.de.jsonl`), Installer-Phasen `koboldcpp` und `llm_config`. Die Messtabelle entsteht mit `./test-3.sh run` auf Sophie-1 (`runtime/test-3/llm-bench.md`) |
| P1-03 | gebaut | `config/validate.py`, `reload.py`; Reload atomar mit Diff |
| P1-04 | gebaut | `ManagedProcess` (Backoff, Health), `supervisor.py` startet Telefon und Discord als Kindprozesse |
| P1-05 … P1-09 | gebaut | Inference-Client, Speicher (SQLite), Suche (SearXNG → KoboldCpp → Wikipedia), Tools, Agent-Schleife; **nicht gegen ein echtes Modell geprüft** (siehe C.3) |
| P1-10 … P1-13 | gebaut, läuft bei Moritz | Audio, SIP, Phone-Worker, Ansagen |
| P1-14 | gebaut | Web-Oberfläche (Login, Statusseite), interne API für die Kindprozesse |
| P1-15 … P1-17 | gebaut | Installer, Updater, systemd; neue Phasen `discord` und `geodata` |
| P1-18 | **offen** | Abnahme auf Sophie-1 |
| P1-19 … P1-28 | gebaut | Skill-Framework und alle Sofortauskünfte aus [13](13-sofortauskuenfte.md) |
| P1-29 | gebaut, Messung offen | Aussprache-Liste, Whisper-`initial_prompt`, Korpus mit 803 Äußerungen (`tests/moritz_agent/data/skills.de.jsonl`, erzeugt von `scripts/build_skill_corpus.py`) – **Hörtest und Vergleich `initial_prompt` gegen `hotwords` stehen aus** |
| P1-30 | **offen** | Abnahme: Protokoll [`docs/abnahme/sofortauskuenfte-vorlage.md`](../abnahme/sofortauskuenfte-vorlage.md) ausfüllen; das Netz-Wächter-Testset (`pytest -m network`) läuft nur mit Internet |
| P1-31 … P1-35 | gebaut | Kanal-Kern, Worker, Text-Chat, Befehle; **nie gegen das echte Discord-Gateway gelaufen** (C.3) |
| P1-32 | gebaut, **Live-Test offen** | Empfang über den DAVE-fähigen Fork in `runtime/discord-venv` (`scripts/setup-discord-voice.sh`); ohne ihn „nur sprechen“. Protokoll: Live-Teil von `./test-3.sh run` |
| P1-36 | gebaut | `/joinvc` als Anruf (`DiscordMedia` + `CallSession`); Empfang nur mit optionalem `discord-ext-voice-recv`, sonst „nur sprechen“ |
| P1-37 … P1-41, P1-43 | gebaut | Sprachnachrichten, Erinnerungen und Abos, Telefon ↔ Discord, Admin, Einrichtung, Persönlichkeit |
| P1-42 | **offen** | Abnahme: [`docs/abnahme/discord-vorlage.md`](../abnahme/discord-vorlage.md) |

### C.2 Abweichungen vom Plan (und warum)

**Abhängigkeiten – eigener Code statt Paket** (weniger Fremdcode, keine Lizenzfragen, offline testbar):

| Geplant | Gebaut | Ort |
| --- | --- | --- |
| `astral` (Sonne), Meeus (Mond/Jahreszeiten) | eigene Rechnung nach NOAA/Meeus; Tests gegen bekannte Werte | `skills/astro/` |
| `icalendar` (Müllkalender) | kleiner eigener ICS-Leser (nur `VEVENT`, `RRULE` einfacher Fälle) | `skills/providers/ics.py` |
| `rapidfuzz` (Ortsnamen) | `difflib` (Schwelle 0,88) plus Kölner Phonetik | `skills/geo/gazetteer.py` |
| `jsonschema` (Tool-Argumente) | kleiner Validator für die benutzten Schlüsselwörter | `tools/schema.py` |

Dadurch entfallen `astral`, `icalendar`, `rapidfuzz` und `jsonschema` in `requirements/*.in`; die
Hinweise in [13 §6/§11](13-sofortauskuenfte.md) und ADR-031 („neue Abhängigkeit `rapidfuzz`“) gelten
nicht mehr.

**Daten:** Das Repository enthält nur die handgepflegte **Grundmenge** (`assets/data/geo/seed-places.tsv`,
`plz-bereiche.tsv`, `world-cities.tsv`; Näherungswerte). Die **vollständigen** GeoNames-Listen
(`de-places.tsv`, `de-postcodes.tsv`) erzeugt `scripts/build_geodata.py`; der Installer ruft es in der
neuen Phase `geodata` auf (übersprungen mit `--skip-models`, Fehler sind nicht fatal). In der
Entwicklungsumgebung war GeoNames nicht erreichbar, die Skripte sind deshalb **nur gegen Testdateien
geprüft**. ADR-031 („≈ 6–7 MB im Repository“) ist damit überholt: die Daten kommen beim Einrichten.

**Skill-Zuschnitt:** `weather.place` ist in `weather.*` aufgegangen (Ort optional), `holiday.other_state`
in `holiday.*` (Bundesland als Slot); einige Gruppen heißen anders als in 13 §6 (`gespraech`, `orte`,
`himmel`, `ratschlaege`, `helfer`, …) – die Skill-IDs sind unverändert.

**Prozess- und API-Aufbau:**

- Der Supervisor ([02](02-architektur.md)) startet Telefon- **und** Discord-Worker als `ManagedProcess`
  (Discord mit `nice 5`, Gesundheit über Statusdatei `data/run/discord-status.json`). Ein Absturz des
  Discord-Workers lässt das Telefon unberührt.
- Die Worker sprechen mit dem Hauptprozess über eine **interne Loopback-API** (`/internal/…`, Header
  `X-Internal-Token`, NDJSON-Ströme für gestreamte Antworten) – `api/internal.py`,
  `api/internal_discord.py`. Proaktive Nachrichten laufen über die Tabelle `outbox`, die der
  Discord-Worker abfragt (`pump_once`), nicht über einen Push.
- **API-02:** Ohne Web-Login wird die Oberfläche nicht an eine Netzwerkadresse gebunden, der Start
  **gelingt aber** (nur Loopback, mit Warnung) statt zu verweigern – das Telefon soll auch bei einer
  vergessenen Einstellung laufen.
- TLS-Zertifikat der Weboberfläche erzeugt `api/tls.py` mit `openssl req` (EC prime256v1, Schlüssel
  `0600`) statt mit einer Python-Bibliothek.
- `data/run/phone-status.json` bleibt als Statusdatei des Telefons erhalten (Plan: eine gemeinsame
  Statusdatei); der Hauptprozess führt sie in `/api/system/status` zusammen.

**Telefon:**

- `phone/media.py` führt die Schnittstelle `CallMedia` (Alias `MediaChannel`, ADR-036) ein; `SipMedia`
  und `DiscordMedia` implementieren sie. `CallSession` kennt kein PJSUA2 mehr.
- Neue Ereignisse im Zustandsautomaten: `BargeIn` (Reinsprechen mit `CallSession.barge_in(heard)`),
  `TimerAlarm` (Eieruhr, Ansage `timer_done`) und die Ansage `first_prompt`.
- **Eieruhr am Telefon:** `SkillResult.start_timer` → `Reply.meta["timer"]` →
  `CallSession._arm_kitchen_timer` → Signalton + `timer_done`.
- Whisper bekommt einen `initial_prompt` aus der Kontextliste (Standard ersetzt, in
  `config/moritz-agent.example.toml` dokumentiert); `hotwords` ist **nicht** gemessen.
- `assets/data/sprache/aussprache.toml` (Tabellen `woerter`, `buchstaben`, `ausdruecke`) steuert die
  Aussprache für Piper; Einheiten, Minus, Bereiche, Geldbeträge (Decimal-Rundung), Postleitzahlen
  (Ziffern) und „ein/eine“ nach Geschlecht stehen in `phone/audio/textnorm.py`.

**Discord:**

- Befehle werden **global** registriert (Gilde und global gleichzeitig würden Duplikate erzeugen);
  der Fingerabdruck der Befehlsliste liegt über die interne API in der Datenbank, damit nicht bei jedem
  Start neu synchronisiert wird (`python -m moritz_agent.discord sync-commands` erzwingt es). Befehle für
  inaktive Funktionen werden nicht registriert.
- Sprachnachrichten werden als **OGG-Audiodatei** gesendet; das native „Sprachnachricht“-Flag ist
  nicht verifiziert (nur im Spike prüfbar, C.3).
- `discord.voice`-Überschreibungen aus [14 §9](14-discord.md#9-sprachkanal) (z. B. Schwellen) sind nicht
  umgesetzt; die Werte stehen im Code als Konstanten (`BargeInDetector` ≥ 300 ms usw.).
- `discord-ext-voice-recv` ist **nicht** in `requirements/discord.lock` (DAVE-Entschlüsselung dort
  unverifiziert); wer es testet, installiert es von Hand ([`requirements/README.md`](../../requirements/README.md)).
- ADR-036 behält den Status „vorläufig – Spike P1-32 offen“.
- Das Profilbild `assets/branding/discord-avatar.png` erzeugt `scripts/build_branding.py`.

### C.3 Nicht in der Entwicklungsumgebung prüfbar

Alles hier ist **ungeprüft** und gehört in die Abnahmen P1-18, P1-30, P1-32 und P1-42:

1. Verbindung zum echten Discord-Gateway, Registrierung der Slash-Befehle, Benutzer-Installation,
   Sichtbarkeit von Antworten (ephemeral).
2. Sprachkanal: Senden mit DAVE, **Empfangen** mit DAVE (Spike P1-32), Dauerlauf 60 min.
3. Whisper und Piper in echt: Wortfehlerrate, Hörtest der Aussprache-Liste, `initial_prompt` gegen
   `hotwords`, Latenzen ([09 §4](09-tests-abnahme.md)) – die Latenztabelle ist **ungemessen**.
4. Echte Dienste: Open-Meteo, Bright Sky, DWD, NINA, PEGELONLINE, EZB, Energy-Charts, OpenLigaDB,
   GeoNames – das Netz-Wächter-Testset (`pytest -m network`) prüft Form und Plausibilität, wurde aber
   wegen fehlenden Internets nur als „übersprungen“ gesehen.
5. KoboldCpp-Tool-Call-Vorlage und echtes Sprachmodell (Agent-Schleife hinter den Skills).
6. SIP-Registrierung, Klingeln und Audio auf Sophie-1 (P1-18); der Rückruf (ADR-038, `makeCall` auf die 201) ist nur mit Unit-Tests geprüft.

### C.4 Fehlerdurchgang nach PR #8 (21.10.2026)

Ein Prüfdurchgang über den ganzen Code (Kern, Telefon, Skripte, Sofortauskünfte, Wetter, Discord) hat
rund 50 Fehler gefunden; alle bestätigten sind behoben und mit Regressionstests abgesichert. Was dabei
**Verhalten oder Plan** ändert:

- **Niederschlag und Sonnenschein** liefern Open-Meteo und Bright Sky als Summe des *vorangehenden*
  Intervalls; beim Einlesen werden sie auf den Intervallbeginn verschoben („ab 6 Uhr Regen“ heißt jetzt
  wirklich ab 6 Uhr). Die Test-Fixtures stempeln wie die echten Dienste.
- **Pollen (DWD):** „heute/morgen/übermorgen“ zählen ab `last_update` der Datei; „-1“ heißt „keine
  Vorhersage“ und wird ehrlich so gesagt.
- **Pegel:** Werte älter als 3 Stunden oder „out-dated“ werden nicht als aktuell genannt.
- **Abfallkalender (ICS):** EXDATE, RECURRENCE-ID, mehrere BYDAY, MONTHLY, COUNT/UNTIL, UTC/TZID.
- **Discord-Postausgang:** fehlgeschlagene Nachrichten werden mit wachsender Pause erneut versucht
  (20 s, verdoppelnd bis 30 min, höchstens 8 Versuche ≈ 42 min) statt nach 10 s verworfen; eine
  geschlossene DM geht in den Standardkanal. Systemhinweise höchstens einmal pro Stunde und Ziel.
- **Sprachkanal:** gehört werden nur Owner und Vertraute; eine Antwort läuft mit den geringeren Rechten
  der zuletzt Gehörten (§9.2).
- **Telefon/Hauptprozess:** ein Anruf ohne Ende-Meldung gilt nach `max_call_duration_s` + 5 min als
  beendet; Datei-Überwachung (`config_poll_s`) lädt wie SIGHUP neu und benachrichtigt die Worker.
- **Speicher:** die Aufbewahrungsfrist leert auch Tool-Argumente und -Zusammenfassungen (STORE-02).
- **Installer/Updater:** `passwords.txt` und die Konfiguration werden als root bearbeitet (Besitzer und
  Modus bleiben); `--keep-backups` muss mindestens 1 sein.
- **Rechnen/Kalender:** kaufmännisches Runden (statt „Banker's Rounding“), Mehrwertsteuer „plus/auf/von“
  rechnet drauf, Zeitrechnung über die Zeitumstellung in UTC, Mariä Himmelfahrt (15.8.) als eigener Tag.
- **Orte:** „Wo liegt Gießen?“ beantwortet `geo.region_of` (nur bei sicher erkannten Namen).

### C.5 Nach dem ersten echten Discord-Test (21.10.2026)

- **Owner ohne Eintrag:** Wer die Discord-App besitzt (bzw. das Team der App), gilt automatisch als
  Owner – gelernt beim Anmelden über `application_info()` und an den Hauptprozess gemeldet
  (`PUT /internal/discord/app-owners`). `discord.owner_user_ids` bleibt zusätzlich gültig. Vorher hieß
  es „Mit dir darf ich leider nicht reden“, solange die eigene ID nicht eingetragen war.
- **Aktivitäten mit Verb:** Discord zeigt bei Bots „Spielt …/Hört …“ nicht mehr zuverlässig an. Anton
  setzt deshalb immer einen Benutzerstatus mit dem ganzen Satz („Spielt im Regen“, „Hört dem Rauschen
  der Lahn zu“); die Texte in `aktivitaeten.de.toml` sind darauf angepasst (ADR-037 unverändert).
- **Einrichtung:** Server-Erkennung meldet Fehler beim Abfragen ehrlich und erklärt, dass ein Link als
  *Benutzer-App* den Bot auf keinen Server bringt; `test-2.sh setup` fragt bis zu fünfmal nach.
  Gibt es auf dem Server genau **einen** Text- bzw. **einen** Sprachkanal, wird er ohne Frage gewählt
  (Sprachkanal → `[discord.voice] default_channel_id`).
- **Neu entpackt über den alten Ordner:** `scripts/setup-env.sh` merkt sich einen Fingerabdruck der
  Lock-Dateien (`runtime/venv/.moritz-locks`) und überspringt `pip install`, wenn sie gleich sind;
  Modelle, PJSIP-Build und Ansagen-Cache werden ohnehin wiederverwendet.
- **„Leg auf“ und Rückruf** auf die 201: ADR-038.

### C.6 Keine Emojis mehr (21.10.2026, vorgezogen für Part 2)

Moritz: „alle Emojis entfernen und im Text gegen :) :( :3 usw. austauschen oder halt weglassen“.

- `stil.de.toml` hat nur noch Textsmileys (`[smiley]`, `[smiley_text]`); höchstens **einer** pro
  Nachricht, Kaomojis sind entfallen. `style = "normal"` nimmt auch die Smileys heraus.
- **Emoji-Filter** `discord/style.py: no_emoji()` an der einzigen Ausgangsstelle (`client.kwargs_for`:
  Text, Embed-Titel/-Beschreibung/-Felder/-Fußzeile) und im Status (`Activity.status`) – greift auch für
  Antworten des Sprachmodells und eigene `/aktivitaet`-Sprüche. Das Profil `discord_chat` sagt
  „Benutze keine Emojis.“
- Aktivitäten, Admin-Status (Zustand als Wort statt Farbpunkt), Abo-/Erinnerungs-Titel („Erinnerung“,
  „Achtung: …“), Hilfe- und Einstellungs-Texte ohne Emojis. Anton reagiert nicht mehr mit ✅;
  👍/👎 **von Moritz** auf Antworten zählen weiter (das sind Eingaben, keine Ausgabe).
- Terminal-Ausgaben der Skripte (✔/✘ in `test-2.sh`) bleiben – das sind Prüfzeichen, keine Antworten
  von Anton.

### C.7 Zweiter Live-Test (21.10.2026, 18:30)

- **Telefon-Befehle nur im Gespräch:** „Leg auf“, „sprich langsamer/schneller“, „lauter/leiser“ und „wie
  lange telefonieren wir“ antworten im Text-Chat nur mit einem Hinweis („… geht nur, wenn wir telefonieren
  oder im Sprachkanal reden“) – vorher hieß es im Discord-Chat „Alles klar, ich lege auf“.
- **Rückruf → SIP 403:** Die eigene Anleitung sperrte `[from-agent]` komplett (`Hangup(21)` = 403). Jetzt
  erlaubt `docs/asterisk-konfiguration.md` §3/§5 genau die `201`. Lehnt die Anlage trotzdem ab
  (401/403/404/407/484 → Ergebnis `forbidden`), schreibt Anton eine klare Log-Warnung und schickt
  höchstens einmal pro Stunde einen Systemhinweis; „keiner geht ran“ bleibt still (ADR-038).
- **Sprachkanal:** Sitzt Moritz mit Anton im Sprachkanal, wird die Antwort auf eine **geschriebene**
  Nachricht – egal in welchem Kanal – zusätzlich laut gesprochen (vorher nur im Chat des Sprachkanals).
- **Zuhören im Sprachkanal** bleibt offen (P1-32): Discord verschlüsselt seit März 2026 jede
  Sprachverbindung (DAVE); `discord-ext-voice-recv` auf PyPI (Stand Juni 2025) kann das nicht
  entschlüsseln. Ein Community-Fork (`zacker150/discord-ext-voice-recv` mit einem discord.py-Fork)
  soll DAVE-Empfang können – Kandidat für Part 2, nicht von PyPI und ungeprüft.

### C.8 Part 1 fertig machen (24.10.2026)

Moritz: „machen wir erstmal Part 1 fertig – das Modell auf /home/models … Sophie-1 bare metal … P1-32
anschauen … Abnahmen mit Protokoll?“

- **Bare metal statt LXC** (ADR-039): Anton läuft direkt auf Sophie-1. Testbetrieb mit `./test-3.sh`,
  Dienst mit `sudo ./moritz-install.sh`. Der Installer akzeptiert jetzt Debian 13 (Proxmox VE 9) und
  installiert zusätzlich `rsync`, `bzip2` und `git`.
- **Modell-Cache `/home/models`** (`scripts/link-models.sh`): `models/` ist ein Link. Vorhandene Modelle
  ziehen um, nichts wird überschrieben oder doppelt geladen, `test-clearup.sh` lässt den Cache stehen
  (`--all` löscht ihn).
  - neue Gruppen in `moritz_agent/phone/audio/models.py`: `llm` (Qwen3-30B-A3B UD-Q3_K_XL, 13,8 GB) und
    `llm-fallback` (Q3_K_S, Q4_K_M, Qwen3-14B Q4_K_M, ≈ 41 GB, `--if-space`)
- **KoboldCpp-Build** (`scripts/setup-koboldcpp.sh`): beim ersten Mal `./koboldcpp.sh rebuild` (ADR-015),
  danach nur `make`, wenn sich der Fingerabdruck der C/C++-Quellen ändert. Ohne GPU: CPU-Bibliothek und
  `use_cuda = false`.
  - KoboldCpp läuft mit der Python seiner Build-Umgebung (`[inference] python`, leer = automatisch).
  - Ist KoboldCpp nicht gebaut, meldet der Status „KoboldCpp ist nicht gebaut“ statt eines
    Startfehlers.
  - Installiert liegt die Engine unter `/opt/moritz-agent/koboldcpp`.
- **Messung** (`scripts/bench_llm.py`): `--moecpu` startet beim konfigurierten Wert und geht hoch, bis
  ≥ 600 MB VRAM frei bleiben, bzw. runter, solange mehr als 1,8 GB frei sind. Der Wert landet in der
  Konfiguration; danach laufen die 40 Telefonfragen direkt durch die Agent-Schleife.
- **P1-32:** Zuhören im Sprachkanal über den DAVE-fähigen Fork in `runtime/discord-venv` (ADR-036,
  Stand 24.10.2026); `[discord] python`, leer = automatisch.
- **Abnahme:** `./test-3.sh run` schreibt `runtime/test-3/abnahme.md`. Der automatische Teil ist
  ausgefüllt, der Live-Teil wird abgehakt. Das ersetzt das Ausfüllen der Vorlagen in `docs/abnahme/`
  für P1-02, P1-18, P1-30, P1-32 und P1-42.
- **Ungeprüft hier:** Build, Messung und DAVE-Empfang brauchen Sophie-1 (GPU, Discord). In der
  Entwicklungsumgebung laufen sie nur gegen ein nachgebautes KoboldCpp
  (`tests/moritz_agent/fake_koboldcpp.py`).

### C.9 Erster Lauf von test-3 auf Sophie-1 (24.10.2026)

Ergebnis: Telefon, Sofortauskünfte (806/806), Datendienste, Testanruf (erste Antwort 2–3 s) und das
Sprachmodell liefen.
- Qwen3 mit `--moecpu 28`: 6,9 von 8 GB VRAM belegt, 40/40 Fragen beantwortet, erste Worte nach
  ≈ 1,8 s (Median).
- Die DAVE-Umgebung (discord.py 2.8.0a) war da.

Behoben:

- **Tests hingen von der Maschine ab:** Die lokale `config/moritz-agent.toml` (gemessenes `--moecpu`) und
  das echte Modell im Cache machten zwei Tests rot. Jetzt sehen die Tests immer die Beispielwerte:
  `tests/moritz_agent/conftest.py` setzt `MORITZ_TESTS_IGNORE_LOCAL_CONFIG`, und Testinstallationen
  zeigen nie auf das echte Modell.
- **`discord sync-commands` stürzte ab:** `setup_hook` fragte den Hauptprozess, den es dort nicht gibt.
- **Tokens/s falsch** (0,6): KoboldCpps `last_eval` ist die Zeit pro Token in ms. Jetzt wird
  `last_eval_speed` benutzt.
- **Keine Websuche bei aktuellen Fragen** (Kanzler, Leitzins, Kino, Nobelpreis – 20/28 richtige
  Werkzeuge): Beide Systemanweisungen sagen jetzt ausdrücklich, dass das Wissen des Modells veraltet ist
  und Amtsinhaber, Termine, Preise, Ergebnisse und „aktuell/gerade/zuletzt/dieses Jahr“ immer über
  `web_search` laufen. Einfache Rechnungen gehen über `calculate`. „In welchem Landkreis liegt
  Weilburg?“ darf aus dem Wissen kommen.
- **„Ruf mich an und …“** nimmt nach „und“ jeden Auftrag an („… beleidige mich“, „… erzähl einen Witz“),
  und „das Datum“ allein ist eine Sofortauskunft. Die Chat-Anweisung sagt nicht mehr „keine Anrufe“,
  sondern erklärt die Formulierung.
- **Flash-Attention** (`[inference] flash_attention = true`, nur mit CUDA): Der Kontext braucht weniger
  VRAM. Das nächste `./test-3.sh run` misst `--moecpu` neu und darf weiter nach unten gehen.
- **Mitschrift:** `runtime/test-3/setup.log` und `run.log` mit der ganzen Ausgabe inklusive Live-Test.

Offen für Moritz:
- „Public Bot“ im Developer Portal ausschalten.
- Das SIP-Passwort `agent` in Asterisk und `passwords.txt` ändern.
- `[web_login]` setzen, damit die Weboberfläche aus dem LAN geht.
- Für den Rückruf die `201` in `[from-agent]` freigeben.


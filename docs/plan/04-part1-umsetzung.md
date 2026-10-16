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
  Validierung der Argumente (jsonschema/pydantic), Ergebnisobjekt
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
  Du bist „Nikita“, die Telefonassistentin von Moritz. Du sprichst Deutsch und duzt Moritz.
  Deine Antworten werden vorgelesen: Antworte in höchstens zwei bis drei kurzen Sätzen,
  ohne Aufzählungen, ohne Markdown, ohne Links, ohne Emojis.
  Für die aktuelle Uhrzeit oder das Datum rufst du immer das Werkzeug get_current_time auf.
  Nenne niemals eine Uhrzeit ohne dieses Werkzeug.
  Für aktuelle Ereignisse, Preise, Wetter, Nachrichten oder alles, was du nicht sicher weißt,
  rufst du web_search auf. Nenne kurz die Quelle, z. B. „laut tagesschau.de“.
  Wenn die Suche fehlschlägt, sag ehrlich, dass du gerade nichts nachschlagen kannst.
  Erfinde keine Fakten. Wenn du etwas nicht verstanden hast, frag kurz nach.
  Du kannst keine Geräte steuern, keine Befehle ausführen und keine Anrufe tätigen.
  ```
- **Tests:** Fast-Path-Erkennung (positive/negative Beispielsätze, inkl. „Um wie viel Uhr
  fährt der Zug?“ = **kein** Fast-Path), Guard, Speakable-Normalisierung, Loop mit Fake-LLM.
- **Anforderungen:** AGENT-01…08, AGENT-10, PHONE-23…27, PHONE-32, PHONE-45.

## P1-10 – Audio-Spike + Audio-Komponenten (VAD, STT, TTS, Resampling)

- **Spike-Teil (zuerst):** `scripts/bench_audio.py` (neu): 30 deutsche Testsätze (von Moritz
  über das echte Telefon aufgenommen **oder** synthetisch + G.711-Codec-Simulation),
  misst Whisper small (int8, 8 Threads; Vergleich `base`) WER + Latenz + RAM und je
  TTS-Engine (Piper thorsten-medium, Polly Hans) Time-to-first-audio + Real-Time-Factor.
  Hans (Polly) ist Standard, Piper Fallback (PHONE-37).
- **Komponenten-Teil:** `moritz_agent/phone/audio/{resample.py,vad.py,stt.py,tts.py,buffers.py}`
  mit Interfaces `SpeechToText.transcribe(pcm16_16k) -> Transcript(text, avg_logprob, no_speech_prob)`,
  `TextToSpeech.synthesize(text) -> Iterator[pcm16_16k_chunk]` (satzweise),
  `VoiceActivityDetector.feed(frame) -> Event` (Silero aus `assets/models/vad/`).
  TTS-Engines `piper` und `polly` (boto3, `Engine=standard`, `VoiceId=Hans`,
  `OutputFormat=pcm`, `SampleRate=16000`) mit automatischem Fallback auf Piper (PHONE-37). Modelle werden einmal geladen, Threads
  konfigurierbar, Self-Test beim Start (kurzer Satz synthetisieren und zurück-transkribieren).
- **Unverständlich-Kriterium:** leerer Text, `no_speech_prob > 0.6`, `avg_logprob < -1.0`
  oder < 2 Zeichen (Werte im Spike kalibrieren).
- **Anforderungen:** PHONE-05, PHONE-22, PHONE-30, PHONE-42, PHONE-43, PHONE-47.

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
- **Anforderungen:** PHONE-20…36, PHONE-40, PHONE-41, PHONE-43, PHONE-44, LOG-03.

## P1-13 – Vorbereitete Ansagen

- **Dateien:** `assets/audio/prompts.de.toml` (Gerüst vorhanden), `moritz_agent/phone/prompts.py`.
- **Aufgaben:** Ansagen aus Textkatalog per TTS erzeugen (Installer + bei Text-/Stimmen-
  änderung), Cache `assets/audio/cache/<voice>/<id>-<hash>.wav` (16 kHz mono), Manifest mit
  Hash von Text+Stimme+TTS-Version; Self-Test „alle Pflichtansagen vorhanden“ (ADR-011).
  Begrüßungstext aus `phone.greeting_text` (Default exakt PHONE-21).
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
- **Anforderungen:** INST-01…11, CFG-02, CFG-04, CFG-09.

## P1-16 – Updater `moritz-update.sh`

- **Spezifikation:** [`07-installation-update.md`](07-installation-update.md) §3.
- **Aufgaben:** Drain mit Timeout und Verschieben, Backup, Git-Update, venv-Swap,
  bedingter KoboldCPP-Rebuild, TXT-Feldergänzung, DB-Migration, Neustart, Health-Prüfung,
  Rollback.
- **Tests:** Rollback-Szenario (absichtlich kaputter Health-Check), TXT mit eigenen Werten
  bleibt byte-identisch bis auf angehängte neue Felder.
- **Anforderungen:** UPD-01…07.

## P1-17 – systemd-Unit + Launcher

- **Dateien:** `deploy/systemd/moritz-agent.service` (Gerüst vorhanden), `moritz-agent` (vorhanden).
- **Aufgaben:** Härtung (`NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths=`,
  `PrivateTmp`, `ProtectHome`), GPU-Gerätezugriff (`DeviceAllow=/dev/nvidia* rw`), Limits
  (`MemoryMax` informativ unter LXC-Limit), `TimeoutStopSec=30`, `KillMode=mixed`.
- **Anforderungen:** INST-08, PRD-01.

## P1-18 – Abnahme auf Sophie-1

- Durchführung exakt nach [`09-tests-abnahme.md`](09-tests-abnahme.md) §3 (Abnahmeprotokoll
  = Originalplan §41, Punkte 1–10). Ergebnisprotokoll als `docs/abnahme/part1-<datum>.md`.
- Erst danach: Tag `v0.1.0`.

---

## Anhang A – Ansagenkatalog (Part 1)

| ID | Text | Verwendung |
| --- | --- | --- |
| `greeting` | Hallo Moritz, hier ist Nikita. Was kann ich für dich tun? | Anrufbeginn |
| `not_understood` | Entschuldigung, das habe ich nicht verstanden. Kannst du das bitte wiederholen? | Reprompt 1 |
| `not_understood_again` | Ich verstehe dich leider schlecht. Sag zum Beispiel: Wie viel Uhr ist es? | Reprompt 2 |
| `still_there` | Bist du noch da? | Stille |
| `goodbye` | Alles klar, bis bald! | Abschied/Stille-Timeout |
| `thinking` | Moment, ich schaue nach. | Zwischenansage |
| `error_generic` | Ich habe gerade eine technische Störung. Bitte versuch es später noch einmal. | LLM/STT/TTS-Fehler |
| `starting_up` | Ich starte gerade noch. Bitte ruf in einer Minute noch einmal an. | LLM lädt |
| `search_failed` | Die Websuche ist gerade nicht erreichbar, deshalb kann ich das nicht nachschlagen. | optional vorgefertigt |
| `timeout` | Das dauert leider zu lange. Frag mich gern noch einmal. | Deadline überschritten |

## Anhang B – Konfigurationsschlüssel Part 1

Vollständig und kommentiert in [`config/moritz-agent.example.toml`](../../config/moritz-agent.example.toml).

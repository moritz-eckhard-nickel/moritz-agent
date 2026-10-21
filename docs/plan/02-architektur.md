# 02 – Architektur

Begründungen der hier getroffenen Entscheidungen stehen in
[`03-entscheidungen.md`](03-entscheidungen.md) (ADR-xxx).

## 1. Überblick

```text
 Internes Telefon ──SIP/RTP──► Asterisk 192.168.1.176 ──SIP 5060/udp + RTP──┐
                                                                             │
 Browser / später Android-WebView ──HTTPS :3501───┐                         │
                                                   ▼                         ▼
┌──────────────────────────── Agent-LXC auf Sophie-1 ───────────────────────────────┐
│  moritz-agent (Supervisor, Hauptprozess)                                           │
│  ├─ Backend API + WebUI (FastAPI/uvicorn)        0.0.0.0:3501 (HTTPS, Login)       │
│  ├─ Agent Core (Profile, Tool-Router, Context)   in-process                        │
│  ├─ Inference-Client (Prioritäts-Queue, Abort)   in-process                        │
│  ├─ Storage (SQLite WAL)                         in-process                        │
│  │                                                                                 │
│  ├─► Child: Phone-Worker  (PJSUA2, VAD, STT, TTS)  SIP :5060/udp, RTP 40000-40199  │
│  ├─► Child: Discord-Worker (discord.py, Sprache)    nur ausgehend: TCP 443, UDP    │
│  ├─► Child: Inference-Worker (koboldcpp.py, CUDA)  127.0.0.1:<dyn>                 │
│  └─► Child: Search-Worker (SearXNG)                127.0.0.1:<dyn>                 │
└────────────────────────────────────────────┬───────────────────────────────────────┘
                                             │ SSH (ab Part 4), gepinnter Host-Key
                                             ▼
                              Redemption-1: Sandbox-VM (Shell, Python, Git, Chromium)
```

Grundprinzip: **Ein Produkt, mehrere isolierte interne Worker.** Der Hauptprozess ist
klein und robust; alles, was abstürzen, hängen oder viel Speicher ziehen kann (Inference,
SIP/Audio, SearXNG, später Browser), läuft in eigenen Prozessen.

## 2. Repository-Layout

KoboldCPP bleibt **unverändert im Wurzelverzeichnis** (ADR-001). Eigener Code liegt in
klar abgegrenzten, neuen Verzeichnissen:

```text
moritz-agent/                      (Repo-Wurzel = Installationsverzeichnis /opt/moritz-agent)
├── moritz-agent                   Startbefehl (Bash-Launcher → venv-Python → moritz_agent)
├── moritz-install.sh / install.sh Installer (+ Wrapper)
├── moritz-update.sh  / update.sh  Updater (+ Wrapper)
├── pyproject.toml                 Paket- und Tool-Konfiguration für moritz_agent
├── CLAUDE.md                      Arbeitsregeln für KI-gestützte Entwicklung
├── THIRD_PARTY_NOTICES.md         Lizenzen aller gebündelten/abhängigen Komponenten
│
├── moritz_agent/                  ── eigener Python-Code ──
│   ├── __main__.py, cli.py        Einstieg: run, check-config, version, setup-Helfer
│   ├── supervisor.py              Startreihenfolge, Child-Prozesse, Health, Backoff
│   ├── config/                    TOML-Settings + passwords.txt-Loader, Validierung, Reload
│   ├── logging_setup.py           Strukturierte Logs, Kategorien (P1-04)
│   ├── redaction.py               textuelle Secret-Redaction für Logs (≥ 8 Zeichen)
│   ├── phone/                     SIP (PJSUA2), Call-State-Machine, Audio, VAD, STT, TTS, Prompts
│   ├── inference/                 KoboldCPP-Prozess, OpenAI-kompatibler Client, Queue, Abort
│   ├── agent/                     Agent-Loop, Profile, Context Manager, Prompts
│   ├── skills/                    Sofortauskünfte ohne LLM: Router, Zeit/Ort-Parser, Wetter, Kalender, … (13, ADR-029)
│   ├── tools/                     Tool-Registry, Schemas, get_current_time, web_search, …
│   ├── research/                  SearXNG-Worker + Client, Web-Fetcher, (später Deep Research)
│   ├── api/                       FastAPI-App, Auth, Routen, interne API
│   ├── storage/                   SQLite, Migrationen, Repositories
│   ├── sandbox/                   SSH-Client, Host-Key-Pinning (Part 4)
│   ├── memory/                    (Part 8)
│   └── setup/                     Installer-/Update-Helfer (atomare Writes, TXT-Migration)
│
├── frontend/                      eigene WebUI (Part 1: Statusseite; Part 2: Chat)
├── third_party/                   ── mitgelieferte Fremdkomponenten (ADR-021), unverändert ──
│   ├── searxng/                   SearXNG, fertig gebaut (Assets + Daten), läuft direkt aus dem Repo
│   ├── pjproject/                 PJSIP/PJSUA2 2.17 Quellcode
│   └── VENDORED.md                Herkunft, Versionen, Lizenzen, Update-Ablauf
├── config/
│   ├── moritz-agent.example.toml  dokumentierte Vorlage (versioniert)
│   ├── moritz-agent.toml          lokale Konfiguration (NICHT versioniert)
│   ├── passwords.template.txt     Vorlage für passwords.txt (versioniert)
│   ├── versions.lock              gepinnte externe Komponenten + SHA-256 (07 §5)
│   └── searxng/settings.yml       SearXNG-Konfiguration (versioniert, ohne secret_key)
├── assets/audio/                  Ansagenkatalog (versioniert) + generierter Cache (nicht versioniert)
├── assets/models/                 kleine Modelle im Repo (Silero VAD, ≤ 100 MB je Datei)
├── assets/data/                   Daten der Sofortauskünfte: geo/ (GeoNames, Fremddaten, nur per Skript), kalender/, wetter/, sprache/, …
├── assets/branding/              Logo m-agent (M + Scribbles), Branding-Regeln; scribbles/ = Maskottchen
├── deploy/systemd/                moritz-agent.service
├── scripts/                       Spikes und Benchmarks (sip_spike, bench_audio, bench_llm)
├── requirements/                  gepinnte Lock-Dateien mit Hashes (ADR-019)
├── docs/plan/                     dieser Plan
├── docs/upstream/                 archivierte KoboldCPP-Dokumentation
├── tests/moritz_agent/            Tests für moritz_agent (Upstream-Tests bleiben in tests/)
│
├── passwords.txt                  lokal, 0600, NICHT versioniert
├── data/                          SQLite, Logs, Zustände (NICHT versioniert)
├── models/                        große Modelle: LLM-GGUF, Whisper small, Piper-Stimme (NICHT versioniert, > 100 MB bzw. HF-Download)
├── runtime/                       venvs, PJSIP-Build, TLS-Zertifikat (NICHT versioniert)
├── backups/                       Update-Sicherungen, 0700 (NICHT versioniert)
│
└── koboldcpp.py, kcpp_*, ggml/, src/, otherarch/, tools/, vendor/, Makefile, …
                                   ── KoboldCPP-Upstream, möglichst unverändert ──
```

> Hinweis: `vendor/` enthält bereits C/C++-Header-Bibliotheken von llama.cpp (Upstream).
> Der im Originalplan skizzierte Ordner `vendor/koboldcpp/` wird deshalb **nicht** angelegt
> (ADR-001). Eigene mitgelieferte Fremdkomponenten liegen in `third_party/` (ADR-021).

## 3. Prozessmodell

| Prozess | Start durch | Bindung | Neustart-Policy | Ausfallverhalten |
| --- | --- | --- | --- | --- |
| **Supervisor/Main** (`python -m moritz_agent run`) | systemd | `0.0.0.0:3501` (HTTPS) + `127.0.0.1:<dyn>` intern | systemd `Restart=on-failure` | Alles stoppt; systemd startet neu |
| **Inference-Worker** (`koboldcpp.py --skiplauncher …`) | Supervisor | `127.0.0.1:<dyn>` | Backoff 2 s → 60 s, unbegrenzt | Phone: Fehleransage; API: 503 |
| **Search-Worker** (SearXNG aus `third_party/searxng` via `granian`) | Supervisor | `127.0.0.1:<dyn>` | Backoff 2 s → 60 s | Fallback-Kette: KoboldCpp-Websuche → Wikipedia → ehrliche Ansage (ADR-020) |
| **Phone-Worker** (`python -m moritz_agent.phone.worker`) | Supervisor | SIP `0.0.0.0:5060/udp`, RTP 40000–40199/udp | Backoff 2 s → 60 s; nie während aktivem Anruf neu starten (außer bei Crash) | Kein Anruf möglich; Status „Phone down“ |
| **Discord-Worker** (`python -m moritz_agent.discord run`, [14](14-discord.md)) | Supervisor (bis P1-04: `moritz-agent run`) | nur ausgehend: Gateway/REST TCP 443, Sprache UDP | Backoff 2 s → 60 s; `nice +5` | Discord nicht erreichbar; Telefon unberührt; Status „Discord down“ |
| *(Part 6)* Remote-Browser-Client | Agent bei Bedarf | – | on demand | Tool „unavailable“ |

**Kommunikation:**

- Supervisor ↔ Children: Prozess-Lebenszyklus (Popen, Signale), stdout/stderr → Logging.
- Phone-Worker → Main: HTTP auf `127.0.0.1:<internal_port>` mit **Per-Start-Token**
  (Env-Variable `MORITZ_INTERNAL_TOKEN`, 32 Byte zufällig). Endpunkte unter `/internal/…`.
- Main → Phone-Worker: Steuer-Endpunkte des Workers (`/control/reload`, `/control/status`)
  auf eigenem Loopback-Port, gleiches Token.
- Main → Inference: OpenAI-kompatibel (`/v1/chat/completions`, Streaming) + KoboldCPP
  `/api/extra/abort`, `/api/extra/perf`, `/api/v1/model`, `/api/extra/websearch` (Such-Fallback).
- Main → SearXNG: `GET /search?format=json&q=…&language=de-DE`.

Warum HTTP statt `multiprocessing`-Pipes: sprachunabhängig, mit `curl` debugbar, gleiche
Auth-Mechanik überall, Worker sind auch einzeln startbar (ADR-004).

## 4. Startablauf

```text
 1. Config laden (TOML) + passwords.txt laden/validieren        → bei Fehler: Abbruch mit Klartext
 2. Logging initialisieren (Redaction-Filter mit geladenen Secrets)
 3. SQLite öffnen, Migrationen anwenden
 4. Internen Token erzeugen, interne API starten
 5. Inference-Worker starten (async, Ladezeit Modell 10–60 s)
 6. Search-Worker starten (async)
 7. Sandbox-Konfiguration prüfen (nur Status, keine Verbindung erzwingen)
 8. Agent Runtime initialisieren (Profile, Tool-Registry)
 9. Web-API + Statusseite starten (HTTPS :3501)
10. Phone-Worker starten:
      a) Ansagen-Cache prüfen/erzeugen, Audio-Komponenten laden (VAD, STT, TTS)
      b) erst wenn der Ansagen-Cache OK ist → SIP-Registrierung (ADR-011)
      c) „Anrufbereit“ melden
11. (kein automatisches Browser-Öffnen – Betrieb im LXC)
```

Schritte 5, 6 und 10 laufen parallel. Telefon darf registrieren, **bevor** das LLM fertig
geladen ist (PHONE-33): Begrüßung kommt aus dem Cache, Fragen erhalten bis dahin die
Ansage „Ich bin gleich bereit, bitte versuch es in einer Minute noch einmal.“

## 5. Telefon: Datenfluss und Zustandsautomat

### 5.1 Audio-Pfad

```text
RTP (G.722 16 kHz | PCMA/PCMU 8 kHz)
  └─► PJSUA2 Conference Bridge (clock 16 kHz, 20 ms Frames, Null-Sound-Device)
        └─► AudioMediaPort.onFrameReceived  → Ringpuffer (PCM16 mono 16 kHz)
              └─► VAD (Silero, 30 ms Fenster)  → Segment „Äußerung“ (+ 300 ms Vorlauf)
                    └─► STT (faster-whisper, de, int8, CPU)  → Text + Konfidenz
                          └─► Main /internal/phone/turn  → Agent (Profil phone) → Antworttext
                                └─► TTS (Piper, de_DE) → PCM 22,05 kHz → Resampling 16 kHz
                                      └─► AudioMediaPort.onFrameRequested → RTP
```

Vorbereitete Ansagen liegen als 16-kHz-PCM-WAV im Cache und werden über denselben
Ausgabe-Port gespielt (kein Sonderweg).

### 5.2 Zustandsautomat pro Anruf

```text
        INVITE (erlaubte Quelle, kein aktiver Call)        INVITE (aktiver Call / fremde Quelle)
IDLE ───────────────────────────────────────────► RINGING          └─► 486 Busy Here / 403
                                                     │ 200 OK (auto-answer)
                                                     ▼
                                                 GREETING  (Cache-WAV, Eingang verworfen)
                                                     │ Wiedergabe fertig
                                                     ▼
          ┌──────────────────────────────────► LISTENING ◄────────────────────────────┐
          │                                     │      │ Stille ≥ silence_prompt_s     │
          │                                     │      └─► PROMPT_SILENCE ─ (1×) ──────┤
          │                                     │            Stille ≥ silence_hangup_s │
          │                                     │            └─► GOODBYE ─► HANGUP     │
          │                       VAD: Sprachende                                       │
          │                                     ▼                                       │
          │                                TRANSCRIBING ── leer/unverständlich ─► REPROMPT ─┘
          │                                     │ Text
          │                                     ▼
          │                                 THINKING ── > thinking_prompt_after_s ─► (Zwischenansage, bleibt THINKING)
          │                                     │ Antworttext / Fehlertext
          │                                     ▼
          └───────────────── Wiedergabe fertig ─ SPEAKING  (Eingang verworfen = klarer Sprecherwechsel)

Jeder Zustand ──BYE/CANCEL/RTP-Timeout──► CLEANUP: Tasks canceln (STT, Agent-Request,
TTS), Inference-Abort falls Phone-Request läuft, Puffer leeren, Call-Record schließen → IDLE
```

### 5.3 Turn-Sequenz (Normalfall mit Websuche)

```text
Phone-Worker         Main/Agent            Inference(KoboldCPP)     SearXNG
    │ POST /internal/phone/turn {call_id, turn, text}
    │──────────────────►│
    │                   │ Sofortauskunft (Skill-Router, 13)? nein – sonst Antwort in ≤ 30 ms (Cache)
    │                   │ chat/completions (tools=[time, web_search, Skill-Tools], prio=PHONE)
    │                   │──────────────────────►│
    │                   │◄── tool_call web_search("…")
    │                   │──────────────────────────────────────────────►│
    │                   │◄──────────────────────────── Top-5 JSON ──────│
    │                   │ chat/completions (+tool result)
    │                   │──────────────────────►│
    │                   │◄── „Laut tagesschau.de …“
    │◄── {text, sources, timings}
    │ TTS → Wiedergabe
```

Zwischenansage, Cancellation und Timeouts liegen im Phone-Worker; der Request an Main
trägt eine `deadline`. Legt der Anrufer auf, schickt der Worker
`POST /internal/phone/cancel {call_id}` → Main bricht Agent-Loop und laufende
Generierung (`/api/extra/abort`) ab.

## 5a. CPU-Threads (E5-2673 v3, max. 18 Threads für den LXC, F-07)

| Verbraucher | Threads | Begründung |
| --- | ---: | --- |
| KoboldCpp Generierung (`--threads`) | 12 | MoE-Experten teilweise auf CPU → speicherbandbreitenlimitiert, mehr Threads bringen kaum etwas |
| KoboldCpp Prompt-Verarbeitung (`--blasthreads`) | 12 | läuft überwiegend auf der GPU |
| STT faster-whisper (`cpu_threads`) | 8 | läuft **vor** der LLM-Generierung, daher kaum Überlappung |
| TTS Piper / onnxruntime | 4 | läuft nach der Generierung |
| VAD, SIP, Main, SearXNG | Rest | leichtgewichtig |

Die Summe übersteigt 18, weil STT, LLM und TTS innerhalb eines Turns **nacheinander**
laufen; die harte Grenze setzt der LXC (`cores: 18`), nicht die Konfiguration.

## 6. Inference-Warteschlange

- `asyncio.PriorityQueue` mit Prioritäten `PHONE=0`, `VOICE=1` (Discord-Sprachkanal, DISCORD-10),
  `INTERACTIVE=2` (Discord-Text, WebUI), `BACKGROUND=3`.
- KoboldCPP läuft mit `--parallelrequests 1` (Default) → eine Generierung gleichzeitig.
- Kommt ein PHONE-Request, während ein BACKGROUND-Request **läuft**: `abort`, Background
  wird mit Markierung „unterbrochen“ neu eingereiht. Läuft ein INTERACTIVE-Request: warten
  bis `phone_preempt_wait_s` (Start 3 s), danach ebenfalls abbrechen.
- Jeder Request hat eine eindeutige `genkey`, damit `abort` nur die eigene Generierung trifft.

## 7. Agent: Phone-Profil

| Parameter | Startwert |
| --- | --- |
| Tools | `get_current_time`, `web_search`, lesende Skill-Tools (`get_weather`, `get_warnings`, `get_pollen`, `get_sun_moon`, `calendar_info`, `calculate`, …; SKILL-23) |
| Max. Tool-Schritte | 3 |
| Max. Antwort-Tokens | 160 |
| Temperatur | 0,3 |
| Gesamtdeadline je Turn | 15 s (danach Fehleransage) |
| Historie | Turns des aktuellen Anrufs, gekürzt auf Budget (4.096 − System − Tools − 300 Reserve) |
| Denkmodus | aus (NoThink-Adapter / `enable_thinking=false`, je nach Modell) |
| Systemanweisung | `moritz_agent/agent/prompts/phone.de.md` (Entwurf siehe 04, Ticket P1-09) |

**Fast-Paths (AGENT-06, AGENT-10, Katalog [12-fast-paths.md](12-fast-paths.md)):** Muster-Erkennung, u. a. für eindeutige Zeit-/Datumsfragen
(„wie spät“, „wie viel Uhr“, „welche Uhrzeit“, „welcher Tag/Datum ist heute“). Treffer →
Tool direkt, Antwort per Template, **kein LLM**. Kein Treffer → normaler Agent-Loop.
**Guard:** Antwort enthält Uhrzeit-Muster (`\b\d{1,2}[:.]\d{2}\b`, „… Uhr …“) ohne
`get_current_time`-Aufruf im Turn → Antwort verwerfen und Tool-Ergebnis verwenden.

**Sofortauskünfte vor dem Agenten (ADR-029, [13](13-sofortauskuenfte.md)):** Seit Block S läuft jede
Äußerung zuerst durch den Skill-Router (Zeit, Kalender, Wetter für den Heimatort 35781 Weilburg oder
einen genannten Ort, Warnungen, Sonne/Mond, Rechnen …). Nur was kein Skill eindeutig beantwortet,
erreicht den Agent-Loop; der nutzt dieselben Skills als Tools. **Wetter-Guard** (AGENT-11): Wetterwerte
ohne Wetter-Tool-Aufruf im Turn → verwerfen, über das Tool neu beantworten.

## 8. Datenmodell (Part 1, SQLite)

```sql
schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)

calls(
  id TEXT PRIMARY KEY,            -- UUID
  started_at TEXT, answered_at TEXT, ended_at TEXT,
  remote_uri TEXT,                -- From-URI (z. B. sip:20@192.168.1.176)
  codec TEXT, end_reason TEXT,    -- caller_hangup | silence_timeout | goodbye | error | busy
  turns INTEGER DEFAULT 0
)

call_turns(
  id INTEGER PRIMARY KEY, call_id TEXT REFERENCES calls(id),
  idx INTEGER, user_text TEXT NULL, agent_text TEXT NULL,   -- NULL wenn Transkripte aus
  path TEXT,                      -- fast_path_time | agent | reprompt | error
  t_vad_end_ms INTEGER, t_stt_ms INTEGER, t_llm_first_ms INTEGER, t_llm_total_ms INTEGER,
  t_tools_ms INTEGER, t_tts_first_ms INTEGER, t_total_ms INTEGER,
  created_at TEXT
)

tool_calls(
  id INTEGER PRIMARY KEY, call_id TEXT NULL, turn_id INTEGER NULL,
  tool TEXT, args_json TEXT, ok INTEGER, error TEXT NULL,
  result_summary TEXT, sources_json TEXT NULL, duration_ms INTEGER, created_at TEXT
)
```

Sofortauskünfte (Block S): jede Auskunft ist ein `tool_calls`-Eintrag mit `tool = 'skill:<id>'`
(z. B. `skill:weather.day`), `args_json` mit Ort/Zeitraum (nie der Satz), `sources_json` mit Datendienst
und Abrufzeit; `call_turns.path = 'skill'`. Dazu zwei kleine Tabellen:

```sql
notes(id INTEGER PRIMARY KEY, list TEXT, text TEXT, created_at TEXT, done_at TEXT NULL)   -- nur wenn skills.notes.enabled
skill_misses(id INTEGER PRIMARY KEY, text TEXT, best_skill TEXT NULL, score REAL, created_at TEXT)  -- 24 h, wie Transkripte
```

Bis zur Datenbank (P1-06) stehen Skill-Aufrufe im Log und Notizen/Fehltreffer in `data/` (JSON, 0600).
Wettercaches liegen als Dateien unter `data/cache/skills/` (13 §3.6), nicht in SQLite.

Discord (Block D): `call_turns` und `tool_calls` bekommen eine Spalte `channel` (`phone|discord|web`);
neue Tabellen `discord_principals`, `discord_subscriptions`, `reminders`, `command_registry`
([14 §16](14-discord.md#16-daten-und-logs)). Bis zur Datenbank liegen Abos und Erinnerungen in `data/discord/` (JSON, 0600).

Spätere Tabellen (Part 3+): `conversations`, `messages`, `agents`, `tasks`,
`research_runs`, `sources`, `files`, `memories`, `settings`, `models`.

## 9. API (Part 1)

| Methode | Pfad | Auth | Zweck |
| --- | --- | --- | --- |
| GET | `/api/system/health` | keine | `{"ok": bool}` für systemd/Updater (keine Details) |
| GET | `/api/system/status` | Login | Status aller Komponenten (`starting/ready/degraded/failed/disabled` + Meldung) |
| GET | `/api/phone/status` | Login | Registrierung, Anrufzustand, Codec, letzte Fehler, STT/TTS-Bereitschaft |
| POST | `/api/system/reload` | Login | `passwords.txt` + TOML neu laden, validieren, anwenden |
| GET | `/api/system/activity` | Loopback + Token-Datei | aktive Anrufe/Generierungen (für Updater) |
| POST | `/api/system/drain` | Loopback + Token-Datei | keine neuen Anrufe/Jobs annehmen (Update) |
| POST | `/api/chat` | Login | Text-Testpfad durch das Phone-Profil (ohne Audio) |
| GET | `/` | Login | Statusseite |
| POST | `/internal/phone/turn`, `/internal/phone/cancel`, `/internal/phone/event` | interner Token | Phone-Worker → Main |

Der Updater authentisiert sich über eine **Token-Datei** `data/run/admin.token` (0600,
bei jedem Start neu erzeugt), nicht über das Web-Passwort.

## 10. Ports & Netzwerk

| Dienst | Bindung | Protokoll | Von wo erreichbar |
| --- | --- | --- | --- |
| Web-UI/API | `0.0.0.0:3501` | TCP (HTTPS) | LAN, nur mit aktivem Login (API-02, F-04) |
| Interne API | `127.0.0.1:<dyn>` | TCP | nur lokal |
| KoboldCPP | `127.0.0.1:<dyn>` | TCP | nur lokal |
| SearXNG | `127.0.0.1:<dyn>` | TCP | nur lokal |
| SIP | `0.0.0.0:5060` | UDP | nur Registrar `192.168.1.176` (Firewall + PHONE-09) |
| RTP/RTCP | `0.0.0.0:40000–40199` | UDP | Asterisk (bei `direct_media=no`) |
| SSH → Sandbox | ausgehend | TCP 22 | Redemption-1 (Part 4) |
| Discord ([14](14-discord.md)) | ausgehend | TCP 443 (Gateway WSS, REST, CDN), UDP zu Discords Sprachservern | kein eingehender Port, keine öffentliche Adresse (DISCORD-11) |
| Datendienste der Sofortauskünfte | ausgehend | TCP 443 (HTTPS) | nur Hosts der Allowlist im HTTP-Client (ADR-032): `api.open-meteo.com`, `air-quality-api.open-meteo.com`, `geocoding-api.open-meteo.com`, `api.brightsky.dev`, `opendata.dwd.de`, `warnung.bund.de`, `www.pegelonline.wsv.de`, `www.ecb.europa.eu`, `api.energy-charts.info`, `creativecommons.tankerkoenig.de`, `api.openligadb.de`, Nachrichtenquelle, iCal-Host – je nach Aktivierung |

## 11. Fehlerisolierung (Matrix)

| Ausfall | Erkennung | Reaktion | Telefon-Verhalten |
| --- | --- | --- | --- |
| KoboldCPP crasht/hängt | Prozess-Exit / Health-Timeout 10 s | Neustart mit Backoff | „Ich habe gerade eine technische Störung …“ |
| SearXNG down | Prozess-Exit / HTTP-Fehler | Neustart | „Die Websuche ist gerade nicht erreichbar.“ |
| Phone-Worker crasht | Prozess-Exit | Neustart, Re-REGISTER; laufender Anruf ist verloren (wird **nicht** übernommen) | Anruf bricht ab |
| Registrierung schlägt fehl | PJSUA2 `onRegState` | Backoff 5 s → 5 min | nicht erreichbar, Status rot |
| STT/TTS lädt nicht | Worker-Self-Test | Status `failed`, Neuversuch mit Backoff (ADR-011) | Annehmen → vorbereitete Störungsansage → Auflegen |
| Ansagen-Cache fehlt/kaputt | Worker-Self-Test | **nicht registrieren**, Status rot (ADR-011) | nicht erreichbar |
| Sandbox offline | SSH-Test | Tool „unavailable“ | keine Auswirkung |
| Wetter-/Datendienst nicht erreichbar oder unplausibel | Timeout 3 s / HTTP-Fehler / Schemaprüfung | Rückfallquelle, Cache bis 6 h, Backoff; Status `degraded` | Antwort aus Cache mit Altersangabe oder ehrliche Absage (13 §3.7); Anruf läuft weiter |
| Discord-Worker crasht / Gateway weg | Prozess-Exit / Gateway-Heartbeat | Neustart mit Backoff, Wiederaufnahme der Sitzung | keine Auswirkung |
| DAVE-Sprachempfang fehlerhaft | Entschlüsselungsfehler, häufige Reconnects | Sprachkanal im Modus „nur sprechen“ (ADR-036) | keine Auswirkung |
| Gazetteer/Datendateien fehlen oder kaputt | Selbsttest beim Start | Orts-Skills `failed`, Rest läuft | „Orte kann ich gerade nicht auflösen“; Wetter für den Heimatort aus den konfigurierten Koordinaten, falls gesetzt |
| Main crasht | systemd | Neustart aller Worker | Anruf bricht ab |

## 12. Upstream-Patches

Änderungen an KoboldCpp-Upstream-Dateien (ADR-001). Jeder Eintrag: Datei, Grund, PR.

| Datei | Änderung | Grund | PR |
| --- | --- | --- | --- |
| `README.md` | ersetzt durch moritz-agent-README; Original nach `docs/upstream/KOBOLDCPP_README.md` | Branding (ADR-002) | P1-00 |
| `.gitignore` | Abschnitt „moritz-agent“ angehängt | Secrets/Laufzeitdaten (CFG-07) | P1-00 |
| `.github/ISSUE_TEMPLATE/create-new-issue.md` | ersetzt durch `bug.md`/`task.md` | Branding | P1-00 |
| `niko.ico`, `nikogreen.ico` | Inhalt durch m-agent-Logo ersetzt (Dateinamen bleiben, Build-Skripte unverändert) | Branding (PRD-08) | P1-00b |
| `embd_res/klite.embd`, `kcpp_docs.embd`, `kcpp_sdui.embd`, `lcpp.gz.embd`, `kcpp_musicui.embd` | gelöscht; KoboldCpp startet ohne sie (prüft per `try/except`) | KoboldCpp-Oberflächen entfernt (F-11) | P1-00b |
| `media/preview*.png` | gelöscht (KoboldCpp-Screenshots) | Branding | P1-00b |
| `kcpp_src/packaging/version_template.txt` | Produkt-/Firmenname → moritz-agent, Lizenzangabe unverändert | Branding | P1-00b |

Bei Upstream-Merges: gelöschte `embd_res`-UI-Dateien erneut löschen (`git rm`), Icons
mit `assets/branding/m-agent.ico` überschreiben.

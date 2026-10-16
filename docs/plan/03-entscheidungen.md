# 03 – Architekturentscheidungen (ADR)

Format je Entscheidung: **Kontext → Entscheidung → Alternativen → Konsequenzen → Status.**
Status: `beschlossen` (gilt), `vorläufig` (gilt bis Spike/Benchmark bestätigt), `offen`.
Eine geänderte Entscheidung wird nicht gelöscht, sondern als `ersetzt durch ADR-xxx` markiert.

---

## ADR-001 – KoboldCPP bleibt an der Repo-Wurzel, eigener Code in `moritz_agent/`

- **Kontext:** Das Repo ist ein vollständiger KoboldCPP-Fork (≈ 430 MB, Makefile, CMake,
  CI, PyInstaller-Skripte mit festen Pfaden). Der Originalplan skizziert `vendor/koboldcpp/`,
  erlaubt aber ausdrücklich, „einen Teil des bestehenden KoboldCPP-Codes direkt zu übernehmen
  und schrittweise neu zu strukturieren“.
- **Entscheidung:** Upstream-Dateien bleiben, wo sie sind. Eigener Code ausschließlich in
  neuen Verzeichnissen (`moritz_agent/`, `frontend/`, `config/`, `assets/`, `deploy/`,
  `docs/plan/`, `tests/moritz_agent/`) plus wenigen Wurzeldateien (Launcher, Skripte,
  `pyproject.toml`, `README.md`, `CLAUDE.md`, `THIRD_PARTY_NOTICES.md`).
- **Upstream-Sync:** Remote `upstream = https://github.com/LostRuins/koboldcpp`. Releases
  werden per Merge-PR in `agent` übernommen (`git merge <upstream-tag>`). Konfliktdateien
  sind absehbar (`README.md` → immer unsere Version; Upstream-README nach
  `docs/upstream/KOBOLDCPP_README.md` übernehmen; `.gitignore` → beide Seiten zusammenführen).
  Nach jedem Sync: Build + Inference-Smoke-Test (Ticket-Vorlage in 04, P1-02).
- **Änderungen an Upstream-Dateien** (z. B. `koboldcpp.py`) nur, wenn unvermeidbar, minimal,
  mit Kommentar `# moritz-agent:` und Eintrag in `docs/plan/02-architektur.md` → Abschnitt
  „Upstream-Patches“ (§12).
- **Alternativen:** (a) alles nach `vendor/koboldcpp/` verschieben → bricht Build/CI, jeder
  Upstream-Merge wird zum Pfad-Konflikt; (b) KoboldCPP als Git-Submodul → verliert die
  bereits vorhandene Fork-History, doppelter Checkout.
- **Status:** beschlossen.

## ADR-002 – Branding-Grenze

- **Entscheidung:** Rebranding betrifft die **Produktoberfläche**: README, GitHub-Templates,
  Startbefehl `moritz-agent`, systemd-Unit, eigene WebUI, Logs/Status des Supervisors,
  Telefon-Ansagen. **Nicht** umbenannt werden KoboldCPP-interne Dateien, Symbole,
  Binärnamen (`koboldcpp_cublas.so`), die KoboldAI-Lite-UI und die PyInstaller-Metadaten
  der Inference-Komponente – das würde jeden Upstream-Merge brechen.
- **Unsichtbarkeit (PRD-03):** Der Nutzer sieht KoboldCPP nicht, weil (1) der Port nur auf
  Loopback lauscht, (2) die eigene WebUI das einzige Frontend ist, (3) Logs des Children mit
  Kategorie `[LLM]` statt Rohausgabe erscheinen.
- **Lizenz:** Copyright-/Lizenzhinweise bleiben vollständig erhalten; README und
  `THIRD_PARTY_NOTICES.md` nennen KoboldCPP als Basis (AGPL-Pflicht + Fairness).
- **Status:** beschlossen.

## ADR-003 – KoboldCPP als Child-Prozess über HTTP, nicht als Python-Import

- **Kontext:** `koboldcpp.py` ist ein 13.000-Zeilen-Monolith mit globalem Zustand, eigenem
  HTTP-Server und Launcher-GUI.
- **Entscheidung:** Start als Subprozess
  `python koboldcpp.py --skiplauncher --host 127.0.0.1 --port <dyn> --model … --contextsize 4096 --gpulayers <n> --usecuda --quiet --jinja`
  (Flags finalisieren in P1-02). Kommunikation über die OpenAI-kompatible API + KoboldCPP-
  Extras (`/api/extra/abort`, `/api/extra/perf`).
- **Konsequenzen:** Absturz der Inference tötet nicht den Agent (PRD-02); Upstream-Updates
  ändern nur die API-Oberfläche, die stabil ist. Kosten: ein lokaler HTTP-Hop (< 1 ms).
- **Status:** beschlossen.

## ADR-004 – Interne Kommunikation: HTTP auf Loopback + Per-Start-Token

- **Entscheidung:** Alle internen Kanäle sind HTTP/JSON auf `127.0.0.1` mit zufälligem Port;
  Auth über `Authorization: Bearer <token>`, Token pro Supervisor-Start neu (32 Byte,
  `secrets.token_urlsafe`), an Children per Umgebungsvariable übergeben.
- **Alternativen:** Unix-Sockets (gut, aber schwerer zu debuggen, PJSIP-Thread-Modell egal),
  `multiprocessing`-Pipes (koppelt Lebenszyklen eng), gRPC (zusätzliche Abhängigkeit).
- **Status:** beschlossen (Unix-Sockets bleiben eine spätere Härtungsoption).

## ADR-005 – SIP-Stack: PJSIP/PJSUA2 (Python-Binding), Version gepinnt

- **Entscheidung:** pjproject aus Quellcode bauen (Release-Tag gepinnt, Kandidat aktuelle
  2.15.x/2.16.x; im Spike P1-11 festlegen), SWIG-Python-Binding `pjsua2`. Konfiguration:
  `audDevManager().setNullDev()`, Conference-Bridge 16 kHz, eigene `AudioMediaPort`-Klasse für
  Frame-Ein-/Ausgabe, Codec-Prioritäten G722=255, PCMA=254, PCMU=253, Rest deaktiviert,
  `ep_cfg.uaConfig.threadCnt = 0` + eigener Poll-Thread **oder** `threadCnt=1` mit strikter
  Thread-Registrierung (`libRegisterThread`) – im Spike entscheiden.
- **Build:** `./configure --enable-shared --disable-video --disable-sound` (kein ALSA nötig),
  `CFLAGS=-fPIC`, dann `make dep && make && make install` in `runtime/pjsip/`, danach
  `pjsip-apps/src/swig/python` bauen und ins venv installieren. Build-Log und -Hash werden
  im Installer gecacht (Neubau nur bei Versionswechsel).
- **Alternativen:**
  - *pyVoIP* (pure Python): einfach, aber nur G.711, fragile RTP-Behandlung, wenig gepflegt.
  - *baresip* + ctrl_tcp: robust, aber Audio-Anbindung über Module/Pipes umständlich.
  - *Asterisk AudioSocket/ARI externalMedia*: elegant, erfordert aber Änderungen an der
    Telefonanlage (Plan: Agent registriert sich als normaler Teilnehmer, Dialplan nur prüfen).
    → **Fallback**, falls PJSUA2 im Spike scheitert; nur nach Rücksprache mit Moritz.
- **Lizenz:** pjproject GPL-2.0-or-later → kompatibel zur AGPL-3.0 des Gesamtwerks.
- **Status:** vorläufig (bis Spike P1-11 erfolgreich).

## ADR-006 – STT: faster-whisper auf CPU (int8), Modell per Benchmark

- **Entscheidung (vorläufig):** `faster-whisper` (CTranslate2, MIT) mit
  `compute_type="int8"`, `language="de"`, `beam_size=1–3`, `vad_filter=False` (eigene VAD).
  Kandidaten im Benchmark P1-10: `base`, `small`, `large-v3-turbo` (int8). Startfavorit: `small`.
- **Kriterien:** Wortfehlerrate auf 30 eigenen Telefon-Testsätzen (8 kHz → 16 kHz),
  Latenz für 2–6 s Äußerungen bei `cpu_threads` = LXC-Kerne − 2, RAM.
- **Alternativen:** KoboldCPP-eigenes Whisper (`--whispermodel`): keine zusätzliche
  Abhängigkeit, aber im selben Prozess wie das LLM, konkurriert um GPU und Request-Lock →
  bleibt **Fallback B**. Vosk (`vosk-model-de-0.21`): sehr schnell/streamingfähig, schwächere
  Erkennung → **Fallback C** für schwache CPUs.
- **Status:** vorläufig.

## ADR-007 – SearXNG: gepinnter Checkout in `runtime/`, eigener venv, granian

- **Entscheidung:** Installer klont `https://github.com/searxng/searxng` auf einen in
  `config/versions.lock` gepinnten Commit nach `runtime/searxng/`, eigenes venv
  `runtime/searxng-venv/`, Start über `granian` (WSGI) auf `127.0.0.1:<dyn>`.
  Settings aus `config/searxng/settings.yml` (versioniert, `use_default_settings: true`,
  `search.formats: [html, json]`, `server.limiter: false`, `server.secret_key` wird beim
  Installieren zufällig erzeugt und **lokal** in `data/searxng/settings.local.yml` abgelegt).
- **Warum nicht ins Repo kopieren:** eigene große Abhängigkeitsbasis, eigener Release-Takt,
  AGPL-Hinweise bleiben im Original-Checkout intakt; Konflikte mit unserem Code vermieden.
- **Engines Start:** `google`, `bing`, `duckduckgo`, `brave`, `wikipedia` (de), `qwant`;
  Engines, die geblockt werden, fallen automatisch weg (SearXNG-Suspend). Ergebnisfeld
  `engines` wird an den Agent weitergegeben (SEARCH-02).
- **Status:** beschlossen (Engines-Liste vorläufig).

## ADR-008 – TTS: Piper (deutsche Stimme) auf CPU

- **Entscheidung (vorläufig):** Piper (`piper-tts`, ONNX, CPU), Stimme Kandidat
  `de_DE-thorsten-high` bzw. `-medium` (männlich, Datensatz CC0); weibliche Alternativen
  `de_DE-kerstin-low`, `de_DE-eva_k-x_low` – Auswahl durch Moritz im Hörtest (F-08).
  Ausgabe 22,05 kHz → Resampling auf 16 kHz (`soxr`).
- **Begründung:** Kokoro (in KoboldCPP) kann **kein Deutsch**; Qwen3-TTS kann Deutsch, ist
  aber deutlich schwerer und bevorzugt GPU (kollidiert mit PHONE-42).
- **Lizenz:** Piper wird seit 2025 als `OHF-Voice/piper1-gpl` (GPL-3.0) weitergeführt →
  kompatibel mit AGPL-3.0; Stimmenlizenzen einzeln in `THIRD_PARTY_NOTICES.md` aufführen.
- **Status:** vorläufig (Benchmark/Hörtest in P1-10).

## ADR-009 – VAD: Silero VAD (ONNX)

- **Entscheidung:** Silero VAD (MIT) über `onnxruntime` (ohnehin Abhängigkeit von Piper),
  16 kHz, 512-Sample-Fenster, Schwelle 0,5, `min_silence_ms` 700 (konfigurierbar),
  `speech_pad_ms` 300, max. Äußerung 20 s. Fallback: `webrtcvad`.
- **Status:** vorläufig.

## ADR-010 – Backend FastAPI/uvicorn, Frontend ohne Build-Schritt (Part 1)

- **Entscheidung:** FastAPI + uvicorn (SSE/WebSocket für Part 2 vorhanden, pydantic für
  Validierung). Frontend Part 1: statisches HTML + Vanilla-JS (Polling `/api/system/status`
  alle 2 s), ausgeliefert aus `frontend/`. Für Part 2 wird das Framework neu entschieden
  (Empfehlung: weiter ohne Node-Laufzeit auf dem Server; Build-Artefakte, falls nötig, im
  Release erzeugt).
- **Alternativen:** stdlib `http.server` (wie KoboldCPP; zu viel Eigenbau für Auth/SSE),
  aiohttp (gleichwertig, kleinere Community für Validierung).
- **Status:** beschlossen für Part 1.

## ADR-011 – Verhalten bei teilweisem Ausfall der Telefonkette

- **Entscheidung:** Registrierung hängt **nur** an SIP-Konfiguration + vorhandenem
  Ansagen-Cache. Fehlt STT, TTS oder LLM: Anruf annehmen → Begrüßung entfällt →
  vorbereitete Störungsansage („Ich habe gerade eine technische Störung. Bitte versuch es
  später noch einmal.“) → auflegen. LLM noch am Laden: eigene Ansage „Ich starte gerade
  noch …“. Fehlt der Ansagen-Cache: nicht registrieren (sonst wäre stilles Abheben möglich).
- **Status:** beschlossen.

## ADR-012 – Konfigurationsformate

- **Entscheidung:** `passwords.txt` = INI (Vorgabe Originalplan), gelesen mit
  `configparser.ConfigParser(interpolation=None, strict=True)`, `optionxform = str`,
  Kommentare nur auf eigenen Zeilen. Nicht geheime Einstellungen = TOML
  (`config/moritz-agent.toml`, gelesen mit `tomllib`), validiert durch pydantic-Modelle.
  Unbekannte Schlüssel → Warnung, falsche Typen → Fehler.
- **Schreiben:** Nur über `moritz_agent.setup` (atomar, Rechte erhaltend). Ergänzen fehlender
  TXT-Felder zeilenbasiert (CFG-09), nie Neu-Serialisieren der ganzen Datei.
- **Status:** beschlossen.

## ADR-013 – Web-Login-Hash: scrypt aus der Standardbibliothek

- **Entscheidung:** `hashlib.scrypt(n=2**15, r=8, p=1, dklen=32)`, 16 Byte Salt, Format
  `scrypt$n$r$p$salt_b64$hash_b64`, gespeichert in `data/state/web_login.json` (0600) zusammen
  mit Benutzername. Beim Start/Reload: Ist das Klartextpasswort in der TXT geändert
  (Vergleich gegen Hash schlägt fehl), wird ein neuer Hash abgeleitet. Login-Prüfung nur
  gegen den Hash, konstante Laufzeit (`hmac.compare_digest`).
- **Status:** beschlossen.

## ADR-014 – Installationsort und Update-Mechanismus

- **Entscheidung:** Installation = Git-Checkout in `/opt/moritz-agent`, Besitzer
  `moritz-agent:moritz-agent`, Code-Dateien für den Dienst nur lesbar (Schreibrechte nur für
  `data/`, `models/`, `runtime/`, `backups/`, `passwords.txt`, `config/moritz-agent.toml`).
  Update = `git fetch` + Checkout eines Release-Tags (`v0.1.x`) oder `origin/agent`
  (`--channel dev`), neues venv in `runtime/venv.new`, Umschalten per Rename, altes venv als
  `runtime/venv.prev` für Rollback. KoboldCPP-Neubau nur, wenn sich native Quellen geändert
  haben (Hash über `git ls-files -s` der C/C++-Pfade).
- **Status:** beschlossen.

## ADR-015 – KoboldCPP-Build im LXC über `koboldcpp.sh rebuild`

- **Entscheidung:** Build aus **unserem** Fork mit dem mitgelieferten Skript
  `./koboldcpp.sh rebuild` (micromamba-Umgebung mit CUDA-Toolkit aus Conda; kein System-CUDA-
  Toolkit im LXC nötig, nur der zum Host-Treiber passende Userspace-Treiber). Optional
  `LLAMA_ARCHES_CU12=1` bzw. Einschränkung auf `sm_86` (RTX 3070) zur Build-Zeitersparnis.
- **Fallback:** Offizielles Release-Binary derselben Upstream-Version (`koboldcpp-linux-x64`,
  Version 1.123.1) mit geprüfter SHA-256 – nur solange keine eigenen C++-Änderungen existieren.
- **Status:** vorläufig (in P1-02 messen: Build-Dauer, Plattenbedarf ≈ 6–10 GB für die Conda-Umgebung).

## ADR-016 – LLM-Startmodell

- **Kriterien:** Deutschqualität (kurze, natürliche Antworten), zuverlässiges Tool-Calling
  mit JSON-Schema, Chat-Template-Unterstützung in KoboldCPP (Adapter in `kcpp_adapters/`
  oder `--jinja`), abschaltbares „Thinking“, Lizenz, Größe Q4_K_M ≤ 5,5 GB.
- **Kandidaten (Benchmark P1-02):** Qwen3-8B (Apache-2.0, `ChatML-NoThink`), Qwen3-VL-8B-
  Instruct (Upstream-Empfehlung), Llama-3.1-8B-Instruct (Llama-Lizenz), Gemma-Varianten mit
  passendem Adapter, Granite-4 (Apache-2.0). Der Benchmark enthält 40 deutsche
  Telefonfragen, davon 15 mit erwartetem Tool-Aufruf.
- **Status:** offen → Entscheidung in P1-02.

## ADR-017 – Uhrzeit-Garantie (Fast-Path + Guard)

- **Entscheidung:** siehe [`02-architektur.md`](02-architektur.md#7-agent-phone-profil).
  Formatierung: „Es ist 19 Uhr 12.“, volle Stunde „Es ist 19 Uhr.“, Mitternacht „Es ist 0 Uhr 5.“
  Datum auf Nachfrage: „Heute ist Freitag, der 16. Oktober 2026.“ Zeit wird **nach** der
  Antwortgenerierung und **direkt vor** TTS gelesen (bei Fast-Path: TTS-Synthese < 300 ms).
- **Status:** beschlossen. (Referenzimplementierung der Formatierung in
  `moritz_agent/tools/time_tool.py` bereits im Gerüst.)

## ADR-018 – Sprache in Code und Dokumentation

- **Entscheidung:** Code, Bezeichner, Commit-Nachrichten, Code-Kommentare: Englisch
  (konsistent mit Upstream). Planung, README, UI-Texte, Ansagen, Systemprompts: Deutsch.
- **Status:** beschlossen (kann Moritz jederzeit ändern).

## ADR-019 – Python-Abhängigkeitsverwaltung

- **Entscheidung:** `pyproject.toml` deklariert Abhängigkeiten in Gruppen (`core`, `phone`,
  `dev`); exakte Versionen werden in `requirements/*.lock` (pip-compile/uv, mit Hashes)
  gepinnt und vom Installer mit `pip install --require-hashes` installiert. Das Upstream-
  `requirements.txt` (KoboldCPP-Konverter) bleibt unberührt.
- **Status:** beschlossen (Lock-Dateien entstehen mit dem ersten Code-Ticket, das eine
  Abhängigkeit einführt).

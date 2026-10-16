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

## ADR-002 – Branding: moritz-agent / m-agent überall

- **Entscheidung (aktualisiert nach F-11/PRD-08):** Alles, was Nutzer sehen, ist
  moritz-agent bzw. m-agent mit dem monochromen Logo (**M + Scribbles**, `assets/branding/`):
  README, eigene WebUI/Favicon, Icons (`niko.ico`/`nikogreen.ico` enthalten jetzt das
  m-agent-Logo), PyInstaller-Metadaten, systemd-Unit, Logs, Ansagen.
- **Maskottchen Scribbles:** Scribbles, das Maskottchen von LayerNX, ist ab sofort das
  Maskottchen von moritz-agent – im Logo (statt des Roboters) und überall, wo die Oberfläche
  eine Figur zeigt. Quelle: `assets/branding/scribbles/scribbles-original.png` (Zeichnung von
  Moritz), daraus per `scripts/build_branding.py` Vektor-SVG, PNGs, Logo und Icons.
  Regeln: [`assets/branding/README.md`](../../assets/branding/README.md).
- **KoboldCpp-Oberflächen entfernt:** KoboldAI Lite, llama.cpp-WebUI, SD-UI, Music-UI und
  die eingebettete API-Doku (`embd_res/*.embd`) sind gelöscht; KoboldCpp startet ohne sie
  (Ladefehler werden dort abgefangen). Zusätzlich lauscht KoboldCpp nur auf Loopback.
- **Nicht umbenannt:** interne Dateinamen/Symbole (`koboldcpp.py`, `koboldcpp_cublas.so`,
  Python-Funktionen), damit Upstream-Merges möglich bleiben. Diese sieht kein Nutzer.
- **Lizenz:** Copyright-/Lizenzhinweise bleiben vollständig; README und
  `THIRD_PARTY_NOTICES.md` nennen KoboldCpp als Basis (AGPL-Pflicht).
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

## ADR-005 – SIP-Stack: PJSIP/PJSUA2 2.17 (im Repo), Python-Binding

- **Entscheidung:** pjproject **2.17** (Commit `5a457451`) liegt unverändert in
  `third_party/pjproject/` (ADR-021) und wird vom Installer gebaut:
  `./configure --enable-shared --disable-video --disable-sound --disable-libyuv --disable-libwebrtc CFLAGS=-fPIC`,
  `make dep && make && make install` nach `runtime/pjsip/`, danach SWIG-Binding
  `pjsip-apps/src/swig/python` ins venv. Konfiguration: `audDevManager().setNullDev()`,
  Conference-Bridge 16 kHz, eigene `AudioMediaPort`-Klasse, Codec-Prioritäten
  G722 > PCMA > PCMU, Rest deaktiviert. Thread-Modell im Spike P1-11 festlegen.
- **R1 („versuch’s trotzdem oder mach’s besser“):** PJSUA2 bleibt Plan A, weil es als einzige
  Option normale Registrierung, G.722, RTP/RTCP, Jitterbuffer und Python-Audio-Callbacks in
  einem gepflegten Paket bietet. Risikominderung: (1) Quellcode im Repo, kein Download;
  (2) Spike zuerst; (3) Callbacks kopieren nur Frames in Ringpuffer, Verarbeitung in eigenen
  Threads; (4) definierter Plan B: Asterisk **AudioSocket** (`Dial(AudioSocket/...)`) –
  Audio als TCP-Strom direkt zum Agent, kein SIP-Stack im Agent nötig; braucht eine Zeile im
  Dialplan (Doku: [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md)).
- **Lizenz:** GPL-2.0-or-later (Teile in `third_party/pjproject/third_party/` mit eigenen
  Lizenzen) → kompatibel zur AGPL-3.0.
- **Status:** beschlossen (Build-Rezept wird im Spike P1-11 bestätigt).

## ADR-006 – STT: faster-whisper **small** auf CPU (int8)

- **Entscheidung (R2):** `faster-whisper` 1.2.x mit Modell `Systran/faster-whisper-small`
  (CTranslate2, 484 MB), `compute_type="int8"`, `language="de"`, `beam_size=1`,
  `cpu_threads=8`, eigene VAD (`vad_filter=False`). Läuft auf der CPU, die GPU bleibt dem LLM.
- **Erwartung auf E5-2673 v3 (AVX2):** grob 0,5–1,5 s für eine 2–5 s lange Äußerung –
  wird im Audio-Spike P1-10 gemessen. Falls zu langsam: `base` als Fallback (gleiche API).
- **Bezug:** Modelldatei > 100 MB → Download durch den Installer (ADR-021).
- **Status:** beschlossen.

## ADR-007 – SearXNG: im Repo (`third_party/searxng`), eigener venv, granian

- **Entscheidung:** SearXNG-Quellcode liegt unverändert in `third_party/searxng/`
  (Commit `8252c0bf`, 16.10.2026) – **fertig gebaut**: Frontend-Assets (`searx/static`) und
  Daten (`searx/data`) sind enthalten, es ist kein Node-/Build-Schritt nötig. SearXNG ist kein
  eigener Dienst, sondern ein vom Supervisor gestarteter Worker des einen Programms. Der
  Installer legt `runtime/searxng-venv/` an und installiert die Abhängigkeiten von PyPI
  (`requirements/searxng.lock` mit Hashes, inkl. `granian`). Geprüft: Start direkt aus dem
  Repo, `/healthz` = OK, Weboberfläche und JSON-Suche antworten. Start:
  `granian --interface wsgi searx.webapp:app --host 127.0.0.1 --port <dyn>` mit
  `SEARXNG_SETTINGS_PATH=config/searxng/settings.yml` und `SEARXNG_SECRET` (beim
  Installieren zufällig erzeugt, in `data/searxng/secret` 0600).
- **Engines (F-09 „alle“):** alle Standard-Engines plus google, bing, qwant, qwant news,
  tagesschau, fireball news. Geprüft: 21 Web-/News-Engines aktiv.
- **Update:** neuen Commit nach `third_party/searxng/` kopieren, Lock neu erzeugen
  (Ablauf in `third_party/VENDORED.md`).
- **Status:** beschlossen.

## ADR-008 – TTS: Stimme „Hans“ (Amazon Polly) als Standard, Piper lokal als Fallback

- **Kontext (F-08, F-08b):** Moritz will die Stimme **Hans**. Hans ist die männliche deutsche
  Standard-Stimme von **Amazon Polly** (Cloud-Sprachausgabe von AWS); lokal gibt es sie nicht.
- **Entscheidung:** TTS-Schnittstelle mit zwei Engines, **Standard = `polly`**:
  1. `polly`: Stimme **Hans**, `Engine=standard`, `OutputFormat=pcm`, `SampleRate=16000`
     (direkt im Telefonformat). Zugangsschlüssel in `passwords.txt` `[optional_services]`
     (`aws_polly_access_key_id`, `aws_polly_secret_access_key`, `aws_polly_region`),
     IAM-Benutzer nur mit `polly:SynthesizeSpeech`. Anleitung für Moritz:
     [`docs/stimme-hans.md`](../stimme-hans.md).
  2. `piper` (lokal, CPU): `de_DE-thorsten-medium`. Springt automatisch ein bei fehlenden
     Schlüsseln, Fehler, Timeout (1,5 s) oder ohne Internet – der Anruf bricht nie ab.
- **Ansagen:** werden beim Einrichten mit Hans vorgerendert und gecacht → Begrüßung klingt
  auch offline nach Hans; ohne AWS-Schlüssel mit Piper.
- **Datenschutz:** Nur Antworttexte gehen an AWS, nie Audio des Anrufers.
- **Status:** beschlossen. Offen ist nur, ob Moritz das AWS-Konto anlegt (bis dahin Piper).

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

## ADR-016 – LLM: Qwen3-30B-A3B-Instruct-2507, halb VRAM / halb RAM

- **Kontext (R3):** Moritz will ein größeres Modell, aufgeteilt etwa **halb RAM, halb VRAM**.
  Dichte Modelle (z. B. 14B/24B) werden mit CPU-Anteil auf einem Haswell-Xeon sehr langsam.
  Ein **Mixture-of-Experts**-Modell aktiviert pro Token nur einen kleinen Teil der Gewichte:
  Die Experten können im RAM liegen, Attention und gemeinsame Gewichte auf der GPU –
  genau die gewünschte Aufteilung, bei brauchbarer Geschwindigkeit.
- **Entscheidung:** `unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF`, Datei
  `Qwen3-30B-A3B-Instruct-2507-UD-Q3_K_XL.gguf` (13.833.048.480 Byte ≈ 13,8 GB; 30B
  Parameter gesamt, 3B aktiv; Apache-2.0; Instruct-Variante ohne Thinking → kurze Antworten,
  gutes Tool-Calling, gutes Deutsch).
- **Start-Flags (in P1-02 feinjustieren):** `--usecuda --gpulayers 999 --moecpu <N>
  --contextsize 4096 --threads 12 --blasthreads 12 --jinja --websearch --quiet`.
  `--moecpu N` hält die Experten der ersten N Schichten im RAM; Startwert N≈24 von 48,
  Ziel: ≈ 6,5–7 GB VRAM belegt, ≈ 6,5–7 GB RAM. N so wählen, dass ≥ 0,6 GB VRAM frei bleiben.
- **Speicherbudget:** passt in das LXC-Limit von 16 GB (siehe 06 §2.2). KV-Cache bei 4.096
  Tokens ≈ 0,4 GB (48 Schichten, 4 KV-Köpfe) → 8.192 ist voraussichtlich möglich (INF-05: messen).
- **Fallbacks:** `Q3_K_S` (13,3 GB) bei Speicherknappheit; `Q4_K_M` (18,6 GB) nur mit
  LXC-RAM > 16 GB; dichtes `Qwen3-14B` Q4_K_M als Notlösung bei MoE-Problemen.
- **Status:** beschlossen (Feinjustierung `--moecpu` in P1-02).

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

## ADR-019 – Python-Abhängigkeiten: Lock-Dateien mit Hashes, Pakete von PyPI

- **Entscheidung:** Gruppen in `requirements/*.in` (`core`, `phone`, `polly`, `searxng`),
  daraus mit `uv pip compile --universal --generate-hashes` erzeugte `requirements/*.lock`.
  Installation von PyPI: `pip install --require-hashes -r requirements/<gruppe>.lock` –
  exakt reproduzierbar, manipulierte Pakete werden abgelehnt.
- **Nicht im Repo:** Moritz: „Prerequirements per requirements.txt sind egal.“ Ein zwischen-
  zeitlich mitgelieferter Wheel-Ordner (≈ 300 MB) wurde deshalb wieder entfernt.
- Geprüft: Für alle Pakete gibt es Wheels für CPython 3.13 und 3.14 (Linux x86_64).
- Das Upstream-`requirements.txt` im Wurzelverzeichnis gehört zu KoboldCpp.
- **Status:** beschlossen.

## ADR-020 – Such-Fallback-Kette (R4)

- **Entscheidung:** `web_search` versucht nacheinander SearXNG → KoboldCpp-Websuche
  (`/api/extra/websearch`, DuckDuckGo, KoboldCpp mit `--websearch`) → Wikipedia-REST →
  ehrliche Fehlermeldung. Optionale API-Dienste mit Schlüssel (Brave, Google Programmable
  Search) werden eingehängt, sobald ein Schlüssel in `passwords.txt` steht. Details:
  [11-suchoptionen.md](11-suchoptionen.md).
- **Status:** beschlossen.

## ADR-021 – Programmbestandteile im Repository (`third_party/`)

- **Kontext:** Moritz: SearXNG „und sowas alles“ muss mit rein, damit alles **standalone als
  ein Programm** läuft; Hugging-Face-Modelle und Requirements dürfen aus dem Netz kommen.
- **Entscheidung:** Im Repo liegen alle **Programmbestandteile**: `third_party/searxng`
  (fertig gebaut), `third_party/pjproject` (Quellcode, wird beim Installieren kompiliert),
  `assets/models/vad/silero_vad.onnx` (2,3 MB). Unverändert übernommen; Herkunft/Version/
  Lizenz in `third_party/VENDORED.md`. Änderungen daran nur als dokumentierter Patch.
- **Aus dem Netz (bewusst):** Python-Pakete von PyPI (Hashes, ADR-019), die CUDA-Build-
  Toolchain für KoboldCpp (`koboldcpp.sh`, Conda), Ubuntu-Systempakete, der NVIDIA-Treiber
  und die Modelle von Hugging Face (LLM 13,8 GB, Whisper small 484 MB, Piper-Stimme 63 MB;
  Größenprüfung, SHA-256 per TOFU in `data/state/model-hashes.json`).
- **Kosten:** ≈ 95 MB zusätzlich im Repo.
- **Status:** beschlossen.

## ADR-022 – Web-UI im LAN auf Port 3501 mit TLS

- **Entscheidung (F-04):** Bindung `0.0.0.0:3501`, nur mit aktivem Web-Login (API-02).
  HTTPS mit **selbst signiertem Zertifikat**, das der Installer erzeugt
  (`runtime/tls/cert.pem`, `key.pem` 0600, 10 Jahre, SAN = LXC-IP + Hostname). Eigenes
  Zertifikat oder Reverse-Proxy optional (`server.tls_cert`, `server.tls_key`). HTTP wird
  nicht angeboten (`server.tls = false` nur für Tests).
- **Status:** beschlossen.

## ADR-023 – Lizenzen: eigener Code MSOL 1.1, Fremdcode behält seine Lizenz

- **Entscheidung (R12, F-14, F-17):**
  - Eigener Code und eigene Doku von moritz-agent: **Moritzsoft Open License (MSOL) 1.1**
    ([`LICENSE-MSOL.md`](../../LICENSE-MSOL.md)), moritz-agent ist ein *Public Release*.
    Quelltexte tragen `SPDX-License-Identifier: LicenseRef-MSOL-1.1`.
  - Scribbles und das m-agent-Logo: **© LayerNX / Moritz Eckhard Nickel, alle Rechte
    vorbehalten** – weder MSOL noch AGPL.
  - KoboldCpp und Upstream-Dateien AGPL-3.0, ggml/llama.cpp MIT, SearXNG AGPL-3.0,
    pjproject GPL-2.0+, Piper GPL-3.0, Silero MIT – unverändert.
  - Zuordnung je Pfad: [`LICENSING.md`](../../LICENSING.md).
- **Verträglichkeit:** MSOL 1.1 ist freizügig (inkl. Unterlizenzierung, keine Zusatzpflichten
  außer §6 Namensrecht und dem Gewährleistungsausschluss) und lässt sich daher mit dem
  AGPL-/GPL-Code kombinieren. Für das Gesamtpaket gelten zusätzlich die AGPL-/GPL-Pflichten
  der Fremdteile (Quellcode anbieten, deren Hinweise behalten). Keine Rechtsberatung.
- **Status:** beschlossen.

## ADR-024 – Zielsystem Ubuntu 26.04 / 25.10, System-Python

- **Entscheidung (F-05):** Ubuntu 26.04 LTS (bevorzugt) oder 25.10 im LXC. System-Python
  (3.14 bzw. 3.13) mit venv; alle Abhängigkeiten haben Wheels für beide Versionen (ADR-019).
  KoboldCpp-Build über `./koboldcpp.sh rebuild` (Conda-Toolchain, ADR-015).
- **Status:** beschlossen.

## ADR-025 – Fast-Paths für einfache Infos

- **Entscheidung (F-13):** Deterministische Antworten ohne LLM für den Katalog in
  [12-fast-paths.md](12-fast-paths.md). Erkennung nur bei eindeutigen Mustern; sonst Agent-Loop.
- **Status:** beschlossen.

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

## ADR-008 – TTS: Stimme „Hans“ (Amazon Polly) – **ersetzt durch ADR-027**

- **Kontext (F-08, F-08b):** Moritz wollte zunächst die Stimme **Hans** (Amazon Polly, Cloud).
- **Entscheidung (16.10.2026):** Engine `polly` als Standard, `piper` lokal als Fallback.
- **Status:** **abgelöst am 17.10.2026** durch ADR-027 (Moritz: „wir nehmen ab jetzt als Stimme
  diese hier für Nikita“ – Thorsten-Voice Hessisch, lokal auf der CPU). Polly, die
  AWS-Zugangsdaten und `docs/stimme-hans.md` sind entfernt; sie bleiben in der Git-Historie
  (Commit `cbb5520`) und lassen sich bei Bedarf als zusätzliche Engine wiederherstellen.

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

- **Entscheidung:** Gruppen in `requirements/*.in` (`core`, `phone`, `tts`, `searxng`),
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
- **Status:** beschlossen; **erweitert durch ADR-029** (Fast-Paths gehen in den Sofortauskünften auf,
  Wetter ist nicht mehr Sache der Websuche).

## ADR-026 – Name des Assistenten: Nikita

- **Entscheidung (Moritz, 16.10.2026):** Der Assistent heißt **Nikita** – ein Mann, deshalb
  die männliche Stimme Thorsten-Voice (ADR-027). Er stellt sich so
  vor („Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?“), der Systemprompt und der
  Fast-Path `identity` verwenden den Namen, der SIP-Anzeigename (`display_name`) und die
  Anrufer-ID in Asterisk lauten Nikita, und die Oberfläche spricht von Nikita.
  Konfigurierbar über `phone.assistant_name`.
- **Unverändert:** Produkt-/Repo-Name `moritz-agent` (Kurzform m-agent), Paketname
  `moritz_agent`, SIP-Konto `agent` (Benutzername/Passwort in Asterisk und `passwords.txt`),
  Maskottchen Scribbles. Der Originalplan (`00-originalplan.md`) bleibt als Referenz unverändert.
- **Status:** beschlossen.

## ADR-027 – Stimme: Thorsten-Voice „Hessisch“ als Piper-Modell auf der CPU

- **Kontext (Moritz, 17./18.10.2026):** Nikita bekommt die Stimme von Thorsten-Voice, **auch die
  hessische Variante**, lokal auf der CPU, vorgefertigte Ansagen gecacht. Zuerst wurde
  CosyVoice3-Hessisch gebaut (17.10.), am 18.10.2026 ersetzt: „nimm nur Piper – das müsste das
  Hessische ja auch können und ist leichter“. Das stimmt: `Thorsten-Voice/Hessisch` enthält ein
  fertiges **Piper-Modell** (`Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx`, 114 MB, Einzelsprecher,
  22,05 kHz, Lizenz CC0). Ersetzt ADR-008 (Polly „Hans“): keine Cloud, keine Zugangsdaten,
  nichts verlässt das Haus.
- **Entscheidung – Stimmenkette** (`phone.tts.engine` + `fallback_engines`):
  1. **`piper`** (Hauptstimme): das Hessisch-Modell, in-process über `piper-tts`/onnxruntime auf der
     CPU (`phone.tts.cpu_threads`, Start 4). Kein zweiter Prozess, keine zusätzliche Python-Umgebung,
     kein PyTorch. Modell lädt `models.py` von Hugging Face (Größe geprüft, SHA-256 beim ersten Mal
     gemerkt). Jede andere Piper-Stimme lässt sich über `phone.tts.piper.voice` eintragen
     (z. B. `de_DE-thorsten-medium` für Hochdeutsch).
  2. **`espeak`** (espeak-ng, Systempaket): Notstimme, falls das Piper-Modell fehlt oder defekt ist,
     und für den Selbsttest. Roboterhaft, aber das Telefon bleibt benutzbar.
- **Cache der vorgefertigten Ansagen:** Feste Texte (Begrüßung, Fehler- und Zwischenansagen,
  Katalog `assets/audio/prompts.de.toml`) werden einmal gerendert und als 16-kHz-WAV in
  `assets/audio/cache/` abgelegt. Schlüssel = `sha256(Version | Engine | Stimme+Modellgröße |
  Lautheit | Satz)`: Ein anderes Modell oder anderer Text rendert neu, alles andere kommt sofort
  aus dem Cache. Das Telefon startet nie ohne sprechbare Ansagen (ADR-011). Live-Sätze liegen nur
  in einem Arbeitsspeicher-Cache (LRU, `live_cache_entries`) – **nie auf der Platte** (PHONE-43).
- **Live-Antworten** werden satzweise gesprochen, damit der erste Satz schon läuft, während der
  Rest entsteht; fällt die Hauptstimme mitten im Satz aus, übernimmt die Notstimme.
- **Text → Sprache:** `moritz_agent/phone/audio/textnorm.py` schreibt Zahlen, Datum, Uhrzeit, Euro,
  Einheiten und Abkürzungen als deutsche Wörter aus, entfernt Markdown und Emojis; Lautheit aller
  Stimmen −20 dBFS, Spitzen ≤ −1,5 dBFS.
- **Folgen:** RAM der Stimme ≈ 0,3–0,6 GB (statt ≈ 5 GB bei CosyVoice) – das 16-GB-Budget aus
  [06](06-infrastruktur.md) bleibt; nur ≈ 0,6 GB Download für Whisper + Stimme. Lizenzen: Modell
  CC0, `piper-tts` GPL-3.0 (als PyPI-Paket genutzt), espeak-ng GPL (Systempaket).
- **Verworfen:** CosyVoice3-Hessisch (4,4 GB Download, ≈ 5 GB RAM, eigene torch-Umgebung, auf der
  CPU voraussichtlich langsamer als Echtzeit). Code und Plan stehen in der Git-Historie
  (Commit `2f308a3`), falls je eine ausdrucksstärkere Stimme gewünscht ist.
- **Offen:** Klang und Geschwindigkeit des Modells auf dem Zielrechner sind noch nicht gehört bzw.
  gemessen (R16, R17); `./test-1.sh speak` / `bench` zeigen es.
- **Status:** beschlossen und gebaut (Ticket P1-10…P1-13).

## ADR-028 – Installation vom Proxmox-Host aus: `install.sh` legt den LXC an, `update.sh` aktualisiert ihn

- **Kontext (Moritz, 18.10.2026):** „Baue in setup.sh und install.sh und sowas, dass es den LXC und
  alles vom Proxmox-Host aus als sudo automatisch aufsetzt oder updated. Geht ja per scp und allem
  drum und dran in einer Konsole von Sophie-1 oder dem Proxmox-Host aus.“ Außerdem: der Test
  (`./test-1.sh`) soll **nicht** von einem LXC-Setup ausgehen.
- **Entscheidung – drei voneinander unabhängige Ebenen:**
  1. **Host** (`install.sh`, `update.sh`, Bibliothek `deploy/lib/host.sh`): benutzt nur `pct`,
     `pveam`, `pvesm`. Legt den Container an (unprivilegiert, `nesting=1`, `onboot`, Ubuntu 26.04 →
     25.10 → 24.04, 18 Kerne mit `cpuunits 512`, 16 GB RAM-Limit, 80 GB Platte, feste Werte aus
     [06 §3](06-infrastruktur.md)), startet ihn, reicht optional die NVIDIA-Geräte durch
     (Proxmox ≥ 8.1, `devN`-Einträge mit `gid`), kopiert das Programm hinein und startet dort
     `moritz-install.sh`. Existiert der Container schon (Name `moritz-agent` oder `--ctid`), ist
     derselbe Aufruf ein Update bzw. setzt eine abgebrochene Installation fort. Läuft als root auf
     dem Host **oder** mit `--remote [user@]host` von einem anderen Rechner: das Programm (ca. 14 MB,
     `deploy/payload.txt`) wird per `scp` kopiert und per `ssh -t` mit `sudo` ausgeführt.
  2. **Container** (`moritz-install.sh`, `moritz-update.sh`): läuft im LXC (oder auf jedem
     Ubuntu/Debian), vom Host in ein Staging-Verzeichnis kopiert und **von dort** gestartet – ein
     neuer Updater aktualisiert also immer eine ältere Installation. Installation: Pakete,
     Dienstbenutzer, Programmdateien, Python-Umgebung, PJSIP, Modelle, `passwords.txt` und
     `config/moritz-agent.toml` (nur wenn sie fehlen), Ansagen, systemd-Dienst, Prüfung. Update:
     Wartungsmodus (laufendes Gespräch abwarten, sonst Exit 75), Sicherung, neue venv bei geänderten
     Paketen, Stopp, Austausch, Start + Prüfung, **Rollback** bei Fehler (Exit 70/71).
  3. **`./test-1.sh`** (ADR-027): ohne root, ohne LXC, ohne Proxmox – gleicher Code, anderer Rahmen.
- **Programm-Transport statt Git im Container:** Der Container braucht keinen GitHub-Zugang; installiert
  wird exakt der Stand des Ordners, aus dem das Skript läuft (geprüft, getestet, notfalls
  ausgecheckter Tag). Die Liste der Programmteile steht in `deploy/payload.txt`; Benutzerdaten
  (`passwords.txt`, `config/moritz-agent.toml`, `models/`, `data/`, `runtime/`, Ansagen-Cache) sind
  nie Teil davon und werden nie überschrieben oder gelöscht. Dateien, die eine neue Version nicht
  mehr mitbringt, werden anhand der Dateiliste der alten Version entfernt.
- **Wartungsmodus ohne Web-API:** Der Dienst schreibt jede Sekunde `data/run/phone-status.json`; der
  Updater legt `data/run/drain` an – neue Anrufe bekommen SIP 486, das laufende Gespräch läuft zu Ende.
- **Sicherheitsnetze beim Update:** Proxmox-Snapshot `moritz-pre-update-<Zeit>` des Containers (die
  letzten 3 bleiben; `--no-snapshot`/`--require-snapshot`), Sicherung im Container (`backups/<Zeit>/`
  mit `passwords.txt`, Konfiguration, Zustand und dem alten Programmcode, die letzten 5), alte venv
  als `venv.prev`.
- **Was am Proxmox-Host geändert wird (ändert INST-02):** nur eine fehlende Ubuntu-Vorlage laden,
  **einen** neuen Container anlegen bzw. dessen `dev`-Einträge ergänzen, Snapshots dieses Containers.
  Keine Host-Pakete, Treiber, Netzwerk-/Firewall-/Speicherkonfiguration, keine anderen Gäste.
  Der Container bekommt **kein** Root-Passwort (Zugang per `pct enter`; optional `--ssh-key`); es werden
  nie Passwörter als Argumente oder Umgebungsvariablen übergeben.
- **Nicht Teil davon (bewusst):** NVIDIA-Treiber am Host und im Container (Plan 06 §4 – erst fürs
  Sprachmodell nötig; das Skript nennt die Host-Treiberversion), nftables-Firewall im Container
  (06 §5), Asterisk-Konfiguration (INST-09), KoboldCpp-/SearXNG-/TLS-Phasen (kommen mit P1-02, P1-08, P1-14).
- **Verworfen:** Docker/Compose (Plan: LXC), Ansible (zusätzliche Abhängigkeit für ein
  Einzelsystem), Git-Pull im Container.
- **Status:** beschlossen und gebaut (P1-15, P1-16); Teststand siehe
  [`docs/proxmox-installation.md`](../proxmox-installation.md) – gegen einen echten Proxmox-Host noch
  nicht gelaufen.

## ADR-029 – Sofortauskünfte (Skills) vor dem Sprachmodell; jeder Skill ist auch ein Tool

- **Kontext (Moritz, 18.10.2026):** „Bevor wir LLM und richtige Agent-Instanzen machen, will ich Nikita
  nach Uhrzeit, Datum und simplen Sachen wie dem Wetter in der Region fragen können. Standard ist 35781
  Weilburg, außer PLZ oder was anderes wird gesagt.“ Bisher waren Wetter, Preise und Sport ausdrücklich
  Sache der Websuche (12 §3), also erst mit LLM möglich – und dort langsam und halluzinationsanfällig.
- **Entscheidung:**
  1. Neues Paket `moritz_agent/skills/` (Plan [13](13-sofortauskuenfte.md)): Vorverarbeitung
     (Normalisieren, Hessisch-Wörterbuch, Zahlwörter), regelbasierte Erkennung mit Score und
     Ausschlusslisten, Angaben-Parser für Zeit/Ort/Zahl, Dialogkontext für Folgefragen, Provider mit
     Cache und Zeitbudget, deutscher Renderer.
  2. `SkillResponder` ersetzt den `TestResponder` am Telefon. Reihenfolge fest: **erst Skills, dann
     LLM** (ab P1-09); kein Treffer → heute die Testantwort.
  3. Die Fast-Paths (ADR-025) werden Skills; `agent/fastpath.py` bleibt als Fassade, bis alle
     Aufrufer umgestellt sind (SKILL-33).
  4. Jeder Skill erzeugt ein Tool mit JSON-Schema (P1-07); das Phone-Profil bekommt die lesenden
     Skill-Tools (PHONE-45). **Wetter-Garantie** (AGENT-11): LLM-Antworten mit Wetterwerten ohne
     Tool-Aufruf werden verworfen.
  5. Heimatort 35781 Weilburg (`skills.home`), Bundesland für Feiertage/Ferien wandert von
     `fastpaths.state` nach `skills.home.state` (alte Schlüssel werden bis 1.0 weiter gelesen).
- **Alternativen:** (a) Wetter weiter über `web_search` + LLM – verworfen: braucht das LLM, Sekunden
  statt Millisekunden, Zahlen nicht prüfbar. (b) Kleines Intent-Modell (z. B. Rasa/NLU) – verworfen
  für Part 1: Trainingsdaten fehlen, Fehlerbilder schwer erklärbar; Regeln + Korpus sind prüfbar und
  für ~180 klar umrissene Fragen ausreichend; ein Klassifikator kann später **zusätzlich** als
  Kandidatenquelle dienen. (c) Alles erst mit dem LLM über Tools – verworfen: Moritz will die
  Funktionen **vor** dem LLM.
- **Konsequenzen:** Block S (P1-19 … P1-30) wird vor den LLM-Tickets umgesetzt; 12 §3 ist geändert;
  neuer Testkorpus (≥ 800 Äußerungen); P1-07/P1-09 bauen auf `skills/tools.py` auf.
- **Status:** beschlossen (Plan); Umsetzung offen.

## ADR-030 – Wetterdaten: Open-Meteo als Hauptquelle, DWD (über Bright Sky und Open Data) für Warnungen, Pollen und Rückfall

- **Kontext:** Wetter für Weilburg und jeden Ort in Deutschland (gelegentlich Ausland), ohne Konto,
  ohne Kosten, mit Lizenz für die Nutzung, schnell und mit Stunden-/Tageswerten. Moritz, 18.10.2026:
  „Wetter bitte Open Source, free if possible.“
- **Entscheidung:**
  - **Open-Meteo** Forecast-API: ein Abruf je Ort liefert aktuelle, 15-Minuten-, Stunden- und
    Tageswerte (bis 16 Tage, `past_days` für Rückblicke); für Deutschland rechnet Open-Meteo mit den
    DWD-ICON-Modellen (`models=best_match`, wahlweise `icon_seamless`). Ohne Schlüssel; Daten CC BY 4.0;
    freie Nutzung nur nicht kommerziell und unter 10.000 Aufrufen/Tag – passt für ein privates Homelab
    mit Vorabruf alle 30 min. Luftqualität/CAMS-Pollen und Geocoding ebenfalls von Open-Meteo.
  - **Bright Sky** (freie JSON-API für DWD-Open-Data): DWD-Warnungen je Ort (`/alerts`, liefert auch die
    Warnzelle), Stationsmessungen und MOSMIX-Vorhersage als **Rückfall**.
  - **DWD Open Data** direkt: Pollenflug-Gefahrenindex (`s31fg.json`), UV/Biowetter-Dateien. DWD-Daten
    stehen unter CC BY 4.0.
  - **NINA** (BBK): Bevölkerungswarnungen auf Kreisebene (ARS des Landkreises Limburg-Weilburg).
  - Jede Antwort wird gegen ein Schema und Wertebereiche geprüft; Cache mit Stale-Regeln (13 §3.6).
  - **Nur Open Source und kostenlos (SKILL-35):** Open-Meteo (Software AGPL-3.0) und Bright Sky
    (Software MIT) sind Open Source, DWD und BBK liefern amtliche offene Daten; alle ohne Konto,
    Schlüssel oder Kosten, Daten unter CC BY 4.0. Proprietäre Wetter-APIs werden auch nicht als
    Rückfall eingebaut. Die Adressen (`skills.weather.open_meteo_url`, `brightsky_url`) sind
    konfigurierbar, damit später eine eigene Instanz im Homelab genutzt werden kann.
- **Alternativen:** OpenWeatherMap/Weatherbit/Tomorrow.io/AccuWeather (proprietär, Schlüssel,
  Kontingente, Kosten – verworfen nach SKILL-35); Scraping von Wetterportalen (AGB, fragil);
  DWD-MOSMIX-Rohdaten selbst parsen (Aufwand, Bright Sky macht das); eigener Open-Meteo-/Bright-Sky-
  Server von Anfang an (Platz/Rechenzeit; später möglich, falls die öffentlichen Instanzen wegfallen –
  R20).
- **Konsequenzen:** ausgehendes HTTPS zu wenigen festen Hosts (ADR-032); Namensnennung der Quellen
  (SKILL-14); Bedingungen werden vor Inbetriebnahme jeder Quelle geprüft und in
  `THIRD_PARTY_NOTICES.md` eingetragen.
- **Status:** beschlossen (Plan).

## ADR-031 – Orte offline: GeoNames-Daten im Repository, Heimatort 35781 Weilburg

- **Kontext:** „Standard ist 35781 Weilburg, außer PLZ oder was anderes wird gesagt.“ Orte müssen
  schnell, ohne Netz und robust gegen Erkennungsfehler aufgelöst werden („Weilborg“, „35 781“).
- **Entscheidung:** Postleitzahlen und bewohnte Orte Deutschlands sowie Weltstädte ≥ 15.000 Einwohner
  aus **GeoNames** (CC BY 4.0) werden per `scripts/build_geodata.py` in kompakte TSV-Dateien unter
  `assets/data/geo/` umgewandelt und mitgeliefert (Herkunft und Prüfsummen in
  `third_party/VENDORED.md`, nur per Skript zu ändern). Auflösung: exakt → ohne Zusätze → Ortsteile →
  unscharf (`difflib`) → phonetisch (Kölner Phonetik); mehrdeutig → Einwohner- und Nähe-Score,
  sonst Rückfrage. Nur unbekannte (meist ausländische) Orte gehen online an das Open-Meteo-Geocoding.
- **Alternativen:** Nominatim/OSM online je Frage (Nutzungsrichtlinie max. 1 Anfrage/s, Netzabhängigkeit),
  Google Geocoding (Schlüssel, Kosten), nur Postleitzahlen ohne Ortsnamen (zu wenig).
- **Konsequenzen:** ≈ 40–80 MB RAM; CLAUDE.md nennt `assets/data/geo/` bei den Daten.
- **Stand 21.10.2026 (Abweichung):** Das Repository enthält nur die handgepflegte Grundmenge; die vollständigen
  GeoNames-Listen (≈ 6–7 MB) erzeugt `scripts/build_geodata.py` beim Einrichten (Installer-Phase `geodata`).
  Statt `rapidfuzz` wird `difflib` benutzt, daher keine neue Abhängigkeit.
- **Status:** beschlossen (Plan), umgesetzt mit der Abweichung oben.

## ADR-032 – Externe Datenabrufe aus dem LXC

- **Kontext:** Bisher holte der Dienst nur bei Installation/Update Daten aus dem Netz (PyPI, Hugging
  Face) und später über SearXNG. Sofortauskünfte fragen im Betrieb regelmäßig Datendienste ab.
- **Entscheidung:** Ein gemeinsamer HTTP-Client (`skills/providers/http.py`): nur `https://`, nur Hosts
  einer festen Liste (Open-Meteo, Bright Sky, DWD Open Data, NINA, PEGELONLINE, EZB, Energy-Charts,
  Tankerkönig, OpenLigaDB, Nachrichtenquelle – je nach Aktivierung), Weiterleitungen nur innerhalb der
  Liste, Zeitlimits 1,5 s/3 s, Antwort ≤ 2 MB, identifizierender User-Agent
  (`moritz-agent/<version>`), Backoff bei 429/5xx, **keine Query-Strings in Logs**. Gesendet werden
  nur gerundete Koordinaten (2 Nachkommastellen), PLZ/Ortsnamen und fachliche Kennungen. Vom Nutzer
  konfigurierte URLs (iCal) nur `https://` und nie auf private/lokale Adressen. Einzige Ausnahme: eine
  ausdrücklich als `open_meteo_url`/`brightsky_url` eingetragene eigene Instanz (darf im LAN liegen).
- **Alternativen:** Proxy über SearXNG (passt nicht zu strukturierten APIs); nftables-Allowlist nach
  Hostnamen (mit wechselnden CDN-Adressen nicht stabil) – die Firewall erlaubt weiter tcp/443 ausgehend
  (06 §5), die Liste wird in der Anwendung durchgesetzt.
- **Konsequenzen:** neue Bedrohungen T19–T24 in [08](08-sicherheit.md); Netztests nur mit
  `@pytest.mark.network`; `skills.online = false` schaltet alle Abrufe ab.
- **Status:** beschlossen (Plan).

## ADR-033 – Discord-Kanal: offizieller Bot, Server- und Benutzer-Installation, eigener Worker mit discord.py

- **Kontext (Moritz, 20.10.2026):** „Plane eine komplette Discord-User-Integration mit allen Features,
  die Nikita jemals hat, und mach ihn zu einem Bot. Beim Setup gibt man den Token ein oder auch in die
  TXT.“ Plan: [14-discord.md](14-discord.md).
- **Entscheidung:**
  1. Nikita ist der **Bot** einer eigenen Discord-Anwendung. „Public Bot“ aus, Server-Installation
     (eigene Server: Chat, Sprache, Threads) **und** Benutzer-Installation (Befehle überall, wo Moritz
     ist). Ein Benutzer-Token („Self-Bot“) wird nie verwendet – verstößt gegen Discords
     Nutzungsbedingungen und gefährdet Moritz’ Konto.
  2. Eigener Prozess **Discord-Worker** (`python -m moritz_agent.discord run`), vom Supervisor
     verwaltet (bis P1-04 von `moritz-agent run`), `nice +5`, Statusdatei, Wartungsmodus wie das
     Telefon. Nur ausgehende Verbindungen: Gateway/REST über TCP 443, Sprache über UDP – kein
     eingehender Port, kein Webhook-Endpunkt.
  3. Bibliothek **discord.py ≥ 2.7 mit `[voice]`** (MIT; Gateway, Slash-Befehle, Komponenten, Sprache
     senden mit DAVE über `davey`). Lock-Gruppe `requirements/discord.lock` (ADR-019).
  4. Token **und Standard-Textkanal-ID** in `passwords.txt` (`[discord] bot_token`, `channel_id`;
     Moritz: „beim Setup oder in der TXT“); Setup-Phase `discord` im Installer mit verdeckter
     Token-Eingabe über stdin, Prüfung gegen die API, Einladungslinks und Kanalauswahl; Updater hängt
     den Abschnitt leer an.
  5. **Privatserver** (Nachtrag 20.10.2026): Nikitas Server enthält nur Moritz und Nikita. Der
     Standard-Textkanal ist ihr Zuhause (Antwort auf alles, Ziel aller Hinweise); der Server dieses
     Kanals ist automatisch erlaubt.
- **Alternativen:** Self-Bot (verboten), Interactions-Endpunkt per HTTPS-Webhook (bräuchte eine
  öffentliche Adresse und eingehenden Port – verworfen), Pycord (Sprache senden mit DAVE seit 2.8,
  Empfang laut Doku mit Vorbehalt; kein Vorteil gegenüber discord.py), hikari (keine eingebaute
  Sprache), discord.js/Node-Worker (zweite Laufzeit im LXC, Audio-Bausteine sind Python),
  Matrix/Telegram statt Discord (nicht gewünscht).
- **Konsequenzen:** Block D (P1-31 … P1-43) in [04](04-part1-umsetzung.md); neue Bedrohungen T25–T32;
  neue Anforderungen DISCORD-01 … DISCORD-47.
- **Status:** beschlossen (Plan); Umsetzung offen.

## ADR-034 – Kanalunabhängiger Kern und Ausgabeprofile je Oberfläche

- **Kontext:** Nikita soll auf Discord **alles** können, was sie irgendwo kann – heute und in jedem
  späteren Part. Zwei Implementierungen derselben Funktion würden auseinanderlaufen.
- **Entscheidung:** Ein Nikita-Kern (SkillResponder → Agent, Tools, Gedächtnis, Aufgaben) bekommt
  Turns mit `principal` (wer, Rolle, persönliche Einstellungen), `channel` (`phone|discord|web`, Ort)
  und `surface` (`spoken|chat`). Kanäle sind dünne Adapter. Skills liefern gesprochenen Text **und**
  `markdown`, `card` und `actions` ([13 §3.3](13-sofortauskuenfte.md#33-schnittstellen)); das LLM-Profil
  wird je Surface gewählt (`phone`, `discord_voice`, `discord_chat`). **Kanal-Parität** wird DoD-Punkt
  jedes Tickets: neue Funktionen kommen im selben Ticket auf alle Kanäle oder die Ausnahme wird
  begründet (Matrix [14 §6](14-discord.md#6-funktionsumfang-alle-funktionen-auf-allen-kanälen)).
- **Alternativen:** Discord-eigene Logik (doppelter Code, Abweichungen), alles über das LLM (langsam,
  verliert die deterministischen Sofortauskünfte).
- **Konsequenzen:** Ticket P1-31 (Kanal-Kern) vor allen Discord-Tickets; `TurnContext` wird
  erweitert; `call_turns`/`tool_calls` bekommen eine Spalte `channel`.
- **Status:** beschlossen (Plan).

## ADR-035 – Zugriffsmodell auf Discord

- **Kontext:** Das Telefon ist nur im LAN erreichbar, Discord aus dem Internet. Discord-Identitäten
  sind besser geschützt als eine Rufnummer, aber Konten können übernommen werden.
- **Entscheidung:** Standard **verweigern**. Rollen an der unveränderlichen Discord-Benutzer-ID:
  Owner (aus dem Besitzer der Anwendung übernommen), Vertraut (Liste), Gast (Standard: ignoriert;
  optional nur Sofortauskünfte in freigegebenen Kanälen). Weil der Server ein Privatserver ist, gibt es
  im Gespräch **keine** Personenauswahl und kein Weckwort; die Rollen wirken nur als Sicherheitsnetz
  gegen Fremde (die ignoriert und einmal gemeldet werden). Server-Allowlist, fremde Server werden
  verlassen. Rate-Limits je Rolle. Admin-Befehle nur Owner, nur DM/ephemeral, Zustandsänderungen mit
  Bestätigungsknopf, optional PIN aus `passwords.txt`. Nie: Shell im LXC, Updates, Dateizugriff,
  Secrets. Sandbox/Browser (Part 4/6) nur Owner mit Bestätigung je riskanter Aktion. `allowed_mentions`
  nie `@everyone`/`@here`/Rollen. Inhalte Dritter sind Daten, keine Anweisungen.
- **Alternativen:** Discord-Serverrollen als Berechtigung (Serveradmins könnten sich selbst Rechte
  geben – verworfen), offener Bot mit Moderation (unnötiges Risiko).
- **Konsequenzen:** T25–T31 in [08](08-sicherheit.md); Tests der vollständigen Rollenmatrix.
- **Status:** beschlossen (Plan).

## ADR-036 – Discord-Sprache: DAVE-Pflicht, Empfang erst nach Spike, Rückfallwege

- **Kontext:** Seit März 2026 verlangt Discord Ende-zu-Ende-Verschlüsselung (DAVE) für alle Sprach- und
  Videoanrufe (Bühnenkanäle ausgenommen). discord.py ≥ 2.7 kann mit `davey` **senden**; Audio
  **empfangen** kann discord.py nicht selbst, und die Erweiterung `discord-ext-voice-recv`
  entschlüsselt DAVE in der veröffentlichten Fassung nicht – es gibt mehrere Forks/PRs dafür.
- **Entscheidung:**
  1. Sprache senden mit discord.py + davey (gesetzt).
  2. Sprache empfangen: **Spike P1-32** vergleicht die DAVE-fähigen Fassungen von
     `discord-ext-voice-recv` und die Python-Bindung an Discords `libdave` (Kriterien: 60 min ohne
     Abbruch, Sprecher- und Schlüsselwechsel, Reconnect, CPU-Last). Stabil → von PyPI, sonst als
     dokumentierte Fremdkomponente in `third_party/` (ADR-021).
  3. Nicht stabil → Modus **„nur sprechen“** (Text im Sprachkanal-Chat oder Sprachnachricht rein,
     gesprochene Antwort raus) und optional Bühnenkanal ohne E2EE; Spike wird wiederholt, sobald eine
     Bibliothek DAVE-Empfang offiziell unterstützt.
  4. Audio-Kette mit den Bausteinen des Telefons (VAD, Whisper, Piper, Resampling), aber im
     Discord-Worker und **nur während Sprachsitzungen geladen** (ab `/joinvc`); höchstens eine Sitzung;
     Barge-in erlaubt (kein Echo im Discord-Audio).
  5. **`/joinvc` = Anruf** (Nachtrag 20.10.2026): Der Sprachkanal benutzt dieselbe `CallSession` und
     denselben Zustandsautomaten wie das Telefon über eine gemeinsame Schnittstelle `MediaChannel`
     (SIP-Anruf bzw. Discord-Sprachkanal). Moritz betritt den Kanal = Anruf angenommen (Begrüßung wie
     PHONE-21), verlässt ihn = aufgelegt; „Tschüss“ = Abschied und Nikita geht; lange Stille = Ruhe-Modus
     (still im Kanal, „Nikita“ weckt) oder wie am Telefon gehen (`on_silence`).
- **Alternativen:** gemeinsamer Sprachdienst für Telefon und Discord (spart ≈ 1 GB RAM, koppelt aber
  Discord an den Telefon-Prozess – „verworfen für jetzt“, neu bewerten nach der RAM-Messung in P1-36);
  Node-Worker mit @discordjs/voice (hat eigene DAVE-Empfangsprobleme, zweite Laufzeit); nur
  Sprachnachrichten ohne Sprachkanal (zu wenig).
- **Konsequenzen:** Risiko R27; DISCORD-23 ist SOLL, DISCORD-24 (Rückfall) MUSS.
- **Stand 21.10.2026:** Der Code unterstützt beide Ausgänge (Empfang über die optionale Erweiterung, sonst „nur
  sprechen“); der Spike P1-32 ist **offen** ([Protokoll](../abnahme/p1-32-discord-spike.md)).
- **Status:** vorläufig – bestätigt oder geändert durch P1-32.

## ADR-037 – Nikita auf Discord: ein bisschen süß, mit schelmischen Aktivitäten

- **Kontext (Moritz, 20.10.2026):** „Mache den User bitte bissl cutey. Er soll als Aktivitäten coole
  Sachen haben wie ‚spielt mit deinen Daten‘ – schelmisch, funny.“
- **Entscheidung:**
  1. **Stil** `discord.style = "cute"` (Standard): Die Kern-Antwort bleibt neutral und exakt; ein
     Stil-Renderer im Discord-Adapter ergänzt höchstens 1–2 passende Emojis, gelegentlich ein Kaomoji
     und herzliche Floskeln aus eigenen Textlisten (`assets/data/discord/stil.de.toml`), deterministisch
     je Nachricht. **Ernst-Modus** ohne Späße bei Warnungen ab Stufe 2, Katastrophen, Admin,
     Sicherheit und Fehlern mit Datenverlust. Gesprochene Antworten bleiben wie am Telefon.
  2. **Aktivitäten:** rotierende, schelmisch-lustige Aktivitäten („Spielt mit deinen Daten 😈“, „Hört
     deinem Kühlschrank zu“, „Schaut Wolken über Weilburg zu“ …) aus
     `assets/data/discord/aktivitaeten.de.toml`, alle 7–15 min, keine Wiederholung unter 10; lagebezogene
     Aktivitäten haben Vorrang (Anruf, Sprachkanal, Nacht, Wetter, Sonderdaten, Wartung, Unwetter im
     Ernst-Modus). Nie Texte, die wie echte Vorfälle wirken; `/aktivitaet` zum Wechseln, Abschalten und
     für eigene Sprüche.
  3. **Profil:** Name „Nikita“, Bio im gleichen Ton, Avatar und Banner aus Scribbles **monochrom** über
     `scripts/build_branding.py` (Branding-Regeln: keine Farben, nicht neu zeichnen – eine niedlichere
     Pose kann nur Moritz zeichnen).
- **Alternativen:** neutraler Ton (nicht gewünscht); Stil im LLM allein (nicht deterministisch, gilt
  nicht für Sofortauskünfte); farbiger Kawaii-Avatar (verstößt gegen die Branding-Regeln).
- **Konsequenzen:** DISCORD-43, DISCORD-44, Ticket P1-43, Risiko R34; `/hilfe datenschutz` stellt klar,
  dass Nikita nicht wirklich mit Daten spielt.
- **Status:** beschlossen (Plan).

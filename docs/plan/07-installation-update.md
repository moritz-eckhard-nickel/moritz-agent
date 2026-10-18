# 07 – Installation und Update (Spezifikation)

Gilt für `moritz-install.sh` / `moritz-update.sh` (Wrapper: `install.sh` / `update.sh`).
Anforderungen: INST-01…11, UPD-01…07, CFG-01…10.

## 1. Grundsätze

- Bash mit `set -Eeuo pipefail`, `umask 077` während Secret-Operationen, Ausführung als
  root im LXC (legt Benutzer/Dienst an), Logdatei `/var/log/moritz-agent/install-<ts>.log`
  (0600) – **ohne** Secrets: Eingaben werden nie geloggt, `set -x` ist verboten.
- Alle Schreibvorgänge an `passwords.txt`, TOML, Hash-Datei laufen über
  `runtime/venv/bin/python -m moritz_agent.setup <befehl>`; Secrets werden per **stdin**
  übergeben, nie als Argument (Prozessliste!) und nie über Umgebungsvariablen.
- Atomar: temporäre Datei im selben Verzeichnis → `fsync` → `chmod/chown` → `rename`.
- Idempotent: jede Phase prüft zuerst, ob sie schon erledigt ist.
- Optionen: `--non-interactive`, `--dry-run`, `--prefix /opt/moritz-agent`,
  `--skip-models`, `--skip-koboldcpp-build`, `--channel stable|dev`.

## 2. Installer-Phasen

| # | Phase | Details | Abbruch wenn |
| --- | --- | --- | --- |
| 1 | `preflight` | root? Ubuntu 26.04/25.10, Python 3.13/3.14, RAM-Limit (`/sys/fs/cgroup/memory.max`), CPU-Threads (≤ 18 erwartet), freier Speicher ≥ 60 GB, `nvidia-smi` + Treiberversion (Warnung wenn fehlt → CPU-Modus nur für Tests), Zeitzone, Ports 3501/5060/RTP frei | Pflicht verletzt |
| 2 | `packages` | `apt-get install` (ohne System-Upgrade): `build-essential python3-venv python3-dev swig libssl-dev libopus-dev pkg-config libsndfile1 tzdata openssl git curl ca-certificates` | apt-Fehler |
| 3 | `user_dirs` | Systembenutzer `moritz-agent` (`--system --home /opt/moritz-agent --shell /usr/sbin/nologin`), Gruppen `video`/`render`, Verzeichnisse `data/ models/ runtime/ backups/` (0750/0700) | – |
| 4 | `python_env` | `runtime/venv`; von PyPI, exakt gepinnt: `pip install --require-hashes -r requirements/core.lock -r requirements/phone.lock` + `pip install --no-deps -e .` | pip-Fehler |
| 5 | `pjsip` | `scripts/build-pjsip.sh --python runtime/venv/bin/python`: Build aus einer Kopie von `third_party/pjproject` (2.17) unter `runtime/pjsip-build/` (ADR-005), SWIG-Binding ins venv; Neubau nur bei geänderter Version/Python (Stempeldatei) oder `--force` | Build-Fehler |
| 6 | `koboldcpp` | `./koboldcpp.sh rebuild` als Dienstbenutzer (ADR-015); Neubau nur bei geändertem Hash der nativen Quellen | Build-Fehler |
| 7 | `searxng` | `runtime/searxng-venv` mit `pip install --require-hashes -r requirements/searxng.lock`, Code fertig gebaut aus `third_party/searxng` (kein Build, kein Clone), Secret erzeugen (`data/searxng/secret`, 0600) | – |
| 8 | `models` | Aus `config/versions.lock`: LLM (13,8 GB), Whisper small (0,5 GB), Piper-Stimme „Hessisch“ (114 MB) (Thorsten-Voice Hessisch, `python -m moritz_agent.phone.audio.models fetch`) mit Größe anzeigen, freien Platz prüfen, bestätigen, Download mit Resume von Hugging Face, Größenprüfung; SHA-256 gegen `versions.lock` bzw. TOFU (ADR-021). VAD liegt im Repo. | Größe/Prüfsumme falsch |
| 9 | `secrets` | `passwords.txt` existiert? → **unverändert lassen**, nur fehlende Felder ergänzen (CFG-09). Sonst aus `config/passwords.template.txt` erzeugen (SIP-Startwerte, 0600). Danach Web-Login und Sandbox abfragen (§2.1) | ungültige Eingabe 3× |
| 10 | `config` | `config/moritz-agent.toml` aus Example erzeugen, falls fehlt; Fragen: LXC-IP für Zertifikat, RTP-Portbereich, Telefon-Einstellungen (Begrüßung, Stimme); Zeitzone `Europe/Berlin` | – |
| 11 | `tls` | Selbst signiertes Zertifikat nach `runtime/tls/` (`openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -days 3650`, SAN = IP + Hostname), Fingerprint anzeigen (ADR-022) | – |
| 12 | `prompts` | Ansagen-Cache erzeugen (P1-13) | TTS-Fehler |
| 13 | `service` | systemd-Unit installieren, `daemon-reload`, `enable --now` | Start schlägt fehl |
| 14 | `verify` | einzeln melden: Dienst läuft · LLM geladen (VRAM/RAM-Anteil) · SearXNG antwortet · STT/TTS Self-Test · SIP registriert · Web-UI `https://<IP>:3501` erreichbar | – (nur Bericht) |
| 15 | `testcall` | Checkliste: „Ruf jetzt 999 an“ → Begrüßung? Audio beidseitig? Uhrzeit? Folgefrage? Websuche? → Ergebnis ins Log. Bei Problemen Verweis auf [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md) | – |

### 2.1 Interaktive Abfragen

- **Web-Login:** Benutzername (Default `moritz`), Passwort 2× ohne Echo (`read -rs`),
  Mindestlänge 12, keine führenden/abschließenden Leerzeichen (CFG-10). Übergabe per stdin an
  `moritz_agent.setup set-web-login` → schreibt TXT + scrypt-Hash (ADR-013).
- **Sandbox-SSH:** Auswahl `[1] jetzt einrichten  [2] später`. Bei 1: Host, Port (22),
  Benutzer, Methode `key|password`; bei `key`: Pfad (Default: neuen ed25519-Schlüssel
  `data/ssh/id_ed25519` erzeugen und Public Key anzeigen), optionale Passphrase; Host-Key per
  `ssh-keyscan` holen, **Fingerprint anzeigen und bestätigen lassen**, in TXT speichern,
  Testverbindung `ssh -o StrictHostKeyChecking=yes … true`. Bei 2: `enabled = false`.
- **Stimme:** keine Abfrage – Nikita spricht mit Thorsten-Voice „Hessisch“ (Piper, lokal, keine Zugangsdaten; ADR-027).
- **SIP:** keine Abfrage bei Ersteinrichtung (Startwerte aus Vorlage). Warnung bei
  `password = agent`. Option `--reconfigure-sip` für spätere interaktive Änderung.

## 3. Update-Ablauf

| # | Phase | Details |
| --- | --- | --- |
| 1 | `preflight` | wie Installer (Kurzform) + Lock-Datei `data/run/update.lock` (kein Doppellauf) |
| 2 | `drain` | `POST /api/system/drain` (Admin-Token) → keine neuen Anrufe (Anrufer bekommen „besetzt“ bzw. Ansage `starting_up`); warten bis `/api/system/activity` keine aktiven Anrufe meldet, max. `--drain-timeout` (Default 600 s). Timeout → Drain aufheben, **Update verschieben**, Exit-Code 75 |
| 3 | `backup` | `backups/<ts>/` (0700): `passwords.txt`, `config/moritz-agent.toml`, `data/state/`, SQLite per Online-Backup-API, aktueller Commit, venv-Verweis. Rotation: letzte 5 |
| 4 | `fetch` | `git fetch --tags`; Ziel = neuester `v*`-Tag (`stable`) oder `origin/agent` (`dev`); Changelog-Ausschnitt anzeigen; Abbruch, wenn lokale Änderungen an versionierten Dateien |
| 5 | `stop` | Dienst stoppen (Phone sendet vorher BYE – es ist aber durch Drain kein Anruf aktiv) |
| 6 | `apply` | Checkout; neues venv `runtime/venv.new`, Lock-Dateien installieren; PJSIP/KoboldCPP/SearXNG nur bei geändertem Versions-Hash neu bauen |
| 7 | `migrate` | `moritz_agent.setup migrate`: fehlende TXT-Felder zeilenbasiert anhängen (bestehende Werte, Kommentare, Reihenfolge byte-identisch); neue **Pflicht**-Zugangsdaten interaktiv abfragen, im `--non-interactive`-Modus Exit-Code 78; neue TOML-Schlüssel ergänzen; DB-Migrationen; neue Modelle laden; Ansagen-Cache aktualisieren |
| 8 | `switch` | `runtime/venv` → `runtime/venv.prev`, `venv.new` → `venv` (Rename) |
| 9 | `start+verify` | Dienst starten, Health je Komponente (Timeout 180 s, LLM-Ladezeit) |
| 10 | `rollback` (bei Fehler in 6–9) | alten Commit auschecken, `venv.prev` zurück, Backups von TXT/TOML/DB zurückspielen, Dienst starten, Ergebnis klar melden (Exit-Code 70) |
| 11 | `report` | Version alt → neu, Komponentenstatus, Dauer; Hinweis „Testanruf empfohlen“ |

## 4. Exit-Codes (beide Skripte)

| Code | Bedeutung |
| ---: | --- |
| 0 | Erfolg |
| 1 | allgemeiner Fehler |
| 2 | falsche Benutzung/Optionen |
| 64 | Preflight nicht erfüllt |
| 70 | Update fehlgeschlagen, Rollback durchgeführt |
| 71 | Update **und** Rollback fehlgeschlagen (manueller Eingriff nötig) |
| 75 | Update verschoben (aktiver Anruf, Drain-Timeout) |
| 78 | Pflichtangabe fehlt im `--non-interactive`-Modus |

## 5. Gepinnte Versionen (`config/versions.lock`)

Eine Datei, eine Wahrheit – vom Installer/Updater gelesen: `koboldcpp` (Upstream-Version),
`pjproject` (Tag + Commit, im Repo), `searxng` (Commit, im Repo), `python` (Lock-Dateien mit Hashes),
`models.vad` (im Repo, SHA-256), `models.llm`/`models.stt`/`models.tts_voice` (Hugging-Face-
URL, Größe in Byte, SHA-256 bzw. `tofu`).

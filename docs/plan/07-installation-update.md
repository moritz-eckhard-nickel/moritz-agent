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
| 1 | `preflight` | root? Distribution (Debian 12/13, Ubuntu 24.04), Python ≥ 3.11, RAM-Limit (`/sys/fs/cgroup/memory.max`), CPU-Kerne, freier Speicher ≥ 40 GB, `nvidia-smi` (Warnung wenn fehlt → CPU-Modus nur für Tests), Zeitzone, Ports 5001/5060/RTP frei | Pflicht verletzt |
| 2 | `packages` | `apt-get install` (ohne Upgrade des Systems): `git curl ca-certificates build-essential python3-venv python3-dev swig libssl-dev libopus-dev pkg-config libsndfile1 sox tzdata nftables`(optional) | apt-Fehler |
| 3 | `user_dirs` | Systembenutzer `moritz-agent` (`--system --home /opt/moritz-agent --shell /usr/sbin/nologin`), Gruppen `video`/`render`, Verzeichnisse `data/ models/ runtime/ backups/` (0750/0700) | – |
| 4 | `python_env` | `runtime/venv` + `pip install --require-hashes -r requirements/core.lock -r requirements/phone.lock` + `pip install -e .` | pip-Fehler |
| 5 | `pjsip` | pjproject-Tag aus `config/versions.lock` laden, SHA-256 prüfen, bauen (ADR-005), SWIG-Binding ins venv; Cache über Versions-Hash | Build-Fehler |
| 6 | `koboldcpp` | `./koboldcpp.sh rebuild` als Dienstbenutzer (ADR-015); Cache über Hash der nativen Quellen | Build-Fehler |
| 7 | `searxng` | Checkout gepinnter Commit nach `runtime/searxng`, venv, `granian`, lokaler `secret_key` | – |
| 8 | `models` | Liste aus `config/versions.lock` (LLM, STT, TTS-Stimme, VAD) mit Größe anzeigen, Summe + freier Platz, Bestätigung, Download (resume), **SHA-256-Prüfung**, falsche Datei → löschen + Fehler | Prüfsumme falsch |
| 9 | `secrets` | `passwords.txt` existiert? → **unverändert lassen**, nur fehlende Felder ergänzen (CFG-09). Sonst aus `config/passwords.template.txt` erzeugen (SIP-Startwerte, 0600). Danach Web-Login und Sandbox abfragen (s. §2.1) | ungültige Eingabe 3× |
| 10 | `config` | `config/moritz-agent.toml` aus Example erzeugen, falls fehlt; Fragen: Web-Bindung (127.0.0.1 / LAN-IP), RTP-Portbereich, Stimme; Zeitzone `Europe/Berlin` | – |
| 11 | `prompts` | Ansagen-Cache erzeugen (P1-13) | TTS-Fehler |
| 12 | `service` | systemd-Unit installieren, `daemon-reload`, `enable --now` | Start schlägt fehl |
| 13 | `verify` | einzeln melden: Dienst läuft · LLM geladen · SearXNG antwortet · STT/TTS Self-Test · SIP registriert · Web-UI erreichbar | – (nur Bericht) |
| 14 | `testcall` | Checkliste ausgeben und interaktiv abfragen: „Ruf jetzt 999 an“ → Begrüßung gehört? Audio beidseitig? Uhrzeit korrekt? Folgefrage? Websuche? → Ergebnis ins Log. Hinweis: Dialplan wird nur geprüft, nicht geändert | – |

### 2.1 Interaktive Abfragen

- **Web-Login:** Benutzername (Default `moritz`), Passwort 2× ohne Echo (`read -rs`),
  Mindestlänge 12, keine führenden/abschließenden Leerzeichen (CFG-10). Übergabe per stdin an
  `moritz_agent.setup set-web-login` → schreibt TXT + scrypt-Hash (ADR-013).
- **Sandbox-SSH:** Auswahl `[1] jetzt einrichten  [2] später`. Bei 1: Host, Port (22),
  Benutzer, Methode `key|password`; bei `key`: Pfad (Default: neuen ed25519-Schlüssel
  `data/ssh/id_ed25519` erzeugen und Public Key anzeigen), optionale Passphrase; Host-Key per
  `ssh-keyscan` holen, **Fingerprint anzeigen und bestätigen lassen**, in TXT speichern,
  Testverbindung `ssh -o StrictHostKeyChecking=yes … true`. Bei 2: `enabled = false`.
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

Eine Datei, eine Wahrheit – vom Installer/Updater gelesen. Einträge: `pjproject`
(Tag + SHA-256 des Tarballs), `searxng` (Commit), `llm` (URL, Dateiname, SHA-256, Größe),
`stt` (Modellname + Revision), `tts_voice` (URL Onnx + JSON, SHA-256), `vad` (URL, SHA-256).
Gerüst mit `TODO`-Werten liegt bei; Werte werden in P1-02/P1-10/P1-11 festgelegt.

# Telefon und Stimme ausprobieren: `./test-1.sh`

`./test-1.sh` richtet den **Telefon- und Stimmenteil** von moritz-agent ein und startet ihn – ohne
Systeminstallation, ohne root, ohne Dienst und **ohne LXC oder Proxmox vorauszusetzen**: es läuft auf
jedem Linux-Rechner (Arbeitsplatz, VM, Konsole von Sophie-1, auch im LXC). Alles landet im
Repository-Ordner (`runtime/`, `models/`, `assets/audio/cache/`, `config/moritz-agent.toml`,
`passwords.txt`) und verschwindet wieder, wenn du diese Ordner löschst.

Es ist **derselbe Code**, der später im LXC als Dienst läuft (`moritz_agent/phone/`, ADR-027); den
LXC samt Dienst legt `./install.sh` auf dem Proxmox-Host an
([proxmox-installation.md](proxmox-installation.md)).

## Was funktioniert – und was noch nicht

| Teil | Stand |
| --- | --- |
| SIP: Anmeldung an der Telefonanlage, Anruf annehmen, 1 Anruf gleichzeitig (zweiter → „besetzt“), Zugriffsliste nach Absender-IP | ✅ gebaut, per echtem SIP/RTP-Anruf getestet |
| Sprachende-Erkennung (Silero VAD, echtes Modell getestet), Spracherkennung (Whisper small, CPU) | ✅ gebaut; Whisper-Modell selbst noch nicht gelaufen (siehe Ende) |
| Stimme Nikita: Thorsten-Voice **„Hessisch“** als Piper-Modell (CPU), Notstimme espeak-ng | ✅ gebaut und mit Test-Engines geprüft; das echte Modell ist noch nicht gelaufen (siehe Ende) |
| Vorgefertigte Ansagen gerendert und gecacht | ✅ |
| Gesprächsablauf: Begrüßung, mehrere Runden, Stille-Erinnerung, Auflegen, Störungsansagen | ✅ |
| Sofort-Antworten (Uhrzeit, Datum, Wochentag, Kalenderwoche, Name, Verabschiedung) | ✅ (Fast-Paths) |
| Sprachmodell, Websuche, Web-UI | ❌ kommen mit den nächsten Tickets – Nikita antwortet hier auf alles andere mit „Ich habe verstanden: …“ |

## Voraussetzungen

* Linux mit Python 3.12 oder 3.13 (`python3 --version`).
* Einmalig Build-Werkzeuge (nur falls sie fehlen – das Skript sagt es dir genau):
  `sudo apt install build-essential python3-venv python3-dev swig pkg-config espeak-ng`
  (`espeak-ng` ist optional, wird aber für den Testanruf und als Notstimme gebraucht).
* Platz: ca. 5 GB frei (Modelle 0,6 GB, Python-Umgebung, PJSIP-Build). RAM: ca. 2 GB.
* Internet für die Einrichtung (PyPI, Hugging Face). Danach läuft alles offline.

## Einrichten

```bash
./test-1.sh setup            # fragt vor dem Modell-Download nach (oder: --yes)
```

Was dabei passiert (jeder Schritt ist wiederholbar und überspringt Fertiges):

1. `scripts/setup-env.sh` – `runtime/venv` mit den exakt gepinnten, per SHA-256 geprüften Paketen
   aus `requirements/core.lock` und `requirements/phone.lock`; danach `scripts/build-pjsip.sh`: baut
   den SIP-Stack PJSIP 2.17 aus `third_party/pjproject` (eine Kopie unter `runtime/pjsip-build/`,
   das Original bleibt unverändert) und installiert das Python-Binding. Beim ersten Mal 3–5 Minuten.
2. `config/moritz-agent.toml` (Kopie der Beispielkonfiguration) und `passwords.txt` (aus der
   Vorlage, Modus 0600) werden angelegt, falls sie fehlen – **bestehende Dateien bleiben unberührt**.
3. Modelle von Hugging Face nach `models/`: Whisper small (0,5 GB) und die Piper-Stimme
   „Hessisch“ (`Thorsten-Voice/Hessisch`, 114 MB). Dateigrößen werden geprüft, die SHA-256-Summen
   beim ersten Mal gemerkt und danach bei jedem Start verglichen.

## Befehle

| Befehl | Zweck |
| --- | --- |
| `./test-1.sh check` | Selbsttest: Konfiguration, SIP-Stack, VAD, Whisper, Stimme, Ansagen, Ports. `--sip` prüft zusätzlich die Anmeldung an der Telefonanlage. |
| `./test-1.sh speak "Text" --play` | Nikitas Stimme hören (`--engine piper\|espeak`, `--out datei.wav`). |
| `./test-1.sh prompts` | Alle vorgefertigten Ansagen rendern und cachen. `--warm-times` rendert zusätzlich alle Viertelstunden-Uhrzeiten. |
| `./test-1.sh bench` | Misst Whisper und die Stimme auf **deinem** Rechner (Echtzeitfaktor). |
| `./test-1.sh call [--quick] ["Satz" …]` | Testanruf ohne Telefonanlage: Nikita startet im Direktmodus (Port 5062, nur 127.0.0.1) und ein Test-Anrufer ruft an, spricht die Sätze und nimmt Nikitas Antworten auf: `runtime/test-1/anruf.wav`. `--quick` nimmt nur die Notstimme und ein festes Text-Skript – damit geht es ohne jeden Modell-Download. |
| `./test-1.sh run` | Nikita starten, bei der Telefonanlage anmelden und Anrufe an die Nebenstelle annehmen (Strg+C beendet). `--no-register` nimmt Anrufe direkt an, `--engines espeak` erzwingt eine Stimme. |
| `./test-1.sh models [status\|fetch]` | Modell-Download prüfen oder nachholen. |

Ablauf eines echten Tests: `./test-1.sh setup` → `./test-1.sh check` →
`./test-1.sh speak "Guude, hier ist Nikita." --play` → `./test-1.sh call` (ohne Telefonanlage) →
in `passwords.txt` den Abschnitt `[sip]` ausfüllen → `./test-1.sh run` → mit dem Telefon die
Nebenstelle **999** wählen.

## Telefonanlage

* Zugangsdaten: `passwords.txt`, Abschnitt `[sip]` (Konto `agent`, Registrar, Port). Die Datei wird nie
  umgeschrieben und nie in Logs oder Fehlermeldungen ausgegeben.
* Asterisk-Konfiguration: [`asterisk-konfiguration.md`](asterisk-konfiguration.md) (Nebenstelle 999 → Konto `agent`).
* Nikita nimmt Anrufe nur von den Adressen in `phone.allowed_source_ips` (`config/moritz-agent.toml`)
  an; alle anderen bekommen SIP 403. Ein zweiter gleichzeitiger Anruf bekommt 486 „besetzt“.
* Nikita ruft **nie** selbst an.

## Die Stimme: Cache und Notstimme

* **Kette:** `piper` (Thorsten-Voice „Hessisch“, `models/tts/piper/Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx`)
  → `espeak` (Notstimme, nur falls das Modell fehlt oder defekt ist). Eine andere Piper-Stimme
  trägst du in `phone.tts.piper.voice` ein, z. B. `de_DE-thorsten-medium` für Hochdeutsch.
* **Vorgefertigte Ansagen** (Begrüßung, Fehler- und Zwischenansagen …, Katalog
  `assets/audio/prompts.de.toml`) werden einmal gerendert und liegen als WAV in
  `assets/audio/cache/`. Der Schlüssel enthält Text, Stimme (inkl. Modellgröße) und Lautheit – ändert sich
  einer davon, wird neu gerendert, alles andere kommt sofort aus dem Cache. Neu erzwingen:
  `rm -r assets/audio/cache` und `./test-1.sh prompts`.
* **Live-Antworten** werden satzweise gesprochen (erster Satz läuft, während der Rest entsteht) und
  liegen nur im Arbeitsspeicher, nie auf der Platte.
* **Geschwindigkeit:** `./test-1.sh bench` misst den Echtzeitfaktor. Stellschraube:
  `phone.tts.cpu_threads` (Standard 4).
* **Text → Sprache:** Zahlen, Uhrzeiten, Datum, Euro, Einheiten und Abkürzungen werden vor der
  Sprachausgabe in deutsche Wörter ausgeschrieben.

## Fehlersuche

| Meldung / Symptom | Ursache und Abhilfe |
| --- | --- |
| „Die Umgebung fehlt“ / „PJSIP (pjsua2) fehlt“ | `./test-1.sh setup` ausführen. |
| „fehlende Build-Voraussetzungen“ | den angezeigten `sudo apt install …`-Befehl einmal ausführen. |
| `check`: Stimme „piper“ nicht bereit | Modell fehlt oder ist defekt (`./test-1.sh models status`, `./test-1.sh models fetch`); Nikita spricht bis dahin mit espeak-ng. Details im Log (`runtime/test-1/agent.log`). |
| Start bricht ab: „Ansagen fehlen“ | keine einzige Stimme bereit – `espeak-ng` installieren oder die Piper-Stimme laden. Nikita registriert sich nie ohne sprechbare Ansagen. |
| Anruf wird mit SIP 403 abgewiesen | Absender-IP nicht in `phone.allowed_source_ips`. |
| Registrierung schlägt fehl | `./test-1.sh check --sip`; Konto/Passwort in `passwords.txt` und Asterisk vergleichen. |
| Port 5060/5062 belegt | `MORITZ_TEST_SIP_PORT=5072 ./test-1.sh call` bzw. `phone.local_sip_port` ändern. |

Logs: `runtime/test-1/agent.log` (Testanruf) und das in der Konfiguration eingestellte Logfile; Zugangsdaten werden
nie geschrieben.

## Aufräumen

```bash
rm -rf runtime models assets/audio/cache config/moritz-agent.toml passwords.txt
```

Das ist alles – es wurde nichts außerhalb des Repository-Ordners installiert (außer den einmalig
nötigen apt-Paketen).

## Ehrlicher Teststand (18.10.2026)

Getestet in einer Entwicklungsumgebung: der komplette SIP-/Gesprächsteil mit echten SIP/RTP-Anrufen
gegen sich selbst (Begrüßung, mehrere Runden, Verabschiedung, 486 bei zweitem Anruf, 403 bei
fremder Adresse, Auflegen mitten in der Ansage, sauberes Beenden), die Einrichtung von Grund auf
(`./test-1.sh setup`), die Voice-Kette mit Notstimme und Test-Engines sowie die Unit-Tests.

**Dort nicht erreichbar und daher noch nicht gelaufen:** die Modelle von Hugging Face (Whisper
small, die Piper-Stimme „Hessisch“). Bekannt ist nur, dass die Modelldatei existiert und ihre
Konfiguration ein normales Piper-Format hat (Einzelsprecher, 22,05 kHz, espeak „de“). Wie die Stimme
klingt – insbesondere wie stark die hessische Färbung bei hochdeutsch geschriebenem Text hörbar ist –
und wie schnell sie auf deiner CPU ist, zeigt erst dein erster Lauf (`./test-1.sh speak`, `./test-1.sh bench`).
Ebenso steht der Test gegen die echte Asterisk-Anlage aus.

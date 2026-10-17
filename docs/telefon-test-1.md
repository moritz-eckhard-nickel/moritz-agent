# Telefon und Stimme ausprobieren: `./test-1.sh`

`./test-1.sh` richtet den **Telefon- und Stimmenteil** von moritz-agent ein und startet ihn – ohne
Systeminstallation, ohne root, ohne Dienst. Alles landet im Repository-Ordner (`runtime/`,
`models/`, `assets/audio/cache/`, `config/moritz-agent.toml`, `passwords.txt`) und verschwindet
wieder, wenn du diese Ordner löschst. Es ist **derselbe Code**, der später im vollständigen System
läuft (`moritz_agent/phone/`, ADR-027) – das Skript ist nur ein bequemer Einstieg.

## Was funktioniert – und was noch nicht

| Teil | Stand |
| --- | --- |
| SIP: Anmeldung an der Telefonanlage, Anruf annehmen, 1 Anruf gleichzeitig (zweiter → „besetzt“), Zugriffsliste nach Absender-IP | ✅ gebaut, per echtem SIP/RTP-Anruf getestet |
| Sprachende-Erkennung (Silero VAD, echtes Modell getestet), Spracherkennung (Whisper small, CPU) | ✅ gebaut; Whisper-Modell selbst noch nicht gelaufen (siehe Ende) |
| Stimme Nikita: Thorsten-Voice **Hessisch** (CosyVoice3, CPU), Rückfall Piper → espeak-ng | ✅ gebaut und mit Test-Engines geprüft; die echten Modelle sind noch nicht gelaufen (siehe Ende) |
| Vorgefertigte Ansagen gerendert und gecacht, Aufwertung auf die Hauptstimme im Hintergrund | ✅ |
| Gesprächsablauf: Begrüßung, mehrere Runden, Stille-Erinnerung, Auflegen, Störungsansagen | ✅ |
| Sofort-Antworten (Uhrzeit, Datum, Wochentag, Kalenderwoche, Name, Verabschiedung) | ✅ (Fast-Paths) |
| Sprachmodell, Websuche, Web-UI, Installer | ❌ kommen mit den nächsten Tickets – Nikita antwortet hier auf alles andere mit „Ich habe verstanden: …“ |

## Voraussetzungen

* Ubuntu/Debian-artiges Linux, Python 3.12 oder 3.13 (`python3 --version`).
* Einmalig Build-Werkzeuge (nur falls sie fehlen – das Skript sagt es dir genau):
  `sudo apt install build-essential python3-venv python3-dev swig pkg-config espeak-ng`
  (`espeak-ng` ist optional, wird aber für den Testanruf und als Notstimme gebraucht).
* Platz: mindestens 12 GB frei (Modelle 5,5 GB, Python-Umgebungen einige GB, PJSIP-Build).
* RAM: ca. 6 GB frei mit CosyVoice (Modell ≈ 4,5–5 GB), ca. 2 GB ohne (`--no-cosyvoice`).
* Internet für die Einrichtung (PyPI, PyTorch-CPU-Index, Hugging Face). Danach läuft alles offline.

## Einrichten

```bash
./test-1.sh setup            # fragt vor dem Modell-Download nach (oder: --yes)
./test-1.sh setup --no-cosyvoice   # nur Whisper + Piper/espeak: schnell, wenig RAM
```

Was passiert dabei (jeder Schritt ist wiederholbar und überspringt Fertiges):

1. `runtime/venv` – Python-Umgebung mit den exakt gepinnten, per SHA-256 geprüften Paketen aus
   `requirements/core.lock` und `requirements/phone.lock`.
2. `scripts/build-pjsip.sh` – baut den SIP-Stack PJSIP 2.17 aus `third_party/pjproject` (eine Kopie
   unter `runtime/pjsip-build/`, das Original bleibt unverändert) und installiert das Python-Binding.
   Beim ersten Mal ca. 3–5 Minuten.
3. `scripts/setup-tts-venv.sh` – `runtime/venv-tts` für die CosyVoice-Stimme: PyTorch 2.10.0 **CPU**
   vom PyTorch-Index (kleine Wheels, keine NVIDIA-Bibliotheken) plus die Pakete aus
   `requirements/tts.txt`. Der Index lässt sich mit `MORITZ_TORCH_INDEX` ändern.
4. `config/moritz-agent.toml` (Kopie der Beispielkonfiguration) und `passwords.txt` (aus der
   Vorlage, Modus 0600) werden angelegt, falls sie fehlen – **bestehende Dateien bleiben unberührt**.
5. Modelle von Hugging Face nach `models/`: Whisper small (0,5 GB), Piper-Stimme (63 MB) und
   CosyVoice3-Hessisch (4,4 GB: Basismodell `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` plus die
   Hessisch-Gewichte von `Thorsten-Voice/CosyVoice3-Hessisch`). Dateigrößen werden geprüft, die
   SHA-256-Summen beim ersten Mal gemerkt und danach bei jedem Start verglichen.

## Befehle

| Befehl | Zweck |
| --- | --- |
| `./test-1.sh check` | Selbsttest: Konfiguration, SIP-Stack, VAD, Whisper, Stimmen, Ansagen, Ports. `--sip` prüft zusätzlich die Anmeldung an der Telefonanlage, `--no-wait` wartet nicht auf CosyVoice. |
| `./test-1.sh speak "Text" --play` | Nikitas Stimme hören (`--engine cosyvoice\|piper\|espeak`, `--out datei.wav`). |
| `./test-1.sh prompts` | Alle vorgefertigten Ansagen rendern und cachen. `--warm-times` rendert zusätzlich alle Viertelstunden-Uhrzeiten (dauert lange). |
| `./test-1.sh bench` | Misst Whisper und jede Stimme auf **deinem** Rechner (Echtzeitfaktor). Das ist die wichtigste Messung für die CPU-Stimme. |
| `./test-1.sh call [--quick] ["Satz" …]` | Testanruf ohne Telefonanlage: Nikita startet im Direktmodus (Port 5062, nur 127.0.0.1) und ein Test-Anrufer ruft an, spricht die Sätze und nimmt Nikitas Antworten auf: `runtime/test-1/anruf.wav`. `--quick` nimmt nur die Notstimme und ein festes Text-Skript – damit geht es ohne jeden Modell-Download. |
| `./test-1.sh run` | Nikita starten, bei der Telefonanlage anmelden und Anrufe an die Nebenstelle annehmen (Strg+C beendet). `--no-register` nimmt Anrufe direkt an, `--engines espeak` erzwingt eine Stimme. |
| `./test-1.sh models [status\|fetch]` | Modell-Download prüfen oder nachholen. |

Ablauf eines echten Tests: `./test-1.sh setup` → `./test-1.sh check` → `./test-1.sh speak "Hallo Moritz, hier ist Nikita." --play`
→ `./test-1.sh call` (ohne Telefonanlage) → in `passwords.txt` den Abschnitt `[sip]` ausfüllen →
`./test-1.sh run` → mit dem Telefon die Nebenstelle **999** wählen.

## Telefonanlage

* Zugangsdaten: `passwords.txt`, Abschnitt `[sip]` (Konto `agent`, Registrar, Port). Die Datei wird nie
  umgeschrieben und nie in Logs oder Fehlermeldungen ausgegeben.
* Asterisk-Konfiguration: [`asterisk-konfiguration.md`](asterisk-konfiguration.md) (Nebenstelle 999 → Konto `agent`).
* Nikita nimmt Anrufe nur von den Adressen in `phone.allowed_source_ips` (`config/moritz-agent.toml`)
  an; alle anderen bekommen SIP 403. Ein zweiter gleichzeitiger Anruf bekommt 486 „besetzt“.
* Nikita ruft **nie** selbst an.

## Die Stimme: Cache, Reihenfolge, Geschwindigkeit

* **Kette:** `cosyvoice` (Thorsten-Voice Hessisch) → `piper` (Thorsten, hochdeutsch) → `espeak` (Notstimme).
  Ändern über `phone.tts.engine` und `fallback_engines` oder mit `--engines`.
* **Vorgefertigte Ansagen** (Begrüßung, Fehler- und Zwischenansagen …, Katalog
  `assets/audio/prompts.de.toml`) werden einmal gerendert und liegen als WAV in
  `assets/audio/cache/`. Der Schlüssel enthält Text, Stimme und Lautheit – ändert sich einer davon,
  wird neu gerendert, alles andere kommt sofort aus dem Cache. Beim ersten Start wird mit der besten
  gerade bereiten Stimme gerendert (damit Nikita sofort antworten kann); sobald CosyVoice geladen
  ist, werden die Ansagen im Hintergrund mit der Hauptstimme ersetzt – nie während eines Anrufs.
  Neu erzwingen: `rm -r assets/audio/cache` und `./test-1.sh prompts`.
* **Live-Antworten** werden satzweise gesprochen. `phone.tts.live_engine = "auto"` nimmt die
  Hauptstimme nur, solange sie einen Satz innerhalb von `live_budget_s` (Standard 6 s) schafft, sonst
  die Rückfallstimme. Live gesprochene Sätze liegen nur im Arbeitsspeicher, nie auf der Platte.
* **Geschwindigkeit:** CosyVoice3 läuft auf der CPU deutlich langsamer als eine schnelle Stimme –
  wie viel, hängt von deiner CPU ab. Miss es mit `./test-1.sh bench`. Hilfreich: `phone.tts.cpu_threads`
  (Standard 16) auf die Zahl der freien Kerne stellen; ist die Hauptstimme live zu langsam,
  `live_engine = "piper"` setzen – die Ansagen bleiben trotzdem in der Hessisch-Stimme.
* **Text → Sprache:** Zahlen, Uhrzeiten, Datum, Euro, Einheiten und Abkürzungen werden vor der
  Sprachausgabe in deutsche Wörter ausgeschrieben (CosyVoices eigene Textaufbereitung kennt nur
  Chinesisch und Englisch).

## Fehlersuche

| Meldung / Symptom | Ursache und Abhilfe |
| --- | --- |
| „Die Umgebung fehlt“ / „PJSIP (pjsua2) fehlt“ | `./test-1.sh setup` ausführen. |
| „fehlende Build-Voraussetzungen“ | den angezeigten `sudo apt install …`-Befehl einmal ausführen. |
| „torch ließ sich nicht … laden“ | Netzwerk/Proxy prüfen; anderer Index: `MORITZ_TORCH_INDEX=… ./test-1.sh setup`. |
| `check`: Stimme „cosyvoice“ nicht bereit | Modell noch nicht (vollständig) geladen (`./test-1.sh models status`) oder `runtime/venv-tts` fehlt; Nikita spricht bis dahin mit Piper/espeak. Details im Log (`runtime/test-1/agent.log`). |
| Warten beim Start „auf eine Stimme für die Ansagen“ | keine einzige Stimme bereit – `espeak-ng` installieren oder Piper-Modell laden. Nikita registriert sich nie ohne sprechbare Ansagen. |
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

## Ehrlicher Teststand (17.10.2026)

Getestet in einer Entwicklungsumgebung: der komplette SIP-/Gesprächsteil mit echten SIP/RTP-Anrufen
gegen sich selbst (Begrüßung, mehrere Runden, Verabschiedung, 486 bei zweitem Anruf, 403 bei
fremder Adresse, Auflegen mitten in der Ansage, sauberes Beenden), die Einrichtung von Grund auf
(`./test-1.sh setup`), die Voice-Kette mit Notstimme und Test-Engines sowie 196 Unit-Tests.

**Dort nicht erreichbar und daher noch nicht gemessen:** die echten Modelle von Hugging Face
(Whisper small, Piper-Stimme, CosyVoice3-Hessisch) und der PyTorch-CPU-Index – ihr Zusammenspiel,
die Sprachqualität und vor allem die **Geschwindigkeit von CosyVoice3 auf deiner CPU** zeigt erst
dein erster Lauf (`./test-1.sh bench`). Ebenso steht der Test gegen die echte Asterisk-Anlage aus.

# moritz-agent – Projektplan

Stand: 16.10.2026. Sophie-1 mit Proxmox, 32 GB RAM und RTX 3070 (8 GB VRAM). Höchste Priorität: interner Telefon-Agent ab Part 1.

## Projektname

**moritz-agent**

Ziel: Ein einziges eigenständiges Programm auf Basis von KoboldCPP, das interne SIP-Telefonie, Spracherkennung, Sprachausgabe, Inference, Agent-Logik, Websuche, Deep Research, Browser-Automation, Tool-Calling, Sandbox-Steuerung, Backend und Frontend in einem Produkt vereint.

Aus Sicht des Benutzers gibt es genau:

- eine Anwendung
- einen Startbefehl
- eine zentrale Konfiguration mit editierbarer `passwords.txt` für Zugangsdaten
- eine Weboberfläche
- ein Repository

Intern darf das Programm mehrere Worker oder Child-Prozesse verwenden.

---

# 1. Grundidee

## Verbindliche Priorität: Telefon ab Part 1

Der wichtigste erste Anwendungsfall ist ein anrufbarer Sprachassistent im internen Telefonnetz. Telefonie ist kein späteres Zusatzfeature. Part 1 ist erst abgeschlossen, wenn ein echter Anruf mit Begrüßung, Zuhören, Uhrzeitantwort und einfacher Websuche funktioniert.

Moritz ruft intern die vorgesehene Nebenstelle **999** an. Der Agent registriert sich dafür mit dem SIP-Konto **agent** an der bestehenden Telefonanlage **192.168.1.176**. Die gewählte Nebenstelle und der SIP-Benutzername sind verschiedene Werte. Der vorhandene Asterisk-Dialplan muss 999 auf den registrierten Agent-Endpunkt leiten; diese Zuordnung wird beim Einrichten geprüft und nicht allein aus dem Benutzernamen vorausgesetzt.

Ablauf ab Part 1:

1. Eingehenden internen Anruf automatisch annehmen.
2. Sofort eine vorbereitete Audiodatei abspielen: „Hallo Moritz, hier ist Agent. Was kann ich für dich tun?“ Die Datei wird mitgeliefert oder vor dem ersten Anruf erzeugt und zwischengespeichert; kein LLM-Warten für die Begrüßung.
3. Nach der Begrüßung zuhören, Sprachende erkennen und die Äußerung auf Deutsch transkribieren.
4. Bei „Wie viel Uhr haben wir?“ ein echtes Uhrzeit-Tool aufrufen und kurz antworten, zum Beispiel „Es ist 19 Uhr 12.“ Die Zeit stammt unmittelbar vor der Ausgabe aus der Systemuhr, mit Zeitzone Europe/Berlin und automatischer Sommerzeitbehandlung. Keine vom Sprachmodell erfundene Uhrzeit.
5. Andere Fragen mit dem Sprachmodell bearbeiten; aktuelle Informationen über die integrierte Websuche abrufen. Eine Google-Abfrage ist nur dann eine Google-Abfrage, wenn die konfigurierte Suchmaschine sie tatsächlich ausführt; SearXNG kann andere verfügbare Suchmaschinen nutzen.
6. Eine kurze deutsche Antwort erzeugen, per TTS sprechen und anschließend wieder zuhören. Mehrere Gesprächsrunden im selben Anruf sind Pflicht.
7. Beim Auflegen alle zum Anruf gehörenden Audio-, STT- und Antwortaufträge abbrechen und Ressourcen freigeben.

Die minimale Telefon-Websuche gehört bereits in Part 1. Deep Research, komplexe Browser-Automation, mehrere gleichzeitige Anrufe und weitere Telefonfunktionen folgen später.

## Telefontechnik und Ressourcen

- Ein integrierter SIP-Worker registriert sich als normaler SIP-Teilnehmer. Als Implementierungskandidat wird PJSIP/PJSUA2 einschließlich Audio-Medienanbindung geprüft und versioniert eingebunden.
- SIP-Signalisierung nutzt gemäß Vorgabe UDP-Port 5060 am Registrar. Sprache läuft separat über RTP/RTCP; ein passender lokaler Medien-Portbereich und die Erreichbarkeit zur Telefonanlage müssen ebenfalls eingerichtet und geprüft werden.
- Codec-Aushandlung, Umwandlung zwischen Telefon-Audio und dem Eingabeformat der Spracherkennung sowie die Rückwandlung der TTS-Ausgabe sind explizite Bestandteile des Phone-Workers.
- Der Betrieb erfolgt ohne physisches Mikrofon und ohne Soundkarte im LXC. Ein- und Ausgabe sind direkt mit dem Gesprächsaudio verbunden.
- VAD/Sprachende-Erkennung, ein kleines deutschfähiges STT-Modell und eine lokale deutsche TTS-Stimme laufen zunächst auf der CPU. Konkrete Engines werden anhand von CPU, Latenz, Qualität und Lizenz ausgewählt; die 3070 bleibt zunächst dem LLM vorbehalten.
- Das Limit von 16 GB RAM umfasst LLM-RAM-Anteile, SIP, STT, TTS, Suche und Backend gemeinsam. Sprachkomponenten sind zusätzliche Modelle, aber kein zweites großes Sprachmodell. Ihr Verbrauch wird unter Telefonlast gemessen.
- Zunächst ein aktiver Anruf, eine LLM-Generierung und ein Gesprächskontext. Ein zweiter Anruf erhält besetzt. Keine Vermischung von Gesprächen.
- Telefon-Anfragen haben Vorrang vor noch nicht gestarteten Hintergrundaufgaben. Laufende lange Generierungen werden, soweit vom Backend unterstützt, kontrolliert abgebrochen; andernfalls erfolgt eine kurze vorbereitete Warteansage mit Timeout.
- Part 1 verwendet klaren Sprecherwechsel: während der eigenen Ausgabe keine erneute Transkription der Agentenstimme. Natürliches Unterbrechen mit Echo-Behandlung folgt später.
- Unverständliche Sprache führt zu einer kurzen Rückfrage. Fehlgeschlagene Suche wird ehrlich angesagt. Bei längerer Stille einmal nachfragen und anschließend nach konfigurierbarem Timeout auflegen.
- Fehlender LLM-Dienst darf die vorbereitete Begrüßung und eine vorbereitete Fehleransage nicht blockieren. Bei fehlender STT/TTS-Bereitschaft keinen normalen Gesprächsbetrieb vortäuschen.
- Keine dauerhafte Audioaufnahme als Standard; temporäre Audiopuffer werden nach Verwendung entfernt. Zugangsdaten gelangen weder in Transkripte noch in LLM-Kontexte oder Logs.
- Part 1 nimmt interne Anrufe an und startet selbst keine ausgehenden Telefonanrufe. Telefon-Tools sind zunächst Uhrzeit, einfache Fragen und Websuche; Shell/SSH bleiben davon getrennt. Eine angezeigte Rufnummer allein ist keine Berechtigung für spätere administrative Aktionen.

## Zentrale Datei passwords.txt

Alle Zugangsdaten werden zentral in der lokalen Datei `moritz-agent/passwords.txt` geführt. Diese Datei ist Teil der installierten Anwendung und direkt editierbar; Zugangsdaten werden nicht an mehreren Stellen im Programmcode fest verdrahtet. Der folgende vollständige Startinhalt ist die Vorgabe für die spätere Implementierung, noch keine hier installierte Konfiguration:

```ini
[sip]
username = agent
auth_username = agent
password = agent
display_name = Agent
registrar = 192.168.1.176
port = 5060
transport = udp
extension = 999

[web_login]
username =
password =

[sandbox_ssh]
enabled = false
host =
port = 22
username =
auth_method =
password =
private_key_path =
private_key_passphrase =
host_key_fingerprint =

[optional_services]
# Weitere Zugangsdaten werden bei Einrichtung des jeweiligen Dienstes ergänzt.
```

- SIP-Werte sind bei der ersten lokalen Einrichtung bereits vorbelegt und lassen sich durch Bearbeiten der TXT ändern.
- Ein INI-Parser liest die Datei als Daten; sie wird nicht als Shell-Code mit `source` ausgeführt. Sonderzeichen und Prozentzeichen in Passwörtern müssen unverändert erhalten bleiben.
- Leere Web-/SSH-Werte sind keine verwendbaren Standardzugänge. Der Installer fragt sie ab; die Web-Anmeldung wird erst mit gültigen Werten aktiviert.
- Für SSH-Schlüsselauthentifizierung steht der Schlüsselpfad mit optionaler Passphrase in der TXT; die Schlüsseldatei bleibt separat geschützt. Bei Passwortauthentifizierung steht das SSH-Passwort direkt in der TXT.
- Änderungen werden über einen kontrollierten Reload oder Neustart übernommen. SIP-Änderungen lösen eine Neuregistrierung aus, sobald kein Gespräch aktiv ist. Ungültige Konfiguration wird mit verständlicher Meldung abgelehnt.
- Die Datei ist entsprechend dem Wunsch eine Klartextdatei. Nur Dienstbenutzer und Administrator dürfen sie lesen; auf Linux standardmäßig Dateimodus 0600. Nicht über Webserver, Downloads, Tool-Dateizugriff oder Diagnosearchive ausliefern.
- `passwords.txt` und Sicherungen stehen in `.gitignore`. Die vorgegebenen SIP-Startwerte werden für die private Installation bereitgestellt; ein öffentliches Repository enthält nur eine bereinigte Vorlage. Bestehende Copyright- und Lizenzhinweise bleiben erhalten.

## Installation und Updates ab Part 1

Die eigentlichen Projektskripte heißen `moritz-install.sh` und `moritz-update.sh`. Die gewünschten Einstiegspunkte `install.sh` und `update.sh` können als dünne Wrapper dieselben Abläufe starten.

**Installation:**

1. Im vorbereiteten Agent-LXC Distribution, Ressourcen, GPU-Verfügbarkeit und benötigte Systempakete prüfen. Änderungen an Proxmox-Treiber und LXC-Gerätezuweisung bleiben ein separat dokumentierter Host-Schritt; kein pauschaler Host-Zugriff durch den Agent-Installer.
2. Dienstbenutzer, Anwendungsverzeichnis, Python-/Native-Abhängigkeiten, SIP-Bibliothek, Modellpfade und Audio-Ressourcen einrichten. Benötigte Modelle/Stimmen mit überprüften Versionen beziehen und Speicherbedarf anzeigen.
3. Vorhandene `passwords.txt` bewahren. Nur bei der ersten Einrichtung die obigen SIP-Werte einsetzen; niemals bei erneutem Installieren über geänderte Werte schreiben.
4. Web-Benutzername und Passwort interaktiv abfragen. Passworteingabe ohne Terminal-Echo; in die TXT schreiben und für die Login-Prüfung einen geeigneten Passwort-Hash ableiten. Keine Passwörter in Kommandozeilen oder Installationslogs.
5. Sandbox-Host, SSH-Port, Benutzer und Authentifizierung abfragen; Host-Schlüssel-Fingerprint prüfen und die Verbindung testen. Auswahl „später einrichten“ hält SSH deaktiviert, damit Telefonie ohne verfügbare Sandbox funktioniert. Alle eingegebenen Verbindungsdaten in der TXT speichern.
6. Zeitzone Europe/Berlin, Begrüßung, Stimme, Sprache, RTP-Portbereich und weitere nicht geheime Einstellungen in der normalen Konfiguration einrichten. SIP-Daten nur in der TXT halten.
7. Systemdienst, Autostart und lokale Schnittstellen konfigurieren. SIP-Registrierung, STT/TTS, LLM und Suche mit einzelnen Statusmeldungen prüfen.
8. Einen manuellen Testanruf an 999 anfordern: Begrüßung, Audio in beide Richtungen, Uhrzeitantwort, Folgefrage und Websuche prüfen. Der Installer kann die Asterisk-Dialplan-Zuordnung ohne dortigen Zugang nur prüfen lassen, nicht automatisch voraussetzen oder ändern.

**Update:**

- Aktive Anrufe vor dem Neustart auslaufen lassen; nach einem Timeout Update verschieben statt ein Gespräch ungefragt abzubrechen.
- Konfiguration, TXT und Datenbank vor Migration geschützt sichern.
- Anwendung und Abhängigkeiten aktualisieren; bestehende Werte, Modelle und Gesprächsdaten erhalten.
- Neue Konfigurationsfelder ergänzen. Nur neue erforderliche Zugangsdaten interaktiv abfragen; optionale Integrationen ohne Daten deaktiviert lassen. Im unbeaufsichtigten Modus bei fehlenden Pflichtangaben kontrolliert abbrechen.
- Die vorbelegten SIP-Daten niemals über eine bereits angepasste TXT zurückschreiben.
- Dateien atomar schreiben, Dateirechte erhalten und Schemaänderungen versionieren.
- Nach Neustart Registrierung, Audio-Komponenten, Modell und API prüfen. Bei Fehlern einen kompatiblen gesicherten Stand wiederherstellen und das Ergebnis klar melden.

---

Wir bauen nicht:

```text
KoboldCPP
+
SearXNG
+
extra Backend
+
extra Frontend
+
extra Agent
+
extra Browser-Service
```

sondern:

```text
moritz-agent
│
├── Phone / SIP / STT / TTS
├── Inference
├── Agent
├── Search
├── Browser
├── Tools
├── Sandbox
├── Backend
└── Frontend
```

Der Benutzer startet später einfach:

```bash
./moritz-agent
```

oder unter Windows:

```text
moritz-agent.exe
```

Danach startet die komplette Anwendung automatisch.

---

# 2. Zielarchitektur

```text
moritz-agent
│
├── Phone Core (Part 1)
│   ├── SIP Registration / Calls
│   ├── RTP Audio / Greeting
│   ├── VAD / STT / TTS
│   └── Conversation Turns
│
├── Inference Core
│   └── KoboldCPP / llama.cpp
│
├── Agent Core
│   ├── Agent Loop
│   ├── Tool Calling
│   ├── Context Manager
│   ├── Memory
│   ├── Task Planner
│   └── Model Router
│
├── Research Engine
│   ├── SearXNG
│   ├── Web Fetcher
│   ├── Chromium / Playwright
│   ├── Source Extraction
│   └── Deep Research
│
├── Tool Runtime
│   ├── Shell
│   ├── Python
│   ├── Files
│   ├── Git
│   ├── HTTP
│   ├── Browser
│   └── SSH / Agent-VM
│
├── Storage
│   ├── SQLite
│   ├── Conversations
│   ├── Memory
│   ├── Research
│   └── Tool Logs
│
├── Backend API
│   ├── /api/chat
│   ├── /api/agent
│   ├── /api/research
│   ├── /api/files
│   └── /v1/... OpenAI-compatible
│
└── Frontend
    ├── Chat
    ├── Agent Mode
    ├── Research
    ├── Files
    ├── Settings
    └── Model Manager
```

---

# 3. KoboldCPP als Basis

KoboldCPP wird als Ausgangspunkt genommen, aber nicht einfach nur umgelabelt.

Die Idee ist:

```text
KoboldCPP
    ↓
Inference-Komponente von moritz-agent
```

KoboldCPP übernimmt weiterhin die komplizierten Low-Level-Bereiche:

- GGUF laden
- llama.cpp
- CUDA
- Vulkan
- CPU-Inference
- GPU-Offload
- Sampling
- Context Handling
- Quantisierung
- Token-Generation

Das eigentliche Produkt wird jedoch **moritz-agent**.

Der Nutzer soll später nicht wissen müssen, dass darunter KoboldCPP läuft.

---

# 4. Fork von KoboldCPP

Der sinnvollste Startpunkt ist ein Fork von KoboldCPP.

Danach wird der Fork möglichst früh zu einem eigenständigen Repository gemacht.

Ziel:

```text
LostRuins/koboldcpp
        │
        └── Fork
              │
              ▼
       moritz-agent
              │
       Leave fork network
              │
              ▼
     eigenständiges Repository
```

Dadurch besteht nicht ständig die Gefahr, versehentlich Pull Requests zurück in das originale KoboldCPP-Projekt zu öffnen.

Die Git-History kann dabei erhalten bleiben.

Falls GitHubs direkte Funktion zum Verlassen des Fork-Netzwerks nicht verfügbar ist, kann das Repository alternativ:

1. bare geklont
2. als neues Repository angelegt
3. per `git push --mirror` übertragen

werden.

---

# 5. Repository-Struktur

Eine mögliche Struktur:

```text
moritz-agent/
│
├── core/
│   ├── phone/
│   ├── agent/
│   ├── inference/
│   ├── tools/
│   ├── research/
│   ├── memory/
│   ├── api/
│   └── storage/
│
├── frontend/
│
├── vendor/
│   ├── koboldcpp/
│   └── searxng/
│
├── runtime/
│   ├── browser/
│   └── sandbox/
│
├── data/
│
├── config/
├── passwords.txt       # lokal, nicht versioniert
├── assets/audio/       # vorbereitete Begrüßung und Statusansagen
├── moritz-install.sh
├── moritz-update.sh
├── install.sh          # Einstieg / Wrapper
├── update.sh           # Einstieg / Wrapper
│
└── main.py
```

Alternativ kann ein Teil des bestehenden KoboldCPP-Codes direkt übernommen und schrittweise neu strukturiert werden.

---

# 6. SearXNG integrieren

SearXNG wird Bestandteil des Projekts.

Es wird jedoch nicht komplett in unseren eigenen Backend-Code kopiert.

Stattdessen:

```text
vendor/
├── koboldcpp/
├── searxng/
└── ...
```

SearXNG bleibt intern ein eigenes Modul beziehungsweise Worker.

Beim Start von `moritz-agent` passiert beispielsweise:

```text
1. Config laden
2. Datenbank öffnen
3. KoboldCPP Backend mit einem Modell initialisieren
4. internen SearXNG Worker starten
5. Sandbox-Verbindung vorbereiten; Browser erst bei Bedarf remote starten
6. Agent Runtime starten
7. Webserver starten
8. UI und Telefonstatus bereitstellen
9. SIP-Worker registrieren; Anrufbereitschaft nach Audio-Checks melden
```

SearXNG läuft ausschließlich intern.

Beispiel:

```text
127.0.0.1:<zufälliger-interner-port>
```

Der Port wird nicht öffentlich freigegeben.

Der Agent nutzt SearXNG intern:

```text
Agent
  ↓
Research Engine
  ↓
SearXNG
  ↓
Google / Bing / Brave / DuckDuckGo / ...
```

Der Nutzer merkt davon nichts.

---

# 7. Ein Programm heißt nicht ein Prozess

Nach außen ist `moritz-agent` **eine Anwendung**.

Intern darf es mehrere Prozesse geben.

Beispiel:

```text
moritz-agent
│
├─ main process
│
├─ phone / audio worker
├─ inference worker
├─ search worker
├─ remote browser client
└─ sandbox communication worker
```

Das ist wichtig für Stabilität.

Wenn Chromium abstürzt, soll nicht das geladene LLM sterben.

Wenn SearXNG hängt, soll KoboldCPP weiterlaufen.

Wenn ein Agent eine kaputte Webseite öffnet, soll die WebUI trotzdem funktionieren.

Prinzip:

> Ein Produkt, mehrere isolierte interne Worker.

---

# 8. Backend

Das Backend sollte in Python geschrieben werden.

Grund:

KoboldCPP besitzt ohnehin bereits einen großen Python-Layer.

Dadurch vermeiden wir unnötige zusätzliche Technologien.

Nicht:

```text
Node.js Backend
↓
Python Backend
↓
KoboldCPP
↓
C++
```

Sondern:

```text
moritz-agent Python Core
             ↓
       KoboldCPP Python
             ↓
        C++ Backend
             ↓
           CUDA
```

Das Backend verwaltet:

- SIP-Registrierung, Anrufe und Audio-Zustände
- Chat
- Agent State
- Tool Calls
- Research
- Memory
- Authentication
- Files
- VM Connection
- Model Loading
- Settings
- WebSocket / SSE Streaming

---

# 9. API

Mögliche interne API-Struktur:

```text
/api/chat
/api/agent
/api/research
/api/files
/api/models
/api/tools
/api/settings
/api/system
/api/phone/status
```

Zusätzlich sollte eine OpenAI-kompatible API erhalten bleiben:

```text
/v1/chat/completions
/v1/models
```

Dadurch können später auch externe Anwendungen `moritz-agent` als normales LLM-Backend verwenden.

---

# 10. Frontend

Es wird keine klassische Desktop-GUI benötigt.

Stattdessen startet `moritz-agent` einen eingebauten Webserver.

Beispiel:

```text
http://127.0.0.1:5001
```

Optional kann der Browser automatisch geöffnet werden.

Später kann das System ebenfalls extern bereitgestellt werden, beispielsweise über:

```text
https://ai.example-domain.de
```

Das gleiche responsive Frontend kann später in einer Android-WebView-App verwendet werden.

Architektur:

```text
Desktop Browser ──────┐
                      │
Android WebView ──────┼── moritz-agent Backend
                      │
Remote Browser ───────┘
```

Dadurch existiert nur eine einzige UI-Codebasis.

---

# 11. WebUI-Konzept

Telefonstatus ist bereits in Part 1 sichtbar: Registrierung, Anrufzustand, STT/TTS-Bereitschaft, letzte Fehler und Suchstatus. Keine Anzeige der Passwörter.

## Linke Seitenleiste

```text
+ New Chat

Chats
────────────
Router Problem
Qwen Tests
Coding Projekt

Agents
────────────
Research
Coding
General
```

## Hauptbereich

```text
Moritz:
Recherchiere XYZ und installiere ...

Agent:
Ich erstelle zunächst einen Plan...

┌ Search Web
│ 8 results
└ ✓

┌ Read Website
│ example.com
└ ✓

┌ SSH → Redemption-Agent
│ apt install ...
└ ✓

┌ Python
│ analyze.py
└ ✓

Antwort...
```

## Rechte Seitenleiste

Optional:

```text
MODEL
7–9B Instruct · Q4

CONTEXT
2,800 / 4,096

TOOLS
✓ Web
✓ Browser
✓ Shell
✓ Python
✓ Files

AGENT VM
● Connected

GPU
97 %
7.6 / 8 GB
```

---

# 12. Sophie-1: Proxmox-Host mit GPU-LXC

Bestätigte Hardware und Umgebung:

- Sophie-1 läuft mit Proxmox VE.
- 32 GB physischer Arbeitsspeicher.
- NVIDIA RTX 3070 mit 8 GB VRAM, physisch in Sophie-1.
- Mindestens 10 GB RAM bleiben für Host, bestehende Dienste und deren Bedarf reserviert.
- Somit höchstens 22 GB RAM als Ausgangsbudget für zusätzliche Last; davon wird nicht alles fest verplant.
- CPU-Modell, Proxmox-Version, aktuelle Speichernutzung und freie SSD-Kapazität müssen vor der Einrichtung erfasst werden.

## RAM-Aufteilung zum Start

| Bereich | Budget auf Sophie-1 |
| --- | ---: |
| Host, vorhandene Dienste und deren Bedarf | mindestens 10 GB RAM |
| moritz-agent LXC | zunächst 16 GB RAM als Limit |
| Zusätzlicher Spielraum | 6 GB RAM |
| RTX 3070 | separater Speicher: 8 GB VRAM |

Die 10 GB sind Moritz’ eingeplantes Budget, keine allgemeine Mindestanforderung von Proxmox. Das LXC-Limit ist ein Höchstwert und keine permanente Reservierung. Andere Gäste und Lastspitzen müssen innerhalb des Gesamtbudgets bleiben.

RAM und VRAM sind keine gemeinsame 30-GB-Speicherfläche. Modellgewichte, CPU-Anteile, Kontext-Cache, Rechenpuffer, Dateicache und Nebenprozesse benötigen jeweils Speicher. Auch GPU-Offload beseitigt den RAM-Bedarf nicht vollständig.

## Ausführungsort

Auf dem Proxmox-Host läuft der NVIDIA-Kerneltreiber. Die Anwendung läuft in einem dedizierten, möglichst unprivilegierten Linux-LXC:

- KoboldCPP-Inference mit CUDA
- genau ein geladenes großes Sprachmodell
- SIP-/Audio-Worker mit kleinen CPU-Modellen für STT und TTS
- Agent Core und Context Manager
- SearXNG und einfacher HTTP-Web-Fetcher
- SQLite, Backend und WebUI
- Verbindung zur separaten Sandbox auf Redemption-1

Shell-Tools, fremder Code, Compiler und Chromium laufen standardmäßig in der Sandbox-VM auf Redemption-1. Der Agent erhält keine allgemeine Shell auf dem Proxmox-Host oder im Inference-LXC.

## GPU-Zugriff im LXC

LXC teilt den Kernel des Hosts. Hier wird Gerätezugriff auf die erforderlichen NVIDIA-Geräte eingerichtet; das ist kein vollständiges PCIe-Passthrough wie bei einer VM.

1. NVIDIA-Treiber auf dem Proxmox-Host installieren und die GPU dort prüfen.
2. Erforderliche NVIDIA-Geräteknoten, einschließlich der für CUDA benötigten UVM-Geräte, in den LXC durchreichen.
3. Geräteberechtigungen beziehungsweise UID/GID-Zuordnung für den Container korrekt setzen.
4. Zum Host-Treiber passende NVIDIA-Userspace-Bibliotheken und die benötigte CUDA-Laufzeit im LXC bereitstellen. Im LXC keinen eigenen Kernel-Treiber bauen.
5. GPU-Erkennung im LXC und anschließend einen echten CUDA-Modelllauf prüfen.
6. Nach Host-Kernel- oder Treiberupdates die Kombination erneut prüfen.

Die genaue Gerätekonfiguration wird aus der vorhandenen Installation abgeleitet. Keine ungeprüften Major-Nummern oder pauschal offenen Geräteberechtigungen übernehmen.

Die GPU darf für diesen Betriebsmodus nicht exklusiv per VFIO an eine andere VM gebunden sein. Andere GPU-Nutzer teilen sich Rechenleistung und VRAM; 8 GB installierter VRAM bedeuten nicht automatisch 8 GB freien VRAM. Es ist keine vGPU-Lizenz oder Aufteilung in virtuelle Grafikkarten vorgesehen.

## Erstes Modell und Startprofil

| Einstellung | Startwert / Ziel |
| --- | --- |
| Modellklasse | Instruction-Modell mit 7–9 Milliarden Parametern |
| Format | GGUF, zunächst Q4_K_M oder vergleichbare 4-Bit-Quantisierung |
| Modellgewichte | grob 4–6 GB, tatsächliche Datei prüfen |
| Kontext | zunächst 4.096 Tokens |
| GPU-Offload | möglichst vollständig, anhand der tatsächlichen Speichernutzung einstellen |
| Geladene Sprachmodelle | genau eines |
| Gleichzeitige Generierungen | eine, weitere Aufträge in einer Warteschlange |
| Zweites / Draft-Modell | deaktiviert |
| Kontext-Cache | Quantisierung optional, sofern Modell und Backend sie unterstützen |

Die Angaben sind Planungswerte, keine Garantie für jedes Modell dieser Größenklasse. Modellarchitektur, Kontext und Backend beeinflussen den Speicherbedarf. Das konkrete Modell wird anhand von Deutschqualität, Tool-Calling, Coding und unterstütztem Chat-Template ausgewählt und getestet.

8.192 Tokens erst freigeben, wenn der gemessene VRAM- und RAM-Verbrauch ausreichend Reserve lässt. Bei Speicherproblemen zuerst Kontext, Batch-Größe und gegebenenfalls GPU-Layer reduzieren. CPU-Offload ist eine Ausweichmöglichkeit, keine Geschwindigkeitsgarantie. Swap dient nicht als regulärer Modellspeicher.

Das bisher als Beispiel genannte 35B-Modell ist kein Startziel mehr. Größere Modelle bleiben spätere Experimente nach Messung von Speicherbedarf und Antwortgeschwindigkeit.

---

# 13. Redemption-1 als Sandbox-Host

Auf Redemption-1 bleibt wie im bisherigen Plan eine dedizierte VM für Agent-Aktionen vorgesehen. Die bestätigten 32 GB RAM und die RTX 3070 gehören zu Sophie-1; sie sind nicht das Ressourcenbudget dieser separaten Maschine.

Die Sandbox bekommt als vorläufigen Startwert 4 GB RAM und 2–4 vCPUs, sofern Redemption-1 dafür ausreichend freie Ressourcen besitzt. Chromium startet nur bei Bedarf, zunächst mit höchstens zwei aktiven Seiten. Compiler und umfangreiche Browser-Arbeit laufen nicht gleichzeitig. Mehr RAM erst nach Messung und Prüfung der freien Ressourcen zuweisen.

Beispiel:

```text
Sophie-1
┌───────────────────────────┐
│ moritz-agent              │
│                           │
│ LLM                       │
│ Search                    │
│ UI                        │
│ Agent brain               │
└──────────────┬────────────┘
               │
         secure RPC/SSH
               │
               ▼
Redemption-1
┌───────────────────────────┐
│ moritz-agent Sandbox VM   │
│                           │
│ bash                      │
│ python                    │
│ git                       │
│ compiler                  │
│ chromium                  │
│ downloads                 │
│ agent workloads           │
└───────────────────────────┘
```

Die Sandbox-VM darf relativ frei arbeiten.

Dort kann der Agent:

- Shell-Befehle ausführen
- Python nutzen
- Git verwenden
- Software installieren
- Dateien herunterladen
- Projekte klonen
- Code kompilieren
- Programme testen
- Browser-Automation durchführen
- Dateien verändern

---

# 14. Sicherheit der Sandbox

Die Sandbox darf **nicht pauschal Zugriff auf das gesamte Homelab bekommen**.

Erlaubt:

- Internet
- Sophie API
- Agent Backend
- benötigte Services

Nicht standardmäßig erlaubt:

- Proxmox Management
- OPNsense
- andere Server
- NAS
- produktive Daten
- komplette internen Netze

Grund:

Webseiten können Prompt-Injection enthalten.

Ein autonomer Agent sollte deshalb nicht direkt Zugriff auf produktive Infrastruktur besitzen.

---

# 15. Sandbox-Verwaltung

Später kann `moritz-agent` Sandboxes automatisch verwalten.

Beispiel:

```text
Create workspace
↓
Snapshot
↓
Run agent
↓
Collect results
↓
Destroy workspace
```

Mögliche Erweiterungen:

- temporäre VM
- temporärer Container
- Snapshot-basierte Wiederherstellung
- Workspace pro Chat
- Workspace pro Task

---

# 16. Agent Core

Der Agent Core ist das Herz des Projekts.

Er übernimmt:

- Agent Loop
- Task Planning
- Reasoning-Steuerung
- Tool-Auswahl
- Context Management
- Memory
- Retry-Logik
- Fehlerbehandlung
- Token-Budget
- Tool-Ergebnisse
- Modellwahl
- Task State

Grundprinzip:

```text
User Prompt
↓
Agent plant
↓
Agent wählt Tool
↓
Tool wird ausgeführt
↓
Ergebnis zurück an LLM
↓
Agent bewertet Ergebnis
↓
nächster Schritt
↓
Final Answer
```

---

# 17. Tools

Die Tools sollten sauber getrennt werden.

Mindestens:

```text
get_current_time
web_search
web_fetch
browser
shell
python
files
git
http
download
archive
ssh
```

Später möglich:

```text
database
email
calendar
docker
proxmox
image
ocr
mcp
```

Die Tools sollten standardisierte Schemas verwenden.

Zum Beispiel JSON oder MCP.

---

# 18. Research Engine

Die Research Engine ist ein eigener Bestandteil.

Sie besteht aus:

```text
SearXNG
+
Web Fetcher
+
Browser
+
Content Extraction
+
Source Evaluation
+
Research Planner
```

---

# 19. Normale Websuche

Einfache Suche:

```text
User
↓
Agent
↓
Search Query
↓
SearXNG
↓
10 Ergebnisse
↓
Agent
↓
Antwort
```

---

# 20. Browse-Modus

Der Agent kann einzelne Ergebnisse weiter untersuchen.

Beispiel:

```text
Result 3 interessant
↓
Seite abrufen
↓
HTML reinigen
↓
relevanten Inhalt extrahieren
↓
Agent bekommt Inhalt
```

---

# 21. Browser-Automation

Für Seiten, die mit normalem HTTP Fetching nicht funktionieren, wird ein echter Browser benutzt.

Technik:

```text
Chromium
+
Playwright
```

Der Agent kann damit:

- Webseiten öffnen
- klicken
- scrollen
- JavaScript ausführen lassen
- Formulare ausfüllen
- Downloads starten
- Screenshots erstellen
- dynamische Webseiten bedienen

---

# 22. Deep Research

Deep Research wird ein eigener Agent-Modus.

Pipeline:

```text
Frage
 ↓
Research Plan
 ↓
5–15 Suchqueries
 ↓
30–100 Ergebnisse
 ↓
Quellen auswählen
 ↓
Webseiten lesen
 ↓
Behauptungen extrahieren
 ↓
weitere Fragen entdecken
 ↓
weitere Recherche
 ↓
Quellen gegeneinander prüfen
 ↓
Synthese
 ↓
Antwort + Quellen
```

Der Agent soll dabei:

- mehrere Quellen vergleichen
- widersprüchliche Aussagen erkennen
- Folgefragen generieren
- Quellen bewerten
- Quellen speichern
- Zitate und Links erhalten
- Ergebnisse zusammenführen

---

# 23. Coding-Agent

Ein eigener Coding-Modus ist ebenfalls vorgesehen.

Workflow:

```text
Repository klonen
↓
Projekt analysieren
↓
Dateien lesen
↓
Problem identifizieren
↓
Code ändern
↓
Tests ausführen
↓
Fehler analysieren
↓
erneut ändern
↓
Diff prüfen
↓
Ergebnis liefern
```

Tools:

- Git
- Shell
- Python
- Compiler
- Test Runner
- Filesystem
- Browser
- Web Search

---

# 24. Memory

Memory sollte nicht einfach durch einen riesigen Chat-Kontext umgesetzt werden.

Stattdessen drei Ebenen:

## Aktueller Kontext

Aktuelle Unterhaltung und Task.

## Persistentes Memory

Wichtige Fakten:

- Benutzerpräferenzen
- Projekte
- Systeme
- häufige Anforderungen

## Retrieval Memory

Dokumente, Dateien, alte Chats und Projektdaten werden bei Bedarf gesucht und in den Kontext geladen.

---

# 25. Datenbank

Für den Anfang reicht SQLite.

Gespeichert werden:

```text
conversations
messages
agents
tasks
tool_calls
research_runs
sources
files
memories
settings
models
```

Später kann bei Bedarf PostgreSQL verwendet werden.

---

# 26. Model Manager

Die WebUI sollte einen Model Manager erhalten.

Funktionen:

- GGUF-Dateien erkennen
- Modelle laden
- Modelle entladen
- Quantisierung anzeigen
- Context konfigurieren
- GPU Layers einstellen
- Backend auswählen
- Presets speichern

Beispiel:

```text
<ausgewaehltes-7B-bis-9B-Instruct-Modell>-Q4_K_M.gguf
```

---

# 27. Agent-Modi

Mögliche v1-Agenten:

```text
Phone (ab Part 1)
General
Research
Coding
Browser
```

Später:

```text
Sysadmin
Document
Data Analysis
Security Analysis
Network
DevOps
```

---

# 28. Multi-Agent-System

Nicht zwingend für Version 1.

Die Architektur sollte es aber später erlauben. Auf der Start-Hardware teilen sich alle Rollen ein geladenes Modell und eine Inference-Warteschlange. Mehrere Rollen bedeuten weder mehrere Modellkopien noch parallele Generierungen. Die nachfolgenden Rollen sind ein späterer Ausbau, kein Bestandteil der ersten Version.

Beispiel:

```text
Supervisor
│
├── Research Agent
├── Coding Agent
├── Browser Agent
└── Review Agent
```

Beispielaufgabe:

```text
Finde heraus, warum Software X abstürzt.
```

Dann:

```text
Research Agent
→ Dokumentation und Issues suchen

Coding Agent
→ Repository analysieren

Browser Agent
→ Webseiten und Tracker untersuchen

Review Agent
→ Ergebnisse auf Fehler prüfen
```

Der Supervisor sammelt anschließend alles und erstellt die finale Antwort.

---

# 29. Android-App

Die Android-App wird erst später gebaut.

Sie verwendet einfach das bestehende Webfrontend.

Technik:

```text
Android App
↓
WebView
↓
moritz-agent WebUI
```

Optional später:

- Datei-Upload
- Kamera
- Mikrofon
- Notifications
- Share Intent
- Download Manager

Dadurch muss keine zweite Oberfläche entwickelt werden.

---

# 30. Produktziel

Das Ziel ist nicht:

> KoboldCPP mit anderem Logo.

Das Ziel ist:

> Ein eigenständiger lokaler KI-Agent mit KoboldCPP als Inference Engine.

Beispielaufgabe:

```text
Recherchiere, welche HBA-Firmware für Karte X aktuell sinnvoll ist,
vergleiche fünf Quellen,
lade die passende Firmware in deine VM,
untersuche sie,
erstelle mir eine Anleitung
und speichere das Ergebnis als Datei.
```

Der Agent soll daraufhin tatsächlich:

```text
Search
↓
Browse
↓
Read
↓
Download
↓
Shell
↓
Python
↓
Analyze
↓
Verify
↓
Create File
↓
Answer
```

durchführen können.

---

# 31. Prozessarchitektur

Empfohlen:

```text
moritz-agent Main
│
├── Phone / Audio Worker (SIP, VAD, STT, TTS)
│
├── Inference Worker
│
├── Search Worker
│
├── Remote Browser Client
│
├── Agent Worker
│
└── Sandbox RPC Worker
```

Kommunikation intern beispielsweise über:

- HTTP localhost
- Unix Socket
- Named Pipes
- IPC
- Python multiprocessing

---

# 32. Startablauf

Beispiel:

```text
moritz-agent startet
↓
Config laden
↓
Logs initialisieren
↓
SQLite öffnen
↓
Inference Engine starten
↓
SearXNG starten
↓
Sandbox-Verbindung prüfen; Chromium remote bei Bedarf starten
↓
Agent Core starten
↓
HTTP API starten
↓
Frontend und Telefonstatus bereitstellen
↓
Audio-Bereitschaft prüfen und SIP registrieren
↓
Interne Anrufe annehmen; Browser optional öffnen
```

---

# 33. Fehlerisolierung

Jede große Komponente sollte isoliert sein.

Beispiel:

```text
Chromium crash
→ Browser Worker neu starten

SearXNG crash
→ Search Worker neu starten

Sandbox offline
→ Agent zeigt Tool unavailable

LLM crash
→ Inference Worker neu starten
```

SIP-Worker-Ausfälle werden separat erkannt; Registrierung wird mit begrenztem Backoff wiederholt. Ein abgebrochener Anruf wird nicht als weiterlaufendes Gespräch übernommen. LLM-/Suchfehler erhalten telefongeeignete Statusansagen.

Die gesamte Anwendung soll dadurch möglichst stabil bleiben.

---

# 34. Logging

Alle Agent-Aktivitäten sollten nachvollziehbar sein.

Beispiel:

```text
[Agent]
Created plan

[Search]
Query: "..."

[Browser]
Opened https://...

[Tool]
shell: apt install ...

[LLM]
Generation finished

[Sandbox]
Command exit code: 0
```

Die UI kann daraus später einen sichtbaren Agent-Timeline-Bereich erzeugen.

---

# 35. Portfolio-Aspekt

Die Agent-Aktivität sollte sichtbar sein.

Nicht nur:

```text
Thinking...
```

sondern:

```text
✓ Search Web
✓ Read 8 Sources
✓ Open Browser
✓ Execute Python
✓ Clone Repository
✓ Run Tests
✓ Compare Results
```

Das zeigt klar, dass es sich um einen echten Agenten handelt und nicht nur um einen Chatbot.

---

# 36. Lizenzthema

Da KoboldCPP und SearXNG unter Copyleft-Lizenzen stehen, müssen die jeweiligen Lizenzbedingungen berücksichtigt werden.

Insbesondere bei einer öffentlich bereitgestellten Version müssen Source-Code- und Lizenzpflichten eingehalten werden.

Das Projekt sollte daher von Anfang an:

- LICENSE-Dateien behalten
- ursprüngliche Copyright-Hinweise erhalten
- Third-Party-Notices dokumentieren
- Vendor-Komponenten klar kennzeichnen

---

# 37. Versionsplan – Telefon zuerst

## Part 1 / Version 0.1: Anrufbarer Agent als vollständiger erster Meilenstein

- GPU-LXC auf Sophie-1 und KoboldCPP-Grundlage einrichten.
- Eigenständiges Projekt moritz-agent mit Installations- und Updateskripten.
- Editierbare passwords.txt mit vorbelegten SIP-Daten; Web-Login und Sandbox-Zugang im Installer erfassen.
- SIP-Registrierung als agent; interne Erreichbarkeit über den bestehenden Dialplan für 999 prüfen.
- Automatisch annehmen und vorbereitete Begrüßung abspielen.
- Deutsche Sprache erkennen, mehrere Gesprächsrunden führen und Antworten sprechen.
- Uhrzeit-Tool mit Europe/Berlin; Antwort unabhängig von geratenem LLM-Wissen.
- Einfache Websuche über SearXNG und kurze gesprochene Zusammenfassung.
- Minimales Backend, Sitzungsverwaltung, Tool-Router und Telefonstatus von Beginn an.
- Ein 7–9B-LLM in 4 Bit, 4.096 Tokens Kontext; kleine CPU-Sprachmodelle innerhalb des gemeinsamen RAM-Budgets testen.
- Gesprächsabbruch, Stille, unverständliche Eingabe, Suchfehler und belegte Leitung behandeln.
- Abnahme über reale Telefonate, nicht nur einen Webchat oder erfolgreiche Registrierung.

## Part 2 / Version 0.2: WebUI ausbauen

Chat, Streaming, Verlauf, Anrufstatus, Modellverwaltung und komfortable Einstellungen. Telefonie aus Part 1 bleibt vollständig nutzbar.

## Part 3 / Version 0.3: Backend und Speicher ausbauen

Eigene APIs, SQLite-Historie, sauber getrennte Gesprächssitzungen, Task-Verwaltung und Wiederaufnahme geeigneter Hintergrundaufgaben. Das notwendige Minimalbackend existiert schon in Part 1.

## Part 4 / Version 0.4: Sandbox und Coding-Tools

Im Installer hinterlegte SSH-Verbindung aktiv nutzen, getrennte Workspaces, Dateien, Git, Python und Tests auf Redemption-1. Administrative Aktionen sind nicht allein durch einen Telefonanruf freigeschaltet.

## Part 5 / Version 0.5: Recherche ausbauen

Die einfache Suche aus Part 1 um Quellenverwaltung, mehrseitige Recherche, bessere Extraktion und längere Ergebnisdarstellung in der WebUI erweitern.

## Part 6 / Version 0.6: Browser-Automation

Chromium/Playwright in der Sandbox, dynamische Seiten, Downloads und strukturierte Browser-Tools.

## Part 7 / Version 0.7: Telefonkomfort

Natürliches Unterbrechen der Sprachausgabe mit Echo-Behandlung, bessere Latenz, konfigurierbare Stimmen und optionale DTMF-Steuerung. Weiterleitungen oder ausgehende Anrufe erst als separat konfigurierte Erweiterung mit klaren Berechtigungen.

## Part 8 / Version 0.8: Memory

Gesprächszusammenfassungen, persistente Fakten und Retrieval. Telefon und Web nutzen die gleiche kontrollierte Memory-Infrastruktur.

## Part 9 / Version 0.9: Deep Research

Rechercheplanung, Quellenvergleich, Folgefragen und belegte Berichte. Lange Aufgaben geben am Telefon eine kurze Statusantwort und liefern die ausführlichen Ergebnisse in der WebUI.

## Version 1.0

Integrierter Telefon- und General-Agent mit Chat, Suche, Research, Coding, Sandbox, Memory und WebUI.

## Version 1.1+

Android-WebView-App, Multi-Agent-Rollen, Plugins/MCP, zusätzliche Modelle, Bilder und weitere Integrationen. Spracherkennung und Sprachausgabe sind bereits seit Part 1 vorhanden und werden nicht hierher verschoben.

---

# 38. Endgültige Architektur

Zusätzlicher gleichberechtigter Eingang ab Part 1: internes Telefon → Asterisk 192.168.1.176 → registrierter SIP-/Audio-Worker im Agent-LXC → STT → Agent/Tools → TTS → Telefon. Die vorbereitete Begrüßung wird direkt aus dem Audio-Worker abgespielt.

```text
Desktop Browser
Android WebView
Remote Browser
       │
       ▼
┌──────────────────────────────────────┐
│            moritz-agent              │
│                                      │
│  WebUI                               │
│    ↓                                 │
│  Backend API                         │
│    ↓                                 │
│  Agent Core                          │
│    ├── Memory                        │
│    ├── Planner                       │
│    ├── Tool Calling                  │
│    └── Research                      │
│         │                            │
│         ├── SearXNG                  │
│         ├── Web Fetch                │
│         └── Remote Browser Client    │
│                                      │
│  Inference                           │
│    ↓                                 │
│  KoboldCPP im GPU-LXC                │
│    ↓                                 │
│  llama.cpp                           │
│    ↓                                 │
│  CUDA / GPU                          │
└──────────────────┬───────────────────┘
                   │
                   │ Secure RPC / SSH
                   ▼
┌──────────────────────────────────────┐
│ Redemption-1 Agent Sandbox VM        │
│                                      │
│ Shell                                │
│ Python                               │
│ Git                                  │
│ Compiler                             │
│ Browser                              │
│ Downloads                            │
│ Temporary Workspaces                 │
└──────────────────────────────────────┘
```

---

# 39. Kurzfassung

`moritz-agent` wird ein eigenständiges lokales KI-Agent-System. Die wichtigste Funktion ist ab Part 1 der intern anrufbare Telefon-Agent mit vorbereiteter Begrüßung, Zuhören, Uhrzeit-Tool und Websuche.

Die wichtigsten Bestandteile:

```text
KoboldCPP
+
llama.cpp
+
SearXNG
+
Chromium / Playwright
+
Agent Runtime
+
Tool Calling
+
Sandbox
+
Memory
+
Deep Research
+
Coding Agent
+
eigenes Backend
+
eigene WebUI
```

Nach außen erscheint alles als:

```text
moritz-agent
```

eine Anwendung, ein Repository und ein Interface.

Intern werden mehrere spezialisierte Worker verwendet, damit Inference, Search, Browser und Sandbox voneinander isoliert bleiben.

Sophie-1 betreibt Proxmox. In einem dedizierten GPU-LXC laufen Inference und Agent mit zunächst 16 GB RAM als Limit und Zugriff auf die RTX 3070. Mindestens 10 GB bleiben für Host und vorhandene Dienste eingeplant, weitere 6 GB als Spielraum.

Redemption-1 stellt eine separate Sandbox-VM bereit, in der der Agent Shell, Python, Git, Browser, Downloads und andere aktive Aufgaben ausführen kann.

Das langfristige Ziel ist ein lokaler General-Agent, der nicht nur antwortet, sondern selbstständig:

- recherchiert
- Webseiten bedient
- Dateien bearbeitet
- Code schreibt
- Tests ausführt
- Software analysiert
- Shell-Kommandos verwendet
- Ergebnisse überprüft
- Quellen sammelt
- Aufgaben plant
- mehrere Arbeitsschritte autonom ausführt

und das Ganze über eine eigene WebUI sowie später eine Android-WebView-App verfügbar macht.


---

# 40. Speicherbewusster Agent-Betrieb

Die folgenden Regeln gelten für alle Module und konkretisieren die allgemein beschriebenen Funktionen:

- Phone, Research, Coding und General verwenden dasselbe geladene Modell mit unterschiedlichen Systemanweisungen und freigegebenen Tools.
- SearXNG und HTTP-Fetching laufen im LXC; Chromium läuft ausschließlich bei Bedarf in der entfernten Sandbox.
- Webseiten und Tool-Ausgaben werden vollständig als Dateien beziehungsweise Datenbankeinträge gespeichert. Das Modell erhält nur relevante Ausschnitte mit Quellenbezug.
- Deep Research verarbeitet Quellen in kleinen Gruppen. 30–100 Ergebnisse sind ein mögliches Gesamtvolumen über viele Schritte, kein einzelner Prompt.
- Der Context Manager reserviert Platz für die Antwort, Tool-Schemas und Systemanweisungen. Historie wird vor Erreichen des Limits gekürzt oder zusammengefasst.
- Zusammenfassungen behalten Quellen-IDs und Dateiverweise. Originale bleiben für erneutes Nachlesen erhalten.
- Retrieval beginnt mit SQLite-Suche beziehungsweise Volltextsuche. Ein dauerhaft geladenes zusätzliches Embedding-Modell ist nicht Teil des Startprofils.
- Modellwechsel entlädt zuerst das bisherige Modell. Keine gleichzeitig geladenen großen Modelle.
- Begrenzte Tool-Schrittzahl, Laufzeit und Ausgabegröße verhindern endlose Schleifen und unkontrollierten Speicherverbrauch.
- Das kleine Modell muss Tool-Aufrufe über gültige Schemas liefern. Fehlerhafte Argumente werden geprüft und mit begrenzten Wiederholungen korrigiert.
- Ein kleineres Modell begrenzt die Zuverlässigkeit bei anspruchsvollem autonomem Coding. Tools und Memory ersetzen keine fehlende Modellfähigkeit.

# 41. Umsetzung und Abnahme auf der tatsächlichen Hardware

1. Sophie-1 inventarisieren, GPU-LXC mit 16 GB RAM-Limit vorbereiten und CUDA prüfen.
2. Installer mit vorhandenen SIP-Vorgaben, interaktivem Web-Login und optional einrichtbarer Sandbox-Verbindung ausführen. Erneutes Ausführen muss angepasste Daten erhalten.
3. SIP-Registrierung und Routing der Nebenstelle 999 separat prüfen. Erfolgreiches REGISTER allein gilt nicht als bestandener Anruftest.
4. Vom internen Telefon anrufen: Agent nimmt an, spielt die vorbereitete Begrüßung und empfängt verständliches Audio. Audio in beide Richtungen einschließlich RTP prüfen.
5. Uhrzeit erfragen und mit der aktuellen Europe/Berlin-Systemzeit vergleichen. Datum/Sommerzeit korrekt behandeln; Uhrzeit kurz vor der Sprachausgabe lesen.
6. Mindestens drei Gesprächsrunden im selben Anruf durchführen. Unverständliche Sprache, Stille, Auflegen während einer Antwort und einen zweiten Anruf testen.
7. Eine aktuelle Suchfrage stellen. Suchaufruf und Quellen protokollieren, Antwort kurz sprechen. Bei deaktivierter Suche eine ehrliche Fehlermeldung statt erfundener Ergebnisse verlangen.
8. LLM, STT, TTS, SearXNG und SIP gemeinsam belasten; RAM/VRAM und Zeit bis zur Antwort messen. Keine OOM-Abbrüche oder dauerhafter Swap-Druck. Erst auf dieser Basis Kontext oder Modelle vergrößern.
9. SIP-Passwort beziehungsweise Registrar testweise über die TXT ändern, kontrolliert neu laden und mit der Telefonanlage konsistent zurücksetzen. Bestehende Anrufe nicht unterbrechen.
10. Update mit eigenen Zugangsdaten testen: Werte bleiben erhalten, fehlende neue Felder werden ergänzt, Dienst und Registrierung kommen wieder hoch. Geheimnisse dürfen weder im Web noch in Logs erscheinen.
11. Später die Sandbox mit abgegrenzter Coding-Aufgabe und Browser-Tests abnehmen. Die Telefon-Grundfunktion muss auch bei ausgeschalteter Sandbox nutzbar bleiben.

Part 1 ist erst fertig, wenn das echte Telefonieren einschließlich Suche funktioniert. Tokenrate, STT-Zeit, TTS-Anlauf und gesamte Antwortlatenz werden gemessen; feste Geschwindigkeitsversprechen ohne Kenntnis der CPU gibt es nicht.

# 42. Technische Referenzen

- [Proxmox: Container-Konfigurationsoptionen einschließlich Geräte-Passthrough](https://github.com/proxmox/pve-docs/blob/master/generated/pct.conf.5-opts.adoc)
- [Linux Containers: NVIDIA-CUDA und Userspace-Bibliotheken im Container](https://discuss.linuxcontainers.org/t/nvidia-cuda-inside-a-lxd-container-ubuntu-20-04/11223) — beschreibt LXD; Proxmox-LXC benötigt seine eigene Gerätekonfiguration.
- [KoboldCPP: offizielle Dokumentation zu GPU-Offload, Kontext und Speicher](https://github.com/LostRuins/koboldcpp/wiki)

Konkrete Installationsbefehle werden erst aus der vorhandenen Proxmox-, Kernel- und Treiberversion abgeleitet.

- [PJSIP/PJSUA2: Konten, Registrierung und RTP-Konfiguration](https://docs.pjsip.org/en/latest/api/generated/pjsip/group/group__PJSUA2__ACC.html)
- [PJSIP/PJSUA2: Audio-Medienanbindung](https://github.com/pjsip/pjproject_docs/blob/master/docs/source/pjsua2/using/media_audio.rst)

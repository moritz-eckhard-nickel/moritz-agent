# 01 – Anforderungskatalog

Quelle: [`00-originalplan.md`](00-originalplan.md) (Stand 16.10.2026). Dieses Dokument
zerlegt den Originalplan in **prüfbare, nummerierte Anforderungen**. Jede Anforderung hat
eine ID, eine Priorität und den Part, in dem sie fertig sein muss. Tickets in
[`04-part1-umsetzung.md`](04-part1-umsetzung.md) verweisen auf diese IDs.

**Prioritäten:** `MUSS` = Abnahmekriterium des Parts · `SOLL` = geplant, Abweichung nur
mit Begründung · `KANN` = optional / wenn Zeit ist.

**Regel:** Wird eine Anforderung geändert, wird sie hier geändert (nicht nur im Code).
Der Originalplan bleibt unverändert als Referenz.

---

## 1. Produkt (PRD)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| PRD-01 | Aus Nutzersicht genau **eine Anwendung**, **ein Startbefehl** (`./moritz-agent`), **eine zentrale Konfiguration** plus editierbare `passwords.txt`, **eine Weboberfläche**, **ein Repository**. | MUSS | 1 |
| PRD-02 | Intern dürfen mehrere Worker/Child-Prozesse laufen; Absturz eines Workers reißt die anderen nicht mit. | MUSS | 1 |
| PRD-03 | KoboldCPP ist die Inference-Komponente, nicht das Produkt. Der Nutzer muss nicht wissen, dass KoboldCPP darunter läuft. | SOLL | 2 |
| PRD-04 | Der interne Telefon-Agent ist die **höchste Priorität** und Bestandteil von Part 1 – kein späteres Zusatzfeature. | MUSS | 1 |
| PRD-05 | Part 1 ist erst abgeschlossen, wenn ein **echter Anruf** mit Begrüßung, Zuhören, Uhrzeitantwort und einfacher Websuche funktioniert. | MUSS | 1 |
| PRD-06 | Lizenzen: eigener Code **MSOL 1.1**, Scribbles/Logo alle Rechte vorbehalten, Fremdcode behält seine Lizenz (AGPL-3.0 KoboldCpp/SearXNG, MIT llama.cpp/ggml, GPL-2.0+ PJSIP); Copyright-Hinweise der Fremdteile bleiben erhalten (ADR-023, `LICENSING.md`). | MUSS | 1 |
| PRD-07 | ~~Windows-Start (`moritz-agent.exe`)~~ – **entfällt** (Moritz, F-12: „niemals“). Zielplattform ist ausschließlich Linux (Ubuntu) im LXC. | – | – |
| PRD-08 | Einheitliches Branding „moritz-agent“ / „m-agent“ mit monochromem Logo (**M + Scribbles**) überall, wo Nutzer etwas sehen (README, WebUI, Favicon, Icons, Metadaten). **Scribbles**, das LayerNX-Maskottchen, ist das Maskottchen von moritz-agent und erscheint überall, wo eine Figur sinnvoll ist ([Branding-Regeln](../../assets/branding/README.md)). KoboldCpp-Oberflächen sind entfernt (F-11). | MUSS | 1 |
| PRD-10 | Der Assistent heißt **Nikita** (männlich, Stimme Thorsten-Voice Hessisch) – in Begrüßung, Systemprompt, Antworten, SIP-Anzeigename und Oberfläche. Technische Namen (Produkt `moritz-agent`, Repo, SIP-Konto `agent`) bleiben (ADR-026). | MUSS | 1 |
| PRD-09 | Alle Programmbestandteile liegen **im Repository** und laufen als Teil des einen Programms: SearXNG (fertig gebaut), pjproject, VAD-Modell (ADR-021). Aus dem Netz kommen nur Abhängigkeiten (PyPI-Pakete mit Hashes, CUDA-Build-Toolchain, Systempakete) und die Hugging-Face-Modelle. | MUSS | 1 |

## 2. Telefonie (PHONE)

### 2.1 SIP und Registrierung

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| PHONE-01 | Integrierter SIP-Worker registriert sich als normaler SIP-Teilnehmer mit Konto `agent` am Registrar `192.168.1.176:5060/udp`. Werte stammen ausschließlich aus `passwords.txt`. | MUSS | 1 |
| PHONE-02 | Nebenstelle (`999`) und SIP-Benutzername (`agent`) sind getrennte Werte. Die Dialplan-Zuordnung 999 → agent wird beim Einrichten **geprüft**, nicht angenommen. | MUSS | 1 |
| PHONE-03 | Implementierungskandidat PJSIP/PJSUA2 inkl. Audio-Medienanbindung; Version wird gepinnt (siehe ADR-005). | MUSS | 1 |
| PHONE-04 | RTP/RTCP über einen konfigurierbaren lokalen Portbereich; Erreichbarkeit zur Telefonanlage wird geprüft. | MUSS | 1 |
| PHONE-05 | Codec-Aushandlung (Präferenz G.722 > PCMA > PCMU), Umwandlung Telefon-Audio → STT-Format (16 kHz mono PCM16) und TTS-Ausgabe → Telefon-Audio sind Teil des Phone-Workers. | MUSS | 1 |
| PHONE-06 | Betrieb ohne Mikrofon und ohne Soundkarte (Null-Audio-Device). | MUSS | 1 |
| PHONE-07 | Registrierungsfehler werden mit begrenztem exponentiellem Backoff wiederholt; Status ist in UI/API sichtbar. | MUSS | 1 |
| PHONE-08 | SIP-Änderungen in `passwords.txt` lösen nach kontrolliertem Reload eine Neuregistrierung aus, **sobald kein Gespräch aktiv ist**. | MUSS | 1 |
| PHONE-09 | Eingehende INVITEs werden nur von der konfigurierten Telefonanlage (Registrar-IP bzw. Allowlist) angenommen; alles andere wird abgewiesen (Schutz vor SIP-Scannern). | MUSS | 1 |
| PHONE-10 | Part 1 startet **keine ausgehenden Anrufe**. | MUSS | 1 |

### 2.2 Gesprächsablauf

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| PHONE-20 | Eingehenden internen Anruf automatisch annehmen. | MUSS | 1 |
| PHONE-21 | Sofort die vorbereitete Begrüßung abspielen: „Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?“ (Name geändert, ADR-026) – aus einer zwischengespeicherten Audiodatei, **ohne LLM-Wartezeit**. | MUSS | 1 |
| PHONE-22 | Nach der Begrüßung zuhören, Sprachende per VAD erkennen, Äußerung auf Deutsch transkribieren. | MUSS | 1 |
| PHONE-23 | Bei Uhrzeitfragen („Wie viel Uhr haben wir?“) ein **echtes Uhrzeit-Tool** aufrufen und kurz antworten („Es ist 19 Uhr 12.“). | MUSS | 1 |
| PHONE-24 | Die Uhrzeit wird **unmittelbar vor der Ausgabe** aus der Systemuhr gelesen, Zeitzone `Europe/Berlin`, Sommerzeit automatisch. Keine vom LLM erfundene Uhrzeit (technisch abgesichert, siehe AGENT-06). | MUSS | 1 |
| PHONE-25 | Andere Fragen beantwortet das LLM; aktuelle Informationen über die integrierte Websuche. | MUSS | 1 |
| PHONE-26 | Antwort ist kurz, deutsch, wird per TTS gesprochen; danach wird wieder zugehört. | MUSS | 1 |
| PHONE-27 | **Mindestens drei Gesprächsrunden** im selben Anruf mit gemeinsamem Gesprächskontext. | MUSS | 1 |
| PHONE-28 | Beim Auflegen werden alle Audio-, STT-, LLM- und TTS-Aufträge des Anrufs abgebrochen und Ressourcen freigegeben. | MUSS | 1 |
| PHONE-29 | Klarer Sprecherwechsel: während der eigenen Ausgabe wird die Agentenstimme nicht transkribiert (Eingang verworfen). | MUSS | 1 |
| PHONE-30 | Unverständliche/leere Erkennung → kurze Rückfrage („Entschuldigung, das habe ich nicht verstanden …“), max. 2× in Folge, danach Hilfe-Hinweis. | MUSS | 1 |
| PHONE-31 | Stille: nach `silence_prompt_s` einmal nachfragen („Bist du noch da?“), nach weiteren `silence_hangup_s` verabschieden und auflegen. Beide Werte konfigurierbar. | MUSS | 1 |
| PHONE-32 | Fehlgeschlagene Suche wird **ehrlich** angesagt; keine erfundenen Suchergebnisse. | MUSS | 1 |
| PHONE-33 | Fehlender LLM-Dienst blockiert weder Begrüßung noch eine vorbereitete Fehleransage. | MUSS | 1 |
| PHONE-34 | Sind STT oder TTS nicht bereit, wird kein normaler Gesprächsbetrieb vorgetäuscht Anruf annehmen → vorbereitete Störungsansage → auflegen. Fehlt der Ansagen-Cache selbst, registriert sich der Agent nicht (ADR-011). | MUSS | 1 |
| PHONE-35 | Dauert die Antwort länger als `thinking_prompt_after_s` (Start: 2,5 s), wird eine vorbereitete Zwischenansage gespielt („Moment, ich schaue nach.“). | SOLL | 1 |
| PHONE-36 | Optionaler Abschied per Sprache („Tschüss“, „Danke, das war’s“) → Verabschiedung und Auflegen. | SOLL | 1 |
| PHONE-37 | Stimme: **Thorsten-Voice CosyVoice3 Hessisch** (lokal auf der CPU, Sprecher `thorsten_hessisch`) ist Nikitas Stimme. Fehlt das Modell, ist es zu langsam oder fällt es aus, spricht die lokale Rückfallkette Piper (Thorsten) → espeak-ng; der Anruf bricht nie wegen der Stimme ab (ADR-027). | MUSS | 1 |

### 2.3 Ressourcen, Parallelität, Datenschutz

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| PHONE-40 | Genau **ein aktiver Anruf**; ein zweiter erhält „besetzt“ (SIP 486 Busy Here). Keine Vermischung von Gesprächskontexten. | MUSS | 1 |
| PHONE-41 | Telefonanfragen haben Vorrang vor nicht gestarteten Hintergrundaufgaben; laufende lange Generierungen werden über `/api/extra/abort` kontrolliert abgebrochen, sonst Warteansage mit Timeout. | MUSS | 1 |
| PHONE-42 | VAD, STT (**Whisper small**, entschieden) und TTS laufen auf der **CPU**; die RTX 3070 bleibt dem LLM vorbehalten. | MUSS | 1 |
| PHONE-43 | Keine dauerhafte Audioaufnahme als Standard; temporäre Audiopuffer werden nach Verwendung verworfen (nur im RAM, kein Disk-Spool). | MUSS | 1 |
| PHONE-44 | Zugangsdaten gelangen weder in Transkripte noch in LLM-Kontexte oder Logs. | MUSS | 1 |
| PHONE-45 | Telefon-Tools in Part 1: nur `get_current_time`, `web_search` (+ ggf. `web_fetch` light). Shell/SSH/Sandbox sind für das Telefonprofil **nicht** freigegeben. | MUSS | 1 |
| PHONE-46 | Eine angezeigte Rufnummer (Caller-ID) ist **keine** Berechtigung für administrative Aktionen – auch nicht in späteren Parts ohne zusätzliche Authentisierung. | MUSS | 1 |
| PHONE-47 | Speicherverbrauch von SIP/VAD/STT/TTS wird unter Telefonlast gemessen und dokumentiert. | MUSS | 1 |
| PHONE-48 | Feste Ansagen (Begrüßung, Fehler-, Zwischenansagen, Uhrzeiten) werden **vorgerendert und gecacht** (`assets/audio/cache/`, Schlüssel aus Text+Stimme); das Telefon registriert sich erst, wenn alle nötigen Ansagen sprechbar sind. | MUSS | 1 |
| PHONE-49 | Live-Antworten werden satzweise gesprochen (erster Satz läuft, während der Rest entsteht); die Stimme für Live-Sätze wird nach gemessener Geschwindigkeit gewählt (`live_engine = auto`). Gerenderte Live-Sätze liegen nie auf der Platte. | MUSS | 1 |
| PHONE-50 | Antworttexte werden vor der Sprachausgabe in ausgeschriebene deutsche Wörter normalisiert (Zahlen, Datum, Uhrzeit, Euro, Einheiten, Abkürzungen; kein Markdown/Emoji). | MUSS | 1 |
| PHONE-51 | Das Telefon ist ohne Systeminstallation ausprobierbar (`./test-1.sh`: Einrichtung unter `runtime/`, Selbsttest, Testanruf gegen sich selbst, Anmeldung an der Telefonanlage). | SOLL | 1 |

## 3. Konfiguration & Zugangsdaten (CFG)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| CFG-01 | Alle Zugangsdaten zentral in `<app>/passwords.txt` (INI). Keine Zugangsdaten im Code. | MUSS | 1 |
| CFG-02 | Startinhalt exakt wie im Originalplan (Sektionen `sip`, `web_login`, `sandbox_ssh`, `optional_services`). Vorlage: [`config/passwords.template.txt`](../../config/passwords.template.txt). | MUSS | 1 |
| CFG-03 | Parser liest die Datei als **Daten** (`configparser`, `interpolation=None`); niemals `source`/`eval`. Sonder- und Prozentzeichen bleiben erhalten. | MUSS | 1 |
| CFG-04 | Leere Web-/SSH-Werte sind keine nutzbaren Zugänge. Web-Login wird erst mit gültigen Werten aktiviert. | MUSS | 1 |
| CFG-05 | Änderungen werden über kontrollierten Reload (API/Signal) oder Neustart übernommen; ungültige Konfiguration wird mit verständlicher Meldung **abgelehnt**, der alte gültige Stand bleibt aktiv. | MUSS | 1 |
| CFG-06 | Dateirechte `0600`, Besitzer Dienstbenutzer. Nie über Webserver, Downloads, Tool-Dateizugriff oder Diagnosearchive ausliefern. Start mit zu offenen Rechten → Warnung + automatische Korrektur, wenn möglich. | MUSS | 1 |
| CFG-07 | `passwords.txt` und Sicherungen (`passwords.txt.*`, `backups/`) stehen in `.gitignore`. | MUSS | 1 |
| CFG-08 | Nicht geheime Einstellungen (Zeitzone, Begrüßungstext, Stimme, Sprache, RTP-Ports, Timeouts, Modellpfade) in `config/moritz-agent.toml`. SIP-Daten **nur** in der TXT. | MUSS | 1 |
| CFG-09 | Neue Felder werden beim Update ergänzt, ohne Formatierung/Kommentare/bestehende Werte der TXT zu verändern (zeilenbasiertes Anhängen, kein Neu-Serialisieren). | MUSS | 1 |
| CFG-10 | Werte mit führenden/abschließenden Leerzeichen werden nicht unterstützt (INI-Grenze) – dokumentiert und bei Eingabe im Installer abgefangen. | MUSS | 1 |

## 4. Installation & Update (INST / UPD)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| INST-01 | Projektskripte `moritz-install.sh` und `moritz-update.sh`; `install.sh`/`update.sh` sind dünne Wrapper. | MUSS | 1 |
| INST-02 | Prüft Distribution, RAM-Limit, CPU, freien Speicher, GPU (`nvidia-smi`) und Systempakete. Ändert **nichts am Proxmox-Host**. | MUSS | 1 |
| INST-03 | Legt Dienstbenutzer, Verzeichnisse, venv, Python-/Native-Abhängigkeiten, PJSIP, Modellpfade und Audio-Ressourcen an. Modelle/Stimmen mit **geprüften Prüfsummen**; Speicherbedarf wird vorher angezeigt. | MUSS | 1 |
| INST-04 | Vorhandene `passwords.txt` wird **nie** überschrieben. SIP-Startwerte nur bei Ersteinrichtung. | MUSS | 1 |
| INST-05 | Web-Benutzer/Passwort interaktiv, Passwort ohne Echo; in TXT schreiben, scrypt-Hash für Login-Prüfung ableiten. Keine Passwörter in Kommandozeilen, Prozesslisten oder Installationslogs. | MUSS | 1 |
| INST-06 | Sandbox-SSH abfragen (Host, Port, Benutzer, Auth-Methode), Host-Key-Fingerprint anzeigen/bestätigen, Verbindung testen. „Später einrichten“ → `enabled = false`. | MUSS | 1 |
| INST-07 | Zeitzone, Begrüßung, Stimme, Sprache, RTP-Portbereich etc. in normaler Konfiguration. | MUSS | 1 |
| INST-08 | systemd-Dienst, Autostart, lokale Schnittstellen; Einzel-Statusmeldungen für SIP, STT, TTS, LLM, Suche. | MUSS | 1 |
| INST-09 | Fordert zum manuellen Testanruf an 999 auf (Checkliste: Begrüßung, Audio beidseitig, Uhrzeit, Folgefrage, Websuche). Dialplan wird nur geprüft, nie verändert. | MUSS | 1 |
| INST-10 | Idempotent: erneutes Ausführen erhält angepasste Daten. | MUSS | 1 |
| INST-11 | `--non-interactive` Modus: bricht kontrolliert mit eindeutigem Exit-Code ab, wenn Pflichtangaben fehlen. | MUSS | 1 |
| UPD-01 | Aktive Anrufe auslaufen lassen (Drain); nach Timeout Update **verschieben**, nicht abbrechen. | MUSS | 1 |
| UPD-02 | Konfiguration, TXT und Datenbank vor Migration geschützt sichern (`0700`/`0600`). | MUSS | 1 |
| UPD-03 | Anwendung und Abhängigkeiten aktualisieren; Werte, Modelle, Gesprächsdaten bleiben erhalten. | MUSS | 1 |
| UPD-04 | Neue Felder ergänzen; nur neue **Pflicht**-Zugangsdaten interaktiv abfragen; optionale Integrationen deaktiviert lassen. | MUSS | 1 |
| UPD-05 | Vorbelegte SIP-Daten nie über eine angepasste TXT schreiben. | MUSS | 1 |
| UPD-06 | Atomare Dateischreibvorgänge (`tmp` + `fsync` + `rename`), Dateirechte erhalten, versionierte Schemamigrationen. | MUSS | 1 |
| UPD-07 | Nach Neustart Registrierung, Audio, Modell, API prüfen; bei Fehler kompatiblen gesicherten Stand wiederherstellen (Rollback) und Ergebnis klar melden. | MUSS | 1 |

## 5. Inference (INF)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| INF-01 | KoboldCPP läuft als isolierter Child-Prozess, nur auf `127.0.0.1` gebunden, interner Port. | MUSS | 1 |
| INF-02 | Genau **ein** geladenes großes Sprachmodell: **Qwen3-30B-A3B-Instruct-2507 (MoE), GGUF UD-Q3_K_XL, ≈ 13,8 GB**, etwa **halb VRAM / halb RAM** (Moritz, R3; ADR-016). Kontext 4.096. | MUSS | 1 |
| INF-03 | Eine Generierung gleichzeitig; Prioritäts-Warteschlange (Telefon > interaktiv > Hintergrund). | MUSS | 1 |
| INF-04 | Kein Draft-/Zweitmodell, kein dauerhaft geladenes Embedding-Modell im Startprofil. | MUSS | 1 |
| INF-05 | 8.192 Kontext erst nach Messung mit ausreichender Reserve. Swap ist kein Modellspeicher. | MUSS | 1 |
| INF-06 | Modellwechsel entlädt zuerst das alte Modell. | MUSS | 2 |
| INF-07 | OpenAI-kompatible API (`/v1/chat/completions`, `/v1/models`) bleibt nach außen erhalten (über moritz-agent, mit Auth). | SOLL | 2 |
| INF-08 | Inference-Crash → automatischer Neustart des Workers mit Backoff; Telefon spielt währenddessen Fehleransage. | MUSS | 1 |

## 6. Agent Core (AGENT)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| AGENT-01 | Agent-Loop: Prompt → (Tool-Wahl → Tool-Ausführung → Ergebnis zurück) × n → finale Antwort. | MUSS | 1 |
| AGENT-02 | Profile (Phone, General, Research, Coding, Browser) teilen ein Modell; unterscheiden sich in Systemanweisung, Tool-Freigaben und Limits. Part 1: nur **Phone** (+ minimaler Text-Testpfad). | MUSS | 1 |
| AGENT-03 | Tools mit JSON-Schema; Argumente werden validiert; fehlerhafte Aufrufe mit begrenzten Wiederholungen (Start: 2) korrigiert. | MUSS | 1 |
| AGENT-04 | Begrenzungen: max. Tool-Schritte (Phone: 3), Laufzeit (Phone: 15 s gesamt), Ausgabegröße. | MUSS | 1 |
| AGENT-05 | Context Manager reserviert Platz für Antwort, Tool-Schemas, Systemanweisung; kürzt Historie vor Erreichen des Limits. | MUSS | 1 |
| AGENT-06 | **Uhrzeit-Garantie:** Eindeutige Zeitfragen gehen über einen deterministischen Fast-Path direkt an `get_current_time`. Enthält eine LLM-Antwort eine Uhrzeit ohne vorherigen Tool-Aufruf im selben Turn, wird sie verworfen und über das Tool neu beantwortet. | MUSS | 1 |
| AGENT-07 | Telefonantworten: max. ~2–3 kurze Sätze, keine Markdown-/Listen-/URL-Ausgabe, Zahlen/Abkürzungen sprechbar. | MUSS | 1 |
| AGENT-08 | Quellen von Suchergebnissen werden pro Turn protokolliert (Log + DB). | MUSS | 1 |
| AGENT-10 | Vordefinierte **Fast-Paths** für einfache Infos (Uhrzeit, Datum, Wochentag, KW, Tage bis …, Feiertage, Zeitumstellung, Rechnen, Identität, Hilfe, Status, Abschied, Wiederholen) ohne LLM – Katalog [12-fast-paths.md](12-fast-paths.md). | MUSS | 1 |
| AGENT-09 | Memory (3 Ebenen), Planner, Multi-Agent – siehe Roadmap. | — | 8/1.1 |

## 7. Suche & Research (SEARCH)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| SEARCH-01 | SearXNG läuft als interner Worker auf `127.0.0.1:<zufälliger Port>`, nie öffentlich. | MUSS | 1 |
| SEARCH-02 | JSON-API aktiviert, Sprache `de-DE`, **alle** Web-/News-Engines aktiv (F-09), konfigurierbar. „Google“ wird nur genannt, wenn die Google-Engine das Ergebnis tatsächlich geliefert hat (Feld `engines` je Treffer). | MUSS | 1 |
| SEARCH-03 | Fehler/Timeout (Start: 6 s) → nächste Stufe der Fallback-Kette (SearXNG → KoboldCpp-Websuche → Wikipedia), erst danach strukturiertes Fehlerergebnis → ehrliche Ansage ([11-suchoptionen.md](11-suchoptionen.md), ADR-020). | MUSS | 1 |
| SEARCH-04 | Einfacher HTTP-Fetcher (Text-Extraktion) im LXC; Chromium **nur** in der Sandbox. | SOLL | 1 / 5 |
| SEARCH-05 | Deep Research, Quellenvergleich, Berichte – siehe Roadmap. | — | 9 |

## 8. Backend, API, Frontend (API / UI)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| API-01 | Python-Backend, eingebauter Webserver, **aus dem LAN erreichbar auf Port 3501** (F-04), HTTPS mit selbst erzeugtem Zertifikat (ADR-022). | MUSS | 1 |
| API-02 | Bindung an Nicht-Loopback-Adresse nur bei aktivem Web-Login; sonst Start verweigern. KoboldCpp-Oberflächen (KoboldAI Lite, llama.cpp-UI, SD-/Music-UI, API-Doku) sind entfernt und nie erreichbar (F-11). | MUSS | 1 |
| API-03 | Part-1-Endpunkte: `/api/system/health`, `/api/system/status`, `/api/phone/status`, `/api/system/reload`, `/api/system/activity`, `/api/system/drain`, `/api/chat` (Text-Testpfad). | MUSS | 1 |
| API-04 | Spätere Endpunkte: `/api/agent`, `/api/research`, `/api/files`, `/api/models`, `/api/tools`, `/api/settings`, `/v1/...`. | — | 2–5 |
| API-05 | Login: scrypt-Hash, Session-Cookie (`HttpOnly`, `SameSite=Strict`, `Secure` bei TLS), Rate-Limit für Login-Versuche. | MUSS | 1 |
| UI-01 | Part 1: Statusseite mit Registrierung, Anrufzustand, STT/TTS-Bereitschaft, LLM, Suche, letzte Fehler. **Keine Passwörter**. | MUSS | 1 |
| UI-02 | Part 2: Chat, Streaming, Verlauf, Agent-Timeline, Modellverwaltung, Einstellungen. Responsive (Android-WebView-tauglich). | — | 2 |

## 9. Speicher & Logging (STORE / LOG)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| STORE-01 | SQLite (WAL) unter `data/moritz-agent.sqlite3`, versionierte Migrationen. | MUSS | 1 |
| STORE-02 | Part 1 speichert Anruf-Metadaten, Turns, Tool-Aufrufe, Latenzen. **Transkript-Text wird 24 Stunden aufbewahrt** und dann gelöscht (F-03); Metadaten/Latenzen bleiben. Kein Audio. | MUSS | 1 |
| LOG-01 | Strukturierte Logs mit Kategorie (`[Phone]`, `[Agent]`, `[Search]`, `[LLM]`, `[Tool]`, `[System]`) nach journald + rotierende Datei. | MUSS | 1 |
| LOG-02 | Secret-Redaction auf Feldebene; PJSIP-Loglevel ≤ 3, SIP-Nachrichten-Logging standardmäßig aus (Authorization-Header). | MUSS | 1 |
| LOG-03 | Pro Turn gemessen und geloggt: VAD-Ende → STT fertig, STT-Dauer, LLM-Zeit bis erster Token / gesamt, Tool-Dauer, TTS-Anlauf, Gesamtlatenz. | MUSS | 1 |

## 10. Nicht-funktionale Anforderungen (NFR)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| NFR-01 | RAM: Alles im Agent-LXC innerhalb **16 GB Limit** ohne OOM und ohne dauerhaften Swap-Druck. | MUSS | 1 |
| NFR-02 | VRAM: LLM + KV-Cache + Puffer passen in die **tatsächlich freien** VRAM-Werte der RTX 3070 (8 GB). | MUSS | 1 |
| NFR-03 | Latenz-**Ziele** (keine Versprechen, werden gemessen): Ende Sprechen → Beginn Antwort ≤ 3 s ohne Suche, ≤ 6 s mit Suche (Zwischenansage ab 2,5 s). | SOLL | 1 |
| NFR-04 | Stabilität: 30 Anrufe in Folge ohne Neustart; Worker-Absturz wird erkannt und selbst geheilt. | MUSS | 1 |
| NFR-05 | Telefonie funktioniert ohne Sandbox (Redemption-1 aus). | MUSS | 1 |
| NFR-06 | Zielsystem **Ubuntu 26.04 LTS** (alternativ 25.10) im unprivilegierten LXC; System-Python 3.13/3.14; alle Abhängigkeiten haben Wheels für beide Versionen (geprüft, ADR-024). | MUSS | 1 |
| NFR-07 | Alle Netzdienste außer Web-UI (Port 3501) und SIP/RTP lauschen nur auf Loopback. | MUSS | 1 |
| NFR-08 | CPU: Xeon E5-2673 v3 (Haswell, AVX2, kein AVX-512); der LXC nutzt **höchstens 18 Threads**, damit der Host nie überlastet (F-07). Thread-Verteilung in ADR-016. | MUSS | 1 |

## 11. Sandbox (SBX) – ab Part 4, Daten ab Part 1

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| SBX-01 | Shell, fremder Code, Compiler, Chromium laufen **nur** in der Sandbox-VM auf Redemption-1, nie im Inference-LXC oder auf dem Host. | MUSS | 4 |
| SBX-02 | Zugang per SSH mit gepinntem Host-Key; Daten in `passwords.txt` `[sandbox_ssh]`. | MUSS | 1 (Daten) / 4 |
| SBX-03 | Netzwerk der Sandbox: **nur** Internet und Verbindung zu Sophie-1 (Agent-LXC); alles andere gesperrt (F-10, bestätigt). | MUSS | 4 |
| SBX-04 | Startwerte: 4 GB RAM, 2–4 vCPU; Chromium on demand, max. 2 Seiten. | SOLL | 4/6 |
| SBX-05 | Administrative Aktionen nie allein über Telefonanruf freischaltbar. | MUSS | 4 |

## 12. Explizit NICHT in Part 1

- Deep Research, mehrseitige Recherche, Quellenverwaltung (Part 5/9)
- Browser-Automation / Chromium (Part 6)
- Mehrere gleichzeitige Anrufe, Barge-in/Unterbrechen mit Echo-Behandlung, DTMF, Weiterleitung, ausgehende Anrufe (Part 7+)
- Shell/SSH/Coding-Tools (Part 4)
- Persistentes Memory, Retrieval (Part 8)
- Vollständige Chat-WebUI, Modellverwaltung in der UI (Part 2)
- Android-App, Multi-Agent (≥ 1.0); Windows-Build entfällt komplett

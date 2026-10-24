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
| PRD-10 | Der Assistent heißt **Anton** (männlich, Stimme Thorsten-Voice Hessisch) – in Begrüßung, Systemprompt, Antworten, SIP-Anzeigename und Oberfläche. Technische Namen (Produkt `moritz-agent`, Repo, SIP-Konto `agent`) bleiben (ADR-026). | MUSS | 1 |
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
| PHONE-10 | Part 1 startet **keine ausgehenden Anrufe** – einzige Ausnahme ist der **Rückruf** (ADR-038): nur auf die konfigurierte interne Nebenstelle (`phone.callback.extension`, Standard 201), nur auf eine geschriebene Bitte des Owners auf Discord („Sag mir am Telefon, …“), 10–15 s Klingeln, sprechen, verabschieden, auflegen – nie zuhören; geht keiner ran, passiert nichts weiter. | MUSS | 1 |

### 2.2 Gesprächsablauf

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| PHONE-20 | Eingehenden internen Anruf automatisch annehmen – nach Klingeln (zufällig `phone.ring_seconds_min` … `ring_seconds_max`, Standard 4–8 s, beide 0 = sofort; der Anrufer hört den Freiton, 180 Ringing). Legt der Anrufer währenddessen auf, passiert nichts weiter. | MUSS | 1 |
| PHONE-21 | Nach dem Abnehmen sofort die vorbereitete Begrüßung abspielen: „Hallo Moritz, hier ist Anton. Was kann ich für dich tun?“ (Name geändert, ADR-026) – aus einer zwischengespeicherten Audiodatei, **ohne LLM-Wartezeit**. | MUSS | 1 |
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
| PHONE-37 | Stimme: **Thorsten-Voice „Hessisch“** (Piper-Modell, lokal auf der CPU) ist Antons Stimme. Fehlt das Modell oder fällt es aus, spricht die lokale Notstimme espeak-ng; der Anruf bricht nie wegen der Stimme ab (ADR-027). | MUSS | 1 |

### 2.3 Ressourcen, Parallelität, Datenschutz

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| PHONE-40 | Genau **ein aktiver Anruf**; ein zweiter erhält „besetzt“ (SIP 486 Busy Here). Keine Vermischung von Gesprächskontexten. | MUSS | 1 |
| PHONE-41 | Telefonanfragen haben Vorrang vor nicht gestarteten Hintergrundaufgaben und vor Discord-Anfragen (Sprache und Text, DISCORD-10); laufende lange Generierungen werden über `/api/extra/abort` kontrolliert abgebrochen, sonst Warteansage mit Timeout. | MUSS | 1 |
| PHONE-42 | VAD, STT (**Whisper small**, entschieden) und TTS laufen auf der **CPU**; die RTX 3070 bleibt dem LLM vorbehalten. | MUSS | 1 |
| PHONE-43 | Keine dauerhafte Audioaufnahme als Standard; temporäre Audiopuffer werden nach Verwendung verworfen (nur im RAM, kein Disk-Spool). | MUSS | 1 |
| PHONE-44 | Zugangsdaten gelangen weder in Transkripte noch in LLM-Kontexte oder Logs. | MUSS | 1 |
| PHONE-45 | Telefon-Tools in Part 1: `get_current_time`, `web_search` (+ ggf. `web_fetch` light) und die **lesenden Skill-Tools** der Sofortauskünfte (`get_weather`, `get_warnings`, `get_sun_moon`, `calendar_info`, `calculate`, … – SKILL-23, ADR-029). Shell/SSH/Sandbox sind für das Telefonprofil **nicht** freigegeben. | MUSS | 1 |
| PHONE-46 | Eine angezeigte Rufnummer (Caller-ID) ist **keine** Berechtigung für administrative Aktionen – auch nicht in späteren Parts ohne zusätzliche Authentisierung. | MUSS | 1 |
| PHONE-47 | Speicherverbrauch von SIP/VAD/STT/TTS wird unter Telefonlast gemessen und dokumentiert. | MUSS | 1 |
| PHONE-48 | Feste Ansagen (Begrüßung, Fehler-, Zwischenansagen, Uhrzeiten) werden **vorgerendert und gecacht** (`assets/audio/cache/`, Schlüssel aus Text+Stimme); das Telefon registriert sich erst, wenn alle nötigen Ansagen sprechbar sind. | MUSS | 1 |
| PHONE-49 | Antworten werden satzweise gesprochen (erster Satz läuft, während der Rest entsteht). Gerenderte Live-Sätze liegen nie auf der Platte. | MUSS | 1 |
| PHONE-50 | Antworttexte werden vor der Sprachausgabe in ausgeschriebene deutsche Wörter normalisiert (Zahlen, Datum, Uhrzeit, Euro, Einheiten, Abkürzungen; kein Markdown/Emoji). | MUSS | 1 |
| PHONE-51 | Das Telefon ist ohne Systeminstallation ausprobierbar (`./test-1.sh`: Einrichtung unter `runtime/`, Selbsttest, Testanruf gegen sich selbst, Anmeldung an der Telefonanlage). | SOLL | 1 |
| PHONE-52 | Nach der Begrüßung darf ein **live** gesprochener Satz folgen (Warnhinweis, SKILL-10); die Begrüßung selbst bleibt die gecachte Ansage und wird dadurch nicht verzögert. | SOLL | 1 |

## 2a. Discord (DISCORD)

Anton als Discord-Bot mit allen Funktionen (Moritz, 20.10.2026). Plan: [14-discord.md](14-discord.md);
Tickets P1-31 … P1-43 (Block D in [04](04-part1-umsetzung.md)); Entscheidungen ADR-033 … ADR-037.

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| DISCORD-01 | Anton läuft als **offizieller Bot** einer eigenen Discord-Anwendung. Kein Benutzer-Token, kein Self-Bot (Discord-Nutzungsbedingungen). | MUSS | 1 |
| DISCORD-02 | Server-Installation **und** Benutzer-Installation: Befehle im eigenen Server, in der DM mit Anton und als Benutzer-App überall, wo Moritz Discord nutzt. | MUSS | 1 |
| DISCORD-03 | „Public Bot“ aus; Anton bleibt nur in `discord.allowed_guild_ids`, verlässt andere Server sofort und meldet das dem Owner. | MUSS | 1 |
| DISCORD-04 | Rollen Owner / Vertraut / Gast hängen an der Discord-Benutzer-ID; Standard: Unbekannte werden ignoriert, Gastmodus aus. | MUSS | 1 |
| DISCORD-05 | Bot-Token nur in `passwords.txt` (`[discord] bot_token`), im Code als `Secret`; nie in Argumenten, Umgebungsvariablen, Logs, Statusdateien oder Antworten. | MUSS | 1 |
| DISCORD-06 | Einrichtung im Installer (Phase `discord`): Token verdeckt per stdin, Prüfung gegen Discord, App-Besitzer als Owner übernehmen, Warnungen (Public Bot an, Message Content aus), Einladungslinks. Alternativ Token direkt in die Datei. | MUSS | 1 |
| DISCORD-07 | Der Updater ergänzt `[discord]` zeilenweise (CFG-09); ohne Token bleibt Discord aus, ohne Abfrage. | MUSS | 1 |
| DISCORD-08 | Token- oder Konfigurationswechsel per Reload → Neuverbindung, ohne eine laufende Sprachsitzung abzubrechen. | MUSS | 1 |
| DISCORD-09 | Eigener Worker-Prozess mit Neustart-Backoff und Statusdatei; Absturz oder Hänger beeinflusst das Telefon nicht (PRD-02). | MUSS | 1 |
| DISCORD-10 | Telefon hat Vorrang: Discord-Worker mit niedrigerer CPU-Priorität; LLM-Warteschlange `PHONE > VOICE > INTERACTIVE > BACKGROUND`. | MUSS | 1 |
| DISCORD-11 | Kein eingehender Port: nur ausgehende Verbindungen (Gateway/REST/CDN über TCP 443, Sprache über UDP). | MUSS | 1 |
| DISCORD-12 | **Kanal-Parität:** jede Anton-Funktion ist auf Discord verfügbar (Matrix [14 §6](14-discord.md#6-funktionsumfang-alle-funktionen-auf-allen-kanälen)); neue Funktionen bringen ihre Discord-Form im selben Ticket mit oder begründen die Ausnahme. | MUSS | 1–1.1+ |
| DISCORD-13 | Text: Im **Standard-Textkanal** (ID `[discord] channel_id` in `passwords.txt`, beim Setup abgefragt) und in DMs antwortet Anton auf jede Nachricht freigegebener Personen ohne Erwähnung; sonst bei Erwähnung, auf Antworten an sie, in ihren Threads, in weiteren Anton-Kanälen und auf „Anton, …“ am Satzanfang. | MUSS | 1 |
| DISCORD-14 | Alle Sofortauskünfte ([13](13-sofortauskuenfte.md)) als Text und als Slash-Befehl; Ausgabe als Karte mit Quelle und Lizenz in der Fußzeile. | MUSS | 1 |
| DISCORD-15 | Rückfragen des Kerns erscheinen als Auswahlliste, Folgeaktionen als Knöpfe; beides zustandslos und neustartfest. | MUSS | 1 |
| DISCORD-16 | Slash-Befehle laut [14 §7](14-discord.md#7-befehle-slash-befehle-kontextmenüs-autovervollständigung); registriert werden nur aktive Funktionen; Autovervollständigung für Orte/PLZ. | MUSS | 1 |
| DISCORD-17 | Kontextmenüs: „Anton fragen“, „Vorlesen“ (Part 1), „Zusammenfassen“, „Übersetzen“ (ab P1-09), „Merken“ (Part 8), „Bild lesen“ (1.1+). | SOLL | 1–1.1+ |
| DISCORD-18 | Ab P1-09: freie Fragen an das LLM mit Streaming, Websuche mit Quellen als Links; Uhrzeit- und Wetter-Garantie (AGENT-06, AGENT-11) gelten. | MUSS | 1 |
| DISCORD-19 | Antworten halten Discords Grenzen ein (Aufteilen an Absätzen, Datei ab Grenze, Embed-Grenzen); `allowed_mentions` pingt nie `@everyone`, `@here` oder Rollen. | MUSS | 1 |
| DISCORD-20 | Ausgabefilter: keine Secrets, keine internen Details in Serverkanälen; Admin- und persönliche Inhalte nur im DM oder nur für den Aufrufer sichtbar. | MUSS | 1 |
| DISCORD-21 | Rate-Limits je Rolle, Eingabe- und Anhangsgrenzen; Anhänge nur vom Discord-CDN, nie ausgeführt, nicht dauerhaft gespeichert. | MUSS | 1 |
| DISCORD-22 | Sprachkanal: `/joinvc` (Kanal von Moritz, sonst Standard-Sprachkanal) und `/leavevc`, optional automatisch beim Betreten durch den Owner; höchstens eine Sitzung; Verlassen nach Abschied, ohne Menschen nach 10 min, bei Höchstdauer oder Wartung. | SOLL | 1 |
| DISCORD-23 | Sprachkanal **wie im Anruf**: Betritt Moritz den Kanal (oder ist schon da), läuft derselbe Gesprächsablauf wie am Telefon (`CallSession` über eine gemeinsame `MediaChannel`-Schnittstelle): Begrüßung, Zuhören, Antworten mit Antons Stimme, Stille-Nachfrage, Rückfragen, Abschied; Verlassen des Kanals = Auflegen. Kein Weckwort und keine Sprecherauswahl (Privatserver), Unterbrechen ≤ 300 ms, DAVE. | SOLL | 1 |
| DISCORD-24 | Ist DAVE-Empfang nicht stabil (Spike P1-32), läuft der Sprachkanal im Modus „nur sprechen“ (Text oder Sprachnachricht rein, Sprache raus); die Entscheidung ist dokumentiert (ADR-036). | MUSS | 1 |
| DISCORD-25 | Kein Audio wird gespeichert, Puffer nur im RAM; Whisper/Piper im Discord-Worker nur während Sprachsitzungen geladen. | MUSS | 1 |
| DISCORD-26 | Sprachnachrichten: Transkript sichtbar + Antwort; Antwort optional als Sprachnachricht bzw. Audiodatei mit Antons Stimme. | SOLL | 1 |
| DISCORD-27 | Erinnerungen und Timer per Direktnachricht, neustartfest; verpasste werden bis 12 h später mit Hinweis nachgeholt. | SOLL | 1 |
| DISCORD-28 | Proaktive Nachrichten nur mit Abo (Warnungen, Morgenbriefing, Müll, Anrufhinweise, Systemhinweise), Ruhezeiten und Drosselung. | SOLL | 1 |
| DISCORD-29 | Persönliche Einstellungen je Person (Heimatort, Ruhezeit, Sprachantwort); ohne Einstellung gilt 35781 Weilburg. | SOLL | 1 |
| DISCORD-30 | Telefon ↔ Discord: Anrufstatus ohne Inhalte; Anrufhinweise, Themen oder Transkript nur per Schalter (Standard aus); „schick mir das auf Discord“ vom Telefon. | SOLL | 1 |
| DISCORD-31 | Admin-Befehle nur für den Owner, nur im DM/nur für ihn sichtbar, Zustandsänderungen mit Bestätigungsknopf (+ optionale PIN aus `passwords.txt`); nie Shell, Updates, Dateizugriff oder Secrets. | MUSS | 1 |
| DISCORD-32 | Präsenz: schelmische, rotierende Aktivitäten (DISCORD-44) und lagebezogene Aktivitäten (Anruf, Sprachkanal, Nacht, Wetter, Sonderdaten, Wartung). | SOLL | 1 |
| DISCORD-33 | Der Wartungsmodus (`data/run/drain`) gilt auch für Discord (keine neuen Sprachsitzungen, Hinweis bei Text). | MUSS | 1 |
| DISCORD-34 | Reaktionen 👍/👎 auf Antworten fließen als Feedback in die Statistik. | KANN | 1 |
| DISCORD-35 | Datenschutz: Transkripte, Notizen und Gedächtnis gehen nur per ausdrücklichem Schalter zu Discord; `/hilfe datenschutz` erklärt das. | MUSS | 1 |
| DISCORD-36 | Log-Kategorie `[Discord]` ohne Inhalte und Token; Turns in der Datenbank mit Kanal; Transkript-Aufbewahrung wie STORE-02. | MUSS | 1 |
| DISCORD-37 | `./test-1.sh discord token\|check\|invite\|run\|say` funktioniert ohne LXC und ohne Systeminstallation. | SOLL | 1 |
| DISCORD-38 | Abhängigkeiten gepinnt mit Hashes (`requirements/discord.lock`), Lizenzen eingetragen; Sprachempfang nur nach Spike, von PyPI oder als dokumentierte Fremdkomponente in `third_party/`. | MUSS | 1 |
| DISCORD-39 | Tests nach [14 §18](14-discord.md#18-tests) laufen ohne Netz in CI (Fake-Discord); Live-Tests nur manuell gegen einen privaten Test-Server. | MUSS | 1 |
| DISCORD-40 | Lange Aufgaben (Recherche, Hintergrundaufgaben, Coding) laufen in eigenen Threads mit Fortschrittsanzeige. | SOLL | 3–9 |
| DISCORD-41 | Sandbox- und Browser-Funktionen über Discord nur für den Owner und mit Bestätigung je riskanter Aktion (SBX-05 sinngemäß). | MUSS | 4/6 |
| DISCORD-42 | Bot-Name „Anton“ und Avatar aus `assets/branding/` (Scribbles), erzeugt mit `scripts/build_branding.py` (PRD-08, PRD-10). | SOLL | 1 |
| DISCORD-43 | **Süßer Stil** („cutey“, `discord.style = "cute"`): herzlicher, verspielter Ton mit höchstens einem Textsmiley (:) :( :3 ^^), **ohne Emojis** (auch nicht aus dem Sprachmodell oder in Aktivitäten); Fakten unverändert; Ernst-Modus ohne Späße bei Warnungen ab Stufe 2, Katastrophen, Admin, Sicherheit und Fehlern mit Datenverlust; gesprochene Antworten wie am Telefon. Bio und Avatar (Scribbles monochrom) passend. | SOLL | 1 |
| DISCORD-44 | **Aktivitäten:** Grundliste schelmisch-lustiger Aktivitäten („Spielt mit deinen Daten >:)“, …, ohne Emojis) in `assets/data/discord/aktivitaeten.de.toml`, Wechsel alle 7–15 min ohne Wiederholung unter den letzten 10; keine Texte, die wie echte Vorfälle wirken; `/aktivitaet neu\|aus\|an\|vorschlag`. | SOLL | 1 |
| DISCORD-45 | Der Standard-Textkanal wird beim Setup per ID oder Auswahlliste festgelegt (geprüft: existiert, Anton darf schreiben) oder direkt in `passwords.txt` eingetragen; sein Server ist automatisch erlaubt; fehlt er, läuft Anton ohne ihn weiter (Abos per DM, Hinweis im Status). | MUSS | 1 |
| DISCORD-46 | Privatserver-Annahme: keine Sprecher- oder Personenauswahl im Gespräch; Fremde werden als Sicherheitsnetz trotzdem ignoriert und einmal im Standardkanal gemeldet. | MUSS | 1 |
| DISCORD-47 | Proaktive Nachrichten, Erinnerungen und Hinweise landen im Standardkanal (`discord.notify.target = "channel"`, wahlweise DM); Anton meldet sich nach dem Start dort (abschaltbar). | SOLL | 1 |

## 3. Konfiguration & Zugangsdaten (CFG)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| CFG-01 | Alle Zugangsdaten zentral in `<app>/passwords.txt` (INI). Keine Zugangsdaten im Code. | MUSS | 1 |
| CFG-02 | Startinhalt exakt wie im Originalplan (Sektionen `sip`, `web_login`, `sandbox_ssh`, `optional_services`); ab Block D zusätzlich `discord` mit `bot_token`, `channel_id`, `admin_pin` (angehängt, [14 §14.2](14-discord.md#142-setup-in-moritz-agent)). Vorlage: [`config/passwords.template.txt`](../../config/passwords.template.txt). | MUSS | 1 |
| CFG-03 | Parser liest die Datei als **Daten** (`configparser`, `interpolation=None`); niemals `source`/`eval`. Sonder- und Prozentzeichen bleiben erhalten. | MUSS | 1 |
| CFG-04 | Leere Web-/SSH-Werte sind keine nutzbaren Zugänge. Web-Login wird erst mit gültigen Werten aktiviert. | MUSS | 1 |
| CFG-05 | Änderungen werden über kontrollierten Reload (API/Signal) oder Neustart übernommen; ungültige Konfiguration wird mit verständlicher Meldung **abgelehnt**, der alte gültige Stand bleibt aktiv. | MUSS | 1 |
| CFG-06 | Dateirechte `0600`, Besitzer Dienstbenutzer. Nie über Webserver, Downloads, Tool-Dateizugriff oder Diagnosearchive ausliefern. Start mit zu offenen Rechten → Warnung + automatische Korrektur, wenn möglich. | MUSS | 1 |
| CFG-07 | `passwords.txt` und Sicherungen (`passwords.txt.*`, `backups/`) stehen in `.gitignore`. | MUSS | 1 |
| CFG-08 | Nicht geheime Einstellungen (Zeitzone, Begrüßungstext, Stimme, Sprache, RTP-Ports, Timeouts, Modellpfade) in `config/moritz-agent.toml`. SIP-Daten **nur** in der TXT; ebenso die Discord-Grunddaten Token und Standardkanal-ID (Moritz’ Wunsch: „beim Setup oder in der TXT“). | MUSS | 1 |
| CFG-09 | Neue Felder werden beim Update ergänzt, ohne Formatierung/Kommentare/bestehende Werte der TXT zu verändern (zeilenbasiertes Anhängen, kein Neu-Serialisieren). | MUSS | 1 |
| CFG-10 | Werte mit führenden/abschließenden Leerzeichen werden nicht unterstützt (INI-Grenze) – dokumentiert und bei Eingabe im Installer abgefangen. | MUSS | 1 |

## 4. Installation & Update (INST / UPD)

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| INST-01 | Skripte auf zwei Ebenen (ADR-028): `install.sh`/`update.sh` laufen auf dem Proxmox-Host (oder per `--remote`) und legen den LXC an bzw. aktualisieren ihn; `moritz-install.sh`/`moritz-update.sh` laufen im LXC. `./test-1.sh` ist davon unabhängig (kein LXC, kein root). | MUSS | 1 |
| INST-02 | Prüft Distribution, RAM-Limit, CPU, freien Speicher, GPU (`nvidia-smi`) und Systempakete. Am **Proxmox-Host** ändert nur `install.sh` etwas, und nur: fehlende Ubuntu-Vorlage laden, **einen** neuen Container anlegen (bzw. dessen GPU-`dev`-Einträge), Snapshots dieses Containers – keine Host-Pakete, Treiber, Netzwerk-, Firewall- oder Speicherkonfiguration, keine anderen Gäste. | MUSS | 1 |
| INST-03 | Legt Dienstbenutzer, Verzeichnisse, venv, Python-/Native-Abhängigkeiten, PJSIP, Modellpfade und Audio-Ressourcen an. Modelle/Stimmen mit **geprüften Prüfsummen**; Speicherbedarf wird vorher angezeigt. | MUSS | 1 |
| INST-04 | Vorhandene `passwords.txt` wird **nie** überschrieben. SIP-Startwerte nur bei Ersteinrichtung. | MUSS | 1 |
| INST-05 | Web-Benutzer/Passwort interaktiv, Passwort ohne Echo; in TXT schreiben, scrypt-Hash für Login-Prüfung ableiten. Keine Passwörter in Kommandozeilen, Prozesslisten oder Installationslogs. | MUSS | 1 |
| INST-06 | Sandbox-SSH abfragen (Host, Port, Benutzer, Auth-Methode), Host-Key-Fingerprint anzeigen/bestätigen, Verbindung testen. „Später einrichten“ → `enabled = false`. | MUSS | 1 |
| INST-07 | Zeitzone, Begrüßung, Stimme, Sprache, RTP-Portbereich etc. in normaler Konfiguration. | MUSS | 1 |
| INST-08 | systemd-Dienst, Autostart, lokale Schnittstellen; Einzel-Statusmeldungen für SIP, STT, TTS, LLM, Suche. | MUSS | 1 |
| INST-09 | Fordert zum manuellen Testanruf an 999 auf (Checkliste: Begrüßung, Audio beidseitig, Uhrzeit, Folgefrage, Websuche). Dialplan wird nur geprüft, nie verändert. | MUSS | 1 |
| INST-10 | Idempotent: erneutes Ausführen erhält angepasste Daten. | MUSS | 1 |
| INST-11 | `--non-interactive` Modus: bricht kontrolliert mit eindeutigem Exit-Code ab, wenn Pflichtangaben fehlen. | MUSS | 1 |
| INST-12 | `install.sh` legt den LXC an (unprivilegiert, Ressourcen und Netzwerk per Optionen, Ubuntu 26.04 → 25.10 → 24.04), startet ihn, kopiert das Programm hinein und führt `moritz-install.sh` aus; existiert der Container, wird stattdessen aktualisiert bzw. die Installation fortgesetzt. | MUSS | 1 |
| INST-13 | Beide Host-Skripte laufen als root auf dem Proxmox-Host **oder** mit `--remote [user@]host` von einem anderen Rechner (scp + ssh, `sudo` auf dem Host). Keine Passwörter als Argumente oder Umgebungsvariablen; der Container bekommt kein Root-Passwort. | MUSS | 1 |
| INST-14 | `update.sh` legt vorher einen Snapshot des Containers an, kopiert die aktuelle Programmversion hinein und führt `moritz-update.sh` aus; Exit-Codes 70/71/75 werden durchgereicht. Programmdateien werden ersetzt, Benutzerdaten (`passwords.txt`, Konfiguration, Modelle, Daten, Cache) nie. | MUSS | 1 |
| INST-15 | Alle vier Skripte kennen `--dry-run` (zeigt nur an, was getan würde) und sind per Test gegen einen simulierten Proxmox-Host bzw. ein Fake-System geprüft. | MUSS | 1 |
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
| INF-02 | Genau **ein** geladenes großes Sprachmodell: **Qwen3-30B-A3B-Instruct-2507 (MoE), GGUF UD-Q3_K_XL, ≈ 13,8 GB**, etwa **halb VRAM / halb RAM** (Moritz, R3; ADR-016). Kontext 8.192 (24.10.2026: Systemanweisung + Werkzeuge ≈ 3.100 Tokens, 4.096 ließ kaum Platz für den Verlauf; Plan 04 Anhang C.11). | MUSS | 1 |
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
| AGENT-10 | Vordefinierte **Fast-Paths** für einfache Infos (Uhrzeit, Datum, Wochentag, KW, Tage bis …, Feiertage, Zeitumstellung, Rechnen, Identität, Hilfe, Status, Abschied, Wiederholen) ohne LLM – Katalog [12-fast-paths.md](12-fast-paths.md). **Erweitert durch die Sofortauskünfte (§6a, [13](13-sofortauskuenfte.md), ADR-029)**; die Fast-Path-IDs gehen dort auf. | MUSS | 1 |
| AGENT-09 | Memory (3 Ebenen), Planner, Multi-Agent – siehe Roadmap. | — | 8/1.1 |
| AGENT-11 | **Wetter-Garantie:** Wetter-, Warn-, Pollen-, Sonnen- und Mondfragen beantwortet das LLM nur über die Skill-Tools (nie über `web_search`). Enthält eine LLM-Antwort Wetterwerte ohne Wetter-Tool-Aufruf im selben Turn, wird sie verworfen und über das Tool neu beantwortet (analog AGENT-06). | MUSS | 1 |

## 6a. Sofortauskünfte (SKILL)

Deterministische Auskünfte **vor** dem Sprachmodell (Moritz, 18.10.2026). Plan und Katalog:
[13-sofortauskuenfte.md](13-sofortauskuenfte.md); Tickets P1-19 … P1-30 (Block S in [04](04-part1-umsetzung.md)).

| ID | Anforderung | Prio | Part |
| --- | --- | --- | --- |
| SKILL-01 | Sofortauskünfte antworten **ohne LLM** und nur bei eindeutiger Erkennung (Score-Schwellen, Ausschlusslisten, lange/zusammengesetzte Sätze ausgenommen); sonst eine Rückfrage oder Weitergabe (heute Testantwort, später Agent-Loop). | MUSS | 1 |
| SKILL-02 | Jede Zahl/Angabe stammt aus Systemuhr, Rechnung, mitgelieferter Datei oder Datenabruf; nichts wird geschätzt oder erfunden. Fehlende Daten → ehrliche Ansage. | MUSS | 1 |
| SKILL-03 | **Heimatort 35781 Weilburg** ist Standard für alle ortsbezogenen Fragen ohne Ortsangabe (Wetter, Warnungen, Pollen, Sonne/Mond, Pegel); konfigurierbar in `skills.home`. | MUSS | 1 |
| SKILL-04 | Gesprochene Postleitzahl (Ziffern, Zahlwörter, zerlegt) oder Ortsname (inkl. Ortsteile, Zusätze, unscharfe Erkennung) ersetzt den Heimatort; der aufgelöste Ort wird in der Antwort genannt. | MUSS | 1 |
| SKILL-05 | Mehrdeutige Orte → höchstens eine kurze Rückfrage oder eindeutiger Favorit mit Nennung; unbekannter Ort/unbekannte PLZ → ehrliche Antwort mit Vorschlag. | MUSS | 1 |
| SKILL-06 | Zeitausdrücke laut [13 §4.3](13-sofortauskuenfte.md#43-zeitangaben-slotswhenpy) werden verstanden (jetzt, Tagesteile, morgen/übermorgen, Wochentage, Wochenende, nächste Woche, „in X …“, Uhrzeiten inkl. „viertel acht“, Datumsangaben, Sonderdaten). | MUSS | 1 |
| SKILL-07 | Folgefragen im selben Anruf („Und morgen?“, „Und in Limburg?“, „Mehr Details“, „Woher?“) nutzen den Kontext der letzten Auskunft (3 Runden / 2 min). | MUSS | 1 |
| SKILL-08 | Wetter: aktuell, heute, Tagesteile, morgen/übermorgen, Wochentag, Wochenende, 7-Tage-Trend, bestimmte Stunde, andere Orte, Regionsüberblick; Regen/Schirm, Schnee, Frost/Glätte, Wind/Sturm, Gewitter, Temperatur. | MUSS | 1 |
| SKILL-09 | Wetter-Zusatz: Regenbeginn/-ende (15-Minuten-Daten), Nebel, gefühlte Temperatur, Luftfeuchte/Schwüle, Luftdruck, Sonnenstunden, UV, gestern, Vergleiche, „wann wird es wieder …“. | SOLL | 1 |
| SKILL-10 | Amtliche Warnungen: DWD (Gemeinde) und NINA (Kreis); auf Frage und – ab `skills.warnings.announce_on_greeting` (Standard: Unwetter) – als ein Satz nach der Begrüßung. | SOLL | 1 |
| SKILL-11 | Pollenflug (DWD, Hessen), Luftqualität (CAMS); Biowetter KANN. | SOLL | 1 |
| SKILL-12 | Alltagsratschläge (Schirm, Jacke, Wäsche, Grillen, Fahrrad, Gießen, Kratzen, Sonnencreme …) nur nach den dokumentierten Regeln aus [13 §7.7](13-sofortauskuenfte.md#77-ratschlagsregeln), immer mit Grund. | SOLL | 1 |
| SKILL-13 | Wetterdaten werden gecacht und für den Heimatort vorab abgerufen; Cache-Antwort ≤ 50 ms; Netzabruf mit Zeitlimit 3 s; Daten älter als 1 h werden mit Alter genannt, älter als 6 h nicht mehr gesprochen. | MUSS | 1 |
| SKILL-14 | Quellen- und Lizenzangaben (Open-Meteo, DWD, GeoNames u. a., CC BY 4.0) in `THIRD_PARTY_NOTICES.md`, Doku und später auf der Über-Seite; am Telefon auf Nachfrage. | MUSS | 1 |
| SKILL-15 | Zeit und Kalender vollständig nach [13 §6.1–6.3](13-sofortauskuenfte.md#61-uhrzeit): Weltzeit, Zeitumstellung, Datumsrechnung, Feiertage aller Länder, Schulferien Hessen (gepflegte Tabelle, ehrlich bei fehlendem Jahr), Arbeits- und Brückentage. | MUSS | 1 |
| SKILL-16 | Sonne, Mond, Jahreszeiten offline für Heimatort und jeden bekannten Ort (± 2 min). | SOLL | 1 |
| SKILL-17 | Rechnen mit eigenem Parser (**kein `eval`**), Prozent, Mehrwertsteuer, Trinkgeld, Aufteilen (MUSS); Einheiten, EZB-Währungskurse, Börsenstrompreis (SOLL). | MUSS | 1 |
| SKILL-18 | Region & Alltag: Lahn-Pegel, Müllabfuhr (iCal), Fußball, Spritpreise (mit Schlüssel), Schlagzeilen, Notizen/Einkaufsliste – jeweils einzeln abschaltbar, Standard laut [13 §10](13-sofortauskuenfte.md#10-konfiguration). | KANN | 1 |
| SKILL-19 | Kleine Helfer: Buchstabieren (DIN 5009:2022 / traditionell), Münze, Würfel, Zufallszahl, Witze, Eieruhr während des Gesprächs. | SOLL | 1 |
| SKILL-20 | Gesprächsfunktionen: Gruß erwidern, Danke, Wiederholen, langsamer/schneller sprechen, Gesprächsdauer, Datenschutz-Auskunft, Version/Status, Hilfe (aus aktiven Skills erzeugt), Abbrechen, Abschied, Tagesüberblick („Guten Morgen“). | MUSS | 1 |
| SKILL-21 | Hessische und umgangssprachliche Formulierungen werden verstanden (Wörterbuch ≥ 50 Einträge, z. B. „Wedder“, „morsche“, „heit“, „isses“, „hammer“, „Guude“), jeder Eintrag mit Test. | MUSS | 1 |
| SKILL-22 | Antworten: ≤ 3 kurze Sätze, wichtigste Angabe zuerst, gerundet wie gesprochen, keine Abkürzungen; Einheiten und Sonderfälle (Minusgrade, l/m², hPa, km/h, Spannen, PLZ ziffernweise) werden sprechbar normalisiert. | MUSS | 1 |
| SKILL-23 | Jeder Skill ist zugleich ein Tool mit JSON-Schema für P1-07 (`{ok, data, sources, speakable}`), damit das spätere LLM dieselben Funktionen nutzt (AGENT-11). | MUSS | 1 |
| SKILL-24 | Skills haben keine Seiteneffekte außerhalb von moritz-agent (keine Geräte, Anrufe, Nachrichten); lokale Notizen nur nach gesprochener Bestätigung, Löschen nur nach Rückfrage. Eine Erinnerung per Discord-Direktnachricht an die Person, die sie bestellt hat, ist eine zeitversetzte Antwort, keine Nachricht an Dritte ([14 §5.3](14-discord.md#53-was-anton-auf-discord-nie-tut)). | MUSS | 1 |
| SKILL-25 | Datensparsamkeit: an Datendienste gehen nur gerundete Koordinaten, PLZ/Ortsnamen und fachliche Kennungen – nie Transkripte, Anrufer oder Zugangsdaten (außer dem Schlüssel des jeweiligen Dienstes); nur HTTPS an Hosts einer festen Liste (ADR-032). | MUSS | 1 |
| SKILL-26 | `skills.online = false` oder Netzausfall: Offline-Skills laufen unverändert, Online-Skills antworten ehrlich; kein Anruf wartet länger als das Zeitbudget. | MUSS | 1 |
| SKILL-27 | Testkorpus ≥ 800 Äußerungen (positiv, negativ, Dialekt, STT-Varianten) und Golden-Antworten mit fester Uhr und aufgezeichneten Antworten; Router + Offline-Skill p95 ≤ 20 ms. | MUSS | 1 |
| SKILL-28 | Nicht erkannte Fragen werden – nur bei aktivierter Transkriptspeicherung, 24 h – gesammelt und per `./test-1.sh misses` angezeigt. | SOLL | 1 |
| SKILL-29 | Text-Testpfad ohne Telefon: `./test-1.sh ask "…"` (`--explain`, `--play`, `--fixtures`) liefert dieselbe Antwort wie am Telefon. | SOLL | 1 |
| SKILL-30 | Orts- und Postleitzahldaten (Deutschland, Weltstädte) liegen offline im Repository (GeoNames, CC BY 4.0), reproduzierbar per Skript erzeugt (ADR-031). | MUSS | 1 |
| SKILL-31 | Status je Datendienst (bereit/eingeschränkt/aus, letzter Abruf, Datenalter) und der aufgelöste Heimatort stehen in der Statusdatei bzw. später auf der Statusseite. | MUSS | 1 |
| SKILL-32 | Uhrzeit wahlweise umgangssprachlich („Viertel nach sieben“, `skills.time.spoken_style`). | KANN | 1 |
| SKILL-33 | Die bestehenden Fast-Paths (`moritz_agent/agent/fastpath.py`) laufen ohne Verhaltensänderung über das Skill-Framework weiter; ihre Tests bleiben grün. | MUSS | 1 |
| SKILL-34 | Fehlerhafte oder unplausible Antworten von Datendiensten (Schema, Wertebereich) werden verworfen; Freitext (Warntexte, Schlagzeilen) wird bereinigt, gekürzt und nie als Anweisung an ein LLM gegeben. | MUSS | 1 |
| SKILL-35 | **Wetter nur Open Source und kostenlos** (Moritz, 18.10.2026): Wetter-, Warn-, Pollen- und Luftdaten nur von Open-Source-Diensten (Open-Meteo AGPL-3.0, Bright Sky MIT) und amtlichen offenen Daten (DWD, BBK) – ohne Konto, Schlüssel oder Kosten, Daten unter freier Lizenz; keine proprietären Wetter-APIs. Die Dienst-Adressen sind konfigurierbar, damit eigene Instanzen genutzt werden können. | MUSS | 1 |

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

# 10 – Risiken und offene Fragen

Stand nach Moritz’ Antworten vom 16.10.2026.

## 1. Risiken

| # | Risiko | Antwort Moritz | Bewertung / Gegenmaßnahme | Ticket |
| --- | --- | --- | --- | --- |
| R1 | PJSUA2-Binding schwer zu bauen; Audio-Callbacks in Python instabil | „versuch’s trotzdem oder mach’s besser“ | Bleibt Plan A, Quellcode 2.17 jetzt im Repo; Spike zuerst; Plan B Asterisk AudioSocket (ADR-005) | P1-11 |
| R2 | CPU-STT zu langsam | „Whisper small auf CPU“ | Entschieden (ADR-006); Messung im Spike, `base` als Notfall | P1-10 |
| R3 | 8B-Modell zu schwach | „größeres, halb RAM halb VRAM“ | Qwen3-30B-A3B (MoE) UD-Q3_K_XL, Experten teilweise im RAM (ADR-016) | P1-02 |
| R4 | Google/Bing blockieren SearXNG | „andere Suchoptionen, evtl. KoboldCpp“ | Fallback-Kette SearXNG → KoboldCpp-Websuche → Wikipedia (ADR-020, [11](11-suchoptionen.md)) | P1-08 |
| R5 | GPU-Treiber-Mismatch Host ↔ LXC | „kp“ | Bleibt: Versionsprüfung in Status/Updater, Anleitung 06 §4 | P1-01, P1-16 |
| R6 | VRAM durch andere GPU-Nutzer knapp | „nur Compute, sonst nichts“ | **Entschärft**; Restrisiko nur durch eigenes Modell → `--moecpu` mit Reserve | P1-02 |
| R7 | Asterisk-Konfiguration passt nicht | „kein Plan, mach eine Asterisk-Config“ | **Erledigt:** [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md) | P1-01 |
| R8 | Kurze Secrets nicht textuell redigierbar | „kp“ | Bleibt: struktureller Schutz über `Secret`-Typ (08 §3) | P1-03 |
| R9 | Upstream-Merges kollidieren | „egal“ | Akzeptiert; Patch-Liste in 02 §12 hilft beim Auflösen | laufend |
| R10 | Echo/Selbsterkennung | „Lösung steht schon da“ | Klarer Sprecherwechsel (Part 1), AEC in Part 7 | P1-12 |
| R11 | Conda-CUDA-Build braucht Platz/Zeit | „kp“ | Disk ≥ 80 GB eingeplant (06 §3) | P1-02 |
| R12 | Lizenzen | „Lizenzen so lassen, dass KoboldCpp und alle anderen ihre behalten; für den Rest ‚msol 1.1‘“ | **Erledigt:** eigener Code MSOL 1.1, Fremdcode unverändert, Scribbles alle Rechte vorbehalten (ADR-023, `LICENSING.md`) | – |
| R13 | **Neu:** Repo-Größe durch Fremdkomponenten (≈ +95 MB für SearXNG und pjproject) | – | Python-Pakete bewusst nicht im Repo (Moritz: „requirements egal“); Updates von `third_party/` bündeln (ADR-021) | laufend |
| R14 | ~~Polly „Hans“ braucht Internet + AWS-Konto~~ – entfallen (ADR-027) | – | Stimme läuft lokal; Rückfallkette Piper/espeak | P1-10 |
| R15 | **Neu:** MoE mit CPU-Experten auf Haswell (DDR4) langsamer als erwartet | – | `--moecpu` senken (mehr auf GPU), Q3_K_S, oder dichtes 14B als Fallback (ADR-016) | P1-02 |
| R16 | **Neu:** Klang des Hessisch-Piper-Modells (2023, „high“) ist ungehört; er liest hochdeutsch geschriebenen Text mit hessischer Färbung | „das Hessische“ | Hörprobe mit `./test-1.sh speak`; Alternative per `phone.tts.piper.voice` (`de_DE-thorsten-medium`, hochdeutsch) | P1-10 |
| R17 | **Neu:** Geschwindigkeit des „high“-Modells auf dem E5-2673 v3 ist ungemessen (erwartet: deutlich schneller als Echtzeit) | – | `./test-1.sh bench`; `phone.tts.cpu_threads` anpassen; Ansagen sind ohnehin gecacht (PHONE-48) | P1-10 |
| R19 | **Neu:** `install.sh`/`update.sh`/`moritz-install.sh` sind nur gegen einen simulierten Proxmox-Host und ein Fake-System getestet, nicht auf echter Hardware (apt, systemd, unprivilegierter LXC, PJSIP-Build und Modell-Download dort; Ubuntu 26.04 mit Python 3.14) | „automatisch aufsetzen oder updaten“ | `--dry-run`; alle Skripte wiederholbar (setzen fort); Proxmox-Snapshot vor jedem Update; Rollback im Container; erster echter Lauf als Protokoll in P1-18 (09) | P1-15 |
| R20 | **Neu:** Open-Meteo ändert Bedingungen/Kontingente oder fällt aus (freie API nur nicht kommerziell, < 10.000 Aufrufe/Tag) | „Wetter in der Region“ | Vorabruf statt Abruf je Frage (≈ 50–150 Aufrufe/Tag), Rückfall Bright Sky (DWD), Cache bis 6 h; beide Dienste sind Open Source – notfalls eigene Instanz, nur Adresse ändern (ADR-030, SKILL-35) | P1-22 |
| R21 | **Neu:** Whisper erkennt Postleitzahlen und Ortsnamen am Telefon schlecht (Zahlen zerstückelt, „Weilborg“) | – | Ziffernfolgen zusammenführen, unscharfe/phonetische Ortssuche, PLZ in der Antwort mit Ortsname wiederholen, Rückfrage bei niedriger Konfidenz, `initial_prompt`/`hotwords` gemessen (13 §9.2) | P1-21, P1-29 |
| R22 | **Neu:** Moritz’ Formulierungen (Hessisch, Umgangssprache) sind nicht abgedeckt → zu viele „nicht verstanden“ | „anton erkennt mein gelaber“ | Dialekt-Wörterbuch, Liste nicht erkannter Fragen (`./test-1.sh misses`), Korpus wächst mit echten (nachgestellten) Sätzen | P1-19, P1-29 |
| R23 | **Neu:** Falsch-positive Erkennung – ein Skill antwortet, obwohl etwas anderes gemeint war („Um wie viel Uhr fährt der Zug?“) | – | Ausschlusslisten, Score-Schwellen, lange Sätze ausgenommen, ≥ 150 Negativbeispiele im Korpus (0 Fehlzuordnungen als Abnahmekriterium) | P1-19 |
| R24 | **Neu:** Schnittstellen von Bright Sky/DWD/NINA/PEGELONLINE ändern sich unangekündigt | – | Schema-Prüfung je Antwort, Netz-Schema-Tests (`-m network`) regelmäßig, Status `degraded` statt falscher Antwort | P1-23, P1-27 |
| R25 | **Neu:** Gepflegte Daten veralten (Schulferien, neue Feiertage, GeoNames-PLZ) | – | Selbsttest warnt < 12 Monate Ferien-Vorlauf; jährlicher Daten-PR; Erzeugung per Skript mit Prüfsummen | P1-20, P1-21 |
| R26 | **Neu:** Piper spricht Fachwörter/Ortsnamen falsch („Böen“, „Hektopascal“, „Limburg-Weilburg“) | – | Ausspracheliste per Hörtest, Renderer schreibt Abkürzungen/Himmelsrichtungen aus (13 §9.3) | P1-29 |
| R27 | **Neu:** DAVE-Empfang (E2EE seit März 2026 Pflicht) ist in Python nur über Forks gelöst → Anton hört im Discord-Sprachkanal evtl. nicht zuverlässig zu | „Discord mit allen Features“ | Spike P1-32 mit festen Kriterien; Rückfall „nur sprechen“ + Sprachnachrichten + Bühnenkanal; neuer Spike bei offizieller Unterstützung (ADR-036) | P1-32 |
| R28 | **Neu:** Discord ändert API/Regeln, Bibliothek hinkt hinterher | – | gepinnt, isolierter Worker, schneller Update-Weg (ADR-028) | P1-33 |
| R29 | **Neu:** Bot-Token gelangt nach außen | – | `passwords.txt` 0600, Redaction, Public Bot aus, Owner-Bestätigung, Reset-Anleitung (T25) | P1-41 |
| R30 | **Neu:** Inhalte liegen dauerhaft bei Discord (kein E2EE für Text) | – | Standards „aus“ für Transkripte/Notizen/Gedächtnis, `/hilfe datenschutz` (DISCORD-35) | P1-34 |
| R31 | **Neu:** CPU/RAM-Konkurrenz zwischen Telefon und Discord-Sprache | „Telefon zuerst“ | `nice +5`, Modelle nur bei Bedarf, eine Sitzung, Priorität PHONE, Messung | P1-36 |
| R32 | **Neu:** Missbrauch durch andere in Servern | – | Allowlists, Standard „ignorieren“, Rate-Limits (T26–T28) | P1-33 |
| R33 | **Neu:** Grenzen der Benutzer-App (in fremden Servern nur Befehle, oft nur privat sichtbar) | – | dokumentiert, volle Funktionen im eigenen Server und per DM | P1-35 |
| R34 | **Neu:** Schelmische Aktivitäten/süßer Ton wirken unpassend oder beunruhigend | „bissl cutey“, „schelmisch, funny“ | nur eigene geprüfte Sprüche, Ernst-Modus, `/aktivitaet aus`, `style = "normal"` (ADR-037) | P1-43 |

## 2. Offene Fragen – beantwortet

| # | Frage | Antwort | Umgesetzt in |
| --- | --- | --- | --- |
| F-01 | Asterisk-Details | „kein Plan“ | Komplette Anleitung [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md) |
| F-02 | Repo öffentlich? SIP-Startwerte in der Vorlage? | öffentlich; SIP-Server nur lokal, daher egal | Vorlage behält `agent/agent`; ACL + Kontext ohne Wählrechte in Asterisk |
| F-03 | Transkripte speichern? | Text, 24 Stunden (ab Part 2: 15 Tage, F-47) | STORE-02, `storage.transcript_retention_hours = 24` |
| F-04 | Web-UI im LAN? | ja, Port 3501, TLS ok | API-01, ADR-022 |
| F-05 | Distribution | Ubuntu 26.04 oder 25.10 | NFR-06, ADR-024, 06 §3 |
| F-06 | NVIDIA-Treiber am Host? Andere GPU-Nutzer? | Treiber nein, Gast nein | 06 §4.1 Host-Treiber-Anleitung |
| F-07 | CPU / Kerne | E5-2673 v3, bis zu 18 Threads, Host darf nie überlasten | NFR-08, 02 §5a, 06 §3 |
| F-08 | Stimme | „Hans“, ab 17.10.2026 „Thorsten-Voice Hessisch“, ab 18.10.2026 „nur Piper“ | ADR-027: Piper-Modell Thorsten-Voice Hessisch auf der CPU, espeak-ng als Notstimme |
| F-09 | Suchmaschinen | alle | `config/searxng/settings.yml`, ADR-007 |
| F-10 | Sandbox-Netz | nur Sophie-1 + Internet | SBX-03, 06 §7 |
| F-11 | KoboldCpp-Oberflächen behalten? | nein, alles weg | ADR-002, Dateien entfernt |
| F-12 | Windows? | niemals | PRD-07 gestrichen |
| F-13 | Fast-Paths für einfache Infos? | ja, alle | AGENT-10, [12-fast-paths.md](12-fast-paths.md) |

## 3. Offene Fragen – neu

| # | Frage | Default bis zur Antwort |
| --- | --- | --- |
| F-08b | ~~Hans = Amazon Polly? AWS-Konto?~~ | **erledigt/ersetzt:** Moritz nimmt statt Hans die Thorsten-Voice-Hessisch-Stimme (lokal, ADR-027). Polly ist entfernt (Git-Historie `cbb5520`). | ADR-027 |
| F-14 | ~~„msol 1.1“?~~ | **beantwortet:** Moritzsoft Open License 1.1 für allen eigenen Code ([`LICENSE-MSOL.md`](../../LICENSE-MSOL.md), [`LICENSING.md`](../../LICENSING.md), ADR-023) |
| F-15 | ~~Bundesland?~~ | **beantwortet:** Hessen (`fastpaths.state = "HE"`, [12-fast-paths.md](12-fast-paths.md) §4) |
| F-16 | ~~HF-Modelle ins Repo?~~ | **beantwortet:** nein, HF-Modelle lädt der Installer; alles andere ins Repo, Python-Requirements dürfen aus dem Netz kommen |
| F-17 | ~~Lizenz Scribbles?~~ | **beantwortet:** alle Rechte vorbehalten (© LayerNX) |
| F-18 | Soll Anton nach der Begrüßung von selbst auf Wetterwarnungen hinweisen – ab welcher Stufe? | ja, ab „Unwetter“ (Stufe 3) – [13 §19](13-sofortauskuenfte.md#19-offene-fragen-an-moritz) |
| F-19 | Uhrzeit „19 Uhr 12“ oder umgangssprachlich („Viertel nach sieben“)? | „19 Uhr 12“ |
| F-20 | Pollen: Allergien (nur diese nennen)? Region Mittelgebirge oder Rhein-Main? | alle Arten, Mittelgebirge |
| F-21 | Müllabfuhr: Link zum Abfallkalender für Straße/Stadtteil? | aus |
| F-22 | Fußball: welcher Verein? | aus (Vorschlag Eintracht Frankfurt) |
| F-23 | Welcher Lahn-Pegel? | nächster automatisch |
| F-24 | „Wetter in der Region“: welche Nachbarorte? | Limburg an der Lahn, Wetzlar |
| F-25 | Spritpreise mit (kostenlosem) Tankerkönig-Schlüssel? Sorte? | aus, E10 |
| F-26 | Nachrichten-Schlagzeilen am Telefon? Quelle? | aus |
| F-27 | Einkaufsliste/Notizen per Telefon (jeder interne Anrufer kann sie hören)? | aus |
| F-28 | Wetterquelle von sich aus nennen oder nur auf Nachfrage? | nur auf Nachfrage |
| F-29 | ~~Eigener Discord-Server? Kanal für alles?~~ | **beantwortet:** Privatserver Moritz + Anton; Standard-Textkanal per ID im Setup oder in der TXT (DISCORD-45) |
| F-30 | Wer außer dir darf Anton auf Discord nutzen? Gastmodus nur mit Sofortauskünften? | nur du; Gastmodus aus |
| F-31 | Soll Anton zusätzlich zu `/joinvc` von selbst kommen, wenn du einen Sprachkanal betrittst? | nein – [14 §23](14-discord.md#23-offene-fragen-an-moritz) |
| F-32 | Welche Abos (Warnungen, Morgenbriefing + Uhrzeit, Müll, Systemhinweise)? | Warnungen ab Unwetter + Systemhinweise |
| F-33 | Anrufhinweise auf Discord? Mit Themen oder Transkript? | aus |
| F-34 | ~~Bot-Name, Stil, Status?~~ | **beantwortet:** „Anton“, süß, schelmische Aktivitäten (ADR-037) |
| F-35 | Auf Sprachnachrichten mit Sprachnachricht antworten? | ja („mirror“) |
| F-36 | PIN für gefährliche Admin-Befehle? | keine PIN, Bestätigungsknopf |
| F-37 | ~~Antworten im Kanal oder per DM?~~ | **beantwortet:** Standardkanal für alles |
| F-38 | Eine extra niedliche Scribbles-Pose für den Avatar zeichnen? (neue Posen nur von dir) | Scribbles weiß auf dunklem Grund |
| F-39 | Sprachkanal bei langer Stille: still bleiben und auf „Anton“ hören oder gehen wie beim Auflegen? | still bleiben |
| F-40 | Eigene Lieblingssprüche für die Aktivitäten? | Liste aus 14 §8.5 |
| F-41 | ~~Wie lange sollen Gespräche gespeichert bleiben?~~ | **beantwortet:** 15 Tage, mit Speichern-Knopf für immer (15 §1) |
| F-42 | ~~WebUI auch über VPN?~~ | **beantwortet:** nur LAN, über die IP 192.168.1.187 |
| F-43 | ~~Mehrere Benutzer?~~ | **beantwortet:** nur Moritz |
| F-44 | ~~Modellwechsel in der WebUI?~~ | **beantwortet:** kein Wechsel, nur das eine Modell |
| F-45 | ~~Tempo gegen Kontext?~~ | **beantwortet:** mindestens 50k Kontext, Tempo zweitrangig |
| F-46 | ~~Ein Gespräch über alle Kanäle?~~ | **beantwortet:** nein, jedes für sich |
| F-47 | ~~Anrufe und Discord im Verlauf der WebUI?~~ | **beantwortet:** ja, 15 Tage (ersetzt die 24 h aus F-03) |
| F-48 | ~~Mikrofon und Vorlesen im Browser?~~ | **beantwortet:** nein |
| F-49 | ~~Wie lange angemeldet bleiben?~~ | **beantwortet:** 10 Tage |
| F-50 | ~~Zugangsdaten in der WebUI setzbar?~~ | **beantwortet:** ja, alles änderbar (nur schreibend) |
| F-51 | Vorlage „layernx“ für das Design? | Fluent-2-Stil dunkel, bis eine Vorlage da ist |
| F-52 | ~~Agenten in der Sandbox?~~ | **beantwortet:** ja, später wie Claude Code; Part 2 legt den Grund (ADR-041) |

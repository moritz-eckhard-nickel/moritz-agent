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

## 2. Offene Fragen – beantwortet

| # | Frage | Antwort | Umgesetzt in |
| --- | --- | --- | --- |
| F-01 | Asterisk-Details | „kein Plan“ | Komplette Anleitung [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md) |
| F-02 | Repo öffentlich? SIP-Startwerte in der Vorlage? | öffentlich; SIP-Server nur lokal, daher egal | Vorlage behält `agent/agent`; ACL + Kontext ohne Wählrechte in Asterisk |
| F-03 | Transkripte speichern? | Text, 24 Stunden | STORE-02, `storage.transcript_retention_hours = 24` |
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

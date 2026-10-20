# moritz-agent – Projektplan

Stand: 20.10.2026 · Zielsystem: Sophie-1 (Proxmox, 32 GB RAM, Xeon E5-2673 v3, RTX 3070 8 GB) ·
**Höchste Priorität: intern anrufbarer Telefon-Agent ab Part 1.** Der Assistent heißt **Nikita** (ADR-026).

| Dokument | Inhalt |
| --- | --- |
| [00-originalplan.md](00-originalplan.md) | Originalplan von Moritz (unverändert, Referenz) |
| [01-anforderungen.md](01-anforderungen.md) | Nummerierte, prüfbare Anforderungen (PRD, PHONE, DISCORD, CFG, INST, UPD, INF, AGENT, SKILL, SEARCH, API, UI, STORE, LOG, NFR, SBX) |
| [02-architektur.md](02-architektur.md) | Repo-Layout, Prozessmodell, Startablauf, Telefon-Zustandsautomat, Datenmodell, API, Ports, Fehlerisolierung |
| [03-entscheidungen.md](03-entscheidungen.md) | Architekturentscheidungen (ADR-001 … ADR-037) |
| [04-part1-umsetzung.md](04-part1-umsetzung.md) | **Ticketplan Part 1** (P1-00, P1-00b … P1-18, Block S: P1-19 … P1-30, Block D: P1-31 … P1-43), Reihenfolge, DoD, Ansagenkatalog |
| [05-roadmap.md](05-roadmap.md) | Part 2 – 9, Version 1.0, 1.1+ |
| [06-infrastruktur.md](06-infrastruktur.md) | Inventar, RAM/VRAM-Budget, LXC, NVIDIA-Treiber am Host, GPU-Zugriff, Firewall, Sandbox-VM |
| [07-installation-update.md](07-installation-update.md) | Spezifikation Installer und Updater, Exit-Codes, Versions-Lock |
| [08-sicherheit.md](08-sicherheit.md) | Bedrohungsmodell, Secret-Handling, Lizenzpflichten |
| [09-tests-abnahme.md](09-tests-abnahme.md) | Teststrategie, Abnahmeprotokoll Part 1, Latenzmessung |
| [10-risiken-offene-fragen.md](10-risiken-offene-fragen.md) | Risiken, beantwortete und neue offene Fragen |
| [11-suchoptionen.md](11-suchoptionen.md) | Suchoptionen und Fallback-Kette (R4) |
| [12-fast-paths.md](12-fast-paths.md) | Vordefinierte Antworten für einfache Infos (F-13), aufgegangen in 13 |
| [13-sofortauskuenfte.md](13-sofortauskuenfte.md) | **Sofortauskünfte vor dem LLM:** Uhrzeit, Kalender, **Wetter für Weilburg 35781** (oder genannte PLZ/Ort), Warnungen, Pollen, Sonne/Mond, Rechnen, Region – rund 180 Auskünfte, Architektur, Datenquellen, Tests, Wellen |
| [14-discord.md](14-discord.md) | **Discord-Bot:** Nikita mit allen Funktionen auf Discord, ein bisschen süß, mit schelmischen Aktivitäten – Standard-Textkanal, Slash-Befehle, Benutzer-App, `/joinvc` = Sprachkanal wie ein Anruf (DAVE), Sprachnachrichten, Erinnerungen, Abos, Admin, Sicherheit, Setup mit Token, Tests, Abnahme |
| [../proxmox-installation.md](../proxmox-installation.md) | `install.sh`/`update.sh`: LXC auf dem Proxmox-Host anlegen und aktualisieren |
| [../telefon-test-1.md](../telefon-test-1.md) | `./test-1.sh`: Telefon und Stimme ohne LXC ausprobieren |
| [../asterisk-konfiguration.md](../asterisk-konfiguration.md) | Komplette Asterisk-Konfiguration für Nebenstelle 999 / Konto `agent` |
| [../../LICENSING.md](../../LICENSING.md) | Welche Lizenz gilt wofür (MSOL 1.1, AGPL, GPL, MIT, Scribbles) |

## Kurzfassung

- **Ein Produkt, mehrere isolierte Worker:** Supervisor (FastAPI-Backend, Agent, Storage)
  startet KoboldCPP (Inference, CUDA), SearXNG (Suche) und den Phone-Worker (PJSUA2, VAD,
  STT, TTS) als eigene Prozesse.
- **KoboldCPP bleibt an der Repo-Wurzel** und wird nicht umgebaut; eigener Code liegt in
  `moritz_agent/` (ADR-001). So bleiben Upstream-Updates mergebar.
- **Telefon zuerst:** Part 1 ist fertig, wenn ein echter Anruf an 999 Begrüßung, ≥ 3 Runden,
  Uhrzeit (über echtes Tool, Europe/Berlin) und Websuche schafft – installiert per Skript.
- **Risiko zuerst:** SIP-Spike (P1-11) und Audio-Spike (P1-10) vor dem Ausbau.
- **Modell:** Qwen3-30B-A3B-Instruct-2507 (MoE, UD-Q3_K_XL, 13,8 GB), etwa halb VRAM / halb
  RAM (ADR-016). **STT:** Whisper small auf CPU. **TTS:** Thorsten-Voice „Hessisch“
  als Piper-Modell auf der CPU (ADR-027), Notstimme espeak-ng. **Web-UI:** HTTPS im LAN auf Port 3501.
- **Alles im Repo, ein Programm:** SearXNG (fertig gebaut), PJSIP 2.17 und VAD liegen in
  `third_party/` und `assets/models/`; aus dem Netz kommen nur PyPI-Pakete (gepinnt), die
  CUDA-Toolchain und die Modelle (ADR-021).
- **Maskottchen:** Scribbles (LayerNX) – im Logo und überall in der Oberfläche.
- **Sofortauskünfte vor dem LLM (ADR-029):** Uhrzeit, Kalender, Wetter (Standard **35781 Weilburg**,
  sonst die genannte PLZ bzw. der genannte Ort), Warnungen, Pollen, Sonne/Mond, Rechnen und mehr –
  deterministisch, mit Cache und ehrlich bei Ausfall; später dieselben Funktionen als LLM-Tools.
- **Discord (ADR-033):** Nikita auch als Discord-Bot – alle Funktionen auf allen Kanälen
  (Kanal-Parität), Token und Standardkanal beim Setup oder in `passwords.txt`, `/joinvc` wie ein
  Anruf, süßer Stil mit schelmischen Aktivitäten, kein offener Port, Telefon hat Vorrang.

## Status

| Ticket | Status |
| --- | --- |
| P1-00 Repo-Grundlage, Rebranding, Plan | ✅ PR #1 |
| P1-00b Antworten, Logo, Fremdkomponenten im Repo | ✅ PR 2 |
| P1-10 Audio (VAD, Whisper, Piper „Hessisch“, Ansagen-Cache) | ✅ gebaut; Messung auf dem Zielrechner offen |
| P1-11 SIP (PJSUA2-Adapter, Klingeln 4–8 s) | ✅ gebaut; läuft an Moritz’ Anlage |
| P1-12 Phone-Worker (ohne LLM, `TestResponder`) | ✅ |
| P1-13 Vorbereitete Ansagen | ✅ |
| P1-15 / P1-16 / P1-17 Installer, Updater, systemd (inkl. `install.sh`/`update.sh` am Proxmox-Host) | ✅ gebaut; KoboldCpp-/SearXNG-/TLS-Phasen folgen |
| **Block S: P1-19 … P1-30 Sofortauskünfte** | geplant ([13](13-sofortauskuenfte.md)) – **als Nächstes, vor dem LLM** |
| **Block D: P1-31 … P1-43 Discord-Bot** | geplant ([14](14-discord.md)) – nach P1-19, parallel zu Block S |
| P1-01 … P1-09, P1-14, P1-18 | offen |

## Pflege

- Planänderungen erfolgen per PR in diesen Dateien, nicht nur im Code.
- Entscheidungen werden in `03-entscheidungen.md` nachgezogen (ADR nie löschen, nur ersetzen).
- Messwerte (RAM/VRAM/Latenz) werden in `06` und `09` eingetragen, sobald sie vorliegen.

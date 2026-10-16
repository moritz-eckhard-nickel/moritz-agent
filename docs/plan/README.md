# moritz-agent – Projektplan

Stand: 16.10.2026 · Zielsystem: Sophie-1 (Proxmox, 32 GB RAM, RTX 3070 8 GB) ·
**Höchste Priorität: intern anrufbarer Telefon-Agent ab Part 1.**

| Dokument | Inhalt |
| --- | --- |
| [00-originalplan.md](00-originalplan.md) | Originalplan von Moritz (unverändert, Referenz) |
| [01-anforderungen.md](01-anforderungen.md) | Nummerierte, prüfbare Anforderungen (PRD, PHONE, CFG, INST, UPD, INF, AGENT, SEARCH, API, UI, STORE, LOG, NFR, SBX) |
| [02-architektur.md](02-architektur.md) | Repo-Layout, Prozessmodell, Startablauf, Telefon-Zustandsautomat, Datenmodell, API, Ports, Fehlerisolierung |
| [03-entscheidungen.md](03-entscheidungen.md) | Architekturentscheidungen (ADR-001 … ADR-019) |
| [04-part1-umsetzung.md](04-part1-umsetzung.md) | **Ticketplan Part 1** (P1-00 … P1-18), Reihenfolge, DoD, Ansagenkatalog |
| [05-roadmap.md](05-roadmap.md) | Part 2 – 9, Version 1.0, 1.1+ |
| [06-infrastruktur.md](06-infrastruktur.md) | Inventar, RAM/VRAM-Budget, LXC, GPU-Zugriff, Firewall, Asterisk-Checkliste, Sandbox-VM |
| [07-installation-update.md](07-installation-update.md) | Spezifikation Installer und Updater, Exit-Codes, Versions-Lock |
| [08-sicherheit.md](08-sicherheit.md) | Bedrohungsmodell, Secret-Handling, Lizenzpflichten |
| [09-tests-abnahme.md](09-tests-abnahme.md) | Teststrategie, Abnahmeprotokoll Part 1, Latenzmessung |
| [10-risiken-offene-fragen.md](10-risiken-offene-fragen.md) | Risiken mit Gegenmaßnahmen, offene Fragen an Moritz mit Defaults |

## Kurzfassung

- **Ein Produkt, mehrere isolierte Worker:** Supervisor (FastAPI-Backend, Agent, Storage)
  startet KoboldCPP (Inference, CUDA), SearXNG (Suche) und den Phone-Worker (PJSUA2, VAD,
  STT, TTS) als eigene Prozesse.
- **KoboldCPP bleibt an der Repo-Wurzel** und wird nicht umgebaut; eigener Code liegt in
  `moritz_agent/` (ADR-001). So bleiben Upstream-Updates mergebar.
- **Telefon zuerst:** Part 1 ist fertig, wenn ein echter Anruf an 999 Begrüßung, ≥ 3 Runden,
  Uhrzeit (über echtes Tool, Europe/Berlin) und Websuche schafft – installiert per Skript.
- **Risiko zuerst:** SIP-Spike (P1-11) und Audio-Spike (P1-10) vor dem Ausbau.

## Status

| Ticket | Status |
| --- | --- |
| P1-00 Repo-Grundlage, Rebranding, Plan | ✅ dieser PR |
| P1-01 … P1-18 | offen |

## Pflege

- Planänderungen erfolgen per PR in diesen Dateien, nicht nur im Code.
- Entscheidungen werden in `03-entscheidungen.md` nachgezogen (ADR nie löschen, nur ersetzen).
- Messwerte (RAM/VRAM/Latenz) werden in `06` und `09` eingetragen, sobald sie vorliegen.

<p align="center">
  <img src="assets/branding/m-agent-logo-192.png" width="128" height="128" alt="m-agent Logo">
</p>

<p align="center"><em>Mit Scribbles, dem Maskottchen von LayerNX und moritz-agent.</em></p>

# moritz-agent

**Ein eigenständiger, lokaler KI-Agent – anrufbar über das interne Telefonnetz, mit
Websuche, Tools, Sandbox und eigener Weboberfläche.**

moritz-agent (kurz **m-agent**) vereint SIP-Telefonie, Spracherkennung, Sprachausgabe,
LLM-Inference, Agent-Logik, Websuche, (später) Deep Research, Browser-Automation,
Tool-Calling, Sandbox-Steuerung, Backend und Frontend in **einer** Anwendung:

- eine Anwendung · ein Startbefehl (`./moritz-agent`) · eine zentrale Konfiguration
  (+ editierbare `passwords.txt`) · eine Weboberfläche · ein Repository

Intern laufen mehrere isolierte Worker, damit ein Absturz von Suche, Browser oder Modell
nicht die ganze Anwendung mitreißt. Als Inference-Engine dient
[KoboldCpp](https://github.com/LostRuins/koboldcpp) (llama.cpp, CUDA) – unsichtbar im
Hintergrund, ohne eigene Oberfläche.

> **Status:** Part 1 / v0.1 ist **gebaut und per automatischen Tests geprüft** (Telefon, Sofortauskünfte,
> Discord-Bot, Konfiguration, Installer). **Noch nicht abgenommen:** Sprachmodell (P1-02), Sophie-1 (P1-01/P1-18),
> echtes Discord (P1-32/P1-42) und Hörtests (P1-30) brauchen echte Hardware und Konten – was fehlt, steht ehrlich in
> [Plan 04, Anhang C](docs/plan/04-part1-umsetzung.md#anhang-c--umsetzungsstand-und-abweichungen-stand-21102026). Der
> vollständige Plan liegt in [`docs/plan/`](docs/plan/README.md). Noch nicht produktiv einsetzbar.

## Part 1: Der Telefon-Agent

Moritz wählt intern die **999** und landet bei **Nikita**, dem Assistenten von moritz-agent. Er ist als SIP-Konto `agent` an der Telefonanlage
`192.168.1.176` registriert und

1. nimmt automatisch ab und begrüßt sofort: „Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?“
2. hört zu, erkennt das Sprachende und transkribiert auf Deutsch (Whisper small, CPU),
3. beantwortet vieles sofort, ohne Sprachmodell – Uhrzeit (immer aus der echten Systemuhr, Europe/Berlin), Datum,
   Kalenderwoche, Rechnen und **Sofortauskünfte**: Wetter für Weilburg (35781) oder jede genannte PLZ/jeden Ort
   (nur freie Dienste: Open-Meteo, Bright Sky, DWD), Warnungen, Pollen, Sonne/Mond, Feiertage, Ferien, Eieruhr und mehr
   ([Plan](docs/plan/13-sofortauskuenfte.md)); dasselbe kann Nikita als **Discord-Bot** – im Textkanal, per Slash-Befehl,
   auf Sprachnachrichten und im Sprachkanal (`/joinvc` wie ein Anruf), süß und mit schelmischen Aktivitäten
   ([Einrichtung](docs/discord-einrichtung.md), [Plan](docs/plan/14-discord.md)),
4. beantwortet andere Fragen mit dem Sprachmodell und nutzt bei Bedarf die integrierte Websuche,
5. spricht die Antwort mit der Stimme **Thorsten-Voice „Hessisch“** (Piper, lokal auf der CPU; feste Ansagen vorgerendert und gecacht – [ADR-027](docs/plan/03-entscheidungen.md)) und hört wieder zu – mehrere Runden pro Anruf,
6. räumt beim Auflegen alles sauber auf.

Asterisk-Einrichtung: [`docs/asterisk-konfiguration.md`](docs/asterisk-konfiguration.md)

## Architektur in einem Bild

```text
moritz-agent
├── Phone Core      SIP (PJSUA2 2.17) · RTP · VAD (Silero) · STT (Whisper small) · TTS (Piper Hessisch)
├── Inference       KoboldCpp / llama.cpp · Qwen3-30B-A3B (MoE) · halb VRAM / halb RAM
├── Agent Core      Agent-Loop · Tool-Calling · Fast-Paths · Context Manager · Profile
├── Research        SearXNG (alle Engines) → KoboldCpp-Websuche → Wikipedia · später Deep Research
├── Tools           get_current_time · web_search · später Shell/Python/Git/SSH (nur Sandbox)
├── Storage         SQLite (Transkripte 24 h)
├── Backend API     HTTPS :3501 · /api/... · später OpenAI-kompatibel /v1/...
└── Frontend        Statusseite (Part 1) · Chat, Agent-Timeline, Modelle (Part 2)
```

Details: [Architektur](docs/plan/02-architektur.md) ·
[Entscheidungen](docs/plan/03-entscheidungen.md) ·
[Roadmap](docs/plan/05-roadmap.md)

## Zielumgebung

| Komponente | Wert |
| --- | --- |
| Host | Sophie-1, Proxmox VE, 32 GB RAM, Xeon E5-2673 v3, NVIDIA RTX 3070 (8 GB VRAM) |
| Laufzeit | unprivilegierter LXC mit **Ubuntu 26.04**, 16 GB RAM-Limit, max. 18 Threads, GPU-Gerätezugriff |
| Telefonanlage | Asterisk `192.168.1.176`, SIP UDP 5060, Nebenstelle 999 → Konto `agent` |
| Web-UI | `https://<LXC-IP>:3501` im LAN, mit Login |
| Sandbox (ab Part 4) | eigene VM auf Redemption-1, nur Internet + Sophie-1 erreichbar |

Infrastruktur-Anleitung (inkl. NVIDIA-Treiber am Host): [docs/plan/06-infrastruktur.md](docs/plan/06-infrastruktur.md)

## Ein Programm, alles im Repository

Alle Programmbestandteile liegen direkt hier, damit moritz-agent eigenständig als **ein**
Programm läuft ([`third_party/VENDORED.md`](third_party/VENDORED.md)):

| Komponente | Ort |
| --- | --- |
| SearXNG (fertig gebaut) | `third_party/searxng/` |
| PJSIP / PJSUA2 2.17 (Quellcode) | `third_party/pjproject/` |
| Silero VAD | `assets/models/vad/` |

SearXNG ist fertig gebaut (Frontend-Assets und Daten liegen bei) und läuft direkt aus dem
Repo als interner Worker von moritz-agent – kein separater Dienst, keine eigene Installation.

Aus dem Netz kommen nur: Python-Pakete von PyPI (exakt gepinnt mit Hashes in
`requirements/*.lock`), die Build-Toolchain für KoboldCpp/CUDA und die Modelle von Hugging Face
(LLM 13,8 GB, Whisper small, Piper-Stimme Hessisch).

## Telefon- und Stimmenteil jetzt ausprobieren: `./test-1.sh`

SIP-Telefon, Spracherkennung und Nikitas Stimme laufen schon – ganz ohne Systeminstallation, alles
unter `runtime/` und `models/` im Repository (Anleitung: [docs/telefon-test-1.md](docs/telefon-test-1.md)). Er setzt keinen LXC voraus und läuft auf jedem Linux-Rechner.
Es ist derselbe Code, der später im vollständigen System läuft; nur das Sprachmodell fehlt noch
(Nikita beantwortet Uhrzeit, Datum usw. über Fast-Paths, sonst „Ich habe verstanden: …“).

```bash
sudo apt install build-essential python3-venv python3-dev swig pkg-config espeak-ng   # einmalig, falls fehlt
./test-1.sh setup          # Python-Umgebung, SIP-Stack bauen, Modelle laden (ca. 0,6 GB)
./test-1.sh check          # Selbsttest
./test-1.sh speak "Hallo Moritz, hier ist Nikita." --play
./test-1.sh call           # Testanruf ohne Telefonanlage (Nikita ruft sich selbst an)
./test-1.sh run            # an der Telefonanlage anmelden und 999 anrufen
```

## Installation auf Proxmox: `install.sh` / `update.sh`

Auf dem Proxmox-Host (als root bzw. mit `sudo`) – legt den LXC an, kopiert das Programm hinein und
installiert alles darin; derselbe Aufruf aktualisiert einen vorhandenen Container:

```bash
git clone https://github.com/moritz-eckhard-nickel/moritz-agent.git && cd moritz-agent
sudo ./install.sh                            # LXC anlegen + installieren (fragt vorher nach, --dry-run zeigt nur)
sudo ./update.sh                             # später: Snapshot, laufendes Gespräch abwarten, Update, bei Fehler Rollback
./install.sh --remote root@proxmox           # oder von Sophie-1s Konsole / einem anderen Rechner (scp + ssh)
```

Der Container wird unprivilegiert mit den Werten aus dem Plan angelegt (Ubuntu 26.04/25.10/24.04, 18 Kerne,
16 GB RAM, 80 GB, optional GPU-Durchreichung). Darin richtet `moritz-install.sh` Dienstbenutzer,
Python-Umgebung (gepinnte PyPI-Pakete), PJSIP aus dem Repo, Modelle, `passwords.txt` (mit vorbelegten
SIP-Werten), die Ansagen und den systemd-Dienst ein. `passwords.txt`, Konfiguration, Modelle und Daten
bleiben bei Updates immer erhalten. Optionen, Ablauf und Fehlersuche:
[docs/proxmox-installation.md](docs/proxmox-installation.md); Spezifikation:
[docs/plan/07-installation-update.md](docs/plan/07-installation-update.md). KoboldCpp, SearXNG und
Web-Login folgen mit ihren Tickets.

## Zugangsdaten: `passwords.txt`

Alle Zugangsdaten stehen zentral in `passwords.txt` (INI, Klartext, Dateimodus `0600`,
**nie** im Repository). Vorlage: [`config/passwords.template.txt`](config/passwords.template.txt).
Änderungen werden per Reload übernommen; SIP-Änderungen führen zur Neuregistrierung,
sobald kein Gespräch aktiv ist. Nicht geheime Einstellungen stehen in
`config/moritz-agent.toml` (Vorlage: [`config/moritz-agent.example.toml`](config/moritz-agent.example.toml)).

## Entwicklung

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ruff check moritz_agent tests/moritz_agent && ruff format --check moritz_agent tests/moritz_agent
pytest
```

- Eigener Code liegt ausschließlich in `moritz_agent/`, `frontend/`, `config/`, `assets/`,
  `deploy/`, `docs/`, `tests/moritz_agent/`.
- KoboldCpp-Dateien an der Repo-Wurzel und alles unter `third_party/` bleiben möglichst
  unverändert (ADR-001, ADR-021).
- Arbeitsregeln für KI-gestützte Entwicklung: [`CLAUDE.md`](CLAUDE.md).
- Ticketplan Part 1: [docs/plan/04-part1-umsetzung.md](docs/plan/04-part1-umsetzung.md).

## Herkunft und Lizenz

moritz-agent ist ein eigenständiges Projekt auf Basis von
[KoboldCpp](https://github.com/LostRuins/koboldcpp) von Concedo/LostRuins, das wiederum auf
[llama.cpp](https://github.com/ggml-org/llama.cpp) und [GGML](https://github.com/ggml-org/ggml)
aufbaut. Die ursprüngliche KoboldCpp-Dokumentation ist unter
[`docs/upstream/KOBOLDCPP_README.md`](docs/upstream/KOBOLDCPP_README.md) archiviert.

Jede Komponente behält ihre Lizenz (Übersicht je Pfad: [LICENSING.md](LICENSING.md)):

- **Eigener Code von moritz-agent: Moritzsoft Open License (MSOL) 1.1** ([LICENSE-MSOL.md](LICENSE-MSOL.md)).
- KoboldCpp und übrige Upstream-Dateien: **GNU AGPL v3.0** ([LICENSE.md](LICENSE.md)), sofern eine Datei nichts anderes angibt.
- GGML, llama.cpp und stable-diffusion.cpp: MIT ([MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md](MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md)).
- SearXNG: AGPL-3.0 · PJSIP: GPL-2.0+ · Piper: GPL-3.0 · Silero VAD: MIT – Details in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Scribbles und das m-agent-Logo: © LayerNX / Moritz Eckhard Nickel, **alle Rechte vorbehalten**.

Alle ursprünglichen Copyright- und Lizenzhinweise bleiben erhalten.

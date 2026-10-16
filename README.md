# moritz-agent

**Ein eigenständiger, lokaler KI-Agent – anrufbar über das interne Telefonnetz, mit
Websuche, Tools, Sandbox und eigener Weboberfläche.**

moritz-agent vereint SIP-Telefonie, Spracherkennung, Sprachausgabe, LLM-Inference,
Agent-Logik, Websuche, (später) Deep Research, Browser-Automation, Tool-Calling,
Sandbox-Steuerung, Backend und Frontend in **einer** Anwendung:

- eine Anwendung · ein Startbefehl (`./moritz-agent`) · eine zentrale Konfiguration
  (+ editierbare `passwords.txt`) · eine Weboberfläche · ein Repository

Intern laufen mehrere isolierte Worker, damit ein Absturz von Suche, Browser oder Modell
nicht die ganze Anwendung mitreißt. Als Inference-Engine dient
[KoboldCpp](https://github.com/LostRuins/koboldcpp) (llama.cpp, CUDA).

> **Status:** Planungs- und Gerüstphase (Part 1 / v0.1 in Arbeit). Der vollständige Plan
> liegt in [`docs/plan/`](docs/plan/README.md). Noch nicht produktiv einsetzbar.

## Part 1: Der Telefon-Agent

Moritz wählt intern die **999**. Der Agent ist als SIP-Konto `agent` an der Telefonanlage
`192.168.1.176` registriert und

1. nimmt automatisch ab und begrüßt sofort: „Hallo Moritz, hier ist Agent. Was kann ich für dich tun?“
2. hört zu, erkennt das Sprachende und transkribiert auf Deutsch,
3. beantwortet „Wie viel Uhr haben wir?“ über ein **echtes Uhrzeit-Tool** (Europe/Berlin),
4. beantwortet andere Fragen mit dem Sprachmodell und nutzt bei Bedarf die integrierte Websuche,
5. spricht die Antwort und hört wieder zu – mehrere Runden pro Anruf,
6. räumt beim Auflegen alles sauber auf.

## Architektur in einem Bild

```text
moritz-agent
├── Phone Core      SIP (PJSUA2) · RTP · VAD · STT · TTS · Gesprächsrunden
├── Inference       KoboldCpp / llama.cpp (CUDA, ein Modell, 7–9B Q4)
├── Agent Core      Agent-Loop · Tool-Calling · Context Manager · Profile
├── Research        SearXNG (intern) · Web-Fetcher · später Deep Research & Browser
├── Tools           get_current_time · web_search · später Shell/Python/Git/SSH (nur Sandbox)
├── Storage         SQLite
├── Backend API     /api/... · später OpenAI-kompatibel /v1/...
└── Frontend        Statusseite (Part 1) · Chat, Agent-Timeline, Modelle (Part 2)
```

Details: [Architektur](docs/plan/02-architektur.md) ·
[Entscheidungen](docs/plan/03-entscheidungen.md) ·
[Roadmap](docs/plan/05-roadmap.md)

## Zielumgebung

| Komponente | Wert |
| --- | --- |
| Host | Sophie-1, Proxmox VE, 32 GB RAM, NVIDIA RTX 3070 (8 GB VRAM) |
| Laufzeit | unprivilegierter Linux-LXC, 16 GB RAM-Limit, GPU-Gerätezugriff |
| Telefonanlage | Asterisk `192.168.1.176`, SIP UDP 5060, Nebenstelle 999 → Konto `agent` |
| Sandbox (ab Part 4) | eigene VM auf Redemption-1 (Shell, Python, Git, Chromium) |

Infrastruktur-Anleitung: [docs/plan/06-infrastruktur.md](docs/plan/06-infrastruktur.md)

## Installation (Zielbild – noch nicht implementiert)

```bash
git clone https://github.com/moritz-eckhard-nickel/moritz-agent.git /opt/moritz-agent
cd /opt/moritz-agent
sudo ./install.sh          # → moritz-install.sh
sudo ./update.sh           # → moritz-update.sh
./moritz-agent             # Start (normalerweise über systemd)
```

Der Installer richtet Dienstbenutzer, Abhängigkeiten, PJSIP, KoboldCpp-Build, SearXNG,
Modelle, `passwords.txt` (mit vorbelegten SIP-Werten), Web-Login und optional die
Sandbox-Verbindung ein und fordert am Ende zu einem Testanruf an 999 auf.
Spezifikation: [docs/plan/07-installation-update.md](docs/plan/07-installation-update.md)

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
  `deploy/`, `docs/plan/`, `tests/moritz_agent/`.
- Die KoboldCpp-Dateien an der Repo-Wurzel (`koboldcpp.py`, `ggml/`, `src/`, `otherarch/`, …)
  bleiben möglichst unverändert, damit Upstream-Updates mergebar bleiben (ADR-001).
- Arbeitsregeln für KI-gestützte Entwicklung: [`CLAUDE.md`](CLAUDE.md).
- Ticketplan Part 1: [docs/plan/04-part1-umsetzung.md](docs/plan/04-part1-umsetzung.md).

## Herkunft und Lizenz

moritz-agent ist ein eigenständiges Projekt auf Basis von
[KoboldCpp](https://github.com/LostRuins/koboldcpp) von Concedo/LostRuins, das wiederum auf
[llama.cpp](https://github.com/ggml-org/llama.cpp) und [GGML](https://github.com/ggml-org/ggml)
aufbaut. Die ursprüngliche KoboldCpp-Dokumentation ist unter
[`docs/upstream/KOBOLDCPP_README.md`](docs/upstream/KOBOLDCPP_README.md) archiviert.

- Das Gesamtwerk steht – wie KoboldCpp – unter der **GNU AGPL v3.0** ([LICENSE.md](LICENSE.md)),
  sofern eine Datei nichts anderes angibt.
- GGML, llama.cpp und stable-diffusion.cpp: MIT ([MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md](MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md)).
- Alle weiteren Komponenten und ihre Lizenzen: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Alle ursprünglichen Copyright- und Lizenzhinweise bleiben erhalten.

# CLAUDE.md – Arbeitsregeln für moritz-agent

## Projekt in einem Satz

moritz-agent ist ein lokaler KI-Agent (Telefon via SIP + WebUI) auf Basis von KoboldCpp.
Der vollständige Plan steht in `docs/plan/` – **vor jeder Aufgabe** das passende Ticket in
`docs/plan/04-part1-umsetzung.md` und die referenzierten Anforderungs-IDs in
`docs/plan/01-anforderungen.md` lesen.

## Repository-Grenzen (ADR-001/002)

- Eigener Code nur in: `moritz_agent/`, `tests/moritz_agent/`, `frontend/`, `config/`,
  `assets/`, `deploy/`, `scripts/`, `requirements/`, `docs/`, sowie die Wurzeldateien
  `moritz-agent`, `moritz-install.sh`, `moritz-update.sh`, `install.sh`, `update.sh`,
  `pyproject.toml`, `README.md`, `CLAUDE.md`, `THIRD_PARTY_NOTICES.md`.
- **KoboldCpp-Upstream-Dateien nicht ändern** (`koboldcpp.py`, `kcpp_*`, `ggml/`, `src/`,
  `otherarch/`, `tools/`, `vendor/`, `Makefile`, `CMakeLists.txt`, `.github/workflows/kcpp-*`,
  `tests/test_*.py`, …). KoboldCpp wird nur als Child-Prozess über HTTP genutzt (ADR-003).
  Unvermeidbare Patches: minimal, Kommentar `# moritz-agent:`, im Plan dokumentieren.
- `LICENSE.md`, `MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md` und Copyright-Header nie entfernen.
- **Lizenzen (ADR-023, `LICENSING.md`):** eigener Code = MSOL 1.1. Jede neue eigene
  Quelltext-/Skript-/Config-Datei beginnt mit `SPDX-License-Identifier: LicenseRef-MSOL-1.1`
  (nach einer Shebang-Zeile). Fremdcode behält seine Lizenz. Scribbles/Logo: alle Rechte vorbehalten.
- `third_party/` (SearXNG, pjproject) und `assets/models/` sind **mitgelieferte
  Fremdkomponenten**: nicht verändern, nur nach `third_party/VENDORED.md` aktualisieren
  (`git add -f third_party`). `third_party/pjproject/CLAUDE.md` gehört zu PJSIP, nicht zu uns.
- Neue Python-Abhängigkeit: in `requirements/<gruppe>.in` eintragen und Lock mit Hashes neu
  erzeugen (ADR-019). Python-Pakete kommen von PyPI und werden **nicht** ins Repo gelegt.
- Branding: nutzer-sichtbar immer „moritz-agent“/„m-agent“ mit Logo aus `assets/branding/`.
  **Scribbles** (`assets/branding/scribbles/`) ist das Maskottchen und wird überall verwendet,
  wo die Oberfläche eine Figur zeigt (Leer-, Lade-, Fehlerzustände, Login, Über-Seite, Doku).
  Regeln: [`assets/branding/README.md`](assets/branding/README.md). Assets nur über
  `scripts/build_branding.py` neu erzeugen. KoboldCpp-Oberflächen bleiben entfernt (ADR-002).

## Sprache

- Code, Bezeichner, Code-Kommentare, Commit-Nachrichten: **Englisch**.
- Plan-Dokumente, README, UI-Texte, Ansagen, Systemprompts: **Deutsch** (mit Umlauten).

## Secrets – harte Regeln

- Zugangsdaten nur in `passwords.txt` (INI, gelesen mit `configparser(interpolation=None)`),
  nie im Code, in Tests (außer offensichtlichen Platzhaltern), Logs, LLM-Kontext oder
  API-Antworten. Werte im Code als `moritz_agent.config.secrets.Secret` halten.
- `passwords.txt` niemals neu serialisieren – fehlende Felder nur zeilenbasiert anhängen.
- Shell-Skripte: kein `set -x`, Secrets nie als Argumente oder Env-Variablen, nur via stdin.

## Befehle

```bash
pip install -e ".[dev]"                       # Entwicklungsumgebung
ruff check moritz_agent tests/moritz_agent scripts
ruff format --check moritz_agent tests/moritz_agent scripts
pytest                                        # testpaths = tests/moritz_agent
shellcheck moritz-agent install.sh update.sh moritz-install.sh moritz-update.sh
python -m moritz_agent --version
```

## Konventionen

- Python ≥ 3.11, Typannotationen überall, `from __future__ import annotations`.
- Async (asyncio) im Main-Prozess; blockierende Arbeit (STT/TTS) in Threads/Executor.
- Neue Konfigurationsschlüssel immer in `config/moritz-agent.example.toml` dokumentieren.
- Neue Abhängigkeiten: in `pyproject.toml` + Lock-Datei, Lizenz in `THIRD_PARTY_NOTICES.md`.
- Jede Änderung, die vom Plan abweicht, aktualisiert den Plan im selben PR.
- PR-Titel `P1-xx: …`, PR-Vorlage ausfüllen, Base-Branch `agent`.

# Mitgelieferte Programmbestandteile (`third_party/`)

moritz-agent läuft als **ein eigenständiges Programm**. Alle Bestandteile, die zum Programm
gehören, liegen deshalb im Repository – nichts wird zur Installationszeit geklont (ADR-021).
Die Inhalte sind **unverändert** aus den Originalquellen übernommen. Eigene Änderungen nur als
dokumentierter Patch (Abschnitt „Patches“).

| Verzeichnis | Komponente | Version | Quelle | Lizenz |
| --- | --- | --- | --- | --- |
| `searxng/` | SearXNG (Metasuche), **fertig gebaut**: Frontend-Assets in `searx/static`, Daten in `searx/data` | Commit `8252c0bf6d5d97e833868099272eed0bb75828b2` (16.10.2026) | https://github.com/searxng/searxng | AGPL-3.0 (`searxng/LICENSE`) |
| `pjproject/` | PJSIP / PJSUA2 (Quellcode, wird vom Installer kompiliert) | 2.17, Commit `5a457451fa2712ba18e12b01738e8ff3af2b26fd` | https://github.com/pjsip/pjproject | GPL-2.0-or-later (`pjproject/COPYING`), Unterkomponenten in `pjproject/third_party/` mit eigenen Lizenzen |
| `cosyvoice/` | CosyVoice – Python-Paket `cosyvoice` (nur Quellcode + LICENSE; Nikitas Stimme, läuft im TTS-Worker, ADR-027) | Commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` (26.05.2026) | https://github.com/FunAudioLLM/CosyVoice | Apache-2.0 (`cosyvoice/LICENSE`) |
| `Matcha-TTS/` | Matcha-TTS – Python-Paket `matcha` (Abhängigkeit von CosyVoice; nur Quellcode + LICENSE) | Commit `dd9105b34bf2be2230f4aa1e4769fb586a3c824e` (27.02.2024) | https://github.com/shivammehta25/Matcha-TTS | MIT (`Matcha-TTS/LICENSE`) |
| `../assets/models/vad/silero_vad.onnx` | Silero VAD | v6.2.3, SHA-256 `1a153a22…88e3` | https://github.com/snakers4/silero-vad | MIT (`LICENSE.silero-vad`) |

Hinweis: `pjproject/` enthält eine eigene `CLAUDE.md` des PJSIP-Projekts. Sie gilt nur für
Arbeiten am PJSIP-Quellcode selbst, nicht für moritz-agent.

## SearXNG direkt aus dem Repo starten (so macht es der Supervisor)

```bash
python3 -m venv runtime/searxng-venv
runtime/searxng-venv/bin/pip install --require-hashes -r requirements/searxng.lock
cd third_party/searxng
SEARXNG_SETTINGS_PATH=../../config/searxng/settings.yml SEARXNG_SECRET=<zufällig> \
  ../../runtime/searxng-venv/bin/granian --interface wsgi --host 127.0.0.1 --port <dyn> searx.webapp:app
```

Geprüft am 16.10.2026: `/healthz` → `OK`, Startseite HTTP 200, `/search?format=json` antwortet.

## Bewusst nicht im Repository

| Was | Warum | Bezug |
| --- | --- | --- |
| Python-Pakete | Moritz: „Requirements sind egal“ | PyPI, exakt gepinnt mit Hashes in `requirements/*.lock` (CosyVoice-Umgebung: `requirements/tts.txt`, torch vom PyTorch-CPU-Index) |
| CUDA-Build-Toolchain für KoboldCpp | Abhängigkeit, nicht Programmbestandteil (≈ 1,4 GB) | `./koboldcpp.sh rebuild` (Conda) |
| Modelle: LLM (13,8 GB), Whisper small (484 MB), Piper-Stimme (63 MB), CosyVoice3-Hessisch (4,4 GB) | Hugging-Face-Downloads (Moritz: „HF-Modelle natürlich nicht“) | Installer, `config/versions.lock` |
| NVIDIA-Treiber, Ubuntu-Systempakete | Systemebene | `docs/plan/06-infrastruktur.md` |

## Aktualisieren

1. Neue Version in ein temporäres Verzeichnis klonen, `.git` entfernen, Verzeichnis hier ersetzen
   (keine `__pycache__`-Ordner mit einchecken).
2. Commit/Version in dieser Datei und in `config/versions.lock` eintragen.
3. Bei SearXNG: `requirements/searxng.lock` neu erzeugen:
   `uv pip compile --universal --python-version 3.13 --generate-hashes --no-header -o requirements/searxng.lock requirements/searxng.in`
4. `git add -f third_party` (einige Dateien fallen sonst unter Regeln der Wurzel-`.gitignore`,
   z. B. `build*/`, `*.bin`, `bin/`).
5. Start aus dem Repo testen (siehe oben), dann PR.

## Patches

Keine.

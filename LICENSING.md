# Lizenzen in diesem Repository

moritz-agent besteht aus eigenem Code von Moritzsoft und aus Komponenten anderer Projekte.
**Jeder Teil behält seine eigene Lizenz.** Diese Datei sagt, was wofür gilt (ADR-023).

| Bereich | Lizenz | Lizenztext |
| --- | --- | --- |
| **Eigener Code und eigene Doku von moritz-agent** (siehe Liste unten) | **Moritzsoft Open License (MSOL) 1.1** – Public Release | [LICENSE-MSOL.md](LICENSE-MSOL.md) |
| **Scribbles** und das **m-agent-Logo** (`assets/branding/`, `niko.ico`, `nikogreen.ico`) | **© LayerNX / Moritz Eckhard Nickel – alle Rechte vorbehalten**. Nicht MSOL, nicht AGPL. Nutzung nur innerhalb von moritz-agent erlaubt | – |
| KoboldCpp, KoboldAI-Reste und alle übrigen Upstream-Dateien im Wurzelverzeichnis | GNU AGPL v3.0, sofern die Datei nichts anderes sagt | [LICENSE.md](LICENSE.md) |
| GGML, llama.cpp, stable-diffusion.cpp | MIT | [MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md](MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md) |
| `third_party/searxng/` | AGPL-3.0 | `third_party/searxng/LICENSE` |
| `third_party/pjproject/` | GPL-2.0-or-later (Unterkomponenten eigene Lizenzen) | `third_party/pjproject/COPYING` |
| `third_party/cosyvoice/` (CosyVoice) | Apache-2.0 | `third_party/cosyvoice/LICENSE` |
| `third_party/Matcha-TTS/` | MIT | `third_party/Matcha-TTS/LICENSE` |
| `assets/models/vad/` (Silero VAD) | MIT | `assets/models/vad/LICENSE.silero-vad` |
| `docs/upstream/KOBOLDCPP_README.md` | AGPL-3.0 (Text von KoboldCpp) | [LICENSE.md](LICENSE.md) |
| Python-Pakete, Modelle (werden installiert, nicht mitgeliefert) | je Paket/Modell | [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

## Eigener Code unter MSOL 1.1

Alle von moritz-agent neu erstellten Dateien, insbesondere:

- `moritz_agent/`, `tests/moritz_agent/`, `scripts/`, `frontend/`, `deploy/`, `requirements/`
- `config/` (Vorlagen und Einstellungen), `assets/audio/`
- `docs/plan/`, `docs/asterisk-konfiguration.md`, `third_party/VENDORED.md`
- `moritz-agent`, `moritz-install.sh`, `moritz-update.sh`, `install.sh`, `update.sh`
- `pyproject.toml`, `README.md`, `CLAUDE.md`, `LICENSING.md`, `THIRD_PARTY_NOTICES.md`,
  `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md`, `.github/workflows/moritz-ci.yaml`

Quelltext-Dateien tragen die Kennung `SPDX-License-Identifier: LicenseRef-MSOL-1.1`.
moritz-agent ist ein **Public Release** im Sinne von MSOL §1/§2.

## Zusammenspiel der Lizenzen

- MSOL 1.1 ist eine freizügige Lizenz (Nutzen, Ändern, Weitergeben, Unterlizenzieren erlaubt,
  ohne Namensnennung). Damit darf der MSOL-Code mit dem AGPL- bzw. GPL-Code kombiniert werden.
- Wer moritz-agent **als Ganzes** weitergibt oder im Netz für andere bereitstellt, muss für die
  enthaltenen AGPL-/GPL-Teile deren Bedingungen erfüllen (Quellcode anbieten, Lizenz- und
  Copyright-Hinweise dieser Teile behalten). Der Verzicht auf Namensnennung in MSOL §4 gilt
  nur für den MSOL-Code, nicht für KoboldCpp, SearXNG, PJSIP usw.
- Scribbles und das Logo sind von MSOL §5.1 ausgenommen: Sie sind nicht unter MSOL lizenziert.
  Wer moritz-agent abwandelt und selbst weitergibt, ersetzt Logo und Maskottchen durch eigene
  (vgl. MSOL §5.3). `scripts/build_branding.py` zeigt, welche Dateien betroffen sind.

> Hinweis: Diese Übersicht ist keine Rechtsberatung.

# Third-Party Notices

moritz-agent's own code is licensed under the Moritzsoft Open License (MSOL) 1.1
([LICENSE-MSOL.md](LICENSE-MSOL.md)); see [LICENSING.md](LICENSING.md) for the per-path overview.
moritz-agent is based on KoboldCpp and combines several open-source components. The
original copyright notices and license texts of all components are retained. Where a
file carries its own license header, that header takes precedence.

The KoboldCpp parts are distributed under the **GNU Affero General Public License v3.0**
(see [LICENSE.md](LICENSE.md)). If you make a modified version available to users over a
network, AGPL-3.0 §13 requires offering them the corresponding source code.

## Included in this repository (inherited from KoboldCpp)

| Component | Location | License |
| --- | --- | --- |
| KoboldCpp (Concedo / LostRuins) | `koboldcpp.py`, `kcpp_*`, `kcpp_src/`, `otherarch/` (unless noted) | AGPL-3.0 |
| KoboldAI Lite | formerly `embd_res/klite.embd` – **removed** by moritz-agent (ADR-002) | AGPL-3.0 |
| GGML, llama.cpp | `ggml/`, `src/`, `common/`, `include/`, `tools/`, `gguf-py/`, `convert_*.py` | MIT ([MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md](MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md)) |
| stable-diffusion.cpp | `otherarch/sdcpp/` | MIT |
| whisper.cpp | `otherarch/whispercpp/` | MIT |
| TTS.cpp | `otherarch/ttscpp/` | MIT |
| Qwen3-TTS.cpp | `otherarch/qwen3tts/` | MIT |
| acestep.cpp | `otherarch/acestep/` | MIT |
| cpp-httplib | `vendor/cpp-httplib/` | MIT |
| nlohmann/json | `vendor/nlohmann/` | MIT |
| miniaudio | `vendor/miniaudio/` | Public Domain / MIT-0 (dual) |
| stb_image | `vendor/stb/` | Public Domain / MIT (dual) |
| subprocess.h (sheredom) | `vendor/sheredom/` | Unlicense |
| hash helpers (sha1, sha256, xxhash) | `vendor/hash/` | see file headers |

## Vendored in this repository by moritz-agent (`third_party/`, `assets/`)

Unmodified copies; provenance and versions in [third_party/VENDORED.md](third_party/VENDORED.md).

| Component | Location | License |
| --- | --- | --- |
| SearXNG (commit 8252c0bf) | `third_party/searxng/` | AGPL-3.0 |
| pjproject / PJSIP 2.17 | `third_party/pjproject/` | GPL-2.0-or-later; bundled sub-components in `third_party/pjproject/third_party/` keep their own licenses |
| Python packages (installed from PyPI, pinned in `requirements/*.lock`) | not vendored | per package (FastAPI, Starlette, Pydantic: MIT; Uvicorn, HTTPX, Granian: BSD-3-Clause; faster-whisper, CTranslate2, ONNX Runtime: MIT; NumPy (BSD-3-Clause), PyAV (BSD-3-Clause), Piper (GPL-3.0), python-soxr (LGPL-2.1-or-later), boto3 (Apache-2.0), Flask (BSD-3-Clause), lxml (BSD-3-Clause), …) |
| Silero VAD v6.2.3 | `assets/models/vad/` | MIT |
| m-agent logo (M + Scribbles) | `assets/branding/`, `niko.ico`, `nikogreen.ico` | contains the Scribbles artwork, see below |
| **Scribbles** – mascot of LayerNX and moritz-agent | `assets/branding/scribbles/` (original drawing + traced SVG/PNG) | © LayerNX / Moritz Eckhard Nickel. **All rights reserved.** Not covered by MSOL or AGPL |

## Downloaded at setup time (not stored in this repository)

| Component | Purpose | License |
| --- | --- | --- |
| Qwen3-30B-A3B-Instruct-2507 GGUF (unsloth) | LLM | Apache-2.0 |
| OpenAI Whisper small (faster-whisper conversion by Systran) | speech-to-text | MIT |
| Thorsten-Voice „Hessisch“ Piper model (`Thorsten-Voice/Hessisch`, `…_Piper_high-Oct2023.onnx`) | Nikita's voice | CC0-1.0 (Thorsten-Voice) – verify per model card |
| espeak-ng (system package, optional) | last-resort voice and test caller | GPL-3.0-or-later (used as a separate program) |

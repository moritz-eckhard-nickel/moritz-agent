# Third-Party Notices

moritz-agent is based on KoboldCpp and combines several open-source components. The
original copyright notices and license texts of all components are retained. Where a
file carries its own license header, that header takes precedence.

The work as a whole is distributed under the **GNU Affero General Public License v3.0**
(see [LICENSE.md](LICENSE.md)). If you make a modified version available to users over a
network, AGPL-3.0 §13 requires offering them the corresponding source code.

## Included in this repository (inherited from KoboldCpp)

| Component | Location | License |
| --- | --- | --- |
| KoboldCpp (Concedo / LostRuins) | `koboldcpp.py`, `kcpp_*`, `kcpp_src/`, `otherarch/` (unless noted) | AGPL-3.0 |
| KoboldAI Lite | embedded UI (`embd_res/klite.embd`) | AGPL-3.0 |
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

## Installed at setup time (planned for Part 1, not stored in this repository)

Versions are pinned in `config/versions.lock`. This table is updated **before** a
component is bundled or installed.

| Component | Purpose | License |
| --- | --- | --- |
| SearXNG | internal metasearch worker | AGPL-3.0 |
| pjproject (PJSIP / PJSUA2) | SIP stack and RTP media | GPL-2.0-or-later |
| faster-whisper, CTranslate2 | speech-to-text | MIT |
| OpenAI Whisper model weights | speech-to-text model | MIT |
| Piper (OHF-Voice/piper1-gpl) | text-to-speech | GPL-3.0 |
| Piper voice `de_DE-thorsten-*` (candidate) | German voice | CC0 (dataset) – verify per voice model card |
| Silero VAD | voice activity detection | MIT |
| ONNX Runtime | model runtime for VAD/TTS | MIT |
| FastAPI, Starlette, Pydantic | backend | MIT |
| Uvicorn, HTTPX, Granian | ASGI server, HTTP client, WSGI server | BSD-3-Clause |
| python-soxr / libsoxr | resampling | LGPL-2.1-or-later |
| LLM weights (selected in P1-02) | inference model | per model card (e.g. Apache-2.0 for Qwen3) |

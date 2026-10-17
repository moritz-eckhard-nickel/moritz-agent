# requirements/

Python-Abhängigkeiten von moritz-agent, exakt gepinnt mit SHA-256 (ADR-019). Die Pakete
kommen bei der Installation von PyPI (`pip install --require-hashes -r <gruppe>.lock`);
sie liegen bewusst nicht im Repository.

| Gruppe | Inhalt |
| --- | --- |
| `core` | Backend, Agent, Inference-Client |
| `phone` | Audio: faster-whisper, Piper, ONNX Runtime, soxr (PJSUA2 wird aus `third_party/pjproject` gebaut) |
| `tts` | Umgebung `runtime/venv-tts` für Nikitas Stimme (CosyVoice3-Hessisch): exakte Versionen in `tts.txt`, **ohne** torch – das kommt per `scripts/setup-tts-venv.sh` vom PyTorch-CPU-Index (ADR-027) |
| `searxng` | Abhängigkeiten des mitgelieferten SearXNG (`third_party/searxng`) inkl. granian |

Neu erzeugen: `uv pip compile --universal --python-version 3.13 --generate-hashes --no-header -o <g>.lock <g>.in`

Das Upstream-`requirements.txt` im Wurzelverzeichnis gehört zu KoboldCpp und bleibt unverändert.

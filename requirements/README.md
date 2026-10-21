# requirements/

Python-Abhängigkeiten von moritz-agent, exakt gepinnt mit SHA-256 (ADR-019). Die Pakete
kommen bei der Installation von PyPI (`pip install --require-hashes -r <gruppe>.lock`);
sie liegen bewusst nicht im Repository.

| Gruppe | Inhalt |
| --- | --- |
| `core` | Backend, Agent, Inference-Client |
| `phone` | Audio: faster-whisper, Piper, ONNX Runtime, soxr (PJSUA2 wird aus `third_party/pjproject` gebaut) |
| `discord` | Discord-Bot: discord.py mit Sprache (PyNaCl, davey) – nur wenn Discord eingerichtet ist |
| `searxng` | Abhängigkeiten des mitgelieferten SearXNG (`third_party/searxng`) inkl. granian |

Neu erzeugen: `uv pip compile --universal --python-version 3.12 --generate-hashes --no-header -o <g>.lock <g>.in`

Das Upstream-`requirements.txt` im Wurzelverzeichnis gehört zu KoboldCpp und bleibt unverändert.

## Optional: Sprachempfang auf Discord

`discord-ext-voice-recv` (Audio aus dem Sprachkanal empfangen) steht **bewusst nicht** in `discord.in`/`discord.lock`:
Discord verschlüsselt Sprache Ende-zu-Ende (DAVE), und ob eine Fassung das entschlüsselt, klärt erst der Spike
[P1-32](../docs/abnahme/p1-32-discord-spike.md). Wer es ausprobiert, installiert es von Hand in die Umgebung; ohne
die Erweiterung läuft der Sprachkanal im Modus „nur sprechen“ (Plan 14 §9.5, ADR-036).

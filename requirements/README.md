# requirements/

Python-Abhängigkeiten von moritz-agent, exakt gepinnt mit SHA-256 (ADR-019). Die Pakete
kommen bei der Installation von PyPI (`pip install --require-hashes -r <gruppe>.lock`);
sie liegen bewusst nicht im Repository.

| Gruppe | Inhalt |
| --- | --- |
| `core` | Backend, Agent, Inference-Client, pypdf (PDFs im Chat) |
| `phone` | Audio: faster-whisper, Piper, ONNX Runtime, soxr (PJSUA2 wird aus `third_party/pjproject` gebaut) |
| `discord` | Discord-Bot: discord.py mit Sprache (PyNaCl, davey) – nur wenn Discord eingerichtet ist |
| `searxng` | Abhängigkeiten des mitgelieferten SearXNG (`third_party/searxng`) inkl. granian |

Neu erzeugen: `uv pip compile --universal --python-version 3.12 --generate-hashes --no-header -o <g>.lock <g>.in`

Das Upstream-`requirements.txt` im Wurzelverzeichnis gehört zu KoboldCpp und bleibt unverändert.

## Optional: Sprachempfang auf Discord

`discord-ext-voice-recv` (Audio aus dem Sprachkanal empfangen) steht **bewusst nicht** in `discord.in`/`discord.lock`:
Discord verschlüsselt Sprache Ende-zu-Ende (DAVE). Entschlüsseln kann das nur der Fork
`zacker150/discord-ext-voice-recv`, und der ersetzt discord.py durch einen eigenen Fork (2.8.0a von GitHub).
Deshalb bekommt er eine **eigene Umgebung** `runtime/discord-venv`, die nur der Discord-Worker benutzt
(`scripts/setup-discord-voice.sh`, von `./test-3.sh setup` und dem Installer angelegt, P1-32, ADR-036):

- Die drei Lock-Dateien werden dort wie gewohnt mit Prüfsummen installiert.
- Nur die zwei GitHub-Pakete sind per Commit statt per Prüfsumme gepinnt, weil pip VCS-Quellen nicht hashen
  kann (Ausnahme von ADR-019).
- Fehlt die Umgebung, läuft der Sprachkanal im Modus „nur sprechen“ (Plan 14 §9.5).

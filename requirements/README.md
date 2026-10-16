# requirements/

Gepinnte Python-Abhängigkeiten mit Hashes (ADR-019), installiert vom Installer mit
`pip install --require-hashes`:

- `core.lock` – Backend, Agent, Inference-Client (entsteht mit P1-05/P1-14)
- `phone.lock` – Audio/STT/TTS (entsteht mit P1-10); PJSUA2 wird aus Quellcode gebaut (ADR-005)

Erzeugung z. B. mit `uv pip compile pyproject.toml --extra <gruppe> --generate-hashes`.
Das Upstream-`requirements.txt` im Wurzelverzeichnis gehört zu KoboldCpp und bleibt unverändert.

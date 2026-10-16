# frontend/

Eigene Weboberfläche von moritz-agent (ADR-010). Die KoboldCpp-/KoboldAI-Lite-Oberflächen
sind für Nutzer nicht sichtbar (ADR-002).

- `status/` – Part 1: Statusseite (Registrierung, Anrufzustand, STT/TTS, LLM, Suche, letzte
  Fehler; **keine** Passwörter). Statisches HTML + Vanilla-JS, kein Build-Schritt. Ticket P1-14.
- Part 2: Chat, Streaming, Verlauf, Agent-Timeline, Modellverwaltung, Einstellungen –
  responsiv, damit dieselbe UI später in der Android-WebView läuft.

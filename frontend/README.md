# frontend/

Eigene Weboberfläche von moritz-agent (ADR-010, ADR-040). Die KoboldCpp-/KoboldAI-Lite-Oberflächen
sind für Nutzer nicht sichtbar (ADR-002).

- `app/` – die WebUI (Part 2, [docs/plan/15](../docs/plan/15-part2-umsetzung.md)): eine Seite mit
  Hash-Routing (`#/chat`, `#/status`, …), Vanilla-JS als ES-Module, **kein Build-Schritt**, kein CDN.
  Dunkel im Stil von layernx.de; alle Farben sind CSS-Variablen in `app.css`.
  - `index.html` – Gerüst, Login, Fehlerseite
  - `app.css` – Design
  - `js/app.js` – Start, Anmeldung, Navigation
  - `js/api.js`, `js/dom.js` – Helfer (Text nur als `textContent`, nie als HTML)
  - `js/views/*.js` – eine Datei je Ansicht
- Ausgeliefert unter `/` und `/app/…` mit strenger Content-Security-Policy (`default-src 'self'`):
  kein Inline-Script, kein Inline-Style im HTML, keine fremden Adressen.
- Läuft auf PC, Tablet und Handy und später unverändert in der Android-WebView (1.1+).

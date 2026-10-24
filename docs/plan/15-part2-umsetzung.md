# 15 – Part 2 Umsetzung: WebUI (Version 0.2)

Stand: 24.10.2026 · Voraussetzung: Part 1 abgenommen ([04](04-part1-umsetzung.md), Abnahme über
`./test-3.sh run`). Ziel aus [05](05-roadmap.md): **Chat mit Streaming, Verlauf, Agent-Timeline,
Anrufstatus live, Modellverwaltung, Einstellungen – responsiv** (UI-02, INF-06, INF-07, PRD-03).

Grundregel wie in jedem Part: **Telefon und Discord aus Part 1 bleiben jederzeit voll nutzbar.** Jedes
Ticket endet mit grünem `pytest` und einem Regressionsanruf in `test-4.sh run`.

## 1. Was es schon gibt (Part 1)

| Baustein | Wo | Für Part 2 |
| --- | --- | --- |
| FastAPI-Backend, Login (scrypt, Cookie), HTTPS, Port 3501 | `moritz_agent/api/` | bleibt, neue Router daneben |
| Statusseite (Vanilla-JS, Polling 2 s) | `frontend/status/` | wird ein Bereich der neuen UI |
| `/api/chat` (Text-Testpfad, ganze Antwort) | `api/routes_chat.py` | bekommt eine Streaming-Variante |
| Ein Kern für alle Kanäle (`ChatService`, `Turn`, Kurzzeitgedächtnis 30 Wechsel) | `core/chat.py` | Web wird ein weiterer Kanal (`place="web"`) |
| Agent mit Werkzeugen, Quellen, Schritten (`AgentResult.tools`, `.sources`, `.steps`) | `agent/loop.py` | Grundlage der Agent-Timeline |
| KoboldCpp als Kindprozess, Argumente pro Neustart neu (`argv_factory`) | `inference/process.py`, Supervisor | Grundlage für Modellwechsel |
| Konfiguration mit Neuladen und „braucht Neustart“ | `config/reload.py` | Grundlage der Einstellungsseite |
| Branding, Scribbles für Leer-/Lade-/Fehlerzustände | `assets/branding/` | Pflicht in jeder Ansicht |

## 2. Entscheidung Frontend (ADR-040, Vorschlag)

ADR-010 hat das Framework für Part 2 offen gelassen. Vorschlag:

- **Kein Build-Schritt, keine Node-Laufzeit:** Vanilla-JS als ES-Module, eine Seite (`frontend/app/`) mit
  Hash-Routing (`#/chat`, `#/status`, `#/modelle`, `#/einstellungen`). Läuft so auch in der Android-WebView (1.1+).
- **Streaming über SSE** (`EventSource` bzw. `fetch` mit `ReadableStream` für POST): einfacher als
  WebSocket, geht durch jeden Proxy, FastAPI kann es ohne Zusatzpaket.
- **Kein CDN:** alles liegt im Repo, Schriften ebenfalls (LAN-Betrieb, Datenschutz).
- Alternativen: Preact/htm ohne Build (vendored, ≈ 10 KB) – nehmen wir, falls die Oberfläche zu groß für
  Vanilla-JS wird; Svelte/React mit Build – abgelehnt, weil Node auf dem Server oder im Release nötig wäre.

## 3. Tickets

Reihenfolge: P2-01 → P2-02 → (P2-03, P2-04 parallel) → P2-05 → P2-06 → P2-07 → P2-08 → P2-09 → P2-10.

### P2-01 – App-Gerüst und Navigation

- `frontend/app/` (index.html, `app.js`, `style.css`, Module je Ansicht), ausgeliefert unter `/`; die
  Statusseite zieht als Ansicht `#/status` ein, `/status` leitet weiter.
- Layout: Seitenleiste (Desktop) bzw. untere Leiste (Handy), helles und dunkles Design, Logo und Scribbles.
- Login-Ansicht mit Scribbles; Sitzung abgelaufen → zurück zum Login, ohne Datenverlust im Eingabefeld.
- Tests: Auslieferung, Content-Security-Policy (`default-src 'self'`), kein externer Request.
- Anforderungen: UI-02, API-02, API-05.

### P2-02 – Chat mit Streaming (SSE)

- `POST /api/chat/stream` → `text/event-stream` mit Ereignissen `token`, `tool_start`, `tool_end`,
  `source`, `done`, `error`. Gleicher Kern wie `/api/chat` (`ChatService`), Profil `web` (wie Discord-Chat:
  Markdown, längere Antworten).
- Abbrechen-Knopf → `POST /api/chat/cancel` (nutzt die Abbruchlogik der Queue, Telefon behält Vorrang).
- Markdown-Darstellung ohne `innerHTML` aus Modelltext (eigener kleiner Renderer, nur sichere Elemente).
- Sofortauskünfte (Wetter, Uhrzeit …) kommen sofort als ein `done`, mit Karten wie auf Discord.
- Tests: Ereignisfolge, Abbruch, Telefon unterbricht Web-Chat (Priorität), XSS-Fälle im Renderer.
- Anforderungen: UI-02, AGENT-04, AGENT-08.

### P2-03 – Verlauf

- Gespräche der WebUI in SQLite (`conversations`, `messages` – Vorgriff auf Part 3, nur Web-Kanal),
  Liste links, umbenennen, löschen, „Neues Gespräch“ (= Kurzzeitgedächtnis leeren).
- Aufbewahrung wie Transkripte (F-03: 24 h) **oder** länger – offene Frage F-41.
- Tests: Migration, Löschen löscht wirklich, Verlauf geht nach Neustart nicht verloren.
- Anforderungen: STORE-01, STORE-02.

### P2-04 – Agent-Timeline

- Unter jeder Antwort aufklappbar: „✓ Websuche ‚Kanzler Deutschland‘ (3 Quellen, 1,2 s)“, „✓ Wetter
  Weilburg“, Dauer, Tokens/s, verworfene Verlaufs-Wechsel (`dropped_turns`).
- Daten kommen aus den SSE-Ereignissen von P2-02; nichts Geheimes (Werkzeug-Argumente gefiltert).
- Anforderungen: UI-02, LOG-02 (Redaktion).

### P2-05 – Anrufstatus und Discord live

- `GET /api/events` (SSE) ersetzt das Polling der Statusseite: Anruf klingelt/aktiv/beendet, Sprachkanal,
  Komponenten (KoboldCpp, SearXNG, Discord), Warnungen.
- Kein Gesprächsinhalt in der Live-Ansicht, nur Zustand und Dauer.
- Anforderungen: UI-01, DISCORD-30.

### P2-06 – Modellverwaltung

- `GET /api/models`: GGUF-Dateien unter `models/llm/` (= `/home/models`) mit Größe, Quantisierung,
  Kontext aus dem GGUF-Kopf; das geladene Modell markiert.
- `POST /api/models/load`: **erst entladen, dann laden** (INF-06) – KoboldCpp stoppen, Argumente neu,
  starten; Fortschritt per SSE. Während des Wechsels sagt das Telefon die vorhandene Ansage
  „Sprachmodell lädt“, Sofortauskünfte gehen weiter.
- Einstellungen je Modell (Presets): Kontext, `--moecpu`, GPU-Schichten, Flash-Attention; „Messen“ startet
  `scripts/bench_llm.py --tune` im Hintergrund.
- Discord: `/admin modell laden|entladen|status` (14 §7, Part 2).
- Tests: Wechsel mit dem Fake-KoboldCpp, VRAM-Prüfung, Telefon während des Wechsels.
- Anforderungen: INF-06, PRD-03, ADR-016.

### P2-07 – Einstellungen

- `GET/PUT /api/settings`: nur nicht geheime Werte aus `config/moritz-agent.toml`, Schema aus den
  pydantic-Modellen; Speichern zeilenbasiert (Kommentare bleiben), danach Neuladen; „braucht Neustart“
  wird angezeigt.
- **Zugangsdaten nie** in der UI und nie in einer API-Antwort; nur „gesetzt/nicht gesetzt“.
- Discord: `/einstellungen` bekommt dieselben Felder für den Owner.
- Anforderungen: CFG-05, CFG-08, UI-02, Sicherheitsregeln (CLAUDE.md).

### P2-08 – OpenAI-kompatible API

- `/v1/chat/completions`, `/v1/models` über moritz-agent mit API-Key (in `passwords.txt`), weitergereicht an
  KoboldCpp über die Queue (Telefon hat Vorrang).
- Anforderungen: INF-07.

### P2-09 – Sofortauskünfte in der WebUI

- Wetterkarte und Vorhersage-Diagramm, Warnungen, Notizen/Einkaufsliste, Liste nicht erkannter Fragen,
  Über-Seite mit Quellen und Lizenzen (13, 05 „Sofortauskünfte in späteren Parts“).

### P2-10 – `test-4.sh` und Abnahme

- `test-4.sh setup|run` verwendet `test-3.sh` wieder (CLAUDE.md, Testskripte) und prüft zusätzlich:
  App ausgeliefert, Login, Streaming-Chat, Modellwechsel mit Fake und echt, Einstellungen speichern,
  Chat und Telefon gleichzeitig.
- Abnahme: „Chat und Telefon parallel benutzbar, Modellwechsel entlädt zuerst“ (05).

## 4. Offene Fragen an Moritz

| ID | Frage | Vorschlag |
| --- | --- | --- |
| F-41 | Wie lange sollen Web-Gespräche gespeichert bleiben? | 30 Tage, einzeln löschbar |
| F-42 | Soll die WebUI auch von außen (über VPN) erreichbar sein oder nur im LAN? | nur LAN wie Part 1 |
| F-43 | Mehrere Benutzer in der WebUI oder nur Moritz? | nur Owner in Part 2, Rollen ab Part 3 |
| F-44 | Darf die WebUI das Modell wechseln, während ein Anruf läuft? | nein, Knopf gesperrt mit Hinweis |

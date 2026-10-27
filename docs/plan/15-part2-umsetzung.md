# 15 – Part 2 Umsetzung: WebUI (Version 0.2)

Stand: 27.10.2026 · Voraussetzung: Part 1 abgenommen ([04](04-part1-umsetzung.md), Abnahme über
`./test-3.sh run`). Ziel aus [05](05-roadmap.md): **Chat mit Streaming, Verlauf, Agent-Timeline,
Anrufstatus live, Modellseite, Einstellungen – auf PC, Handy und allem dazwischen** (UI-02, INF-07, PRD-03).

Grundregel wie in jedem Part: **Telefon und Discord aus Part 1 bleiben jederzeit voll nutzbar.** Jedes
Ticket endet mit grünem `pytest` und einem Regressionsanruf in `test-4.sh run`.

## 1. Moritz' Vorgaben (27.10.2026)

| Thema | Entscheidung |
| --- | --- |
| Erreichbar | nur im LAN, über die IP: **`https://192.168.1.187:3501`** (Sophie-1) |
| Benutzer | nur Moritz (Owner), keine Rollen in Part 2 |
| Verlauf | **Web, Telefon und Discord** in einer Liste, je mit Symbol; alles **15 Tage**, danach gelöscht |
| Für immer behalten | Speichern-Knopf an jedem Gespräch → wird nie automatisch gelöscht |
| Verlauf-Funktionen | durchsuchen, umbenennen, löschen, als Markdown exportieren |
| Kanäle | jedes Gespräch für sich – Anton weiß am Telefon nicht, was im Web stand (das kommt mit Part 8) |
| Modell | **kein Modellwechsel**, es gibt nur Qwen3-30B-A3B; Modellseite = Status, Neustart, Kontext, Messen |
| Kontext | **mindestens 50k Tokens** (Tempo ist zweitrangig) |
| Dateien | Textdateien und PDFs in den Chat ziehen, Anton liest sie |
| Sprechen im Browser | nein (kein Mikrofon, kein Vorlesen) |
| Login | 10 Tage angemeldet bleiben, auch über Neustarts hinweg |
| Einstellungen | **alles** in der WebUI änderbar, auch Zugangsdaten (nur schreiben, nie anzeigen) |
| Aussehen | dunkel, im Stil von **layernx.de** (Screenshot von Moritz, 27.10.2026) |
| Geräte | PC, Handy, Tablet – alles gleich gut |
| **Später: Agenten in der Sandbox** | Anton soll irgendwann wie Claude Code selbstständig in der Sandbox arbeiten (Part 3/4). Part 2 legt dafür den Grund und baut nichts, was das verbaut (§5) |

## 2. Was es schon gibt (Part 1)

| Baustein | Wo | Für Part 2 |
| --- | --- | --- |
| FastAPI-Backend, Login (scrypt, Cookie), HTTPS, Port 3501 | `moritz_agent/api/` | bleibt, neue Router daneben |
| Statusseite (Vanilla-JS, Polling 2 s) | `frontend/status/` | wird ein Bereich der neuen UI |
| `/api/chat` (Text-Testpfad, ganze Antwort) | `api/routes_chat.py` | bekommt eine Streaming-Variante |
| Ein Kern für alle Kanäle (`ChatService`, `Turn`, Kurzzeitgedächtnis 30 Wechsel) | `core/chat.py` | Web wird ein weiterer Kanal (`place="web"`) |
| Agent mit Werkzeugen, Quellen, Schritten (`AgentResult.tools`, `.sources`, `.steps`) | `agent/loop.py` | Grundlage der Agent-Timeline |
| KoboldCpp als Kindprozess, Argumente pro Neustart neu (`argv_factory`) | `inference/process.py`, Supervisor | Neustart mit neuem Kontext |
| Konfiguration mit Neuladen und „braucht Neustart“ | `config/reload.py` | Grundlage der Einstellungsseite |
| Transkripte in SQLite, 24 h | `storage/` | werden 15 Tage, plus Discord und Web |
| Branding, Scribbles für Leer-/Lade-/Fehlerzustände | `assets/branding/` | Pflicht in jeder Ansicht |

## 3. Entscheidung Frontend (ADR-040)

- **Kein Build-Schritt, keine Node-Laufzeit:** Vanilla-JS als ES-Module, eine Seite (`frontend/app/`) mit
  Hash-Routing (`#/chat`, `#/verlauf`, `#/status`, `#/modell`, `#/einstellungen`). Läuft so auch in der
  Android-WebView (1.1+).
- **Streaming über SSE** (`fetch` mit `ReadableStream` für POST, `EventSource` für den Live-Status): einfacher
  als WebSocket, FastAPI kann es ohne Zusatzpaket.
- **Kein CDN, keine fremden Schriften:** alles liegt im Repo. Schrift: Systemschrift
  (`"Helvetica Neue", Helvetica, Arial, "Segoe UI", system-ui`).
- **Design wie layernx.de, dunkel:** fast schwarzer Grund (`#09090c`) mit dezentem violettem Schimmer, Violett
  `#5b3bff` als Akzent mit Leuchten unter dem Hauptknopf, fette, eng gesetzte Überschriften mit einem Wort in
  Violett, kleine graue Großbuchstaben-Labels („ANTON / CHAT“), Zweitknöpfe dunkel mit feinem Rand, beim Login
  ein großer Umriss-Schriftzug „m-agent“ im Hintergrund. Alle Farben sind CSS-Variablen in `frontend/app/app.css`.
- Alternativen: Preact/htm ohne Build (vendored, ≈ 10 KB) – nehmen wir, falls die Oberfläche zu groß für
  Vanilla-JS wird; Svelte/React mit Build – abgelehnt, weil Node auf dem Server oder im Release nötig wäre.

## 4. Großer Kontext (≥ 50k Tokens)

Geschätzt aus den Modelldaten (48 Schichten, 4 KV-Köpfe, 128 Dimensionen), gemessen wird in P2-03:

| Kontext | KV-Cache fp16 | KV-Cache 8 Bit (`--quantkv 1`) |
| --- | --- | --- |
| 8.192 (Part 1) | ≈ 0,8 GB | ≈ 0,4 GB |
| 51.200 (Part 2) | ≈ 4,7 GB | ≈ 2,3 GB |
| 65.536 | ≈ 6,0 GB | ≈ 3,0 GB |

- **`context_size = 51200` mit 8-Bit-KV-Cache** (braucht Flash-Attention, ist an). Der Rest der 8 GB VRAM geht an
  die Modellschichten, `--moecpu` misst `bench_llm.py --tune` neu. Erwartet: ≈ 18–22 statt 28 Tokens/s.
- **Budget je Profil:** Telefon und Sprachkanal nehmen nur so viel Verlauf, wie für schnelle Antworten nötig ist
  (`agent.phone.history_tokens`, Standard 6.000); Web- und Discord-Chat dürfen den ganzen Kontext nutzen.
- **Ein Platz im Cache:** KoboldCpp hält ein Gespräch fertig im Speicher. Kommt ein Anruf dazwischen, muss ein
  langer Web-Chat danach neu eingelesen werden. P2-03 prüft, ob KoboldCpp mehrere Zustände sichern kann
  (`--smartcache`/Speicherstände); sonst zeigt die WebUI „liest das Gespräch neu ein …“ mit Fortschritt.

## 5. Vorleistungen für Agenten in der Sandbox (ADR-041)

Ziel ab Part 3/4: Anton bekommt einen Auftrag („bau mir ein Skript, das …“), plant, arbeitet in der
Sandbox-VM auf Redemption-1 mit Shell, Dateien, Git und Tests, fragt vor riskanten Schritten nach und
liefert Ergebnisse – über Minuten oder Stunden, so wie Claude Code. Damit Part 2 dafür nichts neu bauen
muss, gilt:

1. **Ein Lauf ist ein Lauf.** Jede Antwort ist ein *Lauf* (`run`) mit nummerierten Ereignissen:
   `status`, `token`, `tool_call`, `tool_output` (gestreamt, z. B. später die Ausgabe einer Shell),
   `tool_result`, `approval_request`, `approval_response`, `file`, `source`, `done`, `error`. Eine Web-Antwort
   ist ein Lauf mit 0–3 Schritten, ein Sandbox-Agent später derselbe Lauf mit 200 Schritten. Dasselbe
   Protokoll gilt für SSE, Datenbank, Timeline und Discord-Threads.
2. **Läufe hängen nicht am Browser.** Ein Lauf läuft als Aufgabe im Server. Der Browser hängt sich nur an
   (`GET /api/runs/{id}/events?after=N`) und kann nach Neuladen oder vom Handy aus weiterschauen. Tab zu
   heißt nicht abbrechen; abbrechen ist ein eigener Knopf.
3. **Läufe werden gespeichert:** Tabellen `runs` und `run_events` kommen mit P2-04. Nach einem Neustart steht
   ein unterbrochener Lauf als „abgebrochen (Neustart)“ da; Wiederaufnahme ist Part 3.
4. **Bestätigen ist eingebaut:** Werkzeuge haben eine Stufe `risk = read | write | execute` und
   `needs_approval`. Bei `approval_request` zeigt die WebUI „Anton möchte … – Erlauben / Ablehnen“
   (`POST /api/runs/{id}/approval`), Discord dasselbe als Knöpfe. In Part 2 sind alle Werkzeuge `read`; ein
   Test-Werkzeug prüft den Ablauf. Am Telefon gibt es nie Bestätigungen für `execute` (SBX-05).
5. **Profile sind Agent-Typen:** Ein Profil (`[agent.<name>]`) legt Werkzeuge, Schrittgrenze, Frist und
   Vorrang fest. Part 2 bringt `web`; Part 4 fügt `coding` dazu, ohne Umbau. Agenten-Läufe nutzen die
   Warteschlangen-Stufe `BACKGROUND`, Telefon und Sprachkanal gehen immer vor.
6. **Dateien sind ein Arbeitsbereich:** Uploads liegen je Gespräch in `data/files/<gespräch>/` mit Tabelle
   `files`. Später spiegelt der Agent diesen Ordner in seinen Sandbox-Arbeitsbereich, und Ergebnisse
   (Skripte, Berichte) erscheinen in derselben Liste zum Herunterladen.
7. **Langer Kontext und Verdichten:** 50k Kontext (§4) ist die Grundlage. `ContextBuilder` bekommt eine
   Stelle zum Verdichten (Part 2: älteste Wechsel weglassen wie bisher; Part 4: zusammenfassen).
8. **Modell bleibt austauschbar:** Der Inferenz-Client spricht die OpenAI-API. Reicht Qwen3 für große
   Coding-Aufgaben nicht, kann ein Profil später ein anderes Ziel (zweites Modell, anderer Server) bekommen.
   Part 2 wechselt kein Modell, verbaut es aber nicht.
9. **Sicherheit bleibt:** Ausführen nur in der Sandbox-VM, nie auf Sophie-1 (SBX-01). Die Einstellungsseite
   hat schon den Bereich `[sandbox]` mit SSH-Zugang (nur schreibend). `passwords.txt` sieht kein Werkzeug.

## 6. Tickets

Reihenfolge: P2-01 → P2-02 → P2-03 → P2-04 → P2-05 → P2-06 → P2-07 → P2-08 → P2-09 → P2-10 → P2-11 → P2-12.

### P2-01 – App-Gerüst, Design, Login, Zertifikat

- `frontend/app/` (index.html, `app.js`, `style.css`, Module je Ansicht), ausgeliefert unter `/`; die
  Statusseite zieht als Ansicht `#/status` ein, `/status` leitet weiter.
- Layout: Seitenleiste (PC), einklappbar (Tablet), untere Leiste (Handy); Design wie layernx.de (§3), Logo und Scribbles.
- **Login 10 Tage:** `server.session_ttl_hours = 240`; Sitzungen liegen gehasht in SQLite und überstehen
  Neustarts. Abmelden beendet die Sitzung sofort; „Alle Geräte abmelden“ in den Einstellungen.
- **Zertifikat für die IP:** eine eigene kleine Zertifizierungsstelle (`runtime/tls/ca.pem`) unterschreibt das
  Server-Zertifikat für `192.168.1.187`, alle eigenen IPs und den Hostnamen (`server.public_hosts`).
  `GET /ca.crt` liefert die CA zum Installieren; Anleitung für Windows, Android, iOS und Linux in
  `docs/webui.md`. Danach keine Zertifikatswarnung mehr.
- Tests: Auslieferung, Content-Security-Policy (`default-src 'self'`), kein externer Request, Sitzung nach
  Neustart gültig, nach 10 Tagen ungültig, Zertifikat enthält die IP.
- Anforderungen: UI-02, API-01, API-02, API-05.
- **Umgesetzt (27.10.2026):** `frontend/app/` (Chat über `/api/chat`, Status), `storage/web.py` +
  Migration `0003_web.sql`, `api/tls.py` (eigene CA, Erneuerung bei neuer Adresse oder 30 Tage vor Ablauf, eigenes
  Zertifikat bleibt unangetastet), `POST /api/logout-everywhere`, `docs/webui.md`. Die alte Statusseite
  `frontend/status/` ist entfernt. Der Knopf „Alle Geräte abmelden“ kommt mit der Einstellungsseite (P2-09);
  der Endpunkt ist schon da.

### P2-02 – Chat mit Streaming (SSE)

- `POST /api/chat/stream` startet einen Lauf (§5) und liefert seine Ereignisse als `text/event-stream`;
  `GET /api/runs/{id}/events?after=N` hängt sich wieder an. Gleicher Kern wie `/api/chat` (`ChatService`), Profil `web` (wie Discord-Chat:
  Markdown, längere Antworten, Bro-Persönlichkeit).
- Abbrechen-Knopf → `POST /api/runs/{id}/cancel` (nutzt die Abbruchlogik der Queue, Telefon behält Vorrang).
- Markdown-Darstellung ohne `innerHTML` aus Modelltext (eigener kleiner Renderer, nur sichere Elemente),
  Code-Blöcke mit Kopieren-Knopf.
- Sofortauskünfte (Wetter, Uhrzeit …) kommen sofort als ein `done`, mit Karten wie auf Discord.
- Tests: Ereignisfolge, Abbruch, Telefon unterbricht Web-Chat (Priorität), XSS-Fälle im Renderer.
- Anforderungen: UI-02, AGENT-04, AGENT-08.
- **Umgesetzt (27.10.2026):**
  - `core/runs.py` (`RunManager`): Läufe im Speicher, fertige 10 Minuten lang wieder abrufbar. Pro
    Gespräch läuft höchstens ein Lauf (sonst 409). Gespeichert werden Läufe mit P2-04.
  - Ereignisse: `run`, `status`, `token`, `text`, `tool_call`, `tool_result`, `done`, `cancelled`,
    `error`. Werkzeug-Ereignisse kommen aus `ToolRegistry.call` über `ToolContext.on_event`, die Argumente
    gekürzt.
  - Werkzeuge haben jetzt `risk` (`read`) und `needs_approval` (ADR-041 Nr. 4; das Nachfragen kommt mit
    P2-06).
  - Der Web-Chat nutzt das Chat-Profil wie Discord (Markdown, längere Antworten); ein eigenes Profil `web`
    braucht es noch nicht.
  - `frontend/app/js/markdown.js` (Parser ohne DOM, mit node getestet), Streaming im Chat, Stopp-Knopf,
    Werkzeug-Schritte live. Reißt die Verbindung ab, hängt sich der Chat bis zu dreimal neu an den Lauf.
  - Der Vorrang des Telefons steckt in der Warteschlange und ist dort getestet (`test_inference`).

### P2-03 – Großer Kontext

- §4 umsetzen: `context_size = 51200`, `inference.kv_cache_bits = 8` (→ `--quantkv 1`), Budget je Profil,
  `test-4.sh run` misst Tokens/s und VRAM bei 50k und schreibt `--moecpu` neu.
- Prüfen und dokumentieren, wie lange das Neueinlesen eines vollen Kontexts dauert; Fortschritt im Chat.
- Anforderungen: INF-02 (geändert), INF-05.
- **Umgesetzt (27.10.2026):**
  - `inference.context_size = 51200`, `inference.kv_cache = "q8_0"` (→ `--quantkv q8_0`).
  - `inference.smart_cache = 2` (→ `--smartcache 2`): KoboldCpp legt Gesprächsstände im RAM ab. Nach einem
    Anruf muss ein langer Chat nicht neu eingelesen werden.
  - `agent.phone.context_tokens = 8192`: Telefon und Sprachkanal nehmen davon nur 8.192.
  - Gemerkt werden bis zu 100 Wechsel (vorher 30).
  - Chat-Frist 120 s, `request_timeout_s = 180`, damit ein voller Kontext eingelesen werden kann.
  - `./test-3.sh run` misst jetzt mit 51.200 (`bench_llm.py --tune --context 51200`).
  - Offen bis zum Lauf auf Sophie-1: echte Tokens/s, VRAM und Einlesezeit. Das Messen übernimmt `test-4.sh`
    (P2-12).

### P2-04 – Verlauf über alle Kanäle

- Tabellen `conversations`, `messages`, `runs`, `run_events` und `files` (Vorgriff auf Part 3, §5): Web, Telefon und Discord (Text und
  Sprachkanal) schreiben hinein; Symbol je Kanal in der Liste.
- **Aufbewahrung 15 Tage** (`storage.history_days = 15`, ersetzt die 24 h aus F-03), dann gelöscht.
  **Speichern-Knopf** (`pinned`) → nie automatisch gelöscht; Knopf erneut drücken hebt es auf.
- Durchsuchen (SQLite FTS5 über Titel und Text), umbenennen, löschen, **Export als Markdown**.
- Titel automatisch aus der ersten Frage; ein Web-Gespräch fortsetzen lädt seinen Verlauf ins
  Kurzzeitgedächtnis. Telefon- und Discord-Gespräche sind in der WebUI nur lesbar.
- Tests: Migration, Löschen nach 15 Tagen außer gespeicherten, Suche, Export, Verlauf nach Neustart da.
- Anforderungen: STORE-01, STORE-02 (geändert).
- **Umgesetzt (27.10.2026):**
  - Migration `0004_history.sql` (`conversations`, `messages`, `messages_fts`, `runs`, `run_events`) und
    `storage/history.py`. Den FTS5-Index pflegt der Code mit, weil die Migrationen keine Trigger können.
  - Gespeichert werden Web, Telefon, Discord-Text und Sprachkanal, nur wenn `storage.store_transcripts`
    an ist. Ein Discord-Chat beginnt nach 30 Minuten Ruhe ein neues Gespräch (wie das Kurzzeitgedächtnis).
  - Zu jeder Web-Antwort werden ihre Schritte gespeichert (`tool_call`, `tool_result` …), nicht die
    einzelnen Tokens.
  - `storage.history_days = 15`; gespeicherte Gespräche (`pinned`) löscht die nächtliche Wartung nie.
  - API: `GET /api/conversations` (`q`, `source`, `pinned`, `chat`), `GET/PATCH/DELETE
    /api/conversations/{id}`, `GET /api/conversations/{id}/export.md`.
  - WebUI: Ansicht „Verlauf“ (Suche, Filter, Gruppen Gespeichert/Heute/Gestern/Diese Woche/Älter,
    Speichern, Umbenennen, Export, Löschen). Telefon und Discord sind nur lesbar, Web-Gespräche öffnen im
    Chat und gehen dort weiter. Im Chat gibt es den Knopf „Speichern“, und der Chat lädt nach einem Neuladen
    das letzte Gespräch.
  - Nach einem Neustart bekommt ein fortgesetztes Web-Gespräch sein Kurzzeitgedächtnis aus der Datenbank
    zurück.

### P2-05 – Dateien im Chat

- Text (`.txt`, `.md`, `.csv`, `.json`, Quelltext) und **PDF** per Ziehen oder Büroklammer; Text wird
  ausgelesen (PDF mit `pypdf`, BSD-Lizenz) und als Anhang in den Kontext gelegt.
- Grenzen: 10 MB je Datei, Text gekürzt auf das Kontextbudget mit Hinweis; Dateien liegen beim Gespräch
  und werden mit ihm gelöscht. Inhalte aus Dateien sind Daten, keine Anweisungen (wie Suchergebnisse).
- Gescannte PDFs ohne Text: Hinweis „keine lesbare Schrift“ (OCR kommt in 1.1+).
- Discord bekommt dasselbe für Anhänge (14 §5.5).
- Anforderungen: UI-02, Sicherheit (Prompt-Injection, 08).
- **Umgesetzt (27.10.2026):**
  - `storage/files.py` mit Migration `0005_files.sql`. Dateien liegen in `data/files/` als Original und
    ausgelesener Text. `pypdf` 6.21 ist neu in `requirements/core.lock`, Lizenz BSD-3-Clause.
  - API: Upload als roher Body (`POST /api/files?chat=…&name=…`, ohne Formular-Paket), `GET /api/files/{id}`
    lädt die Datei immer als Download, `DELETE` löscht sie. Lesen hat höchstens 30 s Zeit.
  - Die Dateien eines Gesprächs gehen an das Sprachmodell als Block in der Systemanweisung, markiert als
    „Daten, keine Anweisungen“. Sie bekommen höchstens 75 % des Kontexts und werden sonst gekürzt. Sie bleiben
    bis zum Leeren des Kurzzeitgedächtnisses, damit Folgefragen gehen.
  - Kommt eine Datei mit der Frage, antwortet immer das Sprachmodell, nicht eine Sofortauskunft.
  - Dateien gehen mit ihrem Gespräch: beim Löschen und nach `storage.history_days`.
  - WebUI: Büroklammer und Ziehen in den Chat, Anhänge mit Seiten und Größe, klare Fehler (Bild, zu groß,
    Passwort, gescannt), Datei-Chips an der Frage, auch im Verlauf.
  - Noch offen: Discord-Anhänge (14 §5.5) lesen. Das kommt, wenn Discord die Läufe bekommt.

### P2-06 – Agent-Timeline

- Unter jeder Antwort aufklappbar: „✓ Websuche ‚Kanzler Deutschland‘ (3 Quellen, 1,2 s)“, „✓ Wetter
  Weilburg“, Dauer, Tokens/s, verworfene Verlaufs-Wechsel (`dropped_turns`).
- Daten kommen aus den Lauf-Ereignissen (§5); nichts Geheimes (Werkzeug-Argumente gefiltert).
- Gebaut für lange Läufe: Schritte einklappbar, gestreamte Werkzeug-Ausgabe in einer Konsolen-Ansicht,
  Bestätigungs-Dialog (`approval_request`) mit Test-Werkzeug geprüft.
- Anforderungen: UI-02, LOG-02 (Redaktion).
- **Umgesetzt (27.10.2026):**
  - Nachfragen (ADR-041 Nr. 4): Hat ein Werkzeug `needs_approval`, fragt `ToolRegistry.call` über
    `ToolContext.approver` nach. Der Lauf zeigt `approval_request` mit Werkzeug, Stufe und Argumenten, Moritz
    antwortet über `POST /api/runs/{id}/approval`. Ohne Antwort in 90 s, bei „Ablehnen“ oder ohne jemanden zum
    Fragen (Telefon, Sprachkanal) läuft das Werkzeug nie (`error: denied`).
  - In Part 2 braucht kein ausgeliefertes Werkzeug eine Nachfrage. Den Ablauf prüft ein Test-Werkzeug in
    `test_runs.py`.
  - WebUI: Schritte als aufklappbare Zeitleiste. Während der Antwort ist sie offen, danach zugeklappt mit
    „N Schritte · Nachfragen · Dauer · verworfene Wechsel“. Die Nachfrage-Karte hat „Erlauben / Ablehnen“.
    `tool_output` erscheint als Konsole unter dem Schritt (für die Sandbox-Werkzeuge ab Part 4).
  - `TurnResult.stats` (Schritte, ms, verworfene Wechsel) steht im Verlauf. Tokens/s kommt mit der
    Modellseite (P2-08).
  - Discord bekommt die Nachfrage als Knöpfe, sobald dort Werkzeuge mit Nachfrage auftauchen (Part 4).

### P2-07 – Anrufstatus und Discord live

- `GET /api/events` (SSE) ersetzt das Polling der Statusseite: Anruf klingelt/aktiv/beendet, Sprachkanal,
  Komponenten (KoboldCpp, SearXNG, Discord), Warnungen, Logs der letzten Minuten.
- Anforderungen: UI-01, DISCORD-30.
- **Umgesetzt (27.10.2026):**
  - `GET /api/events` (SSE) schickt den ganzen Status, sobald sich etwas ändert: Anruf, Sprachkanal,
    Komponenten, „das Sprachmodell schreibt“, Wartungsmodus. Die Laufzeit allein löst nichts aus. Alle 20 s
    kommt ein Ping. Gesprächsinhalte stehen nie darin.
  - `GET /api/system/logs?lines=&category=` liest nur das Dateiende (512 KB), nicht die ganze Logdatei.
  - WebUI: Status kommt live, ohne Abfragen (Abzeichen „LIVE“, bei Abbruch „verbindet neu“). Ein laufender
    Anruf ist grün markiert („Anton telefoniert gerade“). Unten gibt es einen aufklappbaren Log-Bereich mit
    Filter nach Kategorie, alle 4 s neu, solange er offen ist.

### P2-08 – Modellseite

- Kein Modellwechsel (nur Qwen3-30B-A3B). Die Seite zeigt: geladen ja/nein, Kontext, VRAM/RAM, Tokens/s der
  letzten Antworten, `--moecpu`.
- Knöpfe: **Neustart** von KoboldCpp, **Kontext** ändern (mit Schätzung des Speichers), **Messen**
  (`scripts/bench_llm.py --tune` im Hintergrund, Ergebnis als Tabelle). Während eines Anrufs gesperrt.
- Discord: `/admin modell status|neustart`.
- Anforderungen: PRD-03, ADR-016, INF-06 (entfällt, kein Wechsel).

### P2-09 – Einstellungen: alles änderbar

- `GET/PUT /api/settings`: **jeder** Wert aus `config/moritz-agent.toml`, gruppiert wie die Datei, Formular aus
  dem pydantic-Schema mit den Kommentaren der Beispielkonfiguration als Hilfetext. Speichern zeilenbasiert
  (Kommentare bleiben), danach Neuladen; „braucht Neustart“ mit Knopf.
- **Zugangsdaten** (SIP-Passwort, Discord-Token, Web-Passwort, API-Schlüssel): Felder **nur zum
  Schreiben**. Die API liefert nur „gesetzt/nicht gesetzt“, nie einen Wert, auch nicht gekürzt. Geschrieben
  wird `passwords.txt` zeilenbasiert: die eine Zeile ersetzen oder anhängen, nie neu serialisieren
  (CLAUDE.md). Das Web-Passwort wird als scrypt-Hash gespeichert und braucht das alte Passwort.
- Jede Änderung steht im Log (welcher Schlüssel, nie der Wert).
- Anforderungen: CFG-05, CFG-08, UI-02, Sicherheitsregeln (CLAUDE.md, 08).

### P2-10 – OpenAI-kompatible API

- `/v1/chat/completions`, `/v1/models` über moritz-agent mit API-Schlüssel (in `passwords.txt`, in den
  Einstellungen setzbar), weitergereicht an KoboldCpp über die Queue (Telefon hat Vorrang).
- Anforderungen: INF-07.

### P2-11 – Sofortauskünfte in der WebUI

- Wetterkarte und Vorhersage-Diagramm, Warnungen, Notizen/Einkaufsliste, Liste nicht erkannter Fragen,
  Über-Seite mit Quellen und Lizenzen (13, 05 „Sofortauskünfte in späteren Parts“).

### P2-12 – `test-4.sh` und Abnahme

- `test-4.sh setup|run` verwendet `test-3.sh` wieder (CLAUDE.md, Testskripte) und prüft zusätzlich:
  App ausgeliefert, Zertifikat für die IP, Login, Streaming-Chat, 50k-Kontext, Datei-Upload, Verlauf und
  Speichern, Einstellungen speichern, Chat und Telefon gleichzeitig.
- Abnahme: „Chat und Telefon parallel benutzbar, langer Chat bleibt im Gedächtnis“ – Protokoll
  `runtime/test-4/abnahme.md` wie bei test-3.

## 7. Fragen an Moritz

| ID | Frage | Antwort |
| --- | --- | --- |
| F-41 | Wie lange sollen Gespräche gespeichert bleiben? | 15 Tage; mit Speichern-Knopf für immer |
| F-42 | WebUI auch über VPN oder nur im LAN? | nur LAN, über die IP 192.168.1.187 |
| F-43 | Mehrere Benutzer oder nur Moritz? | nur Moritz |
| F-44 | Modellwechsel in der WebUI? | kein Wechsel, nur das eine Modell |
| F-45 | Tempo gegen Kontext? | egal; mindestens 50k Kontext |
| F-46 | Ein Gespräch über alle Kanäle? | nein, jedes für sich |
| F-47 | Anrufe und Discord im Verlauf der WebUI? | ja |
| F-48 | Mikrofon und Vorlesen im Browser? | nein |
| F-49 | Wie lange angemeldet bleiben? | 10 Tage |
| F-50 | Zugangsdaten in der WebUI setzbar? | ja, alles änderbar |
| F-51 | Aussehen? | dunkel wie layernx.de |
| F-52 | Agenten in der Sandbox? | ja, später wie Claude Code; Part 2 legt den Grund (§5) |

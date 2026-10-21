# 05 – Roadmap Part 2 bis 1.1+

Grundregel für alle Parts: **Die Telefonfunktion aus Part 1 bleibt jederzeit voll
nutzbar.** Jeder Part endet mit einem Regressionsanruf (09, §3 Punkte 4–7).

| Part | Version | Thema | Kern-Lieferumfang | Abnahme |
| --- | --- | --- | --- | --- |
| 1 | 0.1 | Anrufbarer Agent | siehe [04](04-part1-umsetzung.md) | Echter Anruf mit Uhrzeit + Suche, 3 Runden |
| 1 – Block S | 0.1 | **Sofortauskünfte vor dem LLM** (ADR-029) | Skill-Framework, Zeit/Kalender/Feiertage/Ferien, **Wetter für Weilburg 35781** oder jede genannte PLZ/jeden Ort, Warnungen, Pollen, Sonne/Mond, Rechnen/Umrechnen, Region (Lahn-Pegel, Müll), Helfer – [13](13-sofortauskuenfte.md), Tickets P1-19 … P1-30 | Testanruf nach 13 §17; erst danach P1-02/P1-05/P1-07/P1-09 |
| 1 – Block D | 0.1 | **Discord-Bot** (ADR-033 … ADR-037) | Nikita als Bot – ein bisschen süß, mit schelmischen Aktivitäten – auf einem Privatserver mit Standard-Textkanal (ID beim Setup oder in der TXT): Text, Slash-Befehle, Knöpfe, alle Sofortauskünfte, `/joinvc` = Sprachkanal wie ein Anruf (DAVE, Spike), Sprachnachrichten, Erinnerungen, Abos, Admin für den Owner, Benutzer-App – [14](14-discord.md), Tickets P1-31 … P1-43 | Abnahme nach 14 §21; Telefon bleibt unbeeinträchtigt |
| 2 | 0.2 | WebUI | Chat mit Streaming (SSE), Verlauf, Agent-Timeline („✓ Search Web …“), Anrufstatus live, Modellverwaltung (GGUF erkennen, laden/entladen, Kontext, GPU-Layer, Presets), Einstellungen (nicht geheime Werte), responsive Layout | Chat + Telefon parallel benutzbar, Modellwechsel entlädt zuerst (INF-06) |
| 3 | 0.3 | Backend & Speicher | Tabellen `conversations/messages/tasks/agents/settings/models`, sauber getrennte Sitzungen (Telefon ↔ Web), Task-Verwaltung, Wiederaufnahme geeigneter Hintergrundaufgaben nach Neustart, OpenAI-kompatible `/v1/*`-Weitergabe mit API-Key | Neustart verliert keine Verläufe/Tasks |
| 4 | 0.4 | Sandbox & Coding-Tools | SSH-Client mit gepinntem Host-Key, Workspaces je Task, Tools `shell`, `python`, `files`, `git`, `download`, `archive`, Test-Runner; Ausgabelimits; Bestätigungsmodell für riskante Aktionen; Telefonprofil weiterhin ohne diese Tools | Abgegrenzte Coding-Aufgabe in Redemption-1-VM; Telefon läuft bei ausgeschalteter Sandbox |
| 5 | 0.5 | Recherche ausbauen | `web_fetch` mit Extraktion (readability-artig), Quellenverwaltung (`sources`, `research_runs`), mehrseitige Recherche, längere Ergebnisdarstellung in der WebUI | Rechercheauftrag mit ≥ 5 Quellen, alle zitiert |
| 6 | 0.6 | Browser-Automation | Chromium + Playwright **in der Sandbox**, Remote-Browser-Client, Tools `browser.open/click/type/scroll/screenshot/download`, max. 2 Seiten, Crash-Isolation | Dynamische Seite bedienen, Download in Sandbox |
| 7 | 0.7 | Telefonkomfort | Weitere Stimmen/Engines (Piper-Hessisch ist schon in Part 1 Hauptstimme), Barge-in mit Echo-Behandlung (AEC/Ducking), Streaming-TTS satzweise ab erstem Satz, bessere Latenz, konfigurierbare Stimmen, optional DTMF; Weiterleitung/ausgehende Anrufe nur als separat freigeschaltete Erweiterung | Unterbrechen funktioniert ohne Selbsterkennung |
| 8 | 0.8 | Memory | Gesprächszusammenfassungen, persistente Fakten (mit Bestätigung/Löschbarkeit in der UI), Retrieval über SQLite FTS5 (kein Dauer-Embedding-Modell im Startprofil) | Fakt aus Anruf A wird in Anruf B korrekt genutzt |
| 9 | 0.9 | Deep Research | Rechercheplan, 5–15 Queries, Quellen in kleinen Gruppen, Behauptungs-Extraktion, Widerspruchserkennung, belegter Bericht; am Telefon kurze Statusantwort, Ergebnis in der WebUI | Bericht mit Quellen + Widersprüchen |
| — | 1.0 | Integriert | Telefon- und General-Agent mit Chat, Suche, Research, Coding, Sandbox, Memory, WebUI | Gesamtabnahme |
| — | 1.1+ | Erweiterungen | Android-WebView-App, Multi-Agent-Rollen (Supervisor/Research/Coding/Browser/Review – ein Modell, eine Queue), Plugins/MCP, weitere Modelle, Bilder/OCR (kein Windows-Build, F-12) | je Feature |

## Querschnittsthemen über alle Parts

- **Upstream-Sync KoboldCPP:** quartalsweise oder bei relevanten Features (ADR-001).
- **Sicherheit:** jede neue Tool-Klasse bekommt einen Eintrag im Bedrohungsmodell
  ([`08-sicherheit.md`](08-sicherheit.md)) **bevor** sie gebaut wird.
- **Messungen:** RAM/VRAM-Tabelle in [`06-infrastruktur.md`](06-infrastruktur.md) wird bei
  jedem Part mit neuen Komponenten aktualisiert. Kontext 8.192 erst nach Messung (INF-05).
- **Agent-Modi:** Phone (P1), General (P2), Research (P5/9), Coding (P4), Browser (P6);
  später Sysadmin, Document, Data Analysis, Security Analysis, Network, DevOps.
- **Tools später:** `database`, `email`, `calendar`, `docker`, `proxmox`, `image`, `ocr`, `mcp`
  – jeweils mit eigenem Berechtigungs- und Bedrohungskapitel. Der vorhandene Upstream-MCP-
  Proxy (`--mcpfile`) und `kcpp_agent.py` dienen als Referenz, nicht als Basis.
- **Kanal-Parität (ADR-034):** Jede Funktion jedes Parts kommt im selben Ticket auch auf Discord
  (Matrix [14 §6](14-discord.md#6-funktionsumfang-alle-funktionen-auf-allen-kanälen)): Part 2
  `/admin modell`, `/einstellungen`; Part 3 Verläufe je Kanal/Thread, `/aufgabe`; Part 4 `/code` (nur
  Owner, Bestätigung je Aktion); Part 5 `/recherche` im Thread; Part 6 `/browser` mit Screenshots;
  Part 7 `/stimme`; Part 8 `/merke`, `/vergiss`, `/gedaechtnis`; Part 9 `/deep` mit Bericht als Datei;
  1.1+ Bilder/OCR per Anhang, Multi-Agent-Rollen im Thread, MCP-Tools je Rolle.
- **Sofortauskünfte in späteren Parts** ([13](13-sofortauskuenfte.md)): Part 2 – Wetterkarte,
  Vorhersage-Diagramm, Warnungen, Notizen/Einkaufsliste und Liste nicht erkannter Fragen in der WebUI,
  Über-Seite mit Quellenangaben; Part 3 – Skill-Statistik in der Datenbank; Part 7 – Regenradar
  (Nowcasting), Barge-in auch bei langen Wetterantworten; Part 8 – persönliche Orte („bei Oma“) und
  Geburtstage aus dem Memory; 1.1+ – Bus/Bahn (RMV/DB, mit Schlüssel), Kalender (CalDAV), eigene
  Wetterstation/Home Assistant als lesende Quelle, weitere Bundesländer für Schulferien.

# 11 – Suchoptionen (R4) und Fallback-Kette

Moritz’ Vorgabe: Alle Engines nutzen (F-09) und weitere Suchoptionen finden – „könnte auch
eine KoboldCpp sein“ (R4). Ergebnis: eine **Fallback-Kette** aus lokalen Quellen ohne
API-Schlüssel, optional ergänzt um Dienste mit Schlüssel (ADR-020).

## 1. Bewertete Optionen

| Option | Art | Schlüssel nötig | Kosten | Qualität DE | Robustheit | Einsatz |
| --- | --- | --- | --- | --- | --- | --- |
| **SearXNG** (im Repo, `third_party/searxng`) | Metasuche, ~20 Web-/News-Engines | nein | 0 | gut | mittel – einzelne Engines werden geblockt, SearXNG suspendiert sie automatisch | **Stufe 1 (primär)** |
| **KoboldCpp-Websuche** (`--websearch`, `/api/extra/websearch`) | DuckDuckGo-HTML, Top 3 + Seiteninhalt | nein | 0 | ok | mittel – eine Engine, aber unabhängig von SearXNG; liefert gleich Seitentext | **Stufe 2 (Fallback)** |
| **Wikipedia REST API** (`de.wikipedia.org/api/rest_v1`) | Lexikon | nein | 0 | sehr gut für Fakten | hoch | **Stufe 3** für Fakten-/Definitionsfragen |
| Brave Search API | Websuche-API | ja | Free-Tier begrenzt, danach kostenpflichtig | gut | hoch | optional (Part 5) |
| Google Programmable Search (JSON API) | Websuche-API | ja (Key + CX) | Free-Tier 100 Anfragen/Tag | gut | hoch | optional (Part 5) |
| Mojeek API | eigene Websuche | ja | kostenpflichtig | mittel | hoch | optional |
| Tavily / Exa / SerpAPI | KI-Such-APIs | ja | kostenpflichtig | gut | hoch | nur falls nötig |
| Bing Search API | – | – | – | – | **von Microsoft 2025 eingestellt** | entfällt |

## 2. Fallback-Kette im Agent (Part 1)

```text
web_search(query)
  ├─ 1. SearXNG (alle aktivierten Engines, de-DE, Timeout 6 s)
  │     └─ ≥ 1 Treffer → fertig
  ├─ 2. KoboldCpp /api/extra/websearch (DuckDuckGo, Timeout 8 s)
  │     └─ ≥ 1 Treffer → fertig (Quelle: „duckduckgo via inference“)
  ├─ 3. Wikipedia-Zusammenfassung (nur wenn Frage nach Person/Ort/Begriff aussieht)
  └─ 4. ehrliche Fehlermeldung (PHONE-32): „Die Websuche ist gerade nicht erreichbar …“
```

- Jeder Treffer trägt `source_backend` (`searxng`, `koboldcpp`, `wikipedia`) und – bei SearXNG –
  die tatsächlich liefernden `engines`. „Google“ wird nur genannt, wenn Google geliefert hat.
- KoboldCpp wird dafür mit `--websearch` gestartet; der Endpunkt ist nur auf Loopback
  erreichbar und wird nur vom Agent aufgerufen.
- Optionale API-Dienste werden als Stufe 1b eingehängt, sobald ein Schlüssel in
  `passwords.txt` `[optional_services]` steht (z. B. `brave_api_key`,
  `google_cse_api_key` + `google_cse_id`). Ohne Schlüssel bleiben sie aus.

## 3. Konfiguration

Siehe `[search]` in [`config/moritz-agent.example.toml`](../../config/moritz-agent.example.toml)
(`backends`, Timeouts) und [`config/searxng/settings.yml`](../../config/searxng/settings.yml)
(aktivierte Engines: alle Standard-Engines plus google, bing, qwant, qwant news, tagesschau,
fireball news).

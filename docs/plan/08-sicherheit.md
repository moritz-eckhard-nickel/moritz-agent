# 08 – Sicherheit und Datenschutz

## 1. Schutzgüter

| Schutzgut | Wo | Schutzbedarf |
| --- | --- | --- |
| Zugangsdaten (`passwords.txt`) | Agent-LXC | hoch |
| Telefonanlage / Konto `agent` | Asterisk | hoch (Missbrauch → Gebührenbetrug, falls Trunk erreichbar) |
| Homelab-Infrastruktur (Proxmox, OPNsense, NAS) | LAN | sehr hoch |
| Gesprächsinhalte / Transkripte | SQLite | mittel |
| Verfügbarkeit Telefon-Agent | – | mittel |

## 2. Bedrohungen und Maßnahmen

| # | Bedrohung | Maßnahme | Anf.-ID |
| --- | --- | --- | --- |
| T1 | SIP-Scanner / fremde INVITEs | Annahme nur von Registrar-IP (Allowlist), Firewall auf UDP 5060/RTP nur von 192.168.1.176 | PHONE-09 |
| T2 | Schwaches SIP-Passwort `agent` | Warnung im Installer/Status, Empfehlung starkes Passwort; Agent-Konto in Asterisk ohne Trunk-Zugriff | 06 §6 |
| T3 | Secrets in Logs | Redaction auf Feldebene, PJSIP-Loglevel ≤ 3, kein SIP-Message-Logging, kein `set -x` in Skripten, Installer-Eingaben über stdin | LOG-02, PHONE-44, INST-05 |
| T4 | Secrets im LLM-Kontext | `passwords.txt` wird nur vom Config-Modul gelesen; kein Tool darf die Datei lesen (Pfad-Denylist im späteren `files`-Tool + Sandbox hat die Datei gar nicht) | PHONE-44, CFG-06 |
| T5 | Secrets über Web/Diagnose | Statusendpunkte enthalten nur Booleans/Zustände; Test prüft alle TXT-Werte gegen alle API-Antworten | CFG-06, UI-01 |
| T6 | Prompt-Injection aus Webseiten/Suchergebnissen | Telefonprofil hat keine gefährlichen Tools; Suchergebnisse werden als **Daten** markiert (`<search_results>`-Block, Hinweis im Systemprompt); spätere Tools mit Bestätigungsmodell; Sandbox ohne Zugriff auf interne Netze | PHONE-45, SBX-03 |
| T7 | Caller-ID-Spoofing → Admin-Aktionen | Rufnummer ist nie Berechtigung; Admin-Aktionen per Telefon nur mit zusätzlicher Authentisierung (frühestens Part 7, eigener Plan) | PHONE-46, SBX-05 |
| T8 | Web-UI-Bruteforce / Mitlesen im LAN | scrypt-Hash, Rate-Limit, LAN-Bindung (Port 3501) nur mit Login, HTTPS mit eigenem Zertifikat (ADR-022) | API-02, API-05 |
| T15 | ~~Antworttexte verlassen das Haus (Polly)~~ – entfallen: die Stimme läuft komplett lokal; Live-Sätze liegen nur im RAM, nie auf der Platte | Stimmen-Worker lauscht nur auf 127.0.0.1 mit Token; keine Zugangsdaten nötig | ADR-027 |
| T16 | Manipulierte Fremdkomponenten im Repo | Herkunft + Commit in `third_party/VENDORED.md`, PyPI-Pakete nur mit `--require-hashes` | ADR-021 |
| T9 | Interne Dienste aus LAN erreichbar | KoboldCPP/SearXNG/interne API nur auf 127.0.0.1, Per-Start-Token | NFR-07, ADR-004 |
| T10 | Supply-Chain (Modelle, pip, pjproject, SearXNG) | SHA-256 für alle Downloads, `--require-hashes`, gepinnte Commits/Tags, keine `curl \| bash` | INST-03, ADR-019 |
| T11 | Agent zerstört Host / LXC | Keine Shell im LXC, alle Ausführungstools nur in der Sandbox-VM, Dienstbenutzer ohne sudo, systemd-Härtung | SBX-01, P1-17 |
| T12 | Kompromittierte Sandbox greift Agent-LXC an | Sandbox darf nur Internet + Sophie-1 (F-10), Agent-API nur authentisiert, kein SSH zurück; SSH geht nur LXC → Sandbox | SBX-03 |
| T13 | Audio-/Transkript-Leck | Kein Audio auf Disk; Transkripte konfigurierbar + Retention; DB 0600 | PHONE-43, STORE-02 |
| T14 | Update bricht Telefonie | Drain, Backup, Health-Check, Rollback; zusätzlich Proxmox-Snapshot des Containers vor jedem Update | UPD-01, UPD-07, INST-14 |
| T17 | Das Host-Skript verändert versehentlich den Proxmox-Host oder fremde Gäste | arbeitet nur mit `pct`/`pveam`/`pvesm` auf **einem** Container (Name/ID, Markierung in der Beschreibung; fremde Container nur nach Rückfrage); `--dry-run`; Tests gegen simulierten Host; keine Host-Pakete, -Treiber, -Netzwerk- oder -Firewall-Änderung | INST-02, INST-12, INST-15 |
| T18 | Zugangsdaten beim Kopieren/Installieren | `passwords.txt` ist nie Teil des Programmpakets und wird nie überschrieben; keine Passwörter als Argumente/Umgebungsvariablen; Container ohne Root-Passwort; Installationsprotokolle (0600) enthalten keine Eingaben | INST-04, INST-13 |
| T19 | Sofortauskünfte verraten Standort/Gewohnheiten an Datendienste | nur gerundete Koordinaten (≈ 1 km), PLZ/Ortsnamen, fachliche Kennungen; kein Transkript, keine Rufnummer, kein Anrufbezug; Vorabruf in festem Takt statt je Anruf (verschleiert Anrufzeiten); `skills.online = false` schaltet alles ab | SKILL-25, ADR-032 |
| T20 | Manipulierte oder fehlerhafte Antworten von Datendiensten (falsche Werte, Freitext mit „Anweisungen“) | Schema- und Wertebereichsprüfung, Rückfallquelle; Freitext (Warnungen, Schlagzeilen) bereinigt, gekürzt, nur auf Nachfrage gesprochen; nie als Anweisung an ein LLM, Tool-Ergebnisse als Daten markiert (wie T6) | SKILL-34, AGENT-11 |
| T21 | Ausfall/Rate-Limit eines Datendienstes blockiert Anrufe | Zeitbudget 3 s, Cache mit Stale-Regeln, Backoff bei 429/5xx, Status `degraded`; Offline-Skills unabhängig | SKILL-13, SKILL-26 |
| T22 | SSRF/Datenabfluss über konfigurierbare URLs (iCal-Link) oder Weiterleitungen | nur `https://`, Host-Allowlist, Weiterleitungen nur innerhalb der Liste, keine privaten/Loopback-/Link-Local-Adressen (auch nicht nach DNS-Auflösung), Antwort ≤ 2 MB; Ausnahme nur für eine vom Admin ausdrücklich eingetragene eigene Open-Meteo-/Bright-Sky-Instanz | ADR-032, SKILL-35 |
| T23 | Notizen/Einkaufsliste: jeder interne Anrufer kann sie hören oder löschen | Standard aus; Löschen nur nach Rückfrage; Aufbewahrung begrenzt; Hinweis in der Doku; Caller-ID ist keine Berechtigung (PHONE-46) – für Persönliches später Memory mit Bestätigung (Part 8) | SKILL-24 |
| T24 | API-Schlüssel der Datendienste (Tankerkönig) in Logs, weil sie als URL-Parameter gesendet werden | Schlüssel nur in `passwords.txt` (`[optional_services]`), im Code als `Secret`; der HTTP-Client protokolliert nie Query-Strings, Fehlermeldungen enthalten nur Host und Pfad | LOG-02, CFG-01 |
| T25 | Bot-Token gelangt nach außen → Fremde steuern Nikitas Discord-Konto | Token nur in `passwords.txt` (0600), `Secret`, Redaction, nie in Argumenten/Env/Logs; „Public Bot“ aus; gefährliche Funktionen brauchen Owner-Bestätigung; Reset-Anleitung | DISCORD-05, DISCORD-31 |
| T26 | Fremde in Discord-Servern nutzen oder sondieren Nikita (Spam, Kosten, Ausfragen) | Standard verweigern: Allowlists für Personen und Server, Unbekannte ignorieren, Rate-Limits je Rolle, Bot verlässt fremde Server | DISCORD-03, DISCORD-04, DISCORD-21 |
| T27 | Prompt-Injection über Discord-Nachrichten, Embeds, Anhänge oder Thread-Verläufe anderer | Nachrichten Dritter nur als Daten im Kontext; Aktionen nur auf Anfrage freigegebener Personen; Tools je Rolle; riskante Aktionen mit Bestätigung | DISCORD-13, DISCORD-41 |
| T28 | Datenabfluss: Nikita gibt Interna (Logs, Adressen, Konfiguration, Telefoninhalte) in Kanälen preis, die andere lesen | Ausgabefilter (Secrets ≥ 8 Zeichen), keine Interna in Serverkanälen, Admin nur ephemeral/DM, Telefoninhalte nur per Schalter, Discord als „öffentlich genug“ behandeln | DISCORD-20, DISCORD-35 |
| T29 | Massen-Pings oder Belästigung durch Nikita (`@everyone`, Rollen) | `allowed_mentions` nur auf den Angesprochenen, Drosselung proaktiver Nachrichten, Ruhezeiten | DISCORD-19, DISCORD-28 |
| T30 | Kontoübernahme bei Discord → Angreifer ist „Owner“ | Owner-Rechte bleiben begrenzt (keine Shell im LXC, keine Updates, keine Secrets); Bestätigung + optionale PIN aus `passwords.txt` für gefährliche Befehle; 2FA-Empfehlung | DISCORD-31, PHONE-46 sinngemäß |
| T31 | Bösartige Anhänge (übergroß, falscher Typ, Zip-Bomben, Links außerhalb des CDN) | nur Discord-CDN, Größen-/Typ-/Dauergrenzen, Dekodieren mit Limits, nichts ausführen, nur RAM bzw. Sandbox | DISCORD-21 |
| T32 | Lieferkette Discord-Bibliotheken (Fork für DAVE-Empfang, Rust-Erweiterung `davey`) | PyPI mit Hashes; ein Fork nur als dokumentierte Fremdkomponente in `third_party/` mit Commit und Prüfsumme; Spike vor Aufnahme | DISCORD-38, ADR-021 |

## 3. Redaction – Sonderfall kurze Secrets

Die Startwerte enthalten `password = agent` – identisch zu Benutzername, Anzeigename und
Teil des Produktnamens („moritz-**agent**“). Eine naive Textersetzung aller Secret-Werte in
Logs würde Logs unbrauchbar machen. Daher:

1. **Primär strukturell:** Secrets werden in einem eigenen Typ (`Secret`, `repr` = `'***'`)
   gehalten und nie in Logzeilen formatiert.
2. **Sekundär textuell:** Der Log-Filter ersetzt Secret-Werte **nur ab 8 Zeichen** wörtlich.
   Kürzere Secrets sind ausschließlich durch Punkt 1 geschützt (dokumentierte Grenze).
3. Tests prüfen, dass `str()`, `repr()`, `format()` und JSON-Serialisierung eines `Secret`
   den Wert nie preisgeben.

## 4. Lizenzpflichten (siehe auch `LICENSING.md`, ADR-023)

- Eigener Code: MSOL 1.1 (keine Namensnennungspflicht); Scribbles/Logo: alle Rechte vorbehalten.
- Die folgenden AGPL-/GPL-Pflichten gelten für die Fremdteile:

- Das Gesamtwerk enthält AGPL-3.0-Code (KoboldCPP, KoboldAI Lite) und nutzt SearXNG (AGPL-3.0)
  und pjproject (GPL-2.0+). Wird moritz-agent **über ein Netzwerk für andere Nutzer**
  bereitgestellt (z. B. `https://ai.example-domain.de`), muss diesen Nutzern der Quellcode
  der laufenden Version angeboten werden → Footer-Link „Quellcode“ in der WebUI (Part 2) auf
  das Repo/den Tag.
- `LICENSE.md`, `MIT_LICENSE_GGML_SDCPP_LLAMACPP_ONLY.md` und alle Datei-Header bleiben
  unverändert. Neue Komponenten werden in `THIRD_PARTY_NOTICES.md` eingetragen, **bevor**
  sie gebündelt oder installiert werden.
- Modelle (LLM, Stimmen) haben eigene Lizenzen → ebenfalls in `THIRD_PARTY_NOTICES.md`.
- **Daten der Sofortauskünfte** (Plan [13](13-sofortauskuenfte.md) §7.1, §11): GeoNames (im Repo),
  Open-Meteo, DWD/Bright Sky, CAMS stehen unter **CC BY 4.0** → Namensnennung in
  `THIRD_PARTY_NOTICES.md`, `LICENSING.md` und auf der Über-Seite der WebUI (Part 2). Die freie
  Open-Meteo-API ist nur für nicht kommerzielle Nutzung (privates Homelab: erfüllt). NINA, OpenLigaDB,
  Tankerkönig, Energy-Charts und die Nachrichtenquelle: Bedingungen werden im jeweiligen Ticket geprüft
  und eingetragen, **bevor** der erste Abruf eingebaut wird.

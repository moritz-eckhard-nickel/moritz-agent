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
| T15 | Antworttexte verlassen das Haus (Polly „Hans“, Standard) | nur Antworttexte, nie Anrufer-Audio; IAM-Benutzer nur mit `polly:SynthesizeSpeech`; Budget-Alarm; Piper als lokale Alternative | ADR-008 |
| T16 | Manipulierte Fremdkomponenten im Repo | Herkunft + Commit in `third_party/VENDORED.md`, PyPI-Pakete nur mit `--require-hashes` | ADR-021 |
| T9 | Interne Dienste aus LAN erreichbar | KoboldCPP/SearXNG/interne API nur auf 127.0.0.1, Per-Start-Token | NFR-07, ADR-004 |
| T10 | Supply-Chain (Modelle, pip, pjproject, SearXNG) | SHA-256 für alle Downloads, `--require-hashes`, gepinnte Commits/Tags, keine `curl \| bash` | INST-03, ADR-019 |
| T11 | Agent zerstört Host / LXC | Keine Shell im LXC, alle Ausführungstools nur in der Sandbox-VM, Dienstbenutzer ohne sudo, systemd-Härtung | SBX-01, P1-17 |
| T12 | Kompromittierte Sandbox greift Agent-LXC an | Sandbox darf nur Internet + Sophie-1 (F-10), Agent-API nur authentisiert, kein SSH zurück; SSH geht nur LXC → Sandbox | SBX-03 |
| T13 | Audio-/Transkript-Leck | Kein Audio auf Disk; Transkripte konfigurierbar + Retention; DB 0600 | PHONE-43, STORE-02 |
| T14 | Update bricht Telefonie | Drain, Backup, Health-Check, Rollback | UPD-01, UPD-07 |

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

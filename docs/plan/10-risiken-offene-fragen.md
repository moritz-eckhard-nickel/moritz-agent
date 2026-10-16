# 10 – Risiken und offene Fragen

## 1. Risiken

| # | Risiko | Wahrscheinlichkeit | Auswirkung | Gegenmaßnahme | Ticket |
| --- | --- | --- | --- | --- | --- |
| R1 | PJSUA2-Python-Binding schwer zu bauen; `AudioMediaPort`-Callbacks in Python instabil (GIL, Takt) | mittel | hoch | Spike zuerst; Callbacks minimal (nur Ringpuffer kopieren); Fallbacks ADR-005 | P1-11 |
| R2 | CPU-STT zu langsam für flüssiges Gespräch | mittel | hoch | Benchmark mehrerer Modelle; `base` oder Vosk als Fallback; später STT auf GPU, wenn VRAM reicht | P1-10 |
| R3 | 8B-Modell ruft Tools unzuverlässig auf / Deutsch holprig | mittel | mittel | Fast-Path für Zeit; Benchmark; Schema-Validierung + Retry; Modellwechsel | P1-02, P1-09 |
| R4 | Google/Bing blockieren SearXNG (Captcha) | hoch | mittel | Mehrere Engines, Engine-Suspend, ehrliche Fehlermeldung; „Google“ nur nennen, wenn tatsächlich geliefert | P1-08 |
| R5 | GPU-Treiber-Mismatch Host ↔ LXC nach Host-Update | mittel | hoch | Versionsprüfung im Updater/Status, Doku 06 §4.5 | P1-01, P1-16 |
| R6 | VRAM durch andere GPU-Nutzer knapp | niedrig–mittel | hoch | Inventar; Startprüfung freier VRAM; Kontext/Layer reduzieren | P1-01 |
| R7 | Asterisk-Konfiguration passt nicht (Codecs, direct_media, 999-Routing) | mittel | hoch | Checkliste 06 §6 früh mit Moritz klären | P1-01 |
| R8 | Kurze Secrets (`agent`) nicht textuell redigierbar | sicher | niedrig | Struktureller Schutz (`Secret`-Typ), Doku 08 §3 | P1-03 |
| R9 | Upstream-Merges kollidieren mit eigenen Änderungen | niedrig | mittel | ADR-001 (keine Upstream-Dateien ändern) | laufend |
| R10 | Echo/Selbsterkennung ohne Barge-in-Logik | niedrig (Part 1: Eingang beim Sprechen verworfen) | mittel | klarer Sprecherwechsel; AEC erst Part 7 | P1-12 |
| R11 | Conda-CUDA-Build im LXC braucht viel Platz/Zeit | mittel | niedrig | Plattenbudget 60 GB; Fallback offizielles Binary (ADR-015) | P1-02 |
| R12 | Piper-Projektwechsel (MIT → GPL, Repo-Umzug) / Paketpflege | niedrig | niedrig | Version pinnen, Lizenz geprüft (AGPL-kompatibel) | P1-10 |

## 2. Offene Fragen an Moritz

Bis zur Antwort gilt jeweils der genannte **Default**.

| # | Frage | Default bis zur Antwort |
| --- | --- | --- |
| F-01 | Asterisk: chan_pjsip oder chan_sip? Welche Codecs sind für `agent` erlaubt, ist `direct_media` aus, ist 999 bereits auf `agent` geroutet? (Checkliste 06 §6) | Annahme chan_pjsip, G.711 alaw; wird im Spike geprüft |
| F-02 | Ist das GitHub-Repo öffentlich oder privat? (Bestimmt, ob die SIP-Startwerte in `config/passwords.template.txt` bleiben dürfen – Originalplan: öffentlich nur bereinigte Vorlage.) | Vorlage enthält die Startwerte (internes LAN-Konto). Wird das Repo öffentlich: Passwort aus Vorlage entfernen **und** in Asterisk ändern |
| F-03 | Sollen Gesprächstranskripte (Text) gespeichert werden, und wie lange? | Ja, 30 Tage, abschaltbar (`storage.store_transcripts`) |
| F-04 | Soll die Web-UI im LAN erreichbar sein (welche IP/Hostname) oder nur lokal/per SSH-Tunnel? TLS über vorhandenen Reverse-Proxy? | nur `127.0.0.1`; LAN-Bindung im Installer wählbar |
| F-05 | Distribution für den LXC? | Debian 12 |
| F-06 | Proxmox-Version, NVIDIA-Treiber am Host bereits installiert? Nutzt ein anderer Gast die GPU? | wird im Inventar (P1-01) erfasst |
| F-07 | CPU-Modell von Sophie-1 und wie viele Kerne darf der LXC nutzen? | Kerne − 2 |
| F-08 | Stimme: männlich (Thorsten) oder weiblich (Kerstin/Eva)? Name „Agent“ in der Begrüßung bleibt? | Thorsten, „Agent“ |
| F-09 | Welche Suchmaschinen sind gewünscht/akzeptabel, wenn Google blockiert? | google, bing, duckduckgo, brave, wikipedia, qwant |
| F-10 | Zeitplan/Ressourcen für Redemption-1-Sandbox und VLAN/OPNsense-Regeln? | Part 4; Installer erlaubt „später“ |
| F-11 | Sollen die alten KoboldCPP-Oberflächen (KoboldAI Lite, `/lcpp`) für Admin-Zwecke erreichbar bleiben? | nur über Loopback/SSH-Tunnel |
| F-12 | Windows-Unterstützung: wann relevant? | nach 1.0 |
| F-13 | Soll der Agent auch Datum/Wochentag, Wetter etc. als feste Fast-Paths bekommen? | Datum ja (gleiches Tool), Wetter über Suche |

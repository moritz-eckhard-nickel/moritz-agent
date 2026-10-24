# Part 1 komplett testen: `./test-3.sh`

`test-3.sh` testet **alles aus test-2** (Telefon, Stimme, Sofortauskünfte, Wetter, Discord) und dazu,
was Part 1 noch fehlte:

- das **Sprachmodell**: KoboldCpp mit Qwen3-30B-A3B auf der GPU (Ticket P1-02)
- das **Zuhören im Discord-Sprachkanal** (P1-32)

Gedacht ist es für Sophie-1, direkt auf dem Host ([sophie-1-bare-metal.md](sophie-1-bare-metal.md)).
Es läuft auf jedem Linux-Rechner mit NVIDIA-Treiber. Es gibt keine Ja/Nein-Fragen, gefragt wird nur
nach Werten wie Token und Kanal.

## Einrichten

```bash
./test-3.sh setup
```

| Schritt | Was passiert | Beim zweiten Mal |
| --- | --- | --- |
| 1 | `models/` wird ein Link auf **`/home/models`**; Modelle, die schon im Ordner lagen, ziehen um | nichts |
| 2 | alles aus `./test-2.sh setup` (Python, PJSIP, Stimme, Konfiguration, Discord-Werte) | nur Geändertes |
| 3 | Qwen3-30B-A3B-Instruct-2507 UD-Q3_K_XL (13,8 GB) und, wenn Platz ist, die Ersatzmodelle aus ADR-016 (Q3_K_S, Q4_K_M, Qwen3-14B; ≈ 41 GB) | nichts (liegt im Cache) |
| 4 | KoboldCpp bauen: beim ersten Mal mit eigener CUDA-Umgebung (15–40 min) | nur wenn sich die C/C++-Quellen geändert haben |
| 5 | Zuhören im Sprachkanal: eigene Umgebung `runtime/discord-venv` mit dem DAVE-fähigen Fork | nur bei geänderten Lock-Dateien |

Optionen:

| Option | Wirkung |
| --- | --- |
| `--models-dir DIR` | anderer Cache statt `/home/models` |
| `--no-fallback` | nur das Hauptmodell laden |
| `--cpu` | ohne GPU bauen |
| `--rebuild` | KoboldCpp frisch bauen |
| `--no-voice-recv` | kein Zuhören im Sprachkanal |
| `--skip-models` | nichts herunterladen |

## Testen

```bash
./test-3.sh run            # alles, danach Live-Test (Strg+C beendet)
./test-3.sh run --auto     # nur automatisch (Exit-Code 0 = alles grün)
./test-3.sh live           # nur der Live-Test
```

| # | Schritt | Was geprüft wird |
| --- | --- | --- |
| 1 | alles aus test-2 | Selbsttest, pytest, Sofortauskünfte, Datendienste, Testanruf, Discord (`--no-call`, `--no-discord`, `--no-pytest` gehen weiter) |
| 2 | Sprachmodell bereit | Modelldatei da, KoboldCpp gebaut, GPU sichtbar |
| 3 | Sprachmodell messen | `--moecpu` so einstellen, dass ≥ 600 MB VRAM frei bleiben, und in die Konfiguration schreiben (`--no-tune` misst nur). Danach 40 Telefonfragen direkt an den Agenten: erste Worte, ganze Antwort, Tokens/s, richtiges Werkzeug → `runtime/test-3/llm-bench.md` |
| 4 | Zuhören im Sprachkanal | `runtime/discord-venv` ist da und kann DAVE entschlüsseln |
| 5 | Abnahmeprotokoll | `runtime/test-3/abnahme.md`, siehe unten |
| 6 | Live | Anton komplett **mit** Sprachmodell; Checkliste wie bei test-2 plus freie Fragen und Reden im Sprachkanal |

## Mitschrift

`setup` und `run` schreiben ihre ganze Ausgabe zusätzlich nach `runtime/test-3/setup.log` bzw.
`runtime/test-3/run.log`. Beim `run` gehört der Live-Test mit allen Logs von Anton dazu. Geht etwas
schief, schick einfach diese Datei. Zugangsdaten stehen nicht darin, weil sie nie ausgegeben werden.

## Das Abnahmeprotokoll

Abnahme heißt: auf Sophie-1 einmal nachweisen, dass Part 1 wirklich funktioniert. Danach gilt ein
Ticket als erledigt.

- `run` trägt alles, was ein Skript prüfen kann, schon in `runtime/test-3/abnahme.md` ein: Ergebnisse,
  Messwerte, GPU und Version.
- Übrig bleibt eine kurze Liste zum Abhaken, die nur ein Mensch prüfen kann: anrufen, zuhören,
  im Sprachkanal reden.

Abgehakt deckt das Protokoll die Tickets P1-02, P1-18, P1-30, P1-32 und P1-42 ab. Die alten Vorlagen in
`docs/abnahme/` musst du dann nicht mehr von Hand ausfüllen.

## Aufräumen

```bash
./test-clearup.sh          # alles aus den Testskripten (auch KoboldCpp-Build und conda/); /home/models bleibt
./test-clearup.sh --all    # dazu auch /home/models
./test-clearup.sh --venv   # nur die Python-Umgebungen (auch runtime/discord-venv)
```

# Alles ausprobieren: `./test-2.sh`

`test-2.sh` testet **alles, was Anton bis heute kann**, in einem Durchgang: Telefon und Stimme (wie
[`test-1.sh`](telefon-test-1.md), das es mitbenutzt), Sofortauskünfte, Wetter und Datendienste, Eieruhr,
Discord mit Textkanal, Befehlen, Sprachnachrichten und Sprachkanal und den kompletten Dienst mit
Weboberfläche. Wie test-1 läuft es auf jedem Linux-Rechner ohne Systeminstallation; alles landet unter
`runtime/`, `models/` und im Repository-Ordner.

> **Regel ab jetzt:** Jede große Erweiterung bekommt ein neues `test-N.sh` mit `setup` und `run`, das
> alles Bisherige mit testet. Es gibt **keine Ja/Nein-Fragen** – Downloads laufen ohne Rückfrage, gefragt
> wird nur nach Werten wie Token und Kanal-IDs.

## Einrichten

```bash
sudo apt install build-essential python3-venv python3-dev swig pkg-config espeak-ng   # einmalig, falls fehlt
./test-2.sh setup
```

`setup` baut die Python-Umgebung und PJSIP, lädt die Modelle (≈ 0,6 GB, ohne Rückfrage), legt
`config/moritz-agent.toml` und `passwords.txt` an und installiert pytest für die automatischen Tests.
Danach fragt es nur drei Werte ab – **Enter** überspringt bzw. behält den bisherigen Wert:

| Frage | Woher | Wohin |
| --- | --- | --- |
| Bot-Token (unsichtbar) | Developer Portal → Anwendung → Bot → *Reset Token* ([Anleitung](discord-einrichtung.md)) | `passwords.txt` `[discord] bot_token` |
| Textkanal für Nachrichten | Nummer aus der angezeigten Liste oder Kanal-ID | `passwords.txt` `[discord] channel_id` |
| Sprachkanal für `/joinvc` | Nummer aus der Liste oder Kanal-ID | `config/moritz-agent.toml` `[discord.voice] default_channel_id` |

Gibt es auf dem Server nur **einen** Text- bzw. **einen** Sprachkanal, wird er ohne Frage genommen.
Ist Anton noch auf keinem Server, zeigt `setup` den Einladungslink und fragt bis zu fünfmal nach
(Enter = nochmal suchen). Wichtig: den Link **„Zum Server hinzufügen“** nehmen – als *Benutzer-App*
installiert, ist der Bot auf keinem Server.

**Neue Version über den alten Ordner entpackt?** Einfach wieder `./test-2.sh setup`: Python-Umgebung,
PJSIP-Build, Modelle und Ansagen bleiben und werden nur neu gebaut bzw. geladen, wenn sich etwas
geändert hat (die Lock-Dateien, die PJSIP-Version oder ein Modell). Wer Discord-App-Besitzer ist, ist
automatisch Owner – die eigene ID muss nirgends eingetragen werden.

## Testen

```bash
./test-2.sh run            # automatische Tests, danach Live-Test (Strg+C beendet)
./test-2.sh run --auto     # nur die automatischen Tests (Exit-Code 0 = alles grün)
```

| # | Schritt | Was geprüft wird | Braucht |
| --- | --- | --- | --- |
| 1 | Selbsttest | Umgebung, SIP-Stack, Whisper, Stimmen, Ansagen, Ports (`./test-1.sh check`) | Modelle |
| 2 | Automatische Tests | die ganze Testsuite (`pytest`, ≈ 2 500 Tests, ≈ 4 min) | – (`--no-pytest` überspringt) |
| 3 | Sofortauskünfte | Testkorpus (> 800 Sätze) und 16 Beispielfragen mit erwarteter Antwort (Zeit, Kalender, Feiertage, Rechnen, Mehrwertsteuer, Umrechnen, Orte, Buchstabieren, Eieruhr, „Wer bist du?“) | – |
| 4 | Datendienste | Open-Meteo, Bright Sky, DWD, NINA, Pegel, EZB …, dazu Wetter, Warnungen und Pollen für Weilburg | Internet |
| 5 | Testanruf | echter SIP-Anruf an sich selbst mit Spracherkennung und Stimme | espeak-ng (`--no-call` überspringt) |
| 6 | Discord | Token, Portal-Einstellungen, Server und Kanal; Slash-Befehle registrieren; Testnachricht | Token (`--no-discord` überspringt) |
| 7 | Live | Anton komplett: Telefon (999, „Leg auf“), Discord (Text, Sprachnachricht, Sprachkanal, Rückruf auf die 201), Weboberfläche – mit Checkliste | – |

Das Ergebnis steht am Ende als ✔/✘/– und in `runtime/test-2/ergebnis.txt`. Einzelbefehle (`speak`,
`ask`, `call`, `discord …`) gibt es weiter in `./test-1.sh`.

## Aufräumen

```bash
./test-clearup.sh          # alles, was die Testskripte angelegt haben: Umgebungen, PJSIP-Build, Modelle,
                           # Ansagen-Cache, Testläufe, data/ – passwords.txt und config/moritz-agent.toml bleiben
./test-clearup.sh --venv   # nur die Python-Umgebungen (z. B. vor einem frischen setup)
```

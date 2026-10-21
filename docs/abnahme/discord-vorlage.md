# Abnahmeprotokoll P1-42: Discord

Vorlage – für die Abnahme nach `discord-<datum>.md` kopieren und ausfüllen. Maßgeblich ist
[Plan 14 §21](../plan/14-discord.md#21-abnahme); Einrichtung nach
[../discord-einrichtung.md](../discord-einrichtung.md). Voraussetzung: Ergebnis des
[Spikes P1-32](p1-32-discord-spike.md) (Sprachempfang ja/nein).

Stand der Entwicklung: **offen** – der Bot ist **nie gegen das echte Discord-Gateway gelaufen**. Alles
Logische (Zugriff, Stil, Befehle, Verteiler, Sprachsitzung) ist mit einem Fake-Discord und dem echten
Hauptprozess getestet (`test_discord_*`); die Spalte „Automatisch belegt“ zeigt, wo.

Durchführung auf einem privaten Server (Moritz + Nikita), in einer DM und mit der Benutzer-App.

| # | Prüfung | Erwartung | Automatisch belegt | Ergebnis | Datum / Wer |
| --- | --- | --- | --- | --- | --- |
| 1 | Setup mit Token-Eingabe (`./test-1.sh discord token`); zweiter Lauf | Token nur in `passwords.txt` (0600), Einladungslinks korrekt; zweiter Lauf ändert nichts | `test_setup_discord` | offen | |
| 2 | DM „wie isses wedder morsche?“ | Karte für **Weilburg**, Quelle in der Fußzeile, Folgeknöpfe funktionieren | `test_discord_dispatch` | offen | |
| 3 | `/wetter ort:` mit Autovervollständigung, PLZ 60311, „Neustadt“ | richtige Orte, Auswahlliste bei Mehrdeutigkeit | `test_discord_client` | offen | |
| 4 | Benutzer-App in fremdem Server/Gruppen-DM | `/wetter` geht, Antwort nur für mich sichtbar | – (nur real prüfbar) | offen | |
| 5 | Fremde Person schreibt Nikita / erwähnt sie | keine Reaktion (bzw. Hinweis bei `notice`) | `test_discord_logic` (Zugriff) | offen | |
| 6 | Bot in nicht erlaubten Server einladen | geht nicht (Public Bot aus) bzw. Nikita verlässt ihn | `test_discord_client` | offen | |
| 7 | `/joinvc`, Sprachkanal betreten; drei Fragen ohne „Nikita“; Unterbrechen; „Tschüss“ | Begrüßung wie am Telefon, Antworten gesprochen, Unterbrechen < 300 ms, Abschied und Verlassen | `test_discord_voice` (FakeVoiceClient) | offen | |
| 7a | Im Sprachkanal schweigen; Kanal verlassen und wieder betreten | „Bist du noch da?“ → Ruhe-Modus, „Nikita“ weckt; Verlassen = Auflegen | `test_discord_voice` | offen | |
| 7b | Standardkanal: Frage ohne Erwähnung; Erinnerung und Warnungs-Abo | Antwort ohne Erwähnung; Erinnerung/Warnung landen im Standardkanal | `test_discord_dispatch`, `test_supervisor` | offen | |
| 7c | Stil und Aktivitäten eine Stunde beobachten; Warnung (Fixture) | süß, aber Fakten exakt; Aktivitäten wechseln, keine Wiederholung unter 10; bei Warnung Ernst-Modus | `test_discord_logic` | offen | |
| 8 | Sprachkanal + gleichzeitiger Anruf an 999 | Telefon unbeeinträchtigt (Latenz wie ohne Discord) | – (nur real prüfbar) | offen | |
| 9 | Sprachnachricht senden | Transkript + Antwort, optional als Sprachnachricht (derzeit als OGG-**Datei**, C.2 in Plan 04) | `test_discord_speech` | offen | |
| 10 | `/erinnere wann: in 2 Minuten`, Dienst zwischendurch neu starten | Erinnerung kommt (ggf. „verspätet“) | `test_supervisor`, `test_discord_core` | offen | |
| 11 | Warnungs-Abo mit Test-Warnung (Fixture) | DM kommt, Ruhezeit beachtet | `test_discord_core` | offen | |
| 12 | `/admin status`, `/admin logs`, `/admin wartung` als Owner und als Vertrauter | Owner: geht mit Bestätigung (PIN, falls gesetzt); Vertrauter: verweigert | `test_discord_dispatch` | offen | |
| 13 | Token-Suche über alle Logs/Statusdateien | kein Treffer | `test_redaction`, `test_discord_client` | offen | |
| 14 | Token im Portal neu erzeugen, eintragen, neu laden | Verbindung mit neuem Token, alter ungültig | – (nur real prüfbar) | offen | |
| 15 | Ab P1-09: `/frag` mit Websuche | Antwort gestreamt, Quellen als Links | `test_discord_dispatch` (ScriptedCore) | offen | |
| 16 | Slash-Befehle erscheinen (global registriert, ≤ ein paar Minuten) | `/hilfe` listet nur aktive Funktionen | `test_discord_logic` (Spec) | offen | |
| 17 | Telefon ↔ Discord: Anrufhinweis-Abo, `/anrufe`, „Schick das aufs Handy/Discord“ | Hinweis nach dem Anruf ohne Inhalt, Weiterleitung kommt an | `test_discord_core`, `test_dialogue` | offen | |

## Fazit

Abgenommen: ☐ ja ☐ mit Auflagen ☐ nein – Auflagen/Fehler:

Fragen F-29 … F-40 ([14 §23](../plan/14-discord.md#23-offene-fragen-an-moritz)): bestätigt / geändert:

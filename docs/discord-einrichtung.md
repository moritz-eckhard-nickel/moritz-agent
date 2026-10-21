# Anton auf Discord einrichten

Anton kann auf Discord antworten wie am Telefon: im Textkanal, in Direktnachrichten, mit
Slash-Befehlen, auf Sprachnachrichten – und im Sprachkanal (`/joinvc`) wie in einem Anruf. Er ist ein
**offizieller Discord-Bot** (nie ein Selbst-Bot mit dem Konto einer Person) und läuft nur auf deinem
**privaten Server** mit dir und ihm. Der vollständige Plan steht in
[plan/14-discord.md](plan/14-discord.md).

> Was Anton auf Discord **nie** tut: Zugangsdaten ausgeben, `@everyone` pingen, auf Fremde antworten,
> Shell-Befehle ausführen, Updates starten, Telefon-Mitschnitte schicken (außer du schaltest es ein).

## 1. Im Discord Developer Portal (einmalig, ca. 10 Minuten)

Öffne <https://discord.com/developers/applications> (mit deinem Discord-Konto; **2FA am Konto
einschalten** wird dringend empfohlen).

1. **New Application** → Name `Anton`. Als Bild passt `assets/branding/discord-avatar.png` (Scribbles, weiß auf
   dunkel) – oder später `./test-1.sh discord profile`, das Profilbild und Beschreibung des Bots setzt.
2. Links **Bot**:
   * **Public Bot: aus** – sonst könnte jeder Anton auf seinen Server holen.
   * **Message Content Intent: an** – ohne ihn sieht Anton den Text deiner Nachrichten nicht.
   * **Reset Token** → den Token kopieren. Er ist wie ein Passwort: wer ihn hat, steuert den Bot.
     Er gehört nur in `passwords.txt` (nie in Chats, Screenshots oder Git).
3. Links **Installation**: *Guild Install* und *User Install* an; Scopes `bot` und
   `applications.commands`. Rechte (Permissions): Kanäle ansehen, Nachrichten senden, in Threads
   senden, öffentliche Threads erstellen, Links einbetten, Dateien anhängen, Nachrichtenverlauf lesen,
   Reaktionen hinzufügen, Verbinden, Sprechen, Sprachaktivierung, Sprachnachrichten senden – **keine**
   Administrator- oder Verwaltungsrechte. (Die fertigen Einladungslinks erzeugt das Setup für dich.)
4. In Discord (Einstellungen → Erweitert): **Entwicklermodus** einschalten.

## 2. Server und Kanäle

1. Eigenen Server anlegen (nur du und Anton).
2. Darin einen Textkanal, zum Beispiel `#anton` – das ist Antons **Zuhause** (Standardkanal): dort
   antwortet er auf *jede* Nachricht von dir ohne Erwähnung, dort landen Erinnerungen, Warnungen und
   Hinweise. Außerdem einen Sprachkanal für `/joinvc`.

## 3. In moritz-agent einrichten

### Mit dem Installer (`moritz-install.sh`, im LXC)

Die Phase `discord` fragt nach dem Token (**unsichtbar**, Enter = ohne Discord),
prüft ihn bei Discord (der Bot-Name wird angezeigt), speichert ihn **nur** in `passwords.txt`
(Zeile `bot_token`), schaltet Discord in `config/moritz-agent.toml` ein, trägt dich als Owner ein,
zeigt die **Einladungslinks** und lässt dich Textkanal und Sprachkanal aus einer Liste wählen. Mit
`--non-interactive` wird nichts abgefragt – dann wie unten von Hand.

### Am einfachsten: `./test-2.sh setup`

Fragt nacheinander Token, Textkanal und Sprachkanal ab (Enter = überspringen) und testet danach mit
`./test-2.sh run` alles – siehe [test-2.md](test-2.md).

### Zum Ausprobieren ohne LXC (`./test-1.sh discord …`)

```bash
./test-1.sh setup                 # einmalig (falls noch nicht geschehen)
./test-1.sh discord token         # Token eingeben (bleibt unsichtbar), prüfen, speichern
./test-1.sh discord check         # prüft Token, Portal-Einstellungen, Server, Kanal; zeigt Einladungslinks
#  → den Server-Link öffnen und Anton auf deinen Server holen
./test-1.sh discord channel       # Standardkanal aus der Liste wählen (oder Kanal-ID eingeben)
./test-1.sh discord profile       # Profilbild (Scribbles) und Beschreibung des Bots setzen
./test-1.sh discord run           # Bot starten (Strg+C beendet); Befehle und Sofortauskünfte gehen,
                                  # das Sprachmodell nicht (das gehört zum Dienst)
./test-1.sh discord say "Guude!"  # Testnachricht in den Standardkanal
```

### Von Hand

In `passwords.txt` (Abschnitt `[discord]`):

```ini
[discord]
bot_token = …            # leer = Discord aus
channel_id = 123…        # Rechtsklick auf #anton → Kanal-ID kopieren
admin_pin =              # optional: PIN für gefährliche Admin-Befehle
```

In `config/moritz-agent.toml`:

```toml
[discord]
enabled = true
owner_user_ids = ["123…"]    # deine Discord-ID (Rechtsklick auf dich → Benutzer-ID kopieren)
```

Danach `systemctl reload moritz-agent` (oder in Discord `/admin neu-laden`). Der Discord-Teil läuft
als eigener Prozess; ein Fehler dort stört das Telefon nicht.

## 4. Benutzung

* Im Standardkanal und in Direktnachrichten einfach schreiben: „Wie wird das Wetter morgen?“.
  In anderen Kanälen: `@Anton …` oder „Anton, …“ am Satzanfang.
* Slash-Befehle: `/hilfe` zeigt, was gerade wirklich geht (`/wetter`, `/warnungen`, `/timer`,
  `/erinnere`, `/abo`, `/einstellungen`, `/joinvc`, …). Nicht aktive Funktionen werden nicht angeboten.
* **Abos** (`/abo`): Unwetterwarnungen, Morgenbriefing, Müllabfuhr, Anrufhinweise – Anton schreibt nur
  von sich aus, wenn du es bestellt hast (Ruhezeit standardmäßig 22–7 Uhr, nur Unwetter ab Stufe 3 gehen
  durch).
* **Sprachnachrichten**: eine Sprachnachricht schicken – Anton zeigt klein, was er verstanden hat, und
  antwortet (auch als Audio, einstellbar mit `/einstellungen sprachantwort`).
* **Sprachkanal**: in einen Sprachkanal gehen, `/joinvc` – Anton kommt dazu und verhält sich wie im
  Anruf. Siehe [plan/14 §9](plan/14-discord.md#9-sprachkanal).
* **Süß und schelmisch**: Anton schreibt freundlich mit Emojis und zeigt wechselnde Aktivitäten
  („Spielt Verstecken mit deinen Bits“). Mit `style = "normal"` unter `[discord]` ist das aus,
  `/aktivitaet aus` blendet die Aktivitäten aus.

## 5. Weitere Personen

* `trusted_user_ids = ["…"]` unter `[discord]`: dürfen Sofortauskünfte, Chat und eigene Abos nutzen,
  aber kein Admin und nicht an Moritz’ Notizen.
* Alle anderen werden ignoriert (Standard). Taucht eine fremde Person auf deinem Server auf, schreibt
  Anton einmal einen Hinweis in den Standardkanal. Einladungen auf **fremde** Server verlässt er sofort
  wieder.

## 6. Token wechseln oder zurückziehen

Bei Verdacht (Token geteilt, falsch eingefügt): im Developer Portal **Reset Token**, den neuen Token
mit `./test-1.sh discord token` (bzw. der Installer-Phase `discord`, oder von Hand in `passwords.txt`)
eintragen und neu laden – Anton verbindet sich dann neu. Den Bot ganz abschalten: `bot_token` leeren
oder `enabled = false`.

## 7. Wenn etwas nicht geht

| Beobachtung | Ursache / Abhilfe |
| --- | --- |
| `check`: „Der Message Content Intent ist aus“ | Portal → Bot → *Message Content Intent* einschalten |
| Anton antwortet nicht im Kanal | Kanal-ID stimmt? (`./test-1.sh discord check`), hat Anton dort „Nachrichten senden“? |
| Slash-Befehle fehlen | Beim Start werden sie nur bei Änderungen registriert; erzwingen: `python -m moritz_agent.discord sync-commands`. Dauer bis zur Anzeige: wenige Minuten |
| „Der Bot-Token wurde abgelehnt“ | Token abgelaufen/zurückgesetzt – neuen eintragen |
| Anton verlässt den Server | Es war nicht der Server des Standardkanals (Absicht, siehe oben) |
| Sprachkanal: Anton hört nichts | Discord verschlüsselt Sprache Ende-zu-Ende (DAVE); der Empfang ist ein Prüfpunkt (Ticket P1-32) – ohne ihn bleibt „nur sprechen“ ([plan/14 §9.5](plan/14-discord.md#95-dave-und-rückfallwege-adr-036)) |

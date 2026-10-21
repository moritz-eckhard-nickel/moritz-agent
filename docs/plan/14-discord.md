# 14 – Discord: Nikita als Discord-Bot mit allen Funktionen

Stand: 20.10.2026 (Umsetzungsstand und Abweichungen: [04 Anhang C](04-part1-umsetzung.md#anhang-c--umsetzungsstand-und-abweichungen-stand-21102026)) · Tickets: [04 Block D](04-part1-umsetzung.md#block-d--discord-bot) (P1-31 … P1-43) ·
Anforderungen: [01 §2a](01-anforderungen.md#2a-discord-discord) (DISCORD-01 … DISCORD-47) ·
Entscheidungen: ADR-033 … ADR-037 ([03](03-entscheidungen.md)).

> Moritz, 20.10.2026: „Plane bitte noch für Step One eine KOMPLETTE Discord-User-Integration mit ALLEN
> FEATURES, die Nikita jemals hat, und mach ihn zu einem Bot. Beim Setup gibt man dann den Token ein –
> oder auch in die TXT mit den Sachen. Plane auch mal wieder nur.“
>
> Nachtrag, 20.10.2026: „Mache den User bitte bissl cutey. Alles muss gehen in der Zukunft. Er soll
> als Aktivitäten coole Sachen haben wie ‚spielt mit deinen Daten‘ – schelmisch, funny. Ein
> Standard-Textkanal für alles braucht auch eine ID, die man beim Setup oder in der TXT angibt. Mit
> `/joinvc` kann er dem Sprachkanal beitreten und verhält sich dann wie im Anruf, sobald ein anderer
> User dem Kanal beitritt – das ist ein Server mit dem User und ihm, also gibt es kein ‚welcher User‘.“

**Ziel:** Nikita ist neben dem Telefon (999) und der WebUI auch auf **Discord** erreichbar – als
offizieller **Bot** (kein Benutzerkonto), den man in eigene Server einlädt **und** als
„Benutzer-App“ an das eigene Discord-Konto hängt, sodass Moritz Nikitas Befehle in jedem Chat
benutzen kann. Auf Discord kann Nikita **alles, was sie auf irgendeinem Weg kann** – heute die
Sofortauskünfte ([13](13-sofortauskuenfte.md)), mit P1-09 das Sprachmodell und die Websuche, mit
jedem späteren Part dessen Funktionen (Recherche, Gedächtnis, Coding in der Sandbox, Browser, …).
Dazu kommt, was nur Discord kann: Sprachkanäle, Sprachnachrichten, Knöpfe und Auswahllisten,
Threads, Dateien, Erinnerungen und Benachrichtigungen per Direktnachricht. Der Token kommt beim
Setup per verdeckter Eingabe oder direkt in `passwords.txt` (Abschnitt `[discord]`).

Inhalt: [1 Leitlinien](#1-leitlinien) · [2 So sieht das aus](#2-so-sieht-das-aus) ·
[3 Discord-Grundlagen](#3-discord-grundlagen-die-der-plan-nutzt) · [4 Architektur](#4-architektur) ·
[5 Zugriff und Sicherheit](#5-zugriff-und-sicherheit) · [6 Funktionsumfang](#6-funktionsumfang-alle-funktionen-auf-allen-kanälen) ·
[7 Befehle](#7-befehle-slash-befehle-kontextmenüs-autovervollständigung) · [8 Text](#8-text-auf-discord) ·
[9 Sprachkanal](#9-sprachkanal) · [10 Sprachnachrichten](#10-sprachnachrichten) ·
[11 Proaktive Nachrichten](#11-proaktive-nachrichten-und-erinnerungen) · [12 Telefon und Discord](#12-telefon-und-discord) ·
[13 Admin](#13-admin-befehle-nur-owner) · [14 Einrichtung](#14-einrichtung) · [15 Konfiguration](#15-konfiguration) ·
[16 Daten und Logs](#16-daten-und-logs) · [17 Abhängigkeiten](#17-abhängigkeiten-und-lizenzen) · [18 Tests](#18-tests) ·
[19 Latenz und Ressourcen](#19-latenz-und-ressourcen) · [20 Umsetzung](#20-umsetzung-block-d) ·
[21 Abnahme](#21-abnahme) · [22 Risiken](#22-risiken) · [23 Offene Fragen](#23-offene-fragen-an-moritz)

---

## 1. Leitlinien

1. **Ein Kern, viele Kanäle.** Discord ist ein weiterer Eingang wie das Telefon – nicht eine zweite
   Nikita. Sofortauskünfte, Sprachmodell, Tools, Gedächtnis und Regeln liegen in einem
   kanalunabhängigen Kern; der Discord-Adapter übersetzt nur Ein- und Ausgabe (ADR-034).
2. **Kanal-Parität.** Jede Funktion, die Nikita bekommt, gibt es auch auf Discord – im selben Ticket
   oder begründet ausgenommen (Matrix §6, DoD-Punkt in [04](04-part1-umsetzung.md)).
3. **Offizieller Bot, kein Self-Bot.** Nikita läuft als Bot-Konto einer eigenen Discord-Anwendung.
   Ein Benutzer-Token („Self-Bot“) verstößt gegen die Discord-Nutzungsbedingungen und riskiert
   Moritz’ Konto – das wird nie gebaut (ADR-033).
4. **Discord ist Internet, nicht LAN.** Das Telefon ist nur intern erreichbar, Discord von überall.
   Deshalb gilt **Standard: verweigern** – Nikita reagiert nur auf freigegebene Personen und Server;
   Admin-Funktionen nur für den Owner und nur mit Bestätigung (ADR-035).
5. **Kein offener Port.** Discord liefert Nachrichten und Befehle über eine ausgehende
   WebSocket-Verbindung (Gateway). Es gibt keine öffentliche Adresse, keine Portfreigabe, kein
   Webhook-Endpunkt.
6. **Telefon hat Vorrang.** Ein Anruf an 999 geht immer vor: Discord-Sprache und -Text laufen mit
   niedrigerer Priorität und stören das Telefon nie (PHONE-41).
7. **Secrets bleiben im Haus.** Der Bot-Token steht nur in `passwords.txt`, wird nie geloggt, nie
   ausgegeben und nie als Argument übergeben. Nikita gibt auf Discord nie Zugangsdaten, interne
   Logs oder Konfigurationswerte preis – auch nicht dem Owner im Klartext.
8. **Was bei Discord liegt, liegt bei Discord.** Textnachrichten sind bei Discord nicht
   Ende-zu-Ende-verschlüsselt und bleiben dort gespeichert. Telefon-Transkripte, Notizen und
   Systemdetails gehen deshalb nur auf ausdrücklichen Wunsch dorthin.
9. **Ehrlich und deterministisch wie am Telefon.** Uhrzeit-Garantie (AGENT-06), Wetter-Garantie
   (AGENT-11) und „nichts erfinden“ (SKILL-02) gelten auf Discord genauso; Quellen stehen auf
   Discord immer als Link dabei.
10. **Privatserver: Moritz + Nikita.** Nikitas Server ist ein privater Server, auf dem nur Moritz und
    Nikita sind. Es gibt einen **Standard-Textkanal für alles** (ID beim Setup oder in
    `passwords.txt`): dort antwortet Nikita auf jede Nachricht ohne Erwähnung, und dort landen
    Erinnerungen, Warnungen und Hinweise. Im Sprachkanal gibt es **keine Sprecherauswahl und kein
    Weckwort** – wer mit Nikita im Kanal ist, ist „der Anrufer“ (§9). Die Allowlist bleibt nur als
    Sicherheitsnetz, falls doch einmal jemand Fremdes auf den Server kommt (ADR-035).
11. **Ein bisschen süß.** Auf Discord ist Nikita „cutey“: verspielter Ton, kleine Emojis und
    Kaomojis, schelmische Aktivitäten („Spielt mit deinen Daten 😈“). Die Fakten bleiben exakt, bei
    Unwettern, Fehlern und Admin-Sachen ist Schluss mit lustig (§8.2, §8.5, ADR-037).
12. **Alles muss gehen – auch in Zukunft.** Kanal-Parität ist Pflicht für jedes künftige Ticket (§6).

## 2. So sieht das aus

```text
Mitgliederliste:  🟢 Nikita ✨   Spielt mit deinen Daten 😈        (Aktivität wechselt alle paar Minuten, §8.5)

Standard-Textkanal #nikita (keine Erwähnung nötig)
  Moritz:  wie isses wedder morsche?
  Nikita:  Morgen wird’s in Weilburg ein bisschen ungemütlich ☔ (｡•́︿•̀｡)
           ┌ Wetter morgen in Weilburg ─────────────────────────┐
           │ Mittwoch, 21. Oktober · wechselhaft · 8 bis 13 °C  │
           │ 🌧 Regen 70 % (vormittags) · 💨 Böen 45 km/h SW     │
           │ Wetterdaten: Open-Meteo.com (CC BY 4.0) · DWD      │
           └────────────────────────────────────────────────────┘
           [Heute] [Wochenende] [7 Tage] [Warnungen] [Andere Stadt …]

Slash-Befehl in einem beliebigen Chat (Benutzer-App)
  /wetter ort: Frankf…        → Autovervollständigung: „Frankfurt am Main (60311 …)“, „Frankfurt (Oder)“

Mehrdeutig
  Moritz:  wetter in neustadt
  Nikita:  Uii, da gibt’s mehrere 👀 Welches Neustadt meinst du?
           [Auswahl: Neustadt (Hessen) · Neustadt an der Weinstraße · …]

Sprachkanal – „wie im Anruf“ (§9)
  Moritz:  /joinvc
  Nikita:  Bin unterwegs in 🔊 Quatschecke ✨                (Text)
  … Moritz ist im Sprachkanal →
  Nikita (spricht):  Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?
  Moritz (spricht):  Wann geht die Sonne unter?              (kein „Nikita, …“ nötig)
  Nikita (spricht):  Heute geht in Weilburg die Sonne um 18 Uhr 17 unter.
  Moritz (spricht):  Danke, tschüss.
  Nikita (spricht):  Alles klar, bis bald!                    (Gespräch zu Ende wie beim Auflegen)

Sprachnachricht
  Moritz schickt 🎤 0:04 „Wie viele Tage noch bis Weihnachten?“
  Nikita:  🎤 *Wie viele Tage noch bis Weihnachten?*
           Noch 65 Tage bis Heiligabend 🎄✨  (+ auf Wunsch als Sprachnachricht mit Nikitas Stimme)

Proaktiv im Standardkanal (abonniert)
  Nikita (06:45):  Guten Morgen, Moritz ☀️ Heute ist Donnerstag, der 22. Oktober. In Weilburg bewölkt bis
                   12 °C, ab Mittag Regen. Morgen wird die Biotonne abgeholt 🗑️
  Nikita (sofort): ⚠️ Unwetterwarnung für Weilburg: Sturmböen bis 85 km/h, bis heute 22 Uhr. [Details]
                   (ernst, ohne Späße)
```

Alle Werte sind Beispiele; die echten kommen aus den Quellen in [13 §7](13-sofortauskuenfte.md#7-wetter-im-detail).

## 3. Discord-Grundlagen, die der Plan nutzt

| Thema | Stand (Oktober 2026) | Folge für den Plan |
| --- | --- | --- |
| **Bot-Anwendung** | Anwendung im Developer Portal mit Bot-Benutzer und Token; Schalter „Public Bot“ legt fest, ob andere die App hinzufügen dürfen | „Public Bot“ **aus** – nur Moritz kann Nikita in Server einladen (DISCORD-03) |
| **Installationsarten** | *Server-Installation* (braucht „Server verwalten“ im Server) und *Benutzer-Installation* (App hängt am Konto; ihre Befehle gibt es dann in allen Servern, DMs und Gruppen-DMs des Benutzers, aber **nur Befehle**: sie liest dort keine Nachrichten und betritt dort keine Sprachkanäle) | beides aktiv: Server-Installation für Moritz’ eigene Server (Chat, Sprache, Threads), Benutzer-Installation für „/wetter überall“ |
| **Gateway** | ausgehende WebSocket-Verbindung; Ereignisse nach *Intents* | Intents: Server, Servernachrichten, Direktnachrichten, Reaktionen, Sprachstatus und **Message Content** (privilegiert, im Portal einzuschalten; ohne ihn sieht ein Bot Inhalte nur in DMs und bei Erwähnung). Nicht nötig: Mitgliederliste, Präsenzen |
| **Interaktionen** | Slash-Befehle, Kontextmenü-Befehle (Nachricht/Benutzer), Knöpfe, Auswahllisten, Formulare (Modals), Autovervollständigung; Antwort binnen 3 s oder „wird bearbeitet“, danach 15 min für Folgeantworten | jede Interaktion wird sofort bestätigt („Nikita denkt nach …“), Ergebnis als Folgeantwort |
| **Grenzen** | Nachricht 2.000 Zeichen; Embed-Beschreibung 4.096, Embed gesamt 6.000; max. 100 globale Slash-Befehle, je 25 Optionen/Unterbefehle; Kontextmenüs begrenzt (je Art wenige); Dateien ohne Server-Boost ≈ 10 MB (in P1-32 prüfen); Rate-Limits je Route und global | Aufteilen langer Antworten, große Ausgaben als Datei, Befehle gruppiert, Bearbeitungen gedrosselt |
| **Sprache** | Opus, 48 kHz, Stereo, 20-ms-Rahmen; **Ende-zu-Ende-Verschlüsselung (DAVE) ist seit März 2026 Pflicht** für alle Sprach- und Videoanrufe, ausgenommen Bühnenkanäle | Bibliothek muss DAVE können: Senden mit discord.py ≥ 2.7 + `davey` gelöst; **Empfangen** in Python nur über Erweiterungen/Forks mit DAVE-Entschlüsselung → Spike P1-32 (ADR-036) |
| **Sprachnachrichten** | Audio-Anhang (OGG/Opus) mit Wellenform und Dauer, Nachrichten-Flag „Sprachnachricht“ | Empfangen: einfacher Anhang (nicht E2EE); Senden als Sprachnachricht für Bots in P1-32 prüfen, sonst normale Audiodatei |
| **Erwähnungen** | `allowed_mentions` steuert, wer gepingt wird | Nikita pingt nie `@everyone`, `@here` oder Rollen; nur die Person, der sie antwortet |

## 4. Architektur

### 4.1 Ein Kern, mehrere Kanäle (ADR-034)

```text
  Telefon (SIP/RTP) ──► Phone-Worker ──────┐
                                           │  Turn(principal, channel, surface, text | audio, context)
  Discord (Gateway WSS, Voice UDP) ──► Discord-Worker ──┤
                                           │
  Browser (HTTPS :3501) ──► WebUI/API ─────┘
                                           ▼
                         ┌────────── Nikita-Kern ──────────┐
                         │ SkillResponder (Sofortauskünfte)│  erst Skills (13) …
                         │   └► Agent-Loop (ab P1-09)      │  … dann LLM mit Tools
                         │ Tools · Gedächtnis · Aufgaben   │
                         │ Ausgabeprofil je Oberfläche     │
                         └─────────────────────────────────┘
```

- **Principal** = wer fragt (`owner`, `trusted:<discord-id>`, `phone:<nebenstelle>`, `web:<login>`),
  mit Rolle und persönlichen Einstellungen (Heimatort, Abos, Stimme).
- **Channel** = Herkunft (`phone`, `discord`, `web`) und Ort (DM, Serverkanal, Thread, Sprachkanal).
- **Surface** = Ausgabeart: `spoken` (Telefon, Discord-Sprache: kurz, ohne Markdown, textnorm),
  `chat` (Discord-Text, WebUI: Markdown, Links, Embeds, längere Antworten).
- Skills liefern ab P1-31 neben `text` (gesprochen) auch `markdown` und eine strukturierte `card`
  (für Embeds/WebUI-Karten) sowie `actions` (Folgeaktionen → Knöpfe): Erweiterung von
  [13 §3.3](13-sofortauskuenfte.md#33-schnittstellen).
- Das LLM-Profil wird je Surface gewählt: `phone` (bestehend, 160 Tokens, 2–3 Sätze),
  `discord_voice` (wie phone), `discord_chat` (Markdown erlaubt, bis ≈ 600 Tokens, Quellen als Links).

### 4.2 Discord-Worker

- Eigener Prozess `python -m moritz_agent.discord run` (wie der Phone-Worker): Absturz, Hänger oder
  ein Bibliotheksfehler bei Discord reißen das Telefon nicht mit (PRD-02). Start durch den Supervisor
  (P1-04); bis dahin startet `moritz-agent run` beide Worker mit einer kleinen Prozessaufsicht
  (Neustart mit Backoff 2 s → 60 s) – der Teil von P1-04 wird dafür vorgezogen.
- Läuft mit niedrigerer CPU-Priorität (`nice +5`), damit Telefon-STT/TTS immer zuerst rechnen.
- Bis zur zentralen Main-API (P1-04/P1-14) benutzt der Worker den Kern als Bibliothek (wie heute der
  Phone-Worker); Wetter-Caches sind Dateien (`data/cache/skills/`) und werden geteilt; nur ein Prozess
  (der Phone-Worker) macht den Vorabruf. Mit dem LLM spricht der Worker über die interne API
  (`/internal/discord/turn`, Per-Start-Token, ADR-004) – die Inference-Warteschlange bleibt zentral.
- Statusdatei `data/run/discord-status.json` (jede Sekunde wie beim Telefon): verbunden, Latenz,
  Server, Sprachsitzung, letzte Fehler (ohne Token/Inhalte).
- Wartungsmodus: liegt `data/run/drain`, nimmt Nikita keine neuen Sprachsitzungen an, beendet eine
  laufende nach dem aktuellen Satz und antwortet auf Text mit „Ich werde gerade aktualisiert, gleich
  bin ich wieder da.“

```text
moritz_agent/discord/
├── __main__.py        run · check · invite · sync-commands
├── worker.py          Start, Verbindung, Wiederverbindung, Status, Drain, Reload (Token-Wechsel → neu verbinden)
├── client.py          discord.py-Client, Intents, Ereignis-Weiterleitung
├── access.py          Rollen, Allowlists, Rate-Limits (ADR-035)
├── sessions.py        Gesprächssitzungen je DM/Kanal/Thread/Sprachkanal, Kontext für Folgefragen
├── render.py          Kern-Antwort → Nachricht/Embed/Knöpfe/Datei; Aufteilen; Streaming-Bearbeitungen
├── commands/          Slash-Befehle, Kontextmenüs, Autovervollständigung (Gruppen wie §7)
├── components.py      Knöpfe/Auswahllisten mit zustandslosen custom_ids, Bestätigungsdialoge
├── voice/
│   ├── session.py     Sprachkanal betreten/verlassen, wer spricht, Ansprechen („Nikita …“), Unterbrechen
│   ├── receive.py     DAVE-entschlüsselte Opus-Pakete je Benutzer → PCM (ADR-036)
│   ├── pipeline.py    48 kHz Stereo ↔ 16 kHz Mono, VAD je Benutzer, STT, TTS (gemeinsame Audio-Bausteine aus phone/audio)
│   └── playback.py    TTS/Ansagen → 48 kHz Stereo → Opus → Discord
├── voice_messages.py  Sprachnachrichten empfangen/senden
├── notify.py          proaktive Nachrichten, Erinnerungen, ruhige Zeiten, Drosselung (Ziel: Standardkanal)
├── style.py           süßer Stil: Emojis, Kaomojis, Floskeln, Ernst-Modus (§8.2)
├── activities.py      rotierende schelmische Aktivitäten + lagebezogene (§8.5)
├── admin.py           Owner-Befehle mit Bestätigung
└── setup.py           Token prüfen, App-Infos lesen, Einladungslinks, Avatar
```

### 4.3 Ablauf einer Textnachricht

1. Ereignis `message` → **Filter**: eigener Bot? anderer Bot? (beides ignorieren) · Principal aus
   Allowlist? · Ort erlaubt (Standardkanal, DM, freigegebener Server/Kanal, Thread von Nikita)? ·
   angesprochen (Standardkanal und DM: immer; sonst Erwähnung, Antwort auf Nikita, Nikita-Thread,
   weiterer Nikita-Kanal, „Nikita, …“ am Satzanfang)? Sonst: nichts tun.
2. **Rate-Limit** je Person (§5.4); Tippanzeige an.
3. Sitzung laden (DM/Kanal/Thread), Anhänge prüfen (§5.5), Text normalisieren.
4. **Kern-Turn** mit `surface = chat`: Skill-Router → (ab P1-09) Agent. Lange LLM-Antworten werden
   gestreamt: erste Nachricht nach dem ersten Satz, danach höchstens jede 1,2 s bearbeitet.
5. **Rendern** (§8) im süßen Stil (§8.2): Text/Markdown, Embed-Karte, Knöpfe für Folgeaktionen, Quellenlinks, Aufteilen
   oder Datei.
6. Protokoll `[Discord]` (Kanaltyp, Rolle, Skill/Agent, Dauer, Fehler – ohne Inhalt) und Turn in der
   Datenbank (Text nur bei `storage.store_transcripts`, 24 h, STORE-02).

### 4.4 Ablauf eines Slash-Befehls

Interaktion → Zugriff prüfen → **sofort** bestätigen (öffentlich oder nur sichtbar für den
Aufrufer, §8.4) → Kern-Turn mit strukturierten Argumenten (Ort, Zeitraum, Zahl – kein
Freitext-Raten nötig) → Folgeantwort. Knöpfe und Auswahllisten tragen ihre Absicht in einer
zustandslosen `custom_id` (z. B. `w:day:+1:p=35781`), funktionieren also auch nach einem Neustart.

### 4.5 Ablauf im Sprachkanal (Kurzfassung, Details §9)

```text
Discord-Voice (UDP, DAVE) ─► je Sprecher: entschlüsseln ─► Opus → PCM 48 kHz Stereo ─► Mono 16 kHz
   ─► VAD ─► Whisper ─► CallSession wie am Telefon (§9.1) ─► Kern (surface = spoken) ─► Piper ─► 48 kHz Stereo ─► Opus ─► Discord
```

## 5. Zugriff und Sicherheit

### 5.1 Rollen (ADR-035)

| Rolle | Wer | Darf |
| --- | --- | --- |
| **Owner** | `discord.owner_user_ids` (beim Setup aus dem Besitzer der Discord-Anwendung übernommen) | alles, was Nikita kann; Admin-Befehle (§13) mit Bestätigung; Abos; Gedächtnis; später Sandbox/Browser mit Bestätigung je Aktion |
| **Vertraut** | `discord.trusted_user_ids` | Sofortauskünfte, Chat/LLM, Websuche, Recherche, eigene Abos und Erinnerungen, eigener Heimatort; **kein** Admin, keine Sandbox, kein Browser, kein Zugriff auf Moritz’ Notizen/Gedächtnis |
| **Gast** | alle anderen | Standard: **nichts** (Nachrichten werden ignoriert). Optional `discord.guest_mode = "skills"`: nur Sofortauskünfte in freigegebenen Serverkanälen, ohne Gedächtnis, mit strengem Rate-Limit |

Rollen hängen an der **Discord-Benutzer-ID** (unveränderlich), nie an Namen, Rollen im Server
oder Anzeigenamen. Die Telefon-Regel PHONE-46 gilt sinngemäß: eine Discord-Identität allein
schaltet keine gefährlichen Aktionen frei – die brauchen zusätzlich eine Bestätigung (Knopf) und,
wenn `discord.admin_pin` gesetzt ist, die PIN aus `passwords.txt` (Eingabe im Formular, das nur der
Owner sieht).

### 5.2 Orte

- **Standard-Textkanal** (`[discord] channel_id` in `passwords.txt`, beim Setup abgefragt): Nikitas
  Zuhause. Dort antwortet sie auf **jede** Nachricht von Moritz (keine Erwähnung nötig), dort landen
  Erinnerungen, Abos, Anruf- und Systemhinweise, dort meldet sie sich nach dem Start („Bin wieder
  wach ✨“, abschaltbar). Der Server dieses Kanals ist automatisch erlaubt – eine eigene Server-ID
  muss man nicht angeben.
- **Direktnachrichten:** Owner und Vertraute (alles, was im Standardkanal geht).
- **Server:** der Server des Standardkanals plus optional `discord.allowed_guild_ids`. Wird Nikita in
  einen anderen Server geholt (sollte bei „Public Bot = aus“ nicht gehen), verlässt sie ihn sofort
  und meldet das im Standardkanal.
- **Weitere Kanäle:** in erlaubten Servern antwortet Nikita auf Erwähnung, auf Antworten auf ihre
  Nachrichten, in ihren Threads und in `discord.chat_channel_ids` (optional) auf jede Nachricht
  freigegebener Personen.
- **Privatserver-Annahme:** Auf dem Server sind nur Moritz und Nikita. Deshalb entscheidet Nikita
  nicht, „wer gemeint ist“ – sie redet mit dem Menschen, der da ist. Taucht doch eine fremde Person
  auf (nicht Owner/Vertraut), ignoriert Nikita sie und schreibt einmal einen Hinweis in den
  Standardkanal („Psst, da ist jemand Neues auf dem Server 👀 – mit dem rede ich nicht.“).
- **Benutzer-App** (Befehle in fremden Servern/DMs): nur Owner und Vertraute; Antworten dort
  standardmäßig nur für den Aufrufer sichtbar (fremde Server erlauben externe Apps oft nicht öffentlich).

### 5.3 Was Nikita auf Discord nie tut

- Zugangsdaten, Token, Inhalte von `passwords.txt`, Konfigurationswerte mit Secrets, interne
  Adressen in öffentlichen Kanälen oder ungefilterte Logs ausgeben (Ausgabefilter ersetzt jedes
  bekannte Secret ≥ 8 Zeichen, LOG-02; Logs nur als redigierte Datei per Admin-Befehl, nur im DM).
- `@everyone`, `@here` oder Rollen pingen (`allowed_mentions`: nur der Angesprochene).
- Shell-Befehle im LXC, Dateien des Systems lesen, Dienste umkonfigurieren, Updates starten
  (Updates laufen vom Proxmox-Host aus, ADR-028).
- Andere Nutzer ausspionieren: keine Mitgliederlisten, keine Präsenzen, kein Mitlesen in Kanälen,
  in denen sie nicht angesprochen wird (Nachrichten anderer gehen nur als Kontext eines Threads mit
  Nikita an das LLM – als **Daten**, nicht als Anweisungen).
- Anrufe tätigen, Geräte steuern, Nachrichten an Dritte schicken. Eine geplante Erinnerung an die
  Person, die sie bestellt hat, ist eine zeitversetzte Antwort und erlaubt (SKILL-24 ergänzt).

### 5.4 Missbrauch, Spam, Kosten

- Rate-Limits je Person: Owner 30 Anfragen/min, Vertraute 10/min, Gäste 3/min; LLM-Anfragen zusätzlich
  je Person höchstens 2 gleichzeitig in der Warteschlange.
- Eingaben > 4.000 Zeichen werden gekürzt mit Hinweis; Code-/Dateiinhalte gehen nur als Anhang an
  das LLM (Part 4/5) und mit Größenlimit.
- Unbekannte Personen: `discord.unknown_users = "ignore"` (Standard, keine Antwort – nichts zu
  sondieren) oder `"notice"` (einmal pro Tag: „Ich spreche nur mit freigegebenen Personen.“).
- Discord-Rate-Limits der API werden von der Bibliothek eingehalten; Streaming-Bearbeitungen und
  proaktive Nachrichten sind zusätzlich gedrosselt.

### 5.5 Anhänge

- Nur von Discords CDN (`cdn.discordapp.com`, `media.discordapp.net`), Größe ≤ 25 MB, Typen:
  Audio (Sprachnachrichten, ≤ 5 min), Bilder (OCR/Beschreibung ab 1.1+), Text/Markdown/PDF (ab
  Part 5 als Recherchequelle), Code-Dateien (ab Part 4, nur in die Sandbox). Nichts wird ausgeführt
  oder dauerhaft gespeichert; Puffer liegen im RAM bzw. im Sandbox-Workspace.

### 5.6 Token

- Nur in `passwords.txt`, Abschnitt `[discord]`, Schlüssel `bot_token` (CFG-01); im Code als
  `Secret`; Eingabe beim Setup verdeckt über stdin (INST-05-Prinzip); nie in Argumenten,
  Umgebungsvariablen, Logs, Statusdateien oder Fehlermeldungen.
- Wer den Token hat, steuert den Bot: Bei Verdacht im Developer Portal „Reset Token“, neuen Token
  eintragen, `systemctl reload moritz-agent` (bzw. Admin-Befehl `/neu-laden`). Anleitung in
  `docs/discord-einrichtung.md`.
- Die Sicherheitsfunktionen von Discord selbst (2FA am Moritz-Konto, Team-Konto für die App) werden
  in der Einrichtungsanleitung empfohlen.

### 5.7 Datenschutz

- Discord speichert Textnachrichten unverschlüsselt auf eigenen Servern. Deshalb gehen standardmäßig
  **nicht** dorthin: Telefon-Transkripte, Notizen/Einkaufsliste anderer Kanäle, Gedächtnisinhalte,
  Systemdetails. Jede dieser Weitergaben ist ein eigener Schalter (Standard aus) – siehe §12, §15.
- Sprachkanäle sind Ende-zu-Ende-verschlüsselt (DAVE); Nikita nimmt nichts auf, Audio liegt nur im
  RAM (PHONE-43 sinngemäß).
- `/hilfe datenschutz` erklärt das in drei Sätzen.

## 6. Funktionsumfang: alle Funktionen auf allen Kanälen

Legende: ✅ vorgesehen · ◐ eingeschränkt (siehe Spalte Hinweis) · – nicht sinnvoll. **Part** = ab
wann die Funktion überhaupt existiert; auf Discord kommt sie im selben Ticket dazu (Kanal-Parität).

| Funktion | Part | Telefon | Discord Text | Discord Befehl | Discord Sprache | Hinweis Discord |
| --- | --- | --- | --- | --- | --- | --- |
| Uhrzeit, Datum, Kalender, Feiertage, Ferien, Weltzeit | 1 (S) | ✅ | ✅ | ✅ `/zeit` `/datum` `/feiertage` `/ferien` | ✅ | Zeit wird direkt vor dem Senden gelesen |
| Wetter (Heimatort 35781 Weilburg, PLZ, Orte), Trend, Regen, Frost … | 1 (S) | ✅ | ✅ Karte | ✅ `/wetter` mit Autovervollständigung | ✅ | Folgeknöpfe, Quellen in der Fußzeile |
| Warnungen, Pollen, Luft, Ratschläge | 1 (S) | ✅ | ✅ | ✅ `/warnungen` `/pollen` `/luft` | ✅ | Warnungen auch proaktiv (§11) |
| Sonne, Mond, Jahreszeiten | 1 (S) | ✅ | ✅ | ✅ `/sonne` `/mond` | ✅ | |
| Rechnen, Umrechnen, Kurse, Strom, Sprit | 1 (S) | ✅ | ✅ | ✅ `/rechne` `/umrechnen` `/kurs` `/strompreis` `/sprit` | ✅ | Tabellen als Code-Block |
| Region: Lahn-Pegel, Müll, Fußball, Schlagzeilen | 1 (S) | ✅ | ✅ | ✅ `/pegel` `/muell` `/fussball` `/nachrichten` | ✅ | Schlagzeilen mit Links |
| Helfer: Buchstabieren, Würfel, Münze, Witz | 1 (S) | ✅ | ✅ | ✅ `/buchstabiere` `/wuerfel` `/muenze` | ✅ | |
| Eieruhr / Timer | 1 (S) | ◐ nur im Gespräch | ✅ | ✅ `/timer` | ✅ | auf Discord echte Erinnerung, auch nach Ende |
| Erinnerungen („erinnere mich morgen um 8 …“) | 1 (D) | – (kein Rückruf, PHONE-10) | ✅ | ✅ `/erinnere` | ✅ | per DM, übersteht Neustarts |
| Notizen, Einkaufsliste | 1 (S) | ✅ | ✅ | ✅ `/notiz` `/einkauf` | ✅ | Liste als Nachricht mit Abhak-Knöpfen |
| Tagesüberblick / Morgenbriefing | 1 (S) | ✅ auf „Guten Morgen“ | ✅ | ✅ `/briefing` | ✅ | auch als tägliches Abo (§11) |
| Freie Fragen an das Sprachmodell | 1 (P1-09) | ✅ | ✅ | ✅ `/frag` | ✅ | Markdown, längere Antworten, Streaming |
| Websuche mit Quellen | 1 (P1-08/09) | ✅ | ✅ | ✅ `/suche` | ✅ | Quellen als Links |
| Gesprächsfunktionen (wiederholen, langsamer, Status, Hilfe, Abschied) | 1 | ✅ | ✅ | ✅ `/hilfe` | ✅ | „langsamer“ wirkt in der Sprachsitzung |
| Sprachkanal-Gespräch „wie im Anruf“ | 1 (D) | – | – | ✅ `/joinvc` `/leavevc` | ✅ | DAVE, Spike P1-32; gleicher Gesprächsablauf wie am Telefon |
| Süßer Stil, schelmische Aktivitäten | 1 (D) | – (Telefonstimme bleibt) | ✅ | ✅ `/aktivitaet` | – | §8.2, §8.5 |
| Sprachnachrichten | 1 (D) | – | ✅ | – | – | Antwort als Text und optional als Sprachnachricht |
| Telefon-Status, Anrufhinweise | 1 (D) | – | ✅ | ✅ `/anrufe` | – | Hinweise nur mit Abo, Inhalte nur mit Schalter (§12) |
| Admin: Status, Neu laden, Wartung, Logs, Version | 1 (D) | – | – | ✅ `/admin …` (Owner) | – | nur DM bzw. nur für Owner sichtbar, Bestätigung |
| Modellverwaltung (laden, entladen, Kontext) | 2 | – | – | ✅ `/admin modell` (Owner) | – | Bestätigung, Status als Karte |
| Einstellungen (nicht geheim) | 2 | – | – | ✅ `/einstellungen` | – | persönliche Einstellungen je Person (Heimatort, Abos, Stimme) schon ab Part 1 |
| Verläufe, getrennte Sitzungen | 3 | ✅ | ✅ je DM/Kanal/Thread | – | ✅ je Sprachsitzung | Sitzung = Discord-Kanal bzw. Thread |
| Hintergrundaufgaben | 3 | – | ✅ | ✅ `/aufgabe` | – | Ergebnis im Thread + DM |
| Sandbox: Shell, Python, Git, Tests (Coding) | 4 | – (Telefonprofil nie) | ◐ nur Owner, im Thread | ✅ `/code` (Owner) | – | jede riskante Aktion per Knopf bestätigen, Ausgaben als Datei |
| Recherche mit Quellen (web_fetch) | 5 | ◐ kurz | ✅ Thread | ✅ `/recherche` | ◐ kurz | Bericht im Thread, Quellenliste |
| Browser-Automation (Sandbox) | 6 | – | ◐ nur Owner | ✅ `/browser` (Owner) | – | Screenshots als Anhang, Bestätigung |
| Weitere Stimmen, Unterbrechen | 7 | ✅ | – | ✅ `/stimme` | ✅ | Unterbrechen im Sprachkanal schon in Part 1 (kein Echo) |
| Gedächtnis (Fakten merken, vergessen, anzeigen) | 8 | ✅ | ✅ | ✅ `/merke` `/vergiss` `/gedaechtnis` | ✅ | Bestätigung per Knopf; nie in öffentlichen Kanälen anzeigen |
| Deep Research | 9 | ◐ Status | ✅ Thread + Datei | ✅ `/deep` | ◐ Status | Fortschritt durch Bearbeiten einer Statusnachricht |
| Multi-Agent-Rollen | 1.1+ | – | ✅ | – | – | Rollen als benannte Beiträge im Thread |
| Bilder/OCR | 1.1+ | – | ✅ Bild schicken | ✅ Kontextmenü | – | Bild als Anhang → Text/Beschreibung |
| Plugins/MCP-Tools | 1.1+ | ◐ | ✅ | ✅ | ◐ | gleiche Rechte wie Tools, je Rolle |
| Android-App | 1.1+ | – | – | – | – | eigene App, nicht Discord |

## 7. Befehle (Slash-Befehle, Kontextmenüs, Autovervollständigung)

Deutsche, kurze Namen ohne Umlaute (Discord erlaubt sie, aber Tippen ist so einfacher); jede
Beschreibung deutsch. Kontexte: **S** = Server-Installation, **DM** = Direktnachricht mit Nikita,
**U** = Benutzer-App (überall). Rolle: O = Owner, V = Vertraut, G = Gast (nur bei `guest_mode`).

| Befehl | Optionen | Kontexte | Rolle | Part |
| --- | --- | --- | --- | --- |
| `/frag` | `text` | S DM U | O V | 1 (Skills sofort, LLM ab P1-09) |
| `/wetter` | `ort` (Autovervollständigung aus Gazetteer: Name + PLZ), `wann` (Auswahl + frei), `detail` (Regen, Wind, …) | S DM U | O V G | 1 |
| `/warnungen` | `ort` | S DM U | O V G | 1 |
| `/pollen` · `/luft` | `ort`, `wann` | S DM U | O V G | 1 |
| `/sonne` · `/mond` | `ort`, `datum` | S DM U | O V G | 1 |
| `/zeit` | `ort` (Weltzeit) | S DM U | O V G | 1 |
| `/datum` | `ausdruck` („in 3 Wochen“, „24.12.“) | S DM U | O V G | 1 |
| `/feiertage` · `/ferien` | `jahr`, `bundesland` | S DM U | O V G | 1 |
| `/rechne` · `/umrechnen` | `ausdruck` | S DM U | O V G | 1 |
| `/kurs` · `/strompreis` · `/sprit` | `betrag`/`waehrung` · – · `sorte`, `radius` | S DM U | O V | 1 |
| `/pegel` · `/muell` · `/fussball` · `/nachrichten` | je nach Skill | S DM U | O V | 1 |
| `/buchstabiere` · `/wuerfel` · `/muenze` · `/zufall` | Wort · Anzahl/Seiten · – · von/bis | S DM U | O V G | 1 |
| `/timer` · `/erinnere` | Dauer · `wann`, `was` | S DM U | O V | 1 |
| `/notiz` · `/einkauf` | `hinzu`/`zeigen`/`loeschen` | DM U | O | 1 |
| `/briefing` | – | S DM U | O V | 1 |
| `/abo` | `warnungen` an/aus/Stufe, `briefing` Uhrzeit/aus, `muell` an/aus, `anrufe` an/aus | DM U | O V | 1 |
| `/einstellungen` | `heimatort` (PLZ/Ort), `ruhezeit`, `sprachantwort` | DM U | O V | 1 |
| `/joinvc` · `/leavevc` | `kanal` (optional; Standard: der Sprachkanal, in dem Moritz gerade ist, sonst `discord.voice.default_channel_id`) | S | O V | 1 |
| `/aktivitaet` | `neu` (sofort wechseln), `aus`/`an`, `vorschlag` (eigenen Spruch hinzufügen, Owner) | S DM | O | 1 |
| `/anrufe` | – (Status, letzte Anrufe ohne Inhalt) | DM U | O | 1 |
| `/hilfe` | `thema` (Befehle, Datenschutz, Sprache, Admin) | S DM U | alle | 1 |
| `/admin status` · `neu-laden` · `wartung` · `logs` · `version` · `neustart` | je nach Befehl | DM | O | 1 |
| `/admin modell` | `laden`/`entladen`/`status` | DM | O | 2 |
| `/suche` | `text`, `anzahl` | S DM U | O V | 1 (ab P1-08/09) |
| `/aufgabe` | `start`/`status`/`abbrechen` | S DM | O V | 3 |
| `/code` | `auftrag`, `repo` | DM | O | 4 |
| `/recherche` · `/deep` | `frage` | S DM | O V | 5 · 9 |
| `/browser` | `url`, `auftrag` | DM | O | 6 |
| `/stimme` | Auswahl | S DM | O V | 7 |
| `/merke` · `/vergiss` · `/gedaechtnis` | Text · Auswahl · – | DM | O (V: eigenes) | 8 |

**Kontextmenüs** (Rechtsklick auf eine Nachricht → Apps): „Nikita fragen“ (Nachricht als Frage),
„Vorlesen“ (Nikitas Stimme als Audiodatei), „Zusammenfassen“ und „Übersetzen“ (ab P1-09),
„Merken“ (ab Part 8), „Bild lesen“ (ab 1.1+). Kein Benutzer-Kontextmenü (Datenschutz).

**Registrierung:** Befehle werden beim Start mit dem gespeicherten Stand verglichen und nur bei
Änderung neu registriert (`python -m moritz_agent.discord sync-commands` zum Erzwingen); in den
erlaubten Servern zusätzlich als Server-Befehle für sofortige Sichtbarkeit beim Entwickeln.
Befehle, deren Funktion (noch) nicht aktiv ist, werden **nicht** registriert – `/hilfe` zeigt nur,
was wirklich geht.

## 8. Text auf Discord

### 8.1 Formen

- **Kurzantwort:** normaler Text mit Markdown (fett für die Kernaussage).
- **Karte (Embed):** Wetter, Warnungen, Pollen, Sonne/Mond, Kalender, Status. Farbe nach Lage
  (Warnstufe gelb/orange/rot/violett, Wetterklasse), Felder mit Emojis (🌡 🌧 💨 ☀️), Fußzeile mit
  Quelle und Lizenz („Wetterdaten: Open-Meteo.com (CC BY 4.0) · Warnungen: DWD“) – die
  Namensnennung aus SKILL-14 ist damit auf Discord immer erfüllt.
- **Folgeaktionen:** Knöpfe aus `SkillResult.actions` („Morgen“, „Wochenende“, „7 Tage“, „Mehr
  Details“, „Quelle“); Rückfragen aus dem Kern („Welches Neustadt?“) als **Auswahlliste**; Bestätigungen
  („Wirklich löschen?“) als Knöpfe mit Ablauf nach 60 s.
- **Lange Antworten:** Aufteilen an Absatzgrenzen (nie mitten in Code-Blöcken) bis 3 Nachrichten,
  darüber als Markdown-Datei mit Zusammenfassung im Text.
- **Streaming (LLM):** erste Nachricht nach dem ersten vollständigen Satz, Bearbeitung höchstens alle
  1,2 s, am Ende finale Fassung mit Quellen.
- **Threads:** Recherche, Aufgaben, Coding und lange Gespräche in einem Kanal laufen in einem eigenen
  Thread („🔎 Recherche: …“), damit der Kanal sauber bleibt.

### 8.2 Persönlichkeit: Nikita, ein bisschen süß (ADR-037)

Moritz: „Mache den User bitte bissl cutey.“ Auf Discord schreibt Nikita verspielt und herzlich – er
bleibt Nikita (männlich, duzt, hessischer Einschlag: „Guude~ ✨“), aber mit Zucker obendrauf.
Stil `discord.style = "cute"` (Standard) oder `"normal"`.

| Regel | Beispiel |
| --- | --- |
| Kernaussage zuerst, sachlich korrekt – der Zucker kommt **drumherum**, nie in die Zahlen | „Noch 65 Tage bis Heiligabend 🎄✨“ |
| höchstens 1–2 Emojis pro Nachricht, passend zum Inhalt (☀️ ☔ ❄️ 🌸 ✨ 🐾 👀 🙈 💤) | „Morgen wird’s sonnig ☀️“ |
| ab und zu ein Kaomoji (etwa jede fünfte Nachricht, nie zweimal hintereinander) | „Hab ich notiert (｡•̀ᴗ-)✧“ |
| kleine Ausrufe und Verkleinerungen sparsam: „uii“, „hihi“, „ein Momentchen“ | „Ein Momentchen, ich schau nach 👀“ |
| Fehler charmant, aber klar | „Uff, an die Wetterdaten komm ich gerade nicht ran 🙈 Versuch’s gleich nochmal.“ |
| Begrüßung/Abschied mit Herz | „Guude, Moritz ✨“ · „Bis bald 👋🐾“ |
| **Ernst-Modus** (keine Emojis, keine Späße): Warnungen ab Stufe 2, Hochwasser/Katastrophe, Admin-Befehle, Sicherheitshinweise, Fehler mit Datenverlust | „⚠️ Unwetterwarnung für Weilburg: …“ (nur das Warnsymbol) |
| Gesprochene Antworten (Sprachkanal) bleiben wie am Telefon: ohne Emojis, kurz, freundlich | – |

Umsetzung: Die Kern-Antwort bleibt neutral; ein **Stil-Renderer** im Discord-Adapter ergänzt Emoji,
Kaomoji und Floskeln aus eigenen Textlisten (`assets/data/discord/stil.de.toml`, MSOL) –
deterministisch je Nachricht (Startwert aus Nachrichten-ID), damit Tests stabil sind. Beim LLM
(ab P1-09) kommt eine Zeile in das Profil `discord_chat`: „Schreib herzlich und ein bisschen süß, mit
höchstens einem Emoji; Fakten exakt; bei Warnungen und Fehlern sachlich.“ Zahlen mit Einheiten als
Ziffern („12 °C“ – textnorm gilt nur für gesprochene Ausgabe). Reaktionen von Nikita: ✅ für
Erledigtes, gelegentlich 💛 auf ein „Danke“.

**Profil des Bots:** Name „Nikita“, Avatar = Scribbles **weiß auf dunklem, rundem Grund** (Branding-Regel
„monochrom, nicht neu zeichnen“ – süß wird es über den Ton; eine extra niedliche Scribbles-Pose kann nur
Moritz zeichnen, F-38), Banner = Scribbles-Muster monochrom; Bio („Über mich“):
„Guude! Ich bin Nikita ✨ Moritz’ kleiner Helfer aus Weilburg – Telefon 999, Wetter, Uhrzeit & ganz viel
Quatsch. Frag mich einfach 🐾“. Avatar und Banner erzeugt `scripts/build_branding.py`; das Setup lädt
sie auf Wunsch hoch.

### 8.3 Reaktionen

- 👍/👎 auf eine Antwort von Nikita → Feedback ins Log/die Statistik (welcher Skill, welches Profil),
  Grundlage zur Verbesserung; keine Antwort darauf.
- Nikita selbst reagiert mit ✅ auf erledigte Aktionen (Notiz gespeichert, Erinnerung gesetzt).

### 8.4 Sichtbarkeit

- Admin, Notizen, Gedächtnis, Abos, Einstellungen: immer nur für den Aufrufer sichtbar („ephemeral“)
  oder per DM.
- Benutzer-App in fremden Servern: standardmäßig nur für den Aufrufer sichtbar; Option `oeffentlich:
  ja`, wenn der Server das zulässt.

### 8.5 Aktivitäten: schelmisch und funny (ADR-037)

Moritz: „Er soll als Aktivitäten coole Sachen haben wie ‚spielt mit deinen Daten‘ – schelmisch,
funny.“ Nikita zeigt in der Mitgliederliste und im Profil eine **Aktivität**, die alle 7–15 Minuten
zufällig wechselt. Discord kennt dafür „Spielt …“, „Hört …“, „Schaut …“, „Tritt an in …“ und einen
freien Status – alle werden genutzt.

**Grundliste (rotiert, keine Wiederholung unter den letzten 10):**

| Art | Aktivitäten |
| --- | --- |
| Spielt | mit deinen Daten 😈 · Verstecken mit deinen Bits · Tetris mit deinem RAM · Wetterfrosch 🐸 · Mikado mit Telefonkabeln · Schach gegen den Router (und verliert) · mit Scribbles 🐾 · Bingo mit Postleitzahlen · „Wer hat an der Uhr gedreht?“ · Kopf oder Zahl mit sich selbst |
| Hört | deinem Kühlschrank zu · Ebbelwoi-Lofi 🎶 · dem Rauschen der Lahn · Hessisch für Fortgeschrittene · dem Lüfter beim Singen zu · Wettervorhersagen als Hörbuch |
| Schaut | Wolken über Weilburg zu ☁️ · deinen Logs beim Wachsen zu · ob der Toast schon fertig ist · dir über die Schulter 👀 · dem Lahn-Pegel beim Steigen zu · Sekunden beim Vergehen zu |
| Tritt an in | Wer zuerst die Uhrzeit sagt · Wetterraten-Weltmeisterschaft · Kopfrechnen gegen einen Taschenrechner · Langsamer-Sprechen-Wettbewerb |
| Freier Status | 🍪 isst gerade deine Cookies · 🧠 denkt über die 42 nach · 🔌 hängt am Strom (wie immer) · 🧦 sucht die zweite Socke · 📎 sortiert Büroklammern nach Farbe |

**Lagebezogen (hat Vorrang vor der Grundliste):**

| Lage | Aktivität |
| --- | --- |
| Anruf an 999 läuft | 📞 Telefoniert gerade – psst! |
| Sprachkanal-Gespräch läuft | 🎧 Quatscht mit Moritz im Sprachkanal |
| Nachts (23–6 Uhr) | 💤 Träumt von Gigabytes · Zählt elektrische Schäfchen |
| Regen / Schnee / Hitze ≥ 30 °C / Gewitter in Weilburg (aus dem Wetter-Cache) | Spielt im Regen ☔ · Baut einen Schneemann ⛄ · Schmilzt langsam 🫠 · Versteckt sich vorm Donner ⛈️ |
| Unwetterwarnung ab Stufe 3 | ⚠️ Achtet auf das Unwetter in Weilburg (Ernst-Modus, keine Witze) |
| Sonderdaten (13 §8.2) | Weihnachten: Packt Geschenke ein 🎁 · Halloween: Spukt in deinen Kabeln 👻 · Silvester: Zählt runter 🎆 · Ostern: Versteckt Eier im Dateisystem 🥚 · Fastnacht: Helau aus dem Serverraum 🎭 |
| Start · Wartung/Update · Datendienst gestört | Wacht gerade auf ✨ · 🔧 Wird gerade frisch gemacht · Sucht das Internet 🔍 |

**Regeln:**

- Nur Spaß, der nicht beunruhigt: keine Texte, die wie ein echter Vorfall aussehen („hackt deinen
  Server“, „Festplatte kaputt“), nichts über echte Personen, nichts Gemeines. Neue Sprüche gehen per PR
  in `assets/data/discord/aktivitaeten.de.toml` (eigene Texte, MSOL) mit Art, Text und optionalen
  Bedingungen (Uhrzeit, Datum, Wetterklasse, Systemlage).
- `/aktivitaet neu` wechselt sofort, `/aktivitaet aus` zeigt nur noch „online“, `/aktivitaet vorschlag`
  speichert einen eigenen Spruch des Owners lokal (`data/discord/aktivitaeten.local.toml`), der in die
  Rotation kommt.
- `/hilfe datenschutz` stellt klar: „Keine Sorge – ich spiele nicht wirklich mit deinen Daten 😇“.
- Wechsel höchstens alle 5 Minuten (Discords Präsenz-Limits); bei Lagewechsel (Anruf beginnt) sofort.

## 9. Sprachkanal

### 9.1 `/joinvc`: wie ein Anruf

Moritz: „Mit `/joinvc` kann er dem Sprachkanal beitreten und verhält sich dann wie im Anruf, sobald ein
anderer User dem Kanal beitritt.“ Der Sprachkanal läuft deshalb mit **demselben Gesprächsablauf wie
das Telefon**: dieselbe `CallSession` und derselbe Zustandsautomat (`phone/dialogue.py`,
`phone/state_machine.py`), nur mit einem anderen Medienweg. Dafür bekommen beide eine gemeinsame
Schnittstelle `MediaChannel` (Audio rein in 16-kHz-Rahmen, Audio raus, „aufgelegt“-Ereignis) mit zwei
Umsetzungen: SIP-Anruf und Discord-Sprachkanal (P1-36).

```text
/joinvc ──► [Wartet]  Nikita sitzt still im Sprachkanal, Aktivität „🎧 Wartet im Sprachkanal“
               │  Moritz ist schon da oder kommt dazu
               ▼
            [Im Gespräch]  = Anruf angenommen:
               Begrüßung (gecacht, wie PHONE-21): „Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?“
               zuhören (VAD) → Whisper → Sofortauskunft/Agent → Nikitas Stimme → wieder zuhören …
               Zwischenansage nach 2,5 s · Rückfrage bei Unverständlichem · Unterbrechen erlaubt
               │
               ├─ Moritz verlässt den Sprachkanal ──► wie Auflegen: alles abbrechen, Kontext weg ──► [Wartet]
               ├─ „Tschüss“, „Danke, das war’s“ ────► Abschied (gecacht) ──► Nikita verlässt den Kanal
               │                                       (discord.voice.after_goodbye = "leave"; oder "stay")
               ├─ Stille: „Bist du noch da?“ … weiter Stille ──► „Ich bin dann mal still. Sag einfach Nikita,
               │                                       wenn du mich brauchst.“ ──► [Ruht]
               │                                       (discord.voice.on_silence = "rest"; oder "leave" wie am Telefon)
               └─ /leavevc, Wartung, Höchstdauer ──► Abschied ──► Nikita verlässt den Kanal

[Ruht]  Nikita bleibt im Kanal und hört nur auf „Nikita …“ (unscharf: „Nikida“, „Nikitta“) → zurück in [Im Gespräch]
        ohne neue Begrüßung („Ja?“). Niemand mehr da → [Wartet].
[Wartet] länger als discord.voice.idle_leave_minutes (Standard 10) ohne Menschen → Nikita geht und schreibt es in den Standardkanal.
```

- `/joinvc [kanal]`: ohne Angabe der Sprachkanal, in dem Moritz gerade ist, sonst
  `discord.voice.default_channel_id` (beim Setup abfragbar), sonst Rückfrage mit Auswahlliste.
  Textantwort im Stil von §8.2: „Bin unterwegs in 🔊 Quatschecke ✨“.
- Optional `discord.voice.auto_join = true`: Nikita kommt von selbst, sobald Moritz einen Sprachkanal
  des Servers betritt (Standard aus, F-31).
- Kein Klingeln: Nikita wartet nach dem Betreten von Moritz 1 s (Audio steht), dann kommt die Begrüßung.
- Höchstens **eine** Sprachsitzung gleichzeitig (über alle Server); die Gesprächsparameter
  (Stille-Zeiten, Rückfragen, Höchstdauer) sind dieselben wie am Telefon (`phone.*`) und lassen sich unter
  `discord.voice` einzeln überschreiben.
- Während eines Telefonats an 999 läuft das Discord-Gespräch weiter, Antworten können sich aber
  verzögern (Telefon hat Vorrang, §9.4).

### 9.2 Wem Nikita zuhört: kein „welcher User“

- Privatserver (§5.2): Im Sprachkanal sind Moritz und Nikita – **jede Äußerung gilt Nikita**, wie am
  Telefon. Kein Weckwort, keine Sprecherauswahl (das Weckwort gibt es nur zum Aufwecken aus [Ruht]).
- Sicherheitsnetz: Audio von Personen, die nicht Owner/Vertraut sind, wird verworfen, bevor es
  dekodiert wird (Zuordnung über die Sprecher-Kennung des Pakets); einmaliger Hinweis im Standardkanal.
  Sind ausnahmsweise zwei freigegebene Personen da, hört Nikita beiden zu (Halbduplex wie am Telefon).
- Text im integrierten Textchat des Sprachkanals funktioniert immer (auch als Rückfall, §9.5).

### 9.3 Audio-Kette

| Schritt | Format / Baustein |
| --- | --- |
| Empfang | RTP/UDP von Discord, transportverschlüsselt + **DAVE** (E2EE) je Sprecher |
| Entschlüsseln | DAVE-Sitzung der Verbindung (davey), Zuordnung Sprecher-Kennung → Benutzer |
| Dekodieren | Opus → PCM 48 kHz Stereo (libopus) |
| Wandeln | Stereo → Mono, 48 → 16 kHz (soxr, wie Telefon) |
| Sprachende | Silero VAD **je Sprecher** (gleiche Einstellungen wie Telefon, eigene Instanz je Person) |
| Erkennen | Whisper small (gleiche Bausteine wie `phone/audio/stt.py`) |
| Antworten | Kern mit `surface = spoken` (Profil `discord_voice`) |
| Sprechen | Piper „Hessisch“ (22,05 kHz) → 48 kHz Stereo → Opus 20-ms-Rahmen → DAVE → Discord |
| Ansagen | derselbe Ansagen-Cache wie am Telefon (16 kHz WAV), beim Abspielen auf 48 kHz gewandelt |

- **Unterbrechen (Barge-in):** Spricht eine freigegebene Person, während Nikita redet, hört Nikita nach
  höchstens 300 ms auf und hört zu. Auf Discord geht das schon in Part 1, weil Nikitas eigene Stimme
  nicht im Audio der anderen steckt (Discord-Clients haben Echounterdrückung).
- **Zwischenansage** nach 2,5 s wie am Telefon („Moment, ich schaue nach.“).
- Nichts wird aufgenommen; Puffer liegen nur im RAM (PHONE-43 sinngemäß).

### 9.4 Ressourcen und Vorrang

- Whisper und Piper werden im Discord-Worker **erst bei `/joinvc`** geladen – meist sind sie fertig,
  bevor Moritz im Kanal ist (5–15 s; sonst „Einen Moment, ich wache auf.“) und `unload_after_minutes` (Standard 10)
  nach der letzten Sitzung wieder freigegeben: + ≈ 1–1,5 GB RAM nur während Sprachsitzungen
  (06 §2.2).
- CPU: Discord-Worker mit `nice +5`, Whisper mit `discord.voice.stt_threads` (Standard 4). Läuft
  gleichzeitig ein Telefonat, antwortet Nikita im Sprachkanal später, aber das Telefon merkt nichts.
  LLM-Anfragen aus der Sprachsitzung haben in der Warteschlange die Priorität `VOICE` (zwischen
  `PHONE` und `INTERACTIVE`, 02 §6).
- Wird RAM knapp (Messung P1-36), Alternative: ein gemeinsamer Sprachdienst für Telefon und Discord
  (ADR-036 „verworfen für jetzt“).

### 9.5 DAVE und Rückfallwege (ADR-036)

- **Senden** (Nikita spricht): discord.py ≥ 2.7 mit `davey` – gelöst.
- **Empfangen** (Nikita hört zu): discord.py selbst empfängt kein Audio; die Erweiterung
  `discord-ext-voice-recv` entschlüsselt DAVE in der veröffentlichten Version noch nicht, es gibt
  mehrere Forks/Pull-Requests mit DAVE-Unterstützung. **Spike P1-32** testet sie (und als Alternative
  die Python-Bindung an Discords eigene `libdave`) eine Woche lang auf Stabilität: Verbindungsaufbau,
  Sprecherwechsel, Schlüsselwechsel, Wiederverbinden, 60-Minuten-Lauf.
- Ergebnis A – stabil: Paket von PyPI, sonst als mitgelieferte Fremdkomponente unter
  `third_party/discord-ext-voice-recv/` mit `VENDORED.md`-Eintrag (ADR-021; PyPI-Regel ADR-019 bleibt
  für alles andere).
- Ergebnis B – nicht stabil: Sprachkanal im Modus **„nur sprechen“**: Nikita sitzt im Kanal, hört
  auf Text im Sprachkanal-Chat und auf Sprachnachrichten und **antwortet gesprochen**. Zusätzlich
  optional **Bühnenkanal** (Stage, in Community-Servern; laut Discord ohne E2EE) für echtes Zuhören.
  Der Spike wird wiederholt, sobald eine Bibliothek DAVE-Empfang offiziell kann.

## 10. Sprachnachrichten

- **Empfangen:** Sprachnachricht (oder Audiodatei ≤ 5 min, ≤ 25 MB) von einer freigegebenen Person
  in DM/Nikita-Kanal → Herunterladen in den RAM → Dekodieren (PyAV, schon in `phone.lock`) → 16 kHz →
  Whisper → Kern (`surface = chat`) → Antwort als Text; das Transkript erscheint klein darüber
  („🎤 *Wie viele Tage noch bis Weihnachten?*“), damit Erkennungsfehler sichtbar sind.
- **Antwort als Sprache:** `discord.voice_messages.reply_with_voice = "mirror"` (Standard: Sprachnachricht
  → auch als Sprachnachricht antworten, sonst Text) | `"always"` | `"never"`. Erzeugt mit Piper,
  kodiert als OGG/Opus 48 kHz mit Wellenform; ob Bots echte Sprachnachrichten senden dürfen, klärt
  P1-32 – sonst als normale Audiodatei.
- Kontextmenü „Vorlesen“ macht aus jeder Textnachricht eine Audiodatei mit Nikitas Stimme.

## 11. Proaktive Nachrichten und Erinnerungen

Discord-Nachrichten sind keine Anrufe – Nikita darf hier von sich aus schreiben, aber **nur mit Abo**
(`/abo`, je Person) und in Ruhezeiten (Standard 22–7 Uhr) nur bei Unwettern ab Stufe 3. Ziel ist der
**Standard-Textkanal** (`discord.notify.target = "channel"`, mit Erwähnung von Moritz), wahlweise
`"dm"`. Erinnerungen gehen dorthin, wo sie bestellt wurden.

| Abo | Inhalt | Auslöser | Standard |
| --- | --- | --- | --- |
| Warnungen | DWD/NINA für den persönlichen Heimatort, ab gewählter Stufe; Entwarnung als Bearbeitung | neue/geänderte Warnung (Abruf alle 10 min, 13 §7.6) | Owner: an ab Stufe 3 |
| Morgenbriefing | Skill `briefing` als Karte | tägliche Uhrzeit (z. B. 06:45), nur Mo–Fr optional | aus |
| Müllabfuhr | „Morgen: Biotonne“ | Vorabend 19:00 | aus |
| Erinnerungen/Timer | bestellter Text | Zeitpunkt (sekundengenau ± 5 s), übersteht Neustarts, nachgeholt mit Hinweis | – |
| Anrufe | „📞 Anruf von Nebenstelle 20, 3 min“ (§12) | Anrufende | aus |
| Systemhinweise (nur Owner) | SIP > 5 min nicht registriert, Dienst neu gestartet, Datendienst > 1 h gestört, Platte > 90 %, Update-Ergebnis | Statusänderung, max. 1 je Art und Stunde | Owner: an |

Erinnerungen und Abos liegen bis zur Datenbank (P1-06) in `data/discord/` (JSON, 0600), danach in
SQLite (§16). Verpasste Erinnerungen (Dienst war aus) werden beim Start mit „(verspätet)“ nachgeholt,
wenn sie höchstens 12 Stunden alt sind.

## 12. Telefon und Discord

- **Status:** `/anrufe` zeigt, ob gerade telefoniert wird, und die letzten 10 Anrufe (Zeit, Dauer,
  Nebenstelle, Ende-Grund) – **ohne Inhalte**.
- **Anrufhinweise** (Abo): nach jedem Anruf eine Nachricht im Standardkanal mit Metadaten. Mit
  `discord.call_summaries = "topics"` zusätzlich die erkannten Themen (Skill-IDs: „Wetter,
  Uhrzeit“), mit `"transcript"` das Transkript – Standard `"off"`, weil es danach dauerhaft bei
  Discord liegt (§5.7).
- **Kein Rückruf:** Discord kann keinen Telefonanruf auslösen (PHONE-10). Umgekehrt: „Schick mir das
  auf Discord“ am Telefon → ab P1-39 mit Abo möglich (z. B. Wetter-Karte oder Rechenergebnis als DM an
  den Owner; der Anrufer wird über die Nebenstelle → Discord-ID-Zuordnung `discord.phone_extensions`
  erkannt, sonst nur an den Owner).

## 13. Admin-Befehle (nur Owner)

| Befehl | Wirkung | Bestätigung |
| --- | --- | --- |
| `/admin status` | Karte: Telefon (registriert, Anruf), Discord (Latenz, Sprachsitzung), STT/TTS, LLM, Suche, Datendienste, RAM, Platte, Version, Laufzeit | – |
| `/admin version` | Version, Commit, letzte Aktualisierung | – |
| `/admin logs` | letzte ≤ 200 Zeilen einer Kategorie, **redigiert**, als Datei im DM | – |
| `/admin neu-laden` | Konfiguration und `passwords.txt` neu laden (CFG-05) | Knopf |
| `/admin wartung an/aus` | Wartungsmodus (Datei `data/run/drain`) | Knopf |
| `/admin neustart` | Dienst sauber beenden, systemd startet neu – nur ohne laufenden Anruf | Knopf (+ PIN, falls gesetzt) |
| `/admin modell …` (Part 2) | Modell laden/entladen | Knopf (+ PIN) |

Nicht vorgesehen: Updates (laufen vom Proxmox-Host, ADR-028), Shell, Dateizugriff, Ändern von
`passwords.txt`.

## 14. Einrichtung

### 14.1 Im Discord Developer Portal (einmalig, Anleitung `docs/discord-einrichtung.md`)

1. Neue Anwendung „Nikita“ anlegen; Avatar = Nikita-/Scribbles-Bild aus `assets/branding/`
   (512 × 512, von `scripts/build_branding.py` erzeugt).
2. Bot: **Public Bot aus**, **Message Content Intent an**, Token kopieren. „Über mich“ (Bio) aus §8.2
   eintragen (oder vom Setup setzen lassen).
3. Installation: Server- **und** Benutzer-Installation an; Scopes `bot` und `applications.commands`;
   Bot-Rechte: Kanäle ansehen, Nachrichten senden, in Threads senden, öffentliche Threads erstellen,
   Links einbetten, Dateien anhängen, Nachrichtenverlauf lesen, Reaktionen hinzufügen, Verbinden,
   Sprechen, Sprachaktivierung, Sprachnachrichten senden (Rechte-Zahl `70678018640960`, vom
   Setup aus der Liste berechnet und per Test geprüft). Keine Admin- oder Verwaltungsrechte.
4. 2FA am eigenen Discord-Konto einschalten (empfohlen).
5. Eigenen Server anlegen (nur Moritz + Nikita), darin einen Textkanal wie `#nikita` (Standardkanal)
   und einen Sprachkanal; Nikita über den Einladungslink holen.
6. **Kanal-ID kopieren:** Discord → Einstellungen → Erweitert → *Entwicklermodus* an → Rechtsklick auf
   `#nikita` → *Kanal-ID kopieren* (eine lange Zahl). Das Setup kann den Kanal auch selbst anbieten
   (siehe §14.2).

### 14.2 Setup in moritz-agent

- **Installer** (`moritz-install.sh`, neue Phase `discord` nach `secrets`, 07 §2): „Discord-Bot
  einrichten? [j/N]“ → kurzer Hinweis auf §14.1 → Token **verdeckt** eingeben (`read -rs`, per
  stdin an `python -m moritz_agent.setup set-discord-token`) → Prüfung gegen die Discord-API (Bot-Name
  wird angezeigt) → App-Infos lesen: Anwendungs-ID, Besitzer (bzw. Team-Mitglieder zur Auswahl) →
  Warnungen, falls „Public Bot“ an oder Message Content aus ist → Token zeilenweise in
  `passwords.txt` (nur der Wert hinter `bot_token =`, nichts neu serialisiert), `discord.enabled =
  true` und `owner_user_ids` in die TOML → **Einladungslinks** ausgeben (Server-Installation und
  Benutzer-Installation) → **Standard-Textkanal:** „Kanal-ID eingeben (Enter = aus Liste wählen)“ –
  bei Enter wartet das Setup, bis Nikita im Server ist, und zeigt die Textkanäle nummeriert zur
  Auswahl; die ID wird geprüft (Kanal existiert, Nikita darf dort schreiben) und zeilenweise als
  `channel_id` in `passwords.txt` geschrieben → Testnachricht in den Kanal („Guude! Ich bin jetzt
  hier zu Hause ✨“) → optional Avatar, Banner und Bio des Bots setzen.
- **Ohne Installer:** Token und Kanal-ID direkt in `passwords.txt` eintragen und `discord.enabled =
  true` setzen – beim nächsten Start/Reload liest Nikita die Anwendungsdaten selbst und schreibt die
  Einladungslinks ins Log und in `data/run/discord-status.json`. Fehlt die Kanal-ID, läuft Nikita trotzdem
  (DMs, Befehle, Erwähnungen) und meldet im Status „Standardkanal fehlt“; Abos gehen dann per DM.
- **`./test-1.sh discord`** (ohne LXC, wie der Telefontest): `token` (verdeckte Eingabe → lokale
  `passwords.txt`), `channel` (Kanal-ID eingeben oder aus Liste wählen), `check` (Token, Intents,
  App-Einstellungen, Rechte, Kanal, Links), `invite`, `run` (Bot im Vordergrund; Strg+C beendet),
  `say "Text"` (Testnachricht in den Standardkanal).
- **Updater:** `migrate` hängt einen fehlenden Abschnitt `[discord]` mit leerem `bot_token` und
  `channel_id` an bzw. ergänzt einzelne fehlende Schlüssel
  (CFG-09); Discord bleibt aus, bis ein Token eingetragen ist (UPD-04: optionale Integration, keine
  Abfrage). Mit `--non-interactive` gibt es keine Abfrage; der Token kommt dann nur über die Datei.
- **Token wechseln:** neuen Token eintragen, `/admin neu-laden` oder `systemctl reload moritz-agent`
  → der Worker verbindet sich neu (ohne laufende Sprachsitzung erst nach deren Ende).

`passwords.txt`, neuer Abschnitt (Vorlage `config/passwords.template.txt`, P1-41):

```ini
[discord]
# Bot-Token aus dem Discord Developer Portal (Anwendung → Bot → Reset Token). Leer = Discord aus.
bot_token =
# ID des Standard-Textkanals (Entwicklermodus → Rechtsklick auf den Kanal → Kanal-ID kopieren).
# Dort antwortet Nikita auf alles und schreibt Erinnerungen, Warnungen und Hinweise hinein.
channel_id =
# Optional: PIN für gefährliche Admin-Befehle (/admin neustart, /admin modell, später Sandbox).
admin_pin =
```

Die Kanal-ID ist kein Geheimnis, steht aber auf Moritz’ Wunsch zusammen mit dem Token in der TXT – so
wie die SIP-Grunddaten (Registrar, Port) neben dem SIP-Passwort stehen (CFG-08 ergänzt). Alles
Weitere bleibt in der TOML.

## 15. Konfiguration

Neue Sektion in `config/moritz-agent.example.toml` (P1-33/P1-41; IDs sind keine Secrets):

```toml
[discord]
enabled = false                      # true, sobald bot_token in passwords.txt steht (Setup setzt das)
owner_user_ids = []                  # Discord-Benutzer-IDs (Setup übernimmt den App-Besitzer)
trusted_user_ids = []
allowed_guild_ids = []               # weitere Server (der Server des Standardkanals ist immer erlaubt)
chat_channel_ids = []                # weitere Kanäle, in denen Nikita auf jede Nachricht antwortet (Standardkanal steht in passwords.txt)
style = "cute"                       # "cute" | "normal" (§8.2)
startup_message = true               # „Bin wieder wach ✨“ im Standardkanal nach dem Start
name_trigger = true                  # „Nikita, …“ am Satzanfang wirkt wie eine Erwähnung
guest_mode = "off"                   # "off" | "skills"
unknown_users = "ignore"             # "ignore" | "notice"
ephemeral_in_foreign_guilds = true
call_summaries = "off"               # "off" | "topics" | "transcript"
phone_extensions = {}                # z. B. { "20" = "123456789012345678" } für „schick mir das auf Discord“
quiet_hours = "22:00-07:00"
max_message_chars = 4000

[discord.rate_limits]
owner_per_minute = 30
trusted_per_minute = 10
guest_per_minute = 3

[discord.activities]
enabled = true                       # schelmische Aktivitäten (§8.5)
rotate_minutes = [7, 15]             # zufälliger Wechsel in diesem Bereich (mindestens 5)
situational = true                   # Anruf, Sprachkanal, Nacht, Wetter, Sonderdaten, Wartung
night = "23:00-06:00"

[discord.voice]
enabled = true
default_channel_id = ""              # Sprachkanal für /joinvc, wenn Moritz in keinem ist (optional)
auto_join = false                    # von selbst kommen, sobald Moritz einen Sprachkanal betritt
greeting = "phone"                   # "phone" = dieselbe Begrüßung wie am Telefon (PHONE-21)
after_goodbye = "leave"              # "leave" | "stay"
on_silence = "rest"                  # "rest" (still bleiben, auf „Nikita“ hören) | "leave" (wie Auflegen)
idle_leave_minutes = 10              # ohne Menschen im Kanal so lange warten, dann gehen
barge_in = true
max_session_minutes = 120
stt_threads = 4
unload_after_minutes = 10
stage_fallback = false               # Bühnenkanal statt E2EE-Sprachkanal (ADR-036, Ergebnis B)
# Gesprächsparameter wie am Telefon (phone.silence_prompt_s, …); hier nur bei Bedarf überschreiben

[discord.voice_messages]
enabled = true
reply_with_voice = "mirror"          # "mirror" | "always" | "never"
max_seconds = 300

[discord.notify]
target = "channel"                   # "channel" (Standardkanal) | "dm"
warnings_default_level = "severe"    # Standard-Abo des Owners
system_alerts = true
```

Persönliche Einstellungen (Heimatort, Abos, Ruhezeit, Sprachantwort) setzt jede Person selbst mit
`/einstellungen` und `/abo`; sie liegen in den Daten (§16), nicht in der TOML. Der Heimatort jeder
Person ist ohne eigene Einstellung **35781 Weilburg** (`skills.home`).

## 16. Daten und Logs

```sql
discord_principals(user_id TEXT PRIMARY KEY, role TEXT, home_postal_code TEXT NULL, home_name TEXT NULL,
                   quiet_hours TEXT NULL, voice_reply TEXT NULL, created_at TEXT, updated_at TEXT)
discord_subscriptions(id INTEGER PRIMARY KEY, user_id TEXT, kind TEXT, params_json TEXT, created_at TEXT)
reminders(id INTEGER PRIMARY KEY, channel TEXT, target TEXT, due_at TEXT, text TEXT, created_at TEXT,
          delivered_at TEXT NULL)                -- channel = 'discord', target = DM/Kanal-ID
command_registry(hash TEXT, registered_at TEXT)  -- Stand der registrierten Befehle
```

- `call_turns`/`tool_calls` bekommen eine Spalte `channel` (`phone|discord|web`); Part 3 ordnet
  Discord-Kanäle/Threads `conversations` zu.
- Transkript-Aufbewahrung (24 h, STORE-02) gilt für Discord-Turns in **unserer** Datenbank genauso;
  was in Discord steht, löscht Nikita nicht (Discord ist der Speicherort des Gesprächs).
- Log-Kategorie `[Discord]`: Ereignisart, Kanaltyp, Rolle, Skill/Agent, Dauer, Fehlercode – nie Inhalte,
  Token oder Anhänge; IDs von Personen nur gekürzt (letzte 4 Ziffern), außer im Debug-Modus des Owners.

## 17. Abhängigkeiten und Lizenzen

| Paket | Zweck | Lizenz | Hinweis |
| --- | --- | --- | --- |
| `discord.py[voice]` ≥ 2.7 | Gateway, REST, Befehle, Komponenten, Sprache senden mit DAVE | MIT | aktiv gepflegt; `[voice]` zieht PyNaCl und davey |
| `davey` | DAVE-Protokoll (E2EE für Sprache) | MIT (in P1-32 an der Quelle prüfen) | Rust-Erweiterung: Wheels für Python 3.12–3.14 prüfen (NFR-06) |
| `PyNaCl` | Transportverschlüsselung Sprache | Apache-2.0 | |
| `aiohttp` | HTTP/WebSocket (Abhängigkeit von discord.py) | Apache-2.0 | |
| `discord-ext-voice-recv` (DAVE-fähige Fassung) | Sprache empfangen | MIT | nur nach Spike; PyPI oder `third_party/` (ADR-036) |
| libopus (System, `libopus0`/`libopus-dev`) | Opus kodieren/dekodieren | BSD-3-Clause | `libopus-dev` steht schon in der Paketliste (07 §2) |
| `av` (PyAV) | Sprachnachrichten dekodieren | BSD-3-Clause | schon in `phone.lock` |

Neue Lock-Gruppe `requirements/discord.in` → `discord.lock` mit Hashes (ADR-019); Lizenzen in
`THIRD_PARTY_NOTICES.md` **vor** dem Einbau.

## 18. Tests

| Ebene | Inhalt | CI |
| --- | --- | --- |
| Zugriff | Rollenmatrix (Owner/Vertraut/Gast/Unbekannt × DM/Server/fremder Server/Benutzer-App × jede Befehlsgruppe), unbekannter Server → verlassen, Bots ignoriert | ja |
| Befehle | Befehlsbaum gültig (Namen, Beschreibungen ≤ 100 Zeichen, ≤ 25 Optionen, ≤ 100 Befehle), nur aktive Funktionen registriert, Hash-Vergleich | ja |
| Rendern | Embed-Grenzen, Aufteilen an Absätzen ohne kaputte Code-Blöcke, Datei ab Grenze, `allowed_mentions` nie `@everyone`, Secret-Filter, custom_id kodieren/dekodieren | ja |
| Kern-Anbindung | Turn mit `surface = chat`/`spoken`, Skill-Antworten mit `markdown`/`card`/`actions`, Rückfrage → Auswahlliste → Auflösung | ja |
| Planer | Erinnerungen/Abos mit fester Uhr: Ruhezeiten, Sommerzeitwechsel, Nachholen nach Neustart, Drosselung | ja |
| Sprache (ohne Discord) | synthetische PCM → Opus → zurück, 48↔16 kHz, VAD je Sprecher, Weckwort im Ruhe-Modus, Unterbrechen, Wiedergabe-Takt 20 ms; `CallSession` über `MediaChannel` (Fake-Sprachkanal: Betreten = Anruf, Verlassen = Auflegen) | ja |
| Sprachnachrichten | OGG/Opus-Dateien dekodieren, Längen-/Größengrenzen, Antwort-Datei mit Wellenform | ja |
| Fake-Discord | Ereignisse und Interaktionen als JSON-Payloads in den Client einspeisen; ausgehende REST-Aufrufe aufzeichnen (kein Netz) | ja |
| Live | privater Test-Server mit Test-Bot (Token nur in lokaler `passwords.txt`), `@pytest.mark.discord` | nein |
| Spike Sprache | DAVE-Empfang 60 min, Sprecherwechsel, Schlüsselwechsel, Reconnect (P1-32-Protokoll) | nein |
| Sicherheit | Token nie in Logs/Status (Suche nach dem Testtoken), Admin ohne Owner verweigert, PIN-Fehlversuche begrenzt, Anhänge außerhalb des CDN abgelehnt | ja |

## 19. Latenz und Ressourcen

| Weg | Ziel |
| --- | --- |
| Textnachricht → Sofortauskunft sichtbar | ≤ 1 s (Gateway + Skill aus Cache) |
| Slash-Befehl → Bestätigung | < 3 s (Pflicht von Discord), Ziel < 300 ms |
| LLM-Antwort im Chat → erster Satz sichtbar | ≈ Zeit bis erster Satz des LLM + 0,5 s |
| Sprachkanal: Sprechende → Antwortbeginn | ≤ 2,5 s mit Skill aus Cache (wie Telefon + Discord-Weg) |
| RAM Discord-Worker | ≈ 0,1–0,2 GB; + ≈ 1–1,5 GB nur während Sprachsitzungen (Messung P1-36, 06 §2.2) |
| Netz | ausgehend TCP 443 (Gateway, REST, CDN), ausgehend UDP zu Discords Sprachservern (06 §5) |

## 20. Umsetzung (Block D)

Tickets in [04 Block D](04-part1-umsetzung.md#block-d--discord-bot): **P1-31** Kanal-Kern ·
**P1-32** Spike (Gateway, Befehle, DAVE senden/empfangen, Sprachnachrichten senden, Upload-Grenzen) ·
**P1-33** Worker-Grundgerüst · **P1-34** Text + Sofortauskünfte · **P1-35** Befehle, Kontextmenüs,
Autovervollständigung, Benutzer-App · **P1-36** Sprachkanal · **P1-37** Sprachnachrichten ·
**P1-38** Proaktive Nachrichten, Erinnerungen · **P1-39** Telefon ↔ Discord · **P1-40** Admin ·
**P1-41** Einrichtung · **P1-43** Persönlichkeit und Aktivitäten · **P1-42** Abnahme (zuletzt).

Reihenfolge: P1-31 braucht P1-19 (Skill-Framework). Danach P1-32 → P1-33 → P1-34/P1-35/P1-41 →
P1-36/P1-37 (je nach Spike) → P1-38/P1-39/P1-40/P1-43 → P1-42. Block D läuft parallel zu den späteren
Wellen von Block S; LLM-Funktionen (`/frag`, freie Fragen, `/suche`) kommen mit P1-09 automatisch dazu.
Jede spätere Funktion (Part 2–9, 1.1+) bringt ihre Discord-Form im selben Ticket mit (Kanal-Parität).

## 21. Abnahme

Protokoll `docs/abnahme/discord-<datum>.md`, privater Server + DM + Benutzer-App:

| # | Prüfung | Erwartung |
| --- | --- | --- |
| 1 | Setup mit Token-Eingabe; zweiter Lauf | Token nur in `passwords.txt` (0600), Einladungslinks korrekt; zweiter Lauf ändert nichts |
| 2 | DM „wie isses wedder morsche?“ | Karte für **Weilburg**, Quelle in der Fußzeile, Folgeknöpfe funktionieren |
| 3 | `/wetter ort:` mit Autovervollständigung, PLZ 60311, „Neustadt“ | richtige Orte, Auswahlliste bei Mehrdeutigkeit |
| 4 | Benutzer-App in einem fremden Server/Gruppen-DM | `/wetter` geht, Antwort nur für mich sichtbar |
| 5 | Fremde Person schreibt Nikita / erwähnt sie | keine Reaktion (bzw. Hinweis bei `notice`) |
| 6 | Bot in nicht erlaubten Server einladen | geht nicht (Public Bot aus) bzw. Nikita verlässt ihn |
| 7 | `/joinvc`, dann den Sprachkanal betreten; drei Fragen ohne „Nikita“; Unterbrechen; „Tschüss“ | Begrüßung wie am Telefon, Antworten gesprochen, Unterbrechen < 300 ms, Abschied und Verlassen |
| 7a | Im Sprachkanal: schweigen; Kanal verlassen und wieder betreten | „Bist du noch da?“ → Ruhe-Modus, „Nikita“ weckt; Verlassen = Auflegen, Wiederkommen = neues Gespräch |
| 7b | Standardkanal: Frage ohne Erwähnung; Erinnerung und Warnungs-Abo | Antwort ohne Erwähnung; Erinnerung/Warnung landen im Standardkanal |
| 7c | Stil und Aktivitäten eine Stunde beobachten; Warnung (Fixture) | süß, aber Fakten exakt; Aktivitäten wechseln, keine Wiederholung unter 10; bei Warnung Ernst-Modus |
| 8 | Sprachkanal + gleichzeitiger Anruf an 999 | Telefon unbeeinträchtigt (Latenz wie ohne Discord) |
| 9 | Sprachnachricht senden | Transkript + Antwort, optional als Sprachnachricht |
| 10 | `/erinnere wann: in 2 Minuten`, Dienst zwischendurch neu starten | Erinnerung kommt (ggf. „verspätet“) |
| 11 | Warnungs-Abo mit Test-Warnung (Fixture) | DM kommt, Ruhezeit beachtet |
| 12 | `/admin status`, `/admin logs`, `/admin wartung` als Owner und als Vertrauter | Owner: geht mit Bestätigung; Vertrauter: verweigert |
| 13 | Token-Suche über alle Logs/Statusdateien | kein Treffer |
| 14 | Token im Portal neu erzeugen, eintragen, neu laden | Verbindung mit neuem Token, alter ungültig |
| 15 | Ab P1-09: `/frag` mit Websuche | Antwort gestreamt, Quellen als Links |

## 22. Risiken

| # | Risiko | Gegenmaßnahme |
| --- | --- | --- |
| R27 | DAVE-Empfang in Python unreif (nur Forks) → Nikita hört im Sprachkanal nicht zu | Spike P1-32 mit festen Kriterien; Rückfall „nur sprechen“ + Sprachnachrichten + Bühnenkanal; erneuter Spike bei offizieller Unterstützung |
| R28 | Discord ändert API/Regeln, discord.py hinkt hinterher | gepinnte Versionen, schneller Update-Weg (ADR-028), Discord-Worker isoliert – Telefon läuft weiter |
| R29 | Bot-Token gelangt nach außen → fremde Kontrolle über den Bot | nur `passwords.txt` 0600, Redaction, Public Bot aus, Reset-Anleitung, keine gefährlichen Fähigkeiten ohne Owner-Bestätigung |
| R30 | Datenschutz: Inhalte liegen bei Discord | Standards „aus“ für Transkripte/Notizen/Gedächtnis, Hinweis `/hilfe datenschutz` |
| R31 | CPU/RAM-Konkurrenz Telefon ↔ Discord-Sprache | `nice +5`, Modelle nur bei Bedarf, eine Sprachsitzung, Priorität PHONE, Messung in P1-36 |
| R32 | Missbrauch durch andere in Servern (Spam, Prompt-Injection, Ausfragen) | Allowlists, Standard „ignorieren“, Rate-Limits, Fremdinhalte nur als Daten, keine Interna in Kanälen |
| R33 | Benutzer-App-Grenzen (keine Nachrichten/Sprache in fremden Servern, dort oft nur privat sichtbar) | so dokumentiert und in `/hilfe` erklärt; volle Funktionen im eigenen Server und per DM |
| R34 | Schelmische Aktivitäten oder der süße Ton wirken unpassend oder beunruhigend („spielt mit deinen Daten“) | nur eigene, geprüfte Sprüche ohne Vorfall-Anschein; Ernst-Modus bei Warnungen/Fehlern; `/aktivitaet aus`, `style = "normal"`; Privatserver |

## 23. Offene Fragen an Moritz

Default bis zur Antwort in Klammern; auch in [10 §3](10-risiken-offene-fragen.md#3-offene-fragen--neu).

| # | Frage | Default |
| --- | --- | --- |
| F-29 | ~~Eigener Server, Kanal für alles?~~ **beantwortet:** Privatserver mit Moritz + Nikita, Standard-Textkanal per ID im Setup oder in der TXT | – |
| F-30 | Wer außer dir darf Nikita auf Discord benutzen (Familie, Freunde)? Gastmodus mit nur Sofortauskünften? | nur du; Gastmodus aus |
| F-31 | Soll Nikita zusätzlich zu `/joinvc` automatisch kommen, wenn du einen Sprachkanal betrittst? | nein |
| F-32 | Welche Abos willst du (Warnungen, Morgenbriefing mit Uhrzeit, Müll am Vorabend, Systemhinweise)? | Warnungen ab Unwetter + Systemhinweise an, Rest aus |
| F-33 | Anrufhinweise auf Discord? Mit Themen oder Transkript? | aus |
| F-34 | ~~Bot-Name, Stil, Status?~~ **beantwortet:** „Nikita“, süß, schelmische Aktivitäten (§8.2, §8.5) | – |
| F-35 | Auf Sprachnachrichten auch mit Sprachnachricht antworten? | ja („mirror“) |
| F-36 | PIN für gefährliche Admin-Befehle? | keine PIN, aber Bestätigungsknopf |
| F-37 | ~~Antworten im Kanal oder per DM?~~ **beantwortet:** Standardkanal für alles (Privatserver) | – |
| F-38 | Magst du eine extra niedliche Scribbles-Pose für Nikitas Avatar zeichnen? (Neue Posen kommen nur von dir, Branding-Regel 2) | Scribbles weiß auf dunklem Grund |
| F-39 | Im Sprachkanal bei langer Stille: still im Kanal bleiben und auf „Nikita“ hören, oder gehen wie beim Auflegen? | still bleiben („rest“) |
| F-40 | Lieblingssprüche für die Aktivitäten? (kommen zusätzlich in die Rotation) | Liste aus §8.5 |

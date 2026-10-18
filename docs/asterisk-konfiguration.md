# Asterisk-Konfiguration für moritz-agent

Diese Anleitung beschreibt **alles, was auf der Telefonanlage `192.168.1.176` vorhanden sein
muss**, damit Moritz intern die **999** wählen kann und bei **Nikita** (dem Agent) landet. Der moritz-agent-
Installer ändert an Asterisk **nichts** (Anforderung PHONE-02, INST-09) – diese Schritte
macht der Admin der Anlage einmalig von Hand.

| Wert | Inhalt | Herkunft |
| --- | --- | --- |
| SIP-Benutzer / Auth-User | `agent` | `passwords.txt` → `[sip] username`, `auth_username` |
| SIP-Passwort | `agent` (Startwert) | `passwords.txt` → `[sip] password` |
| Registrar | `192.168.1.176`, UDP 5060 | `passwords.txt` → `[sip] registrar`, `port`, `transport` |
| Nebenstelle zum Anrufen | `999` | `passwords.txt` → `[sip] extension` |
| IP des Agent-LXC | `<AGENT_IP>` (feste IP, im Folgenden einsetzen) | Proxmox-LXC-Konfiguration; `install.sh` nennt sie am Ende, feste Adresse per `--ip 192.168.1.50/24 --gateway …` ([proxmox-installation.md](proxmox-installation.md)) |
| RTP-Ports Agent | UDP 40000–40199 | `config/moritz-agent.toml` → `[phone] rtp_port_*` |

> Die Platzhalter `<AGENT_IP>` und `<INTERN_CONTEXT>` (der Dialplan-Kontext, in dem eure
> Telefone wählen, oft `from-internal` oder `internal`) müssen ersetzt werden.

---

## 1. Herausfinden, was bei euch läuft

Auf der Telefonanlage als root:

```bash
asterisk -rx "core show version"          # Version (empfohlen: 18 LTS, 20 LTS oder 22 LTS)
asterisk -rx "module show like pjsip"     # chan_pjsip geladen? → Abschnitt 2
asterisk -rx "module show like chan_sip"  # alter chan_sip (nur bis Asterisk 20) → Abschnitt 6
asterisk -rx "module show like g722"      # codec_g722 für HD-Audio
asterisk -rx "pjsip show endpoints"       # vorhandene Telefone und deren Kontext
asterisk -rx "dialplan show"              # Kontexte; hier <INTERN_CONTEXT> ablesen
ls /etc/asterisk/                         # pjsip.conf / extensions.conf vorhanden?
```

Ist eine **FreePBX**-Oberfläche installiert (Ordner `/etc/asterisk/` enthält `*_custom.conf`-
Dateien und `freepbx_*`), gilt Abschnitt 5 statt 2 und 3.

## 2. `pjsip.conf` (Asterisk mit chan_pjsip, Standard seit Asterisk 13)

Am Ende von `/etc/asterisk/pjsip.conf` einfügen. Falls bereits ein UDP-Transport auf 5060
existiert, den Block `transport-udp` **nicht** doppelt anlegen.

```ini
; ---------------------------------------------------------------------------
; moritz-agent – SIP-Konto "agent", erreichbar über Nebenstelle 999
; ---------------------------------------------------------------------------

; Nur anlegen, wenn noch kein UDP-Transport auf 5060 existiert:
;[transport-udp]
;type = transport
;protocol = udp
;bind = 0.0.0.0:5060

; Nur der Agent-LXC darf sich als "agent" registrieren bzw. Anrufe senden.
[agent-acl]
type = acl
deny = 0.0.0.0/0.0.0.0
permit = <AGENT_IP>/255.255.255.255

[agent]
type = auth
auth_type = userpass
username = agent
password = agent              ; muss exakt [sip] password aus passwords.txt entsprechen

[agent]
type = aor
max_contacts = 1              ; genau ein Agent-Endpunkt
remove_existing = yes         ; Neustart des Agents ersetzt die alte Registrierung
qualify_frequency = 30        ; Asterisk merkt nach spätestens ~30 s, wenn der Agent weg ist
qualify_timeout = 3.0

[agent]
type = endpoint
transport = transport-udp     ; Namen des vorhandenen UDP-Transports eintragen
context = from-agent          ; eigener, abgeschotteter Kontext (Abschnitt 3)
auth = agent
aors = agent
acl = agent-acl
callerid = Nikita <999>
disallow = all
allow = g722                  ; 16 kHz HD-Audio → bessere Spracherkennung
allow = alaw                  ; G.711 a-law (Europa)
allow = ulaw                  ; G.711 µ-law (Fallback)
direct_media = no             ; RTP läuft immer über Asterisk → einfache Firewall
rtp_symmetric = yes
force_rport = yes
rewrite_contact = yes
dtmf_mode = rfc4733           ; für spätere DTMF-Steuerung (Part 7)
send_pai = yes
trust_id_inbound = no
allow_subscribe = no
device_state_busy_at = 1      ; zweiter Anruf → besetzt (der Agent antwortet ohnehin 486)
```

Danach: `asterisk -rx "module reload res_pjsip.so"`.

## 3. `extensions.conf` (Dialplan)

```ini
; ---------------------------------------------------------------------------
; moritz-agent – 999 klingelt beim registrierten Agent
; In den Kontext einfügen, aus dem eure Telefone wählen (<INTERN_CONTEXT>):
; ---------------------------------------------------------------------------
[<INTERN_CONTEXT>]
exten => 999,1,NoOp(moritz-agent: Anruf von ${CALLERID(all)})
 same => n,Set(CALLERID(name)=${CALLERID(name)})
 same => n,Dial(PJSIP/agent,30)          ; 30 s klingeln lassen, der Agent nimmt sofort ab
 same => n,GotoIf($["${DIALSTATUS}" = "BUSY"]?busy)
 same => n,Playback(vm-nobodyavail)      ; Agent nicht registriert / nicht erreichbar
 same => n,Hangup()
 same => n(busy),Busy(5)
 same => n,Hangup()

; ---------------------------------------------------------------------------
; Kontext des Agents selbst: darf NICHTS anrufen (Part 1 macht keine
; ausgehenden Anrufe, PHONE-10). Schützt vor Missbrauch des Kontos.
; ---------------------------------------------------------------------------
[from-agent]
exten => _X.,1,NoOp(moritz-agent darf nicht wählen)
 same => n,Hangup(21)
exten => _[a-zA-Z*#+].,1,Hangup(21)
```

Danach: `asterisk -rx "dialplan reload"`.

## 4. Asterisk-seitige Ports und Firewall

`/etc/asterisk/rtp.conf` (meist schon vorhanden, nur prüfen):

```ini
[general]
rtpstart = 10000
rtpend = 20000
```

Firewall **auf der Telefonanlage**: UDP 5060 und UDP `rtpstart–rtpend` vom Agent-LXC
(`<AGENT_IP>`) erlauben. Firewall **im Agent-LXC**: siehe
[`docs/plan/06-infrastruktur.md`](plan/06-infrastruktur.md) §5.

## 5. Variante FreePBX

FreePBX erzeugt `pjsip.conf` und `extensions.conf` selbst – dort nichts von Hand eintragen.

1. **Einstellungen → Asterisk SIP Settings → Codecs:** `g722`, `alaw`, `ulaw` aktivieren.
2. Den Endpunkt mit Benutzername `agent` in `/etc/asterisk/pjsip.endpoint_custom_post.conf`,
   `pjsip.auth_custom_post.conf`, `pjsip.aor_custom_post.conf` anlegen (Inhalte wie in
   Abschnitt 2, jeweils nur der passende `type`-Block), weil FreePBX-Nebenstellen sonst
   numerische Benutzernamen erzwingen.
3. Dialplan in `/etc/asterisk/extensions_custom.conf`:
   ```ini
   [from-internal-custom]
   exten => 999,1,Dial(PJSIP/agent,30)
    same => n,Hangup()

   [from-agent]
   exten => _X.,1,Hangup(21)
   ```
4. `fwconsole reload`.

Alternative ohne Custom-Dateien: In FreePBX eine PJSIP-Nebenstelle **999** anlegen und in
`passwords.txt` `username = 999`, `auth_username = 999` und das dort vergebene Secret
eintragen (`extension = 999` bleibt). Der Agent funktioniert mit beiden Varianten.

## 6. Variante altes `chan_sip` (`sip.conf`, nur Asterisk ≤ 20)

```ini
[agent]
type = friend
host = dynamic
secret = agent
defaultuser = agent
context = from-agent
disallow = all
allow = g722
allow = alaw
allow = ulaw
directmedia = no
nat = force_rport,comedia
qualify = yes
call-limit = 1
deny = 0.0.0.0/0.0.0.0
permit = <AGENT_IP>/255.255.255.255
```

Dialplan wie Abschnitt 3, aber `Dial(SIP/agent,30)`. Empfehlung: auf chan_pjsip wechseln,
chan_sip ist in aktuellen Asterisk-Versionen entfernt.

## 7. Prüfen

```bash
# Nach dem Start von moritz-agent (Statusseite zeigt "registriert"):
asterisk -rx "pjsip show contacts"              # agent/sip:agent@<AGENT_IP>:5060  Avail
asterisk -rx "pjsip show endpoint agent"        # Codecs, Kontext from-agent, ACL
asterisk -rx "dialplan show 999@<INTERN_CONTEXT>"
# Anruf von einem Telefon an 999, parallel:
asterisk -rvvv                                   # Live-Log: Dial(PJSIP/agent) → ANSWER
asterisk -rx "core show channels verbose"        # ausgehandelter Codec (g722 bevorzugt)
```

Abnahmepunkt 3 in [`docs/plan/09-tests-abnahme.md`](plan/09-tests-abnahme.md): **REGISTER
allein reicht nicht** – erst wenn ein Anruf an 999 beim Agent klingelt, ist der Dialplan
korrekt.

## 8. Fehlerbilder

| Symptom | Ursache | Lösung |
| --- | --- | --- |
| Status „Registrierung fehlgeschlagen 401/403“ | Passwort/Benutzer in `passwords.txt` ≠ Asterisk | Werte angleichen, Reload in der Web-UI |
| Registrierung ok, 999 → „nicht verfügbar“ | 999 nicht im `<INTERN_CONTEXT>` | Abschnitt 3 prüfen, `dialplan show 999@…` |
| Anruf wird angenommen, aber Stille | RTP blockiert (Firewall/NAT) | `direct_media = no`, Firewall RTP-Ports, `rtp_symmetric = yes` |
| Nur eine Richtung Audio | Asymmetrisches RTP/NAT | `rewrite_contact`, `force_rport`, feste IP des LXC |
| Schlechte Erkennung | nur G.711 ausgehandelt | `codec_g722` laden, `allow = g722` vor `alaw` |
| Zweiter Anrufer hört Klingeln statt besetzt | `device_state_busy_at` fehlt | setzen; Agent antwortet zusätzlich mit 486 |
| `No matching endpoint found` im Log | ACL oder falscher Benutzername | `<AGENT_IP>` in `agent-acl`, `username` prüfen |

## 9. Sicherheit

- Das Konto `agent/agent` ist nur aus dem LAN erreichbar und durch die ACL auf die IP des
  Agent-LXC beschränkt; der Kontext `from-agent` kann nichts wählen. Damit ist das schwache
  Startpasswort vertretbar (Entscheidung Moritz, F-02). Ein stärkeres Passwort wird trotzdem
  empfohlen – dann in `pjsip.conf` **und** `passwords.txt` ändern.
- Port 5060 der Telefonanlage niemals ins Internet weiterleiten.

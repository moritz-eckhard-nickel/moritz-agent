# moritz-agent auf Proxmox einrichten und aktualisieren

`install.sh` und `update.sh` richten Nikita **vom Proxmox-Host aus** ein: Sie legen den LXC-Container an
(oder verwenden ihn weiter), kopieren das Programm hinein und starten dort den Installer bzw. Updater.
Entscheidung und Hintergründe: ADR-028 in [`plan/03-entscheidungen.md`](plan/03-entscheidungen.md).

> Zum **Ausprobieren ohne LXC** gibt es `./test-1.sh` ([`telefon-test-1.md`](telefon-test-1.md)) – es setzt weder
> Proxmox noch einen Container noch root voraus.

## Ablauf in Kürze

```bash
# 1. Programm auf den Proxmox-Host bringen (eine Möglichkeit):
git clone https://github.com/moritz-eckhard-nickel/moritz-agent.git && cd moritz-agent
#    oder: scp -r moritz-agent root@proxmox:~/   (vom Rechner, auf dem das Repo liegt)

# 2. Container anlegen und installieren (auf dem Proxmox-Host, als root bzw. mit sudo):
sudo ./install.sh

# 3. Später, nach einem git pull im selben Ordner:
sudo ./update.sh
```

**Ohne das Repo auf dem Proxmox-Host** – von Sophie-1s Konsole oder irgendeinem Rechner mit ssh-Zugang:

```bash
./install.sh --remote root@proxmox          # kopiert nur das Programm (≈ 14 MB) per scp und führt dort aus
./update.sh  --remote root@proxmox          # genauso für Updates
./install.sh --remote admin@proxmox --ssh-port 2222 --identity ~/.ssh/id_ed25519   # normaler Benutzer: sudo auf dem Host
```

Bei `--remote` mit normalem Benutzer fragt `sudo` auf dem Host nach dem Passwort (ssh läuft mit Terminal).
Mit `--dry-run` zeigt jeder Aufruf nur an, was er täte.

## Was `install.sh` tut

1. Prüft, dass es auf einem Proxmox-Host läuft (`pct`, `pveam`, `pvesm`), und sucht einen Container namens
   `moritz-agent` (oder `--ctid`). **Gibt es ihn schon**, wird stattdessen aktualisiert (oder eine abgebrochene
   Installation fortgesetzt) – nichts geht verloren, das Skript kann beliebig oft laufen.
2. Wählt Speicher (`local-lvm`, sonst den ersten aktiven) und die **Ubuntu-Vorlage** (26.04, sonst 25.10, sonst
   24.04) und lädt sie bei Bedarf herunter.
3. Zeigt den Plan und fragt nach (`--yes` überspringt das), dann `pct create`: **unprivilegiert**, `nesting=1`,
   Start beim Booten, ohne Root-Passwort, Zeitzone `Europe/Berlin`, mit den Werten aus
   [`plan/06-infrastruktur.md`](plan/06-infrastruktur.md) §3.
4. Startet den Container und wartet auf das Netzwerk. Hat der Host eine NVIDIA-GPU (`/dev/nvidia0`), werden die
   Geräte durchgereicht (`--gpu auto`, Proxmox ≥ 8.1) – für Telefon und Stimme nicht nötig, erst für das
   spätere Sprachmodell.
5. Kopiert das Programm in den Container und startet `moritz-install.sh`: Systempakete, Dienstbenutzer
   `moritz-agent`, Programm nach `/opt/moritz-agent`, Python-Umgebung (gepinnte Pakete mit Prüfsummen),
   PJSIP-Build, Modelle (Whisper small, Piper-Stimme „Hessisch“, ≈ 0,6 GB), `passwords.txt` und
   `config/moritz-agent.toml` aus den Vorlagen, Ansagen vorrendern, systemd-Dienst `moritz-agent`, Prüfung.
6. Zeigt am Ende die Adresse des Containers und die nächsten Schritte.

### Optionen (`install.sh`)

| Option | Standard | Bedeutung |
| --- | --- | --- |
| `--ctid ID` | nächste freie | Container-ID; ein vorhandener Container wird weiterverwendet |
| `--hostname NAME` | `moritz-agent` | Name – daran wird der Container wiedergefunden |
| `--storage NAME` | `local-lvm` | Speicher der Root-Platte |
| `--template-storage NAME` | `local` | Speicher der Vorlage |
| `--os-template NAME` | Ubuntu 26.04 → 25.10 → 24.04 | andere Vorlage (`pveam available`) |
| `--disk GB` | 80 | Plattengröße |
| `--memory MB` / `--swap MB` | 16384 / 2048 | RAM-Limit (kein Reservieren) / Swap |
| `--cores N` / `--cpuunits N` | 18 (höchstens die des Hosts) / 512 | CPU; niedrigeres Gewicht lässt dem Host Vorrang |
| `--bridge`, `--vlan`, `--ip`, `--gateway`, `--dns`, `--search-domain` | `vmbr0`, –, `dhcp` | Netzwerk. **Feste Adresse empfohlen** (Asterisk-ACL): `--ip 192.168.1.50/24 --gateway 192.168.1.1` |
| `--gpu auto\|yes\|no` | `auto` | NVIDIA-Geräte durchreichen |
| `--ssh-key DATEI` | – | öffentlicher Schlüssel für `root` im Container |
| `--timezone ZONE` | `Europe/Berlin` | |
| `--no-start` | – | Container nur anlegen |
| `--skip-models`, `--jobs N` | – | Modelle nicht laden / Build-Prozesse |
| `--yes`, `--dry-run` | – | ohne Rückfrage / nur anzeigen |
| `--remote [USER@]HOST`, `--ssh-port`, `--identity` | – | von einem anderen Rechner ausführen |

## Was `update.sh` tut

1. Findet den Container (`moritz-agent` oder `--ctid`), startet ihn falls nötig und legt einen
   **Proxmox-Snapshot** `moritz-pre-update-<Zeit>` an (die letzten 3 bleiben; `--no-snapshot`,
   `--require-snapshot`, `--keep-snapshots N`). Speicher ohne Snapshot-Unterstützung: Warnung, weiter.
2. Kopiert **die Programmversion des Ordners, aus dem es läuft**, in den Container und startet dort
   `moritz-update.sh` – immer die neue Version des Updaters:
   - **Wartungsmodus:** Neue Anrufe bekommen das Besetztzeichen, ein laufendes Gespräch wird zu Ende geführt
     (`--drain-timeout`, Standard 600 s). Läuft danach noch eines, wird das Update **verschoben** (Exit 75) –
     es wurde nichts verändert.
   - **Sicherung** nach `/opt/moritz-agent/backups/<Zeit>/` (0700): `passwords.txt`, Konfiguration, Zustand und
     der alte Programmcode (die letzten 5).
   - **Neue Python-Umgebung** nur, wenn sich Pakete oder PJSIP geändert haben – sie wird gebaut, *während der
     Dienst noch läuft*; die alte bleibt als `venv.prev`.
   - Dienst stoppen, Programmdateien austauschen (nur Programmteile; veraltete Dateien der alten Version werden
     entfernt), Modelle/Ansagen nachziehen, Dienst starten und auf „läuft“ warten.
   - **Rollback** bei Fehler: alter Code, alte Umgebung, gesicherte Dateien zurück, Dienst wieder starten
     (Exit 70; bei fehlgeschlagenem Rollback Exit 71 – dann `pct rollback <ID> <Snapshot>`).
3. Gibt den Exit-Code des Updaters weiter und räumt alte Snapshots auf.

**Unverändert bleiben immer:** `passwords.txt`, `config/moritz-agent.toml`, `models/`, `data/` (Logs, Zustand),
`runtime/` und der Ansagen-Cache.

### Exit-Codes

| Code | Bedeutung |
| ---: | --- |
| 0 | alles in Ordnung |
| 2 | falsche Benutzung / Rückfrage nötig, aber kein Terminal (`--yes`) |
| 64 | Voraussetzung nicht erfüllt (kein Proxmox-Host, kein Container, nicht installiert …) |
| 70 | Update fehlgeschlagen, alter Stand wiederhergestellt |
| 71 | Update **und** Rollback fehlgeschlagen – `pct rollback` |
| 75 | Update verschoben (ein Gespräch läuft) |

## Nach der Installation

```bash
pct enter <ID>                                            # Konsole im Container
pct exec <ID> -- nano /opt/moritz-agent/passwords.txt     # [sip]: Konto/Passwort/Registrar der Anlage
pct exec <ID> -- systemctl reload moritz-agent            # Änderungen übernehmen
pct exec <ID> -- journalctl -u moritz-agent -n 50         # Log
```

1. **SIP:** Die Vorlage enthält die Startwerte (`agent`/`agent` bei `192.168.1.176`). Ein starkes Passwort in
   Asterisk **und** `passwords.txt` wird empfohlen.
2. **Asterisk:** Die Adresse des Containers (am Ende der Installation genannt) gehört in die ACL –
   [`asterisk-konfiguration.md`](asterisk-konfiguration.md). Der Installer verändert Asterisk nie.
3. **Testanruf:** Nebenstelle **999** wählen: Begrüßung, „Wie viel Uhr haben wir?“, „Tschüss“.
4. Ohne Sprachmodell antwortet Nikita auf alles außer den Sofort-Antworten (Uhrzeit, Datum …) mit „Ich habe
   verstanden: …“ – das Sprachmodell kommt mit den nächsten Tickets.

## Was am Proxmox-Host verändert wird

Nur: eine fehlende Ubuntu-Vorlage laden · **einen** neuen Container anlegen (bzw. dessen GPU-`dev`-Einträge
ergänzen) · Snapshots dieses Containers. Keine Host-Pakete, Treiber, Netzwerk-, Firewall- oder Speicher-
einstellungen, keine anderen Container oder VMs. Fremde Container (ohne die Markierung in der Beschreibung)
fasst das Skript nur nach ausdrücklicher Rückfrage an.

## Entfernen

```bash
pct stop <ID> && pct destroy <ID>      # Container samt Daten löschen – unwiderruflich
```

## Nicht automatisiert (bewusst)

- **NVIDIA-Treiber** am Host und im Container (Plan 06 §4) – erst für das Sprachmodell nötig. Das Skript nennt
  die Host-Treiberversion; im Container muss der Userspace-Treiber exakt dieselbe haben.
- **Firewall** im Container (Plan 06 §5: nftables) und Asterisk-Einrichtung.

## Fehlersuche

| Symptom | Ursache / Abhilfe |
| --- | --- |
| „'pct' nicht gefunden“ | nicht auf dem Proxmox-Host – dort ausführen oder `--remote` benutzen |
| „keine Ubuntu-Vorlage … gefunden“ | Host ohne Internet / `pveam update` fehlgeschlagen |
| „der Container hat … kein Netzwerk“ | Bridge/VLAN/DNS prüfen (`--bridge`, `--vlan`, `--dns`), `pct enter <ID>` |
| Installer bricht ab | Meldung lesen, beheben, **denselben Befehl noch einmal** – setzt fort; Protokolle im Container unter `/var/log/moritz-agent/` |
| „Python >= 3.12 nötig“ | Vorlage zu alt (`--os-template` Ubuntu 24.04 oder neuer) |
| Update „verschoben“ (75) | Es läuft ein Gespräch; später wiederholen oder `--drain-timeout` erhöhen |
| Registrierung schlägt fehl | `passwords.txt` [sip] und Asterisk-Konto vergleichen; `pct exec <ID> -- journalctl -u moritz-agent` |

## Ehrlicher Teststand (18.10.2026)

Getestet wurde in einer Entwicklungsumgebung ohne Proxmox: `install.sh`/`update.sh` gegen einen **simulierten
Proxmox-Host** (aufzeichnende `pct`/`pveam`/`pvesm`/`ssh`/`scp`-Ersatzprogramme: Container anlegen, Vorlage, Optionen,
GPU-Einträge, Update mit Snapshot, Aufräumen, Remote-Weg, Dry-Run, Exit-Codes) und `moritz-install.sh`/`moritz-update.sh`
als **echte Läufe** gegen einen kleinen Programmbaum mit aufzeichnenden Ersatzbefehlen für `apt-get`, `useradd`,
`chown`, `systemctl` (Neuinstallation, Wiederholung ohne Datenverlust, Update, Verschieben bei laufendem Gespräch,
Rollback, Sicherungen, Umgebung nur bei Bedarf neu). Zusätzlich lief der Wartungsmodus des Dienstes mit echten
SIP-Anrufen (486 bei `drain`).

**Noch nicht gelaufen:** ein echter Proxmox-Host, ein echter Ubuntu-LXC (Pakete per `apt`, systemd-Unit,
unprivilegierter Container mit `nesting`, PJSIP-Build und Modell-Download dort), die GPU-Durchreichung und
Python 3.14 (Ubuntu 26.04). Der erste echte Lauf ist deshalb der eigentliche Test – bei einem Fehler genügt es,
die Meldung zu schicken; das Skript lässt sich gefahrlos wiederholen.

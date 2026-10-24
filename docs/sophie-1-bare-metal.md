# Anton auf Sophie-1 – direkt auf dem Host (bare metal)

Seit dem 24.10.2026 läuft moritz-agent **direkt auf Sophie-1**, ohne LXC (ADR-039). Diese Seite sagt,
was einmalig von Hand passiert und was die Skripte erledigen.

| Was | Wie | Wer |
| --- | --- | --- |
| NVIDIA-Treiber | einmalig, Abschnitt 1 | du (Neustart nötig) |
| alles testen | `./test-3.sh setup` und `./test-3.sh run` im entpackten Ordner | Skript |
| als Dienst installieren | `sudo ./moritz-install.sh` | Skript |
| Modelle | liegen alle in `/home/models`, `models/` ist nur ein Link | Skript |

## 1. NVIDIA-Treiber (einmalig)

Sophie-1 ist ein Proxmox VE 9 (Debian 13). Ohne Treiber laufen Telefon, Stimme und Sofortauskünfte,
aber nicht das Sprachmodell. Als root:

```bash
apt install proxmox-default-headers build-essential dkms     # Kernel-Header passend zum Proxmox-Kernel
printf 'blacklist nouveau\noptions nouveau modeset=0\n' > /etc/modprobe.d/blacklist-nouveau.conf
update-initramfs -u && reboot
# NVIDIA-Treiber (Production Branch, kann die RTX 3070) von nvidia.com laden, dann:
sh NVIDIA-Linux-x86_64-<VERSION>.run --dkms
nvidia-smi                                                    # muss die RTX 3070 mit 8 GB zeigen
```

Das CUDA-Toolkit brauchst du **nicht**. KoboldCpp holt sich beim ersten Build seine eigene
CUDA-Umgebung in den Ordner `conda/` (≈ 6–10 GB).

## 2. Testen: `./test-3.sh`

```bash
./test-3.sh setup     # Cache /home/models, alles aus test-2, Qwen3 (13,8 GB) + Ersatzmodelle, KoboldCpp bauen,
                      # Zuhören im Discord-Sprachkanal – ohne Rückfragen, beim ersten Mal ≈ 30–60 min
./test-3.sh run       # alle Tests, Sprachmodell einmessen (--moecpu), Abnahmeprotokoll, danach Live-Test
```

Wenn du eine neue Version über die alte entpackst und wieder `setup` aufrufst, wird nur neu gebaut
oder geladen, was sich geändert hat. Details: [test-3.md](test-3.md).

## 3. Als Dienst: `moritz-install.sh`

```bash
sudo ./moritz-install.sh          # nach /opt/moritz-agent, Dienst moritz-agent.service, Benutzer moritz-agent
```

- KoboldCpp wird nach `/opt/moritz-agent/koboldcpp` kopiert und dort gebaut. Der Build bleibt bei
  Updates erhalten.
- Die Modelle kommen aus `/home/models`. Was `test-3` schon geladen hat, wird nicht noch einmal
  heruntergeladen.
- Den `--moecpu`-Wert, den `./test-3.sh run` gemessen hat, übernimmt der Installer aus dem entpackten
  Ordner.
- Updates gehen mit `sudo ./moritz-update.sh` aus dem neuen Ordner.

`install.sh` und `update.sh` (LXC auf einem Proxmox-Host anlegen, ADR-028) gibt es weiter, auf Sophie-1
brauchst du sie aber nicht mehr.

## 4. Wenn etwas nicht geht

| Beobachtung | Abhilfe |
| --- | --- |
| `setup`: „keine NVIDIA-GPU sichtbar“ | Abschnitt 1. Für einen Test ohne GPU gibt es `./test-3.sh setup --cpu` (sehr langsam). |
| `setup`: zu wenig Platz | Für Qwen3 werden ≈ 15 GB in `/home/models` gebraucht. Die Ersatzmodelle (≈ 41 GB) werden einfach übersprungen. |
| Status „KoboldCpp ist nicht gebaut“ | `./test-3.sh setup`, oder `./test-3.sh setup --rebuild` für einen frischen Build |
| Anton hört im Sprachkanal nicht zu | `runtime/discord-venv` fehlt: `./test-3.sh setup` (braucht `git`). Im Log steht „nur sprechen“. |
| alles weg und neu | `./test-clearup.sh`. Der Modell-Cache bleibt, `--all` löscht auch ihn. |

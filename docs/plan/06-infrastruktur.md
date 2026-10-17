# 06 – Infrastruktur: Sophie-1, Agent-LXC, Asterisk, Redemption-1

> Konkrete Treiber-Befehle werden **aus den Ist-Werten** (Abschnitt 1) abgeleitet. Nichts
> hier blind ausführen. Der Agent-Installer ändert **nie** etwas am Proxmox-Host (INST-02).

## 1. Inventar

| Wert | Befehl (Host bzw. LXC) | Ist-Wert |
| --- | --- | --- |
| Proxmox-VE-Version | `pveversion -v \| head -3` | _offen_ |
| Host-Kernel | `uname -r` | _offen_ |
| CPU | `lscpu` | **Intel Xeon E5-2673 v3** (Haswell-EP, AVX2/FMA, kein AVX-512), 24 Threads verfügbar (F-07) |
| Davon für moritz-agent | – | **bis zu 18 Threads** (`cores: 18`), Rest für Host (F-07) |
| RAM gesamt | `free -h` | 32 GB |
| Freier SSD-Speicher | `pvesm status` | _offen_ (benötigt ≥ 80 GB, siehe §3) |
| GPU | `lspci -nnk \| grep -A3 -i nvidia` | RTX 3070, 8 GB |
| GPU an VFIO gebunden? | Ausgabe oben: `Kernel driver in use` | **nein** (F-06) |
| NVIDIA-Treiber am Host | `nvidia-smi` | **noch keiner installiert** (F-06) → §4.1 |
| Weitere GPU-Nutzer | – | **keine**, GPU nur für Compute (F-06, R6) |
| LXC-Distribution | `cat /etc/os-release` | **Ubuntu 26.04 LTS** (alternativ 25.10, F-05) |
| Asterisk-Version / Kanaltreiber | `asterisk -rx "core show version"` | _offen_ → [`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md) §1 |

## 2. RAM- und VRAM-Budget

### 2.1 Sophie-1 gesamt (Originalplan §12)

| Bereich | Budget |
| --- | ---: |
| Host + vorhandene Dienste | ≥ 10 GB |
| moritz-agent LXC (Limit, keine Reservierung) | 16 GB |
| Spielraum | 6 GB |
| RTX 3070 (separat) | 8 GB VRAM |

### 2.2 Erwarteter Bedarf im LXC (Schätzung → in P1-02/P1-18 messen)

Modell: Qwen3-30B-A3B-Instruct-2507 UD-Q3_K_XL, 13,8 GB, „halb/halb“ per `--moecpu` (ADR-016).

| Komponente | RAM (Schätzung) | VRAM (Schätzung) | Gemessen |
| --- | ---: | ---: | --- |
| LLM-Gewichte, Experten-Anteil im RAM (`--moecpu ≈ 24`) | ≈ 6,5–7 GB | – | _offen_ |
| LLM-Gewichte auf GPU (Attention, gemeinsame Gewichte, restliche Experten) | – | ≈ 6,0–6,5 GB | _offen_ |
| KV-Cache 4.096 Tokens (48 Schichten, 4 KV-Köpfe, fp16) | – | ≈ 0,4 GB | _offen_ |
| CUDA-Kontext + Compute-Puffer | 0,5–1 GB | 0,4–0,7 GB | _offen_ |
| STT faster-whisper small int8 | 0,6–1,0 GB | – | _offen_ |
| TTS CosyVoice3-Hessisch (Worker, CPU, fp32) | ≈ 4,5–5 GB | – | _offen_ |
| TTS-Rückfall Piper + espeak | 0,15–0,3 GB | – | _offen_ |
| Silero VAD | < 0,05 GB | – | _offen_ |
| PJSIP + Phone-Worker | 0,1–0,2 GB | – | _offen_ |
| SearXNG (granian) | 0,2–0,4 GB | – | _offen_ |
| Main (FastAPI, Agent, SQLite) | 0,15–0,3 GB | – | _offen_ |
| **Summe** | **≈ 13–15,5 GB** | **≈ 6,8–7,6 GB** | _offen_ |

Folgerung (mit CosyVoice, ADR-027): 16 GB RAM-Limit reicht **knapp** – das LXC-Limit auf 18–20 GB zu erhöhen (innerhalb der 6 GB Spielraum) ist die sichere Wahl; ohne CosyVoice (`--no-cosyvoice`, Piper) bleibt es bei ≈ 9–10,5 GB. VRAM ist eng → `--moecpu` so wählen, dass
≥ 0,6 GB frei bleiben. 8.192 Kontext (+ ≈ 0,4 GB VRAM) erst nach Messung (INF-05).
Größere Quantisierung (Q4_K_M, 18,6 GB) bräuchte ein LXC-Limit von ≈ 20 GB – innerhalb der
6 GB Spielraum möglich, aber erst nach Messung.

## 3. Agent-LXC anlegen

| Einstellung | Wert |
| --- | --- |
| Typ | unprivilegiert (`unprivileged: 1`) |
| OS-Template | **Ubuntu 26.04 LTS** (`pveam update && pveam available \| grep ubuntu`) |
| RAM / Swap | `memory: 16384`, `swap: 2048` (Swap nur Notpuffer, kein Modellspeicher) |
| CPU | `cores: 18` (F-07), optional `cpuunits: 512`, damit der Host Vorrang hat |
| Disk | ≥ 80 GB (Modell 13,8 GB, Whisper 0,5 GB, CosyVoice-Modelle 4,4 GB, Conda/CUDA-Build ≈ 10 GB, Repo inkl. third_party ≈ 1 GB, venvs ≈ 3 GB + torch-CPU-Umgebung ≈ 1,5 GB, Backups, Reserve) |
| Netzwerk | Bridge im Server-/Telefonie-Netz, **feste IP**, Asterisk 192.168.1.176 direkt erreichbar (kein NAT) |
| Zeit | LXC erbt Host-Uhr (Host-NTP aktiv), Zeitzone `Europe/Berlin`, Paket `tzdata` |
| Autostart | `onboot: 1`, Startreihenfolge nach Asterisk |

## 4. GPU im LXC

### 4.1 Host: NVIDIA-Treiber installieren (einmalig, manuell; F-06 „noch keiner“)

1. Proxmox-Repository mit Kernel-Headern: `apt install proxmox-default-headers` (bzw.
   `pve-headers-$(uname -r)`), `build-essential`, `dkms`.
2. Nouveau sperren: `/etc/modprobe.d/blacklist-nouveau.conf` mit `blacklist nouveau` und
   `options nouveau modeset=0`, `update-initramfs -u`, Neustart.
3. Aktuellen NVIDIA-Treiber (Production Branch, unterstützt RTX 3070) als `.run`-Datei von
   nvidia.com laden und mit DKMS installieren:
   `sh NVIDIA-Linux-x86_64-<VER>.run --dkms` (Version notieren → `<VER>`).
4. Prüfen: `nvidia-smi` am Host zeigt RTX 3070, 8 GB.
5. Gerätedateien beim Boot erzeugen: `nvidia-persistenced` aktivieren und
   `/etc/modules-load.d/nvidia.conf` mit `nvidia`, `nvidia_uvm`; zusätzlich
   `nvidia-modprobe -u -c=0` (legt `/dev/nvidia-uvm*` an).

### 4.2 LXC-Konfiguration (`/etc/pve/lxc/<ID>.conf`)

Proxmox ≥ 8.1 unterstützt `devN`-Einträge (keine rohen cgroup-Major-Nummern):

```text
dev0: /dev/nvidia0,gid=<GID video im CT>
dev1: /dev/nvidiactl,gid=<…>
dev2: /dev/nvidia-uvm,gid=<…>
dev3: /dev/nvidia-uvm-tools,gid=<…>
dev4: /dev/nvidia-modeset,gid=<…>        # nur falls vorhanden
```

GIDs im Container ablesen (`getent group video render`), nicht raten. Keine pauschalen
`lxc.cgroup2.devices.allow: c *:* rwm`.

### 4.3 Im LXC

1. Userspace-Treiber **exakt Version `<VER>`** ohne Kernelmodul:
   `sh NVIDIA-Linux-x86_64-<VER>.run --no-kernel-module --silent`.
2. `nvidia-smi` im LXC prüfen. Kein CUDA-Toolkit nötig (ADR-015).
3. Nach jedem Host-Kernel-/Treiberupdate 4.1 (DKMS baut automatisch) und 4.3 wiederholen;
   Updater/Statusseite warnen bei Versionsabweichung (R5).

## 5. Firewall (LXC, nftables)

```text
eingehend:
  udp 5060           von 192.168.1.176            (SIP)
  udp 40000-40199    von 192.168.1.176            (RTP/RTCP, direct_media=no)
  tcp 3501           von LAN                      (Web-UI HTTPS, F-04)
  tcp 22             von <Admin-Netz>             (Verwaltung)
  sonst: drop
ausgehend:
  udp/tcp 53, tcp 80/443 (Suche, Modelldownload), udp 123 (NTP),
  udp 5060 + RTP zu 192.168.1.176, tcp 22 zur Sandbox-VM (Part 4)
```

## 6. Asterisk

Vollständige Konfiguration (Endpoint `agent`, Dialplan 999, Codecs, ACL, Prüfung, Fehlerbilder):
**[`docs/asterisk-konfiguration.md`](../asterisk-konfiguration.md)**.

Das schwache Startpasswort `agent/agent` bleibt (F-02: Repo öffentlich, aber die Anlage ist
nur intern erreichbar). Abgesichert durch ACL auf die Agent-IP und einen Kontext ohne Wählrechte.

## 7. Redemption-1: Sandbox-VM (ab Part 4)

| Einstellung | Wert |
| --- | --- |
| VM (kein LXC – stärkere Isolation für fremden Code) | Ubuntu 26.04 |
| RAM / vCPU | 4 GB / 2–4 |
| Disk | 40 GB, Snapshots (Basis-Snapshot `clean`) |
| Benutzer | `agent`, Zugang nur per SSH-Key aus dem Agent-LXC, Host-Key in `passwords.txt` gepinnt |
| Netzwerk (F-10, festgelegt) | **nur** Internet und Sophie-1 (Agent-LXC); alles andere gesperrt (Proxmox-Management, OPNsense, NAS, andere Server, interne Netze) |
| Chromium | Part 6, on demand, max. 2 Seiten |

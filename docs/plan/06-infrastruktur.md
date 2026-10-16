# 06 – Infrastruktur: Sophie-1, Agent-LXC, Asterisk, Redemption-1

> Konkrete Befehle für Treiber und Gerätedurchreichung werden **erst aus den Ist-Werten**
> (Abschnitt 1) abgeleitet. Nichts hier ist blind auszuführen. Der Agent-Installer ändert
> **nie** etwas am Proxmox-Host (INST-02).

## 1. Inventar (vor jeder Einrichtung ausfüllen)

| Wert | Befehl (Host bzw. LXC) | Ist-Wert |
| --- | --- | --- |
| Proxmox-VE-Version | `pveversion -v \| head -3` | _offen_ |
| Host-Kernel | `uname -r` | _offen_ |
| CPU-Modell / Kerne / Threads | `lscpu` | _offen_ |
| RAM gesamt / frei / belegt durch Gäste | `free -h`, `pvesh get /nodes/$(hostname)/status` | 32 GB / _offen_ |
| Freier SSD-Speicher (Ziel-Storage) | `pvesm status` | _offen_ |
| GPU sichtbar am Host | `lspci -nnk \| grep -A3 -i nvidia` | RTX 3070 / _offen_ |
| GPU an VFIO gebunden? | Ausgabe oben: `Kernel driver in use` | _muss `nvidia` sein, nicht `vfio-pci`_ |
| NVIDIA-Treiberversion Host | `nvidia-smi` | _offen_ |
| Weitere GPU-Nutzer (andere LXCs) | `grep -l nvidia /etc/pve/lxc/*.conf` | _offen_ |
| Freier VRAM im Leerlauf | `nvidia-smi --query-gpu=memory.used,memory.total --format=csv` | _offen_ |
| LXC-Distribution | `cat /etc/os-release` | _offen (Empfehlung Debian 12/13)_ |
| Asterisk-Version / Kanaltreiber | `asterisk -rx "core show version"`, `module show like pjsip` | _offen_ |

## 2. RAM- und VRAM-Budget

### 2.1 Sophie-1 gesamt (Vorgabe Originalplan §12)

| Bereich | Budget |
| --- | ---: |
| Host + vorhandene Dienste | ≥ 10 GB |
| moritz-agent LXC (Limit, keine Reservierung) | 16 GB |
| Spielraum | 6 GB |
| RTX 3070 (separat) | 8 GB VRAM |

### 2.2 Erwarteter Bedarf im LXC (Schätzung → in P1-18 messen)

| Komponente | RAM (Schätzung) | VRAM (Schätzung) | Gemessen |
| --- | ---: | ---: | --- |
| KoboldCPP-Prozess inkl. CUDA-Kontext, Host-Puffer | 1,5–3 GB | – | _offen_ |
| 8B-Modell Q4_K_M, volles Offload | (mmap/Page-Cache, verdrängbar) | 4,7–5,2 GB | _offen_ |
| KV-Cache 4.096 Tokens (fp16, GQA 8B) | – | ≈ 0,6 GB | _offen_ |
| Compute-Puffer + CUDA-Kontext | – | 0,5–0,9 GB | _offen_ |
| STT faster-whisper `small` int8 | 0,6–1,0 GB | – | _offen_ |
| TTS Piper (eine Stimme) + onnxruntime | 0,15–0,3 GB | – | _offen_ |
| Silero VAD | < 0,05 GB | – | _offen_ |
| PJSIP + Phone-Worker (Python) | 0,1–0,2 GB | – | _offen_ |
| SearXNG (granian, 1–2 Worker) | 0,2–0,4 GB | – | _offen_ |
| Main (FastAPI, Agent, SQLite) | 0,15–0,3 GB | – | _offen_ |
| **Summe** | **≈ 3–5,5 GB** | **≈ 5,8–6,7 GB** | _offen_ |

Folgerung: RAM-Limit 16 GB ist großzügig (Page-Cache der Modelldatei nutzt den Rest
sinnvoll); VRAM ist der Engpass → 8.192 Kontext (+ ≈ 0,6 GB) nur nach Messung, und nur
wenn kein anderer Gast die GPU belegt.

## 3. Agent-LXC anlegen (Empfehlung)

| Einstellung | Wert |
| --- | --- |
| Typ | unprivilegiert (`unprivileged: 1`) |
| OS-Template | Debian 12 oder 13 (Python ≥ 3.11) |
| RAM / Swap | `memory: 16384`, `swap: 2048` (Swap nur Notpuffer, kein Modellspeicher) |
| CPU | `cores:` = physische Kerne − 2 (Rest für Host); STT profitiert direkt |
| Disk | ≥ 60 GB (Modelle ≈ 6 GB, Conda/CUDA-Build ≈ 10 GB, SearXNG/venvs ≈ 3 GB, Reserve) |
| Netzwerk | Bridge im Telefonie-/Server-Netz, **feste IP**, Asterisk 192.168.1.176 direkt erreichbar (keine NAT dazwischen) |
| Features | `nesting=0` (nicht nötig) |
| Zeit | Host-NTP aktiv (LXC erbt Host-Uhr), Zeitzone LXC `Europe/Berlin`, Paket `tzdata` |
| Autostart | `onboot: 1`, Startreihenfolge nach Asterisk |

## 4. GPU im LXC (Gerätezugriff, kein PCIe-Passthrough)

1. **Host:** NVIDIA-Treiber installieren (Version notieren), `nvidia-smi` prüfen,
   Persistenzmodus `nvidia-persistenced` aktivieren, damit `/dev/nvidia*` beim Boot existieren
   (inkl. `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools` – ggf. `nvidia-modprobe -u -c=0`).
2. **LXC-Konfiguration** (Proxmox ≥ 8.1: `devN`-Einträge statt roher cgroup-Major-Nummern):
   ```text
   dev0: /dev/nvidia0,gid=<render/video-GID im CT>
   dev1: /dev/nvidiactl,gid=<…>
   dev2: /dev/nvidia-uvm,gid=<…>
   dev3: /dev/nvidia-uvm-tools,gid=<…>
   dev4: /dev/nvidia-modeset,gid=<…>     # nur falls vorhanden/nötig
   ```
   GIDs aus dem Container ableiten (`getent group video render`), nicht raten. Keine
   pauschalen `lxc.cgroup2.devices.allow: c *:* rwm`.
3. **LXC:** Userspace-Treiber **exakt derselben Version** wie am Host installieren, ohne
   Kernelmodul (`./NVIDIA-Linux-x86_64-<ver>.run --no-kernel-module` oder die passende
   Distributions-Paketvariante). Kein CUDA-Toolkit nötig (ADR-015).
4. Prüfen: `nvidia-smi` im LXC; danach echter Modelllauf (P1-02).
5. **Nach jedem Host-Kernel-/Treiberupdate:** Schritt 3–4 wiederholen. Der Updater prüft
   die Versionsgleichheit (`nvidia-smi` Treiber vs. Userspace-Lib) und warnt.

## 5. Firewall (LXC, nftables)

```text
eingehend:
  udp 5060           von 192.168.1.176            (SIP)
  udp 40000-40199    von 192.168.1.176            (RTP/RTCP, bei direct_media=no)
  tcp 5001           von <Admin-Netz>             (Web-UI, nur wenn server.host ≠ 127.0.0.1)
  tcp 22             von <Admin-Netz>             (Verwaltung)
  sonst: drop
ausgehend:
  udp/tcp 53, tcp 80/443 (Suche, Modelldownload, Updates), udp 123 (NTP),
  udp 5060 + RTP zu 192.168.1.176, tcp 22 zu Redemption-1-Sandbox (Part 4)
```

Die Firewall gehört zur Infrastruktur (manuell bzw. Proxmox-Firewall), nicht zum Installer;
der Installer prüft nur, ob die Ports lokal frei sind.

## 6. Asterisk-Checkliste (nur prüfen, nicht ändern)

| Prüfpunkt | Erwartung | Ist |
| --- | --- | --- |
| Endpoint/Peer `agent` existiert | chan_pjsip: `endpoint`, `auth` (agent/agent), `aor` mit `max_contacts=1` | _offen_ |
| Codecs am Endpoint | `allow=!all,g722,alaw,ulaw` (G.722 bevorzugt für bessere STT) | _offen_ |
| Medienpfad | `direct_media=no` (RTP nur von Asterisk → einfache Firewall) | _offen_ |
| DTMF | `dtmf_mode=rfc4733` (für Part 7) | _offen_ |
| Dialplan 999 | z. B. `exten => 999,1,Dial(PJSIP/agent,30)` + `same => n,Hangup()` | _offen_ |
| Erreichbarkeit | `pjsip show contacts` zeigt `agent` nach Registrierung als `Avail` | _offen_ |
| Qualify | `qualify_frequency=30` (Asterisk erkennt toten Agent) | _offen_ |
| Sicherheit | Agent-Konto darf nur interne Ziele, **keine** externen Trunks wählen (Context ohne Trunk-Zugang) | _offen_ |

**Hinweis Zugangsdaten:** `agent/agent` ist trivial erratbar. Da nur im internen Netz
erreichbar, akzeptiert der Plan es als Startwert; empfohlen wird ein starkes Passwort in
Asterisk **und** `passwords.txt` (Änderung = Originalplan §41 Punkt 9). Der Installer gibt
eine Warnung aus, solange `password = agent` gesetzt ist.

## 7. Redemption-1: Sandbox-VM (ab Part 4, vorbereiten ab Part 1)

| Einstellung | Startwert |
| --- | --- |
| VM (kein LXC – stärkere Isolation für fremden Code) | Debian 12/13 |
| RAM / vCPU | 4 GB / 2–4 (nur wenn Redemption-1 frei genug ist) |
| Disk | 40 GB, Snapshots aktiviert (Basis-Snapshot `clean`) |
| Benutzer | `agent` ohne sudo; Software-Installation über dedizierte, eingeschränkte sudo-Regel oder Rootless-Tools (Entscheidung Part 4) |
| Zugang | nur SSH-Key von Agent-LXC, Host-Key-Fingerprint in `passwords.txt` gepinnt |
| Netzwerk | eigenes VLAN/Segment; OPNsense-Regeln: Internet erlaubt; Agent-LXC:5001 erlaubt; **gesperrt:** Proxmox-Management, OPNsense-UI, NAS, andere Server, interne Netze |
| Chromium | erst Part 6, on demand, max. 2 Seiten |

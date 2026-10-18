#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# install.sh – set up moritz-agent in its own LXC container on the Proxmox host (ADR-028).
#
# Run on the Proxmox host as root, or from any other machine with --remote:
#     sudo ./install.sh                         # on the Proxmox host
#     ./install.sh --remote root@proxmox        # from Sophie-1's console / a workstation (scp + ssh)
#
# Creates the container (Ubuntu template, unprivileged, resources from the plan), copies the
# program into it and runs moritz-install.sh there. If the container already exists, the same
# call updates it instead (and an unfinished installation is continued) – nothing is lost.
set -Eeuo pipefail
umask 022

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT
LOG_PREFIX="install"
# shellcheck source=deploy/lib/common.sh
source "${ROOT}/deploy/lib/common.sh"
# shellcheck source=deploy/lib/host.sh
source "${ROOT}/deploy/lib/host.sh"

host_usage() {
	cat <<'USAGE'
Usage: install.sh [options]        (als root auf dem Proxmox-Host; sonst mit --remote)

Container
  --ctid ID              Container-ID (Standard: nächste freie; vorhandene wird weiterverwendet)
  --hostname NAME        Hostname/Name (Standard: moritz-agent; so wird der Container wiedergefunden)
  --storage NAME         Speicher für die Root-Platte (Standard: local-lvm, sonst erster aktive)
  --template-storage N   Speicher für die Ubuntu-Vorlage (Standard: local)
  --os-template NAME     Vorlage (Standard: Ubuntu 26.04, sonst 25.10, sonst 24.04)
  --disk GB              Plattengröße (Standard: 80)
  --memory MB            RAM-Limit (Standard: 16384)        --swap MB   Swap (Standard: 2048)
  --cores N              CPU-Kerne (Standard: 18, höchstens die des Hosts)
  --cpuunits N           CPU-Gewicht (Standard: 512, damit der Host Vorrang hat)
  --bridge NAME          Netzwerk-Bridge (Standard: vmbr0)  --vlan TAG
  --ip dhcp|IP/MASKE     Adresse (Standard: dhcp; für Asterisk besser fest)  --gateway IP
  --dns IP               Nameserver     --search-domain NAME
  --gpu auto|yes|no      NVIDIA-Geräte durchreichen (Standard: auto = nur wenn der Host eine hat)
  --ssh-key DATEI        öffentlicher SSH-Schlüssel für root im Container
  --timezone ZONE        Zeitzone (Standard: Europe/Berlin)
  --no-start             Container nur anlegen, nicht installieren

Installation im Container
  --skip-models          Modell-Download überspringen     --jobs N   Build-Prozesse

Ablauf
  --yes, -y              ohne Rückfrage
  --dry-run              nur anzeigen, was getan würde
  --remote [USER@]HOST   von einem anderen Rechner: Programm per scp auf den Proxmox-Host kopieren
                         und dort ausführen (--ssh-port N, --identity DATEI)
  -h, --help             diese Hilfe
USAGE
}

print_plan() {
	cat <<PLAN

Geplant:
  Container      ${CTID} (${CT_HOSTNAME}), unprivilegiert, nesting, onboot
  Vorlage        ${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}
  Root-Platte    ${ROOTFS_STORAGE}, ${DISK_GB} GB
  Ressourcen     ${CORES} Kerne (cpuunits ${CPUUNITS}), ${MEMORY_MB} MB RAM, ${SWAP_MB} MB Swap
  Netzwerk       ${BRIDGE}${VLAN:+ (VLAN ${VLAN})}, ${IP_CONFIG}${GATEWAY:+ via ${GATEWAY}}
  GPU            ${GPU}
  Programm       moritz-agent $(version_of "${ROOT}") → ${PREFIX_IN_CT}
Am Proxmox-Host wird sonst nichts verändert.
PLAN
}

main() {
	parse_host_args "$@"
	if [[ -n "${REMOTE}" ]]; then
		remote_run install.sh "${FORWARD_ARGS[@]}"
		exit $?
	fi
	require_proxmox
	find_ct

	if [[ ${CT_EXISTS} -eq 1 ]]; then
		if ! ct_is_ours; then
			confirm_or_die "Container ${CTID} wurde nicht von moritz-agent angelegt. Trotzdem darin installieren?"
		fi
		log "Container ${CTID} gibt es schon"
		ensure_running
		if ct_has_installation; then
			log "moritz-agent ist dort installiert – aktualisiere (wie update.sh)"
			do_update_in_container
		else
			log "moritz-agent ist dort noch nicht (vollständig) installiert – setze die Installation fort"
			do_install_in_container
		fi
		print_summary
		return 0
	fi

	if [[ -z "${ROOTFS_STORAGE}" ]]; then ROOTFS_STORAGE="$(find_storage rootdir local-lvm)"; fi
	[[ -n "${ROOTFS_STORAGE}" ]] || die 64 "kein aktiver Speicher für Container-Platten gefunden (pvesm status --content rootdir) – --storage angeben"
	if [[ -z "${TEMPLATE_STORAGE}" ]]; then TEMPLATE_STORAGE="$(find_storage vztmpl local)"; fi
	[[ -n "${TEMPLATE_STORAGE}" ]] || die 64 "kein Speicher für Vorlagen gefunden (pvesm status --content vztmpl) – --template-storage angeben"
	host_run pveam update >/dev/null 2>&1 || warn "pveam update fehlgeschlagen – verwende die vorhandene Vorlagenliste"
	choose_template
	if [[ -z "${CTID}" ]]; then CTID="$(next_ctid)"; fi
	print_plan
	confirm_or_die "Container ${CTID} so anlegen und moritz-agent installieren?"

	ensure_template
	create_container
	if [[ ${START_AFTER} -eq 0 ]]; then
		log "Container ${CTID} angelegt (nicht gestartet). Installation später: ./install.sh --ctid ${CTID}"
		return 0
	fi
	host_run pct start "${CTID}"
	wait_for_network
	configure_gpu
	do_install_in_container
	print_summary
}

main "$@"

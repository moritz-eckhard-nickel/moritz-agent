#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# update.sh – update moritz-agent in its LXC container from the Proxmox host (ADR-028).
#
#     sudo ./update.sh                          # on the Proxmox host
#     ./update.sh --remote root@proxmox         # from Sophie-1's console / a workstation (scp + ssh)
#
# Takes a snapshot of the container, copies THIS program version into it and runs moritz-update.sh
# there: a running call is finished first (otherwise the update is postponed, exit 75), a failed
# update is rolled back (exit 70). passwords.txt, configuration, models and caches are kept.
set -Eeuo pipefail
umask 022

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT
LOG_PREFIX="update"
# shellcheck source=deploy/lib/common.sh
source "${ROOT}/deploy/lib/common.sh"
# shellcheck source=deploy/lib/host.sh
source "${ROOT}/deploy/lib/host.sh"

host_usage() {
	cat <<'USAGE'
Usage: update.sh [options]         (als root auf dem Proxmox-Host; sonst mit --remote)

  --ctid ID              Container-ID (Standard: der Container namens moritz-agent)
  --hostname NAME        anderer Name statt moritz-agent
  --drain-timeout SEK    so lange auf ein laufendes Gespräch warten (Standard: 600), sonst verschieben (Exit 75)
  --keep-backups N       Sicherungen im Container behalten (Standard: 5)
  --skip-models          Modell-Download überspringen     --jobs N   Build-Prozesse
  --no-snapshot          keinen Proxmox-Snapshot vorher anlegen
  --require-snapshot     abbrechen, wenn der Snapshot nicht möglich ist
  --keep-snapshots N     so viele moritz-pre-update-Snapshots behalten (Standard: 3)
  --yes, -y              ohne Rückfrage
  --dry-run              nur anzeigen, was getan würde
  --remote [USER@]HOST   von einem anderen Rechner: Programm per scp auf den Proxmox-Host kopieren
                         und dort ausführen (--ssh-port N, --identity DATEI)
  -h, --help             diese Hilfe

Exit-Codes: 0 ok · 64 Voraussetzung fehlt · 70 Update fehlgeschlagen, zurückgerollt · 71 auch Rollback
fehlgeschlagen · 75 verschoben (Gespräch läuft)
USAGE
}

main() {
	parse_host_args "$@"
	if [[ -n "${REMOTE}" ]]; then
		remote_run update.sh "${FORWARD_ARGS[@]}"
		exit $?
	fi
	require_proxmox
	find_ct
	[[ ${CT_EXISTS} -eq 1 ]] ||
		die 64 "kein Container '${CT_HOSTNAME}' gefunden${CTID:+ (ID ${CTID})} – zuerst ./install.sh ausführen"
	if [[ ${CREATION_OPTIONS_SET} -eq 1 ]]; then
		warn "Optionen zur Container-Erstellung (Ressourcen, Netzwerk, GPU …) wirken nur bei install.sh und werden hier ignoriert"
	fi
	if ! ct_is_ours; then
		confirm_or_die "Container ${CTID} wurde nicht von moritz-agent angelegt. Trotzdem aktualisieren?"
	fi
	ensure_running
	ct_has_installation || die 64 "in Container ${CTID} ist moritz-agent nicht installiert – ./install.sh --ctid ${CTID}"
	local rc=0
	do_update_in_container || rc=$?
	if [[ ${rc} -eq 0 ]]; then print_summary; fi
	return "${rc}"
}

main "$@"

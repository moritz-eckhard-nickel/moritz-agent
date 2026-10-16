#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# moritz-update.sh – updater for moritz-agent (ticket P1-16).
#
# Specification: docs/plan/07-installation-update.md §3 (drain, backup, apply, migrate,
# verify, rollback) and §4 (exit codes).
# Status: skeleton. Phases are declared but not implemented yet; use --dry-run to list them.
#
# Never interrupts an active call: if calls are still running after --drain-timeout,
# the update is postponed (exit code 75). Never overwrites customised passwords.txt values.
set -Eeuo pipefail
umask 077

readonly EXIT_OK=0 EXIT_USAGE=2 EXIT_NOT_IMPLEMENTED=1
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR

NON_INTERACTIVE=0
DRY_RUN=0
CHANNEL="stable"
DRAIN_TIMEOUT=600

PHASES=(
	"preflight:Kurzprüfung und Update-Lock"
	"drain:Keine neuen Anrufe; auf Gesprächsende warten (sonst verschieben, Exit 75)"
	"backup:passwords.txt, Konfiguration, Zustände und Datenbank sichern"
	"fetch:Neue Version holen (Tag bzw. origin/agent)"
	"stop:Dienst stoppen"
	"apply:Checkout, neues venv, Komponenten bei Bedarf neu bauen"
	"migrate:Fehlende Felder ergänzen, DB-Migrationen, Modelle, Ansagen"
	"switch:venv umschalten (altes als venv.prev)"
	"start_verify:Dienst starten, Komponenten prüfen"
	"report:Ergebnis melden (bei Fehler: Rollback, Exit 70/71)"
)

usage() {
	cat <<USAGE
Usage: $(basename "$0") [options]

  --channel stable|dev      stable = neuester v*-Tag, dev = origin/agent (Default: ${CHANNEL})
  --drain-timeout SECONDS   max. Wartezeit auf aktive Anrufe (Default: ${DRAIN_TIMEOUT})
  --non-interactive         keine Rückfragen; fehlende Pflichtangaben → Exit-Code 78
  --dry-run                 nur anzeigen, was getan würde
  -h, --help                diese Hilfe
USAGE
}

log() { printf '[moritz-update] %s\n' "$*"; }
die() {
	local code="$1"
	shift
	printf '[moritz-update] FEHLER: %s\n' "$*" >&2
	exit "${code}"
}

parse_args() {
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--channel)
			[[ $# -ge 2 && ( "$2" == "stable" || "$2" == "dev" ) ]] || die "${EXIT_USAGE}" "--channel braucht stable oder dev"
			CHANNEL="$2"
			shift 2
			;;
		--drain-timeout)
			[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "${EXIT_USAGE}" "--drain-timeout braucht Sekunden"
			DRAIN_TIMEOUT="$2"
			shift 2
			;;
		--non-interactive) NON_INTERACTIVE=1; shift ;;
		--dry-run) DRY_RUN=1; shift ;;
		-h | --help) usage; exit "${EXIT_OK}" ;;
		*) usage >&2; die "${EXIT_USAGE}" "unbekannte Option: $1" ;;
		esac
	done
}

run_phase() {
	local name="$1" description="$2"
	if [[ "${DRY_RUN}" -eq 1 ]]; then
		log "[dry-run] ${name}: ${description}"
		return 0
	fi
	die "${EXIT_NOT_IMPLEMENTED}" "Phase '${name}' ist noch nicht implementiert (Ticket P1-16)."
}

main() {
	parse_args "$@"
	log "moritz-agent Update – ${APP_DIR}, Kanal ${CHANNEL}, Drain-Timeout ${DRAIN_TIMEOUT}s, non-interactive=${NON_INTERACTIVE}"
	local entry
	for entry in "${PHASES[@]}"; do
		run_phase "${entry%%:*}" "${entry#*:}"
	done
	log "Fertig."
}

main "$@"

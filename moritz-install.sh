#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# moritz-install.sh – installer for moritz-agent (ticket P1-15).
#
# Specification: docs/plan/07-installation-update.md §2 (phases, prompts, exit codes).
# Status: skeleton. Phases are declared but not implemented yet; use --dry-run to list them.
#
# Rules (docs/plan/08-sicherheit.md): never `set -x`, never pass secrets as arguments or
# environment variables (only via stdin to `python -m moritz_agent.setup`), never overwrite
# an existing passwords.txt, never modify the Proxmox host or the Asterisk configuration.
set -Eeuo pipefail
umask 077

readonly EXIT_OK=0 EXIT_USAGE=2 EXIT_NOT_IMPLEMENTED=1
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR

PREFIX="/opt/moritz-agent"
NON_INTERACTIVE=0
DRY_RUN=0
SKIP_MODELS=0
SKIP_KOBOLDCPP_BUILD=0

PHASES=(
	"preflight:Distribution, Python, RAM-Limit, CPU, Speicher, GPU, Ports prüfen"
	"packages:Systempakete installieren (ohne System-Upgrade)"
	"user_dirs:Dienstbenutzer und Verzeichnisse anlegen"
	"python_env:venv und gepinnte Python-Abhängigkeiten"
	"pjsip:pjproject + PJSUA2-Binding bauen (ADR-005)"
	"koboldcpp:KoboldCpp mit CUDA bauen (ADR-015)"
	"searxng:SearXNG-Checkout, venv, secret_key (ADR-007)"
	"models:LLM, STT, TTS-Stimme, VAD laden und SHA-256 prüfen"
	"secrets:passwords.txt anlegen/ergänzen, Web-Login, Sandbox-SSH abfragen"
	"config:config/moritz-agent.toml anlegen"
	"prompts:Ansagen-Cache erzeugen (P1-13)"
	"service:systemd-Dienst installieren und starten"
	"verify:Komponentenstatus einzeln melden"
	"testcall:Testanruf an 999 anleiten und Ergebnis abfragen"
)

usage() {
	cat <<USAGE
Usage: $(basename "$0") [options]

  --prefix DIR              Installationsverzeichnis (Default: ${PREFIX})
  --non-interactive         keine Rückfragen; fehlende Pflichtangaben → Exit-Code 78
  --dry-run                 nur anzeigen, was getan würde
  --skip-models             Modell-Downloads überspringen
  --skip-koboldcpp-build    KoboldCpp-Build überspringen
  -h, --help                diese Hilfe
USAGE
}

log() { printf '[moritz-install] %s\n' "$*"; }
die() {
	local code="$1"
	shift
	printf '[moritz-install] FEHLER: %s\n' "$*" >&2
	exit "${code}"
}

parse_args() {
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--prefix)
			[[ $# -ge 2 ]] || die "${EXIT_USAGE}" "--prefix braucht ein Verzeichnis"
			PREFIX="$2"
			shift 2
			;;
		--non-interactive) NON_INTERACTIVE=1; shift ;;
		--dry-run) DRY_RUN=1; shift ;;
		--skip-models) SKIP_MODELS=1; shift ;;
		--skip-koboldcpp-build) SKIP_KOBOLDCPP_BUILD=1; shift ;;
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
	die "${EXIT_NOT_IMPLEMENTED}" "Phase '${name}' ist noch nicht implementiert (Ticket P1-15)."
}

main() {
	parse_args "$@"
	log "moritz-agent Installer – Quelle ${APP_DIR}, Ziel ${PREFIX}"
	log "Optionen: non-interactive=${NON_INTERACTIVE} skip-models=${SKIP_MODELS} skip-koboldcpp-build=${SKIP_KOBOLDCPP_BUILD}"
	local entry
	for entry in "${PHASES[@]}"; do
		run_phase "${entry%%:*}" "${entry#*:}"
	done
	log "Fertig."
}

main "$@"

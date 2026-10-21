#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# moritz-update.sh – updater inside the LXC, ticket P1-16.
#
# Normally started by ./update.sh on the Proxmox host (ADR-028): the host copies the new program
# version into a staging directory in the LXC and runs the updater FROM THERE, so a newer updater
# always updates an older installation. The installation directory (--prefix) is the target.
#
# Specification: docs/plan/07-installation-update.md §3. Flow:
#   preflight → drain (let a running call finish; otherwise postpone, exit 75) → backup →
#   build a new virtual environment if the packages changed (service still running) → stop →
#   apply (program files, venv switch, models, configuration, announcements) → start + verify →
#   report. A failure after "stop" rolls everything back (exit 70; 71 if the rollback failed).
#
# Never touched: passwords.txt, config/moritz-agent.toml, models, data, announcement cache.
set -Eeuo pipefail
umask 022

readonly EXIT_OK=0 EXIT_USAGE=2 EXIT_PREFLIGHT=64 EXIT_ROLLED_BACK=70 EXIT_ROLLBACK_FAILED=71 EXIT_POSTPONED=75
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR
LOG_PREFIX="moritz-update"
# shellcheck source=deploy/lib/common.sh
source "${APP_DIR}/deploy/lib/common.sh"

PREFIX="/opt/moritz-agent"
SERVICE_USER="moritz-agent"
DRY_RUN=0
SKIP_MODELS=0
SKIP_ENV=0
NO_SERVICE=0
DRAIN_TIMEOUT=600
KEEP_BACKUPS=5
JOBS="${MORITZ_JOBS:-$(nproc 2>/dev/null || echo 2)}"
START_TIMEOUT="${MORITZ_START_TIMEOUT:-180}"
LOG_DIR="${MORITZ_LOG_DIR:-/var/log/moritz-agent}"

BACKUP_DIR=""
NEW_VENV=0
DRAINING=0
SERVICE_WAS_ACTIVE=0
OLD_VERSION="unbekannt"
NEW_VERSION="unbekannt"
STARTED=$SECONDS

usage() {
	cat <<USAGE
Usage: $(basename "$0") [options]

  --prefix DIR          Installationsverzeichnis (Standard: ${PREFIX})
  --user NAME           Dienstbenutzer (Standard: ${SERVICE_USER})
  --drain-timeout SEC   so lange auf ein laufendes Gespräch warten (Standard: ${DRAIN_TIMEOUT}); danach wird
                        das Update verschoben (Exit-Code 75)
  --keep-backups N      so viele Sicherungen behalten (Standard: ${KEEP_BACKUPS})
  --skip-models         Modell-Download überspringen
  --skip-env            Python-Umgebung nicht neu aufbauen/prüfen (Test)
  --no-service          keinen systemd-Dienst anfassen
  --non-interactive     keine Rückfragen
  --dry-run             nur anzeigen, was getan würde
  --jobs N              parallele Build-Prozesse (Standard: Anzahl CPUs)
  -h, --help            diese Hilfe

Exit-Codes: 0 ok · 2 Benutzung · 64 Voraussetzung nicht erfüllt · 70 fehlgeschlagen, Rollback
durchgeführt · 71 fehlgeschlagen und Rollback fehlgeschlagen · 75 verschoben (Anruf aktiv)
USAGE
}

parse_args() {
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--prefix)
			[[ $# -ge 2 ]] || die "${EXIT_USAGE}" "--prefix braucht ein Verzeichnis"
			PREFIX="$2"
			shift 2
			;;
		--user)
			[[ $# -ge 2 ]] || die "${EXIT_USAGE}" "--user braucht einen Namen"
			SERVICE_USER="$2"
			shift 2
			;;
		--drain-timeout)
			[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "${EXIT_USAGE}" "--drain-timeout braucht Sekunden"
			DRAIN_TIMEOUT="$2"
			shift 2
			;;
		--keep-backups)
			# at least 1: the backup of this very update is what a rollback needs
			[[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] || die "${EXIT_USAGE}" "--keep-backups braucht eine Zahl ab 1"
			KEEP_BACKUPS="$2"
			shift 2
			;;
		--jobs)
			[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "${EXIT_USAGE}" "--jobs braucht eine Zahl"
			JOBS="$2"
			shift 2
			;;
		--skip-models) SKIP_MODELS=1; shift ;;
		--skip-env) SKIP_ENV=1; shift ;;
		--no-service) NO_SERVICE=1; shift ;;
		--non-interactive | -y) shift ;; # the updater never asks anyway
		--dry-run) DRY_RUN=1; shift ;;
		-h | --help) usage; exit "${EXIT_OK}" ;;
		*) usage >&2; die "${EXIT_USAGE}" "unbekannte Option: $1" ;;
		esac
	done
	[[ "${PREFIX}" == /* ]] || die "${EXIT_USAGE}" "--prefix muss ein absoluter Pfad sein"
}

run() {
	if [[ ${DRY_RUN} -eq 1 ]]; then
		log "[dry-run] $*"
		return 0
	fi
	"$@"
}

service_active() {
	[[ ${NO_SERVICE} -eq 0 ]] && command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet moritz-agent.service
}

installer() { # installer SOURCE-DIR PHASES – run selected phases of the (new) installer
	local args=(--prefix "${PREFIX}" --user "${SERVICE_USER}" --non-interactive --skip-packages
		--jobs "${JOBS}" --phases "$2")
	if [[ ${SKIP_MODELS} -eq 1 ]]; then args+=(--skip-models); fi
	if [[ ${SKIP_ENV} -eq 1 ]]; then args+=(--skip-env); fi
	if [[ ${NO_SERVICE} -eq 1 ]]; then args+=(--no-service); fi
	run "$1/moritz-install.sh" "${args[@]}"
}

# -- phases ------------------------------------------------------------------------------------------
phase_preflight() {
	if [[ ${DRY_RUN} -eq 0 ]] && ! is_root; then
		die "${EXIT_PREFLIGHT}" "bitte als root ausführen"
	fi
	[[ "${APP_DIR}" != "${PREFIX}" ]] ||
		die "${EXIT_PREFLIGHT}" "Quelle und Ziel sind dasselbe Verzeichnis – update.sh vom Proxmox-Host kopiert den neuen Stand in ein Staging-Verzeichnis und startet den Updater von dort"
	[[ -d "${PREFIX}/data" && -f "${PREFIX}/config/moritz-agent.example.toml" ]] ||
		die "${EXIT_PREFLIGHT}" "keine Installation in ${PREFIX} gefunden – zuerst install.sh ausführen"
	if [[ ${SKIP_ENV} -eq 0 && ! -x "${PREFIX}/runtime/venv/bin/python" ]]; then
		die "${EXIT_PREFLIGHT}" "keine Python-Umgebung in ${PREFIX}/runtime/venv – install.sh ausführen"
	fi
	if [[ ${DRY_RUN} -eq 0 ]]; then
		mkdir -p "${PREFIX}/data/run"
		exec 9>"${PREFIX}/data/run/update.lock"
		flock -n 9 || die "${EXIT_PREFLIGHT}" "es läuft schon ein Update"
	fi
	OLD_VERSION="$(version_of "${PREFIX}")"
	NEW_VERSION="$(version_of "${APP_DIR}")"
	log "Version ${OLD_VERSION} → ${NEW_VERSION}"
	if service_active; then SERVICE_WAS_ACTIVE=1; fi
}

phase_drain() {
	if [[ ${SERVICE_WAS_ACTIVE} -eq 0 ]]; then
		log "Dienst läuft nicht – kein Gespräch abzuwarten"
		return 0
	fi
	log "Wartungsmodus: neue Anrufe bekommen das Besetztzeichen; warte auf laufende Gespräche (höchstens ${DRAIN_TIMEOUT} s)"
	if [[ ${DRY_RUN} -eq 1 ]]; then return 0; fi
	DRAINING=1
	if ! drain_wait "${PREFIX}" "${DRAIN_TIMEOUT}"; then
		drain_stop "${PREFIX}"
		DRAINING=0
		warn "es läuft noch ein Gespräch – Update verschoben, nichts wurde verändert"
		exit "${EXIT_POSTPONED}"
	fi
}

phase_backup() {
	BACKUP_DIR="${PREFIX}/backups/$(date +%Y%m%d-%H%M%S)"
	log "sichere nach ${BACKUP_DIR}"
	if [[ ${DRY_RUN} -eq 1 ]]; then return 0; fi
	install -d -m 0700 "${BACKUP_DIR}"
	local file
	for file in passwords.txt config/moritz-agent.toml; do
		if [[ -f "${PREFIX}/${file}" ]]; then
			install -d -m 0700 "${BACKUP_DIR}/$(dirname "${file}")"
			cp -p "${PREFIX}/${file}" "${BACKUP_DIR}/${file}"
		fi
	done
	if [[ -d "${PREFIX}/data/state" ]]; then cp -a "${PREFIX}/data/state" "${BACKUP_DIR}/state"; fi
	if [[ -s "${PREFIX}/data/state/payload-manifest.txt" ]]; then
		tar --create --gzip --file "${BACKUP_DIR}/code.tgz" --directory "${PREFIX}" \
			--files-from "${PREFIX}/data/state/payload-manifest.txt"
	else
		warn "keine Dateiliste der alten Version – Programmcode wird nicht gesichert (kein Rollback des Codes möglich)"
	fi
	chmod -R go-rwx "${BACKUP_DIR}"
	# rotation: keep the newest KEEP_BACKUPS
	local old
	while IFS= read -r old; do
		if [[ -n "${old}" && "${PREFIX}/backups/${old}" != "${BACKUP_DIR}" ]]; then
			rm -rf -- "${PREFIX}/backups/${old}"
		fi
	done < <(find "${PREFIX}/backups" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null |
		LC_ALL=C sort -r | tail -n +$((KEEP_BACKUPS + 1)))
}

phase_prepare_env() {
	if [[ ${SKIP_ENV} -eq 1 ]]; then return 0; fi
	local new_hash old_hash=""
	new_hash="$(env_hash "${APP_DIR}")"
	if [[ -f "${PREFIX}/runtime/.env-hash" ]]; then old_hash="$(cat "${PREFIX}/runtime/.env-hash")"; fi
	if [[ "${new_hash}" == "${old_hash}" ]]; then
		log "Python-Pakete und PJSIP unverändert – bestehende Umgebung bleibt"
		return 0
	fi
	NEW_VENV=1
	log "Pakete/PJSIP haben sich geändert – baue eine neue Umgebung (der Dienst läuft währenddessen weiter)"
	run rm -rf "${PREFIX}/runtime/venv.new"
	run "${APP_DIR}/scripts/setup-env.sh" --venv "${PREFIX}/runtime/venv.new" --no-pjsip --jobs "${JOBS}"
	run "${APP_DIR}/scripts/build-pjsip.sh" --python "${PREFIX}/runtime/venv.new/bin/python" --jobs "${JOBS}" \
		--build-root "${PREFIX}/runtime/pjsip-build"
}

phase_stop() {
	if [[ ${SERVICE_WAS_ACTIVE} -eq 1 ]]; then
		log "stoppe den Dienst"
		run systemctl stop moritz-agent.service
	fi
}

# apply: program files, venv switch, then the installer phases that need the new environment.
phase_apply() {
	installer "${APP_DIR}" "user_dirs,code"
	if [[ ${NEW_VENV} -eq 1 && ${DRY_RUN} -eq 0 ]]; then
		log "schalte auf die neue Python-Umgebung um (die alte bleibt als venv.prev)"
		rm -rf "${PREFIX}/runtime/venv.prev"
		mv "${PREFIX}/runtime/venv" "${PREFIX}/runtime/venv.prev"
		mv "${PREFIX}/runtime/venv.new" "${PREFIX}/runtime/venv"
		"${PREFIX}/runtime/venv/bin/python" -m compileall -q "${PREFIX}/moritz_agent"
		chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}/runtime"
	elif [[ ${SKIP_ENV} -eq 0 && ${DRY_RUN} -eq 0 ]]; then
		"${PREFIX}/runtime/venv/bin/python" -m compileall -q "${PREFIX}/moritz_agent"
	fi
	installer "${PREFIX}" "searxng,models,secrets,config,prompts"
}

phase_start_verify() {
	if [[ ${NO_SERVICE} -eq 1 ]]; then return 0; fi
	if [[ ${DRY_RUN} -eq 0 ]]; then drain_stop "${PREFIX}"; DRAINING=0; fi
	if [[ ${SERVICE_WAS_ACTIVE} -eq 1 || -f "${UNIT_DIR}/moritz-agent.service" ]]; then
		installer "${PREFIX}" "service"
	else
		log "kein Dienst eingerichtet – ${PREFIX}/moritz-agent run von Hand starten"
		return 0
	fi
	if [[ ${DRY_RUN} -eq 1 ]]; then return 0; fi
	log "warte auf den Dienst (bis zu ${START_TIMEOUT} s) …"
	local state
	state="$(wait_running "${PREFIX}" "${START_TIMEOUT}")" || {
		warn "der Dienst meldet sich nach dem Update nicht"
		return 1
	}
	log "Dienst läuft: ${state}"
}

rollback() {
	warn "Update fehlgeschlagen – stelle den alten Stand wieder her"
	local failed=0
	if [[ -z "${BACKUP_DIR}" || ! -d "${BACKUP_DIR}" ]]; then return 1; fi
	[[ ${NO_SERVICE} -eq 1 ]] || systemctl stop moritz-agent.service 2>/dev/null || true
	# the venv was switched if the new one is gone from venv.new and the old one waits as venv.prev
	if [[ ${NEW_VENV} -eq 1 && -d "${PREFIX}/runtime/venv.prev" && ! -d "${PREFIX}/runtime/venv.new" ]]; then
		rm -rf "${PREFIX}/runtime/venv.failed"
		mv "${PREFIX}/runtime/venv" "${PREFIX}/runtime/venv.failed" || failed=1
		mv "${PREFIX}/runtime/venv.prev" "${PREFIX}/runtime/venv" || failed=1
		rm -rf "${PREFIX}/runtime/venv.failed"
	fi
	if [[ -f "${BACKUP_DIR}/code.tgz" ]]; then
		# remove what the new version put there, then unpack the old files again
		if [[ -f "${PREFIX}/data/state/payload-manifest.txt" ]]; then
			local path
			while IFS= read -r path; do
				case "${path}" in /* | *..* | "") continue ;; esac
				rm -f -- "${PREFIX}/${path}"
			done <"${PREFIX}/data/state/payload-manifest.txt"
		fi
		tar --extract --gzip --file "${BACKUP_DIR}/code.tgz" --directory "${PREFIX}" --same-permissions || failed=1
		if [[ -f "${BACKUP_DIR}/state/payload-manifest.txt" ]]; then
			cp -p "${BACKUP_DIR}/state/payload-manifest.txt" "${PREFIX}/data/state/payload-manifest.txt" || failed=1
		fi
	else
		warn "keine Code-Sicherung vorhanden – nur Konfiguration wird zurückgespielt"
		failed=1
	fi
	local file
	for file in passwords.txt config/moritz-agent.toml; do
		if [[ -f "${BACKUP_DIR}/${file}" ]]; then cp -p "${BACKUP_DIR}/${file}" "${PREFIX}/${file}" || failed=1; fi
	done
	drain_stop "${PREFIX}"
	if [[ ${NO_SERVICE} -eq 0 && ${SERVICE_WAS_ACTIVE} -eq 1 ]]; then
		systemctl daemon-reload || true
		systemctl start moritz-agent.service || failed=1
	fi
	return "${failed}"
}

on_exit() {
	if [[ ${DRAINING} -eq 1 ]]; then drain_stop "${PREFIX}"; fi
}

main() {
	parse_args "$@"
	trap on_exit EXIT
	if [[ ${DRY_RUN} -eq 0 && ${EUID} -eq 0 ]]; then
		install -d -m 0700 "${LOG_DIR}"
		local logfile
		logfile="${LOG_DIR}/update-$(date +%Y%m%d-%H%M%S).log"
		exec > >(tee -a "${logfile}") 2>&1
		log "Protokoll: ${logfile}"
	fi
	log "moritz-agent Update – Quelle ${APP_DIR}, Ziel ${PREFIX}"
	log "── preflight"
	phase_preflight
	log "── drain"
	phase_drain
	log "── backup"
	phase_backup
	log "── Umgebung vorbereiten"
	phase_prepare_env
	log "── stop"
	phase_stop

	local rc=0
	guarded phase_apply || rc=$?
	if [[ ${rc} -eq 0 ]]; then
		log "── start + verify"
		guarded phase_start_verify || rc=$?
	fi
	if [[ ${rc} -ne 0 ]]; then
		if [[ ${DRY_RUN} -eq 1 ]]; then exit "${rc}"; fi
		if rollback; then
			warn "alter Stand ${OLD_VERSION} ist wiederhergestellt und läuft (Sicherung: ${BACKUP_DIR})"
			exit "${EXIT_ROLLED_BACK}"
		fi
		warn "Rollback unvollständig – manueller Eingriff nötig (Sicherung: ${BACKUP_DIR})"
		exit "${EXIT_ROLLBACK_FAILED}"
	fi

	if [[ ${DRY_RUN} -eq 0 ]]; then
		if [[ ${NEW_VENV} -eq 1 && ${SKIP_ENV} -eq 0 ]]; then
			env_hash "${PREFIX}" >"${PREFIX}/runtime/.env-hash"
		fi
	fi
	log "Update ${OLD_VERSION} → ${NEW_VERSION} fertig in $((SECONDS - STARTED)) s. Ein Testanruf an 999 wird empfohlen."
}

main "$@"

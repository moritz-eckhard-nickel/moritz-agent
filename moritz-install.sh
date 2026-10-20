#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# moritz-install.sh – installer inside the LXC (or any Ubuntu/Debian machine), ticket P1-15.
#
# Normally started by ./install.sh from the Proxmox host (ADR-028), which creates the LXC, copies
# the program into it and calls this script. It can also be run by hand inside a machine:
#     sudo ./moritz-install.sh [--prefix /opt/moritz-agent]
#
# Specification: docs/plan/07-installation-update.md §2 (phases, exit codes). Implemented phases:
# everything the phone needs today (system packages, service user, program files, Python
# environment, PJSIP, models, passwords.txt, configuration, announcements, systemd service,
# verification). KoboldCpp/SearXNG/TLS phases follow with their tickets and are only announced.
#
# Rules (docs/plan/08-sicherheit.md): never `set -x`, never pass secrets as arguments or
# environment variables, never overwrite an existing passwords.txt or config/moritz-agent.toml.
# Re-running is safe: user data (passwords, configuration, models, caches) is always kept.
set -Eeuo pipefail
umask 022

readonly EXIT_OK=0 EXIT_USAGE=2 EXIT_PREFLIGHT=64 EXIT_BUSY=75
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR
LOG_PREFIX="moritz-install"
# shellcheck source=deploy/lib/common.sh
source "${APP_DIR}/deploy/lib/common.sh"

PREFIX="/opt/moritz-agent"
SERVICE_USER="moritz-agent"
NON_INTERACTIVE=0
DRY_RUN=0
SKIP_MODELS=0
SKIP_PACKAGES=0
SKIP_ENV=0
NO_SERVICE=0
PHASE_FILTER=""
JOBS="${MORITZ_JOBS:-$(nproc 2>/dev/null || echo 2)}"
MIN_DISK_GB="${MORITZ_MIN_DISK_GB:-8}"
VERIFY_TIMEOUT="${MORITZ_VERIFY_TIMEOUT:-120}"
DRAIN_TIMEOUT=600
LOG_DIR="${MORITZ_LOG_DIR:-/var/log/moritz-agent}"

# apt packages the phone needs (python build tools for PJSIP, audio libraries, emergency voice)
PACKAGES=(build-essential python3 python3-venv python3-dev swig pkg-config libssl-dev libsndfile1
	espeak-ng tzdata openssl ca-certificates curl)

PHASES=(
	"preflight:Distribution, Python, RAM-Limit, CPU, Speicher prüfen"
	"packages:Systempakete installieren (ohne System-Upgrade)"
	"user_dirs:Dienstbenutzer und Verzeichnisse anlegen"
	"code:Programmdateien ins Installationsverzeichnis kopieren"
	"python_env:venv und gepinnte Python-Pakete (mit Prüfsummen)"
	"pjsip:PJSIP + PJSUA2-Binding bauen (ADR-005)"
	"koboldcpp:KoboldCpp bauen (kommt mit Ticket P1-02)"
	"searxng:SearXNG-Umgebung für die Websuche einrichten"
	"models:Whisper small und Piper-Stimme Hessisch laden"
	"secrets:passwords.txt anlegen (vorhandene bleibt unverändert)"
	"config:config/moritz-agent.toml anlegen (vorhandene bleibt unverändert)"
	"prompts:Ansagen vorrendern und cachen"
	"service:systemd-Dienst installieren und starten"
	"verify:Dienst und SIP-Registrierung prüfen"
	"testcall:Testanruf an 999 anleiten"
)

usage() {
	cat <<USAGE
Usage: $(basename "$0") [options]

  --prefix DIR          Installationsverzeichnis (Standard: ${PREFIX})
  --user NAME           Dienstbenutzer (Standard: ${SERVICE_USER})
  --non-interactive     keine Rückfragen (Modelle werden ohne Nachfrage geladen)
  --dry-run             nur anzeigen, was getan würde
  --skip-models         Modell-Download überspringen
  --skip-packages       apt überspringen (Pakete sind schon da)
  --skip-env            Python-Umgebung und PJSIP überspringen (Test)
  --no-service          keinen systemd-Dienst einrichten
  --jobs N              parallele Build-Prozesse (Standard: Anzahl CPUs)
  --phases LISTE        nur diese Phasen ausführen (Komma-getrennt, z. B. models,prompts; vom Updater genutzt)
  --skip-koboldcpp-build  (ohne Wirkung, für spätere Versionen vorgesehen)
  -h, --help            diese Hilfe

Exit-Codes: 0 ok · 1 Fehler · 2 Benutzung · 64 Voraussetzung nicht erfüllt · 75 aktiver Anruf
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
		--jobs)
			[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "${EXIT_USAGE}" "--jobs braucht eine Zahl"
			JOBS="$2"
			shift 2
			;;
		--phases)
			[[ $# -ge 2 ]] || die "${EXIT_USAGE}" "--phases braucht eine Liste"
			PHASE_FILTER="$2"
			shift 2
			;;
		--non-interactive | -y) NON_INTERACTIVE=1; shift ;;
		--dry-run) DRY_RUN=1; shift ;;
		--skip-models) SKIP_MODELS=1; shift ;;
		--skip-packages) SKIP_PACKAGES=1; shift ;;
		--skip-env) SKIP_ENV=1; shift ;;
		--no-service) NO_SERVICE=1; shift ;;
		--skip-koboldcpp-build) shift ;;
		-h | --help) usage; exit "${EXIT_OK}" ;;
		*) usage >&2; die "${EXIT_USAGE}" "unbekannte Option: $1" ;;
		esac
	done
	[[ "${PREFIX}" == /* ]] || die "${EXIT_USAGE}" "--prefix muss ein absoluter Pfad sein"
	[[ "${SERVICE_USER}" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "${EXIT_USAGE}" "ungültiger Benutzername: ${SERVICE_USER}"
}

# run CMD… – execute a system-changing command (shown instead of executed with --dry-run)
run() {
	if [[ ${DRY_RUN} -eq 1 ]]; then
		log "[dry-run] $*"
		return 0
	fi
	"$@"
}

PY() { printf '%s\n' "${PREFIX}/runtime/venv/bin/python"; }

# -- phases ----------------------------------------------------------------------------------------
phase_preflight() {
	if [[ ${DRY_RUN} -eq 0 ]] && ! is_root; then
		die "${EXIT_PREFLIGHT}" "bitte als root ausführen (sudo ${0})"
	fi
	local pretty="" id="" version=""
	if [[ -r /etc/os-release ]]; then
		pretty="$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-}")"
		id="$(. /etc/os-release && printf '%s' "${ID:-}")"
		version="$(. /etc/os-release && printf '%s' "${VERSION_ID:-}")"
	fi
	log "System: ${pretty:-unbekannt}"
	case "${id}:${version}" in
	ubuntu:24.04 | ubuntu:25.10 | ubuntu:26.04) ;;
	*) warn "getestet ist Ubuntu 24.04/25.10/26.04 (hier: ${id:-?} ${version:-?})" ;;
	esac
	if [[ ${SKIP_PACKAGES} -eq 0 ]] && ! command -v apt-get >/dev/null 2>&1; then
		die "${EXIT_PREFLIGHT}" "apt-get fehlt – nur Debian/Ubuntu werden unterstützt (oder --skip-packages)"
	fi
	if command -v python3 >/dev/null 2>&1; then
		python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
			die "${EXIT_PREFLIGHT}" "Python >= 3.12 nötig (gefunden: $(python3 --version 2>&1)) – Ubuntu 24.04 oder neuer verwenden"
	elif [[ ${SKIP_PACKAGES} -eq 1 ]]; then
		die "${EXIT_PREFLIGHT}" "python3 fehlt"
	fi
	local limit="" total_kb
	if [[ -r /sys/fs/cgroup/memory.max ]]; then limit="$(cat /sys/fs/cgroup/memory.max)"; fi
	if [[ "${limit}" =~ ^[0-9]+$ ]]; then
		total_kb=$((limit / 1024))
	else
		total_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
	fi
	log "RAM-Limit: $((total_kb / 1024)) MB, CPU-Kerne: $(nproc 2>/dev/null || echo '?')"
	((total_kb >= 3 * 1024 * 1024)) || warn "weniger als 3 GB RAM – Whisper small und die Stimme brauchen zusammen etwa 2 GB"
	local probe="${PREFIX}"
	while [[ ! -d "${probe}" && "${probe}" != "/" ]]; do probe="$(dirname "${probe}")"; done
	local free_kb
	free_kb="$(df -Pk "${probe}" | awk 'NR==2 {print $4}')"
	if ((free_kb < MIN_DISK_GB * 1024 * 1024)); then
		die "${EXIT_PREFLIGHT}" "zu wenig freier Speicher: $((free_kb / 1024 / 1024)) GB frei, mindestens ${MIN_DISK_GB} GB nötig"
	fi
	if command -v nvidia-smi >/dev/null 2>&1; then
		log "NVIDIA-GPU im Container sichtbar (wird für das Sprachmodell gebraucht, nicht für Telefon/Stimme)"
	fi
}

phase_packages() {
	if [[ ${SKIP_PACKAGES} -eq 1 ]]; then
		log "apt übersprungen (--skip-packages)"
		return 0
	fi
	local missing=() pkg
	for pkg in "${PACKAGES[@]}"; do
		dpkg -s "${pkg}" >/dev/null 2>&1 || missing+=("${pkg}")
	done
	if ((${#missing[@]} == 0)); then
		log "alle Systempakete sind schon installiert"
		return 0
	fi
	log "installiere Systempakete: ${missing[*]}"
	run env DEBIAN_FRONTEND=noninteractive apt-get update -qq
	run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
}

phase_user_dirs() {
	if ! getent passwd "${SERVICE_USER}" >/dev/null 2>&1; then
		log "lege Dienstbenutzer ${SERVICE_USER} an"
		run useradd --system --home-dir "${PREFIX}" --no-create-home --shell /usr/sbin/nologin \
			--user-group "${SERVICE_USER}"
	fi
	local group
	for group in video render; do # GPU access for the language model later
		if getent group "${group}" >/dev/null 2>&1; then run usermod -aG "${group}" "${SERVICE_USER}"; fi
	done
	run mkdir -p "${PREFIX}"
	local dir
	for dir in data data/logs data/run data/state models runtime assets/audio/cache; do
		run mkdir -p "${PREFIX}/${dir}"
	done
	run install -d -m 0700 "${PREFIX}/backups"
	for dir in data models runtime assets/audio/cache; do
		run chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}/${dir}"
	done
}

phase_code() {
	if [[ "${APP_DIR}" == "${PREFIX}" ]]; then
		log "Quelle und Ziel sind identisch (${PREFIX}) – nichts zu kopieren"
		return 0
	fi
	log "kopiere Programmdateien: ${APP_DIR} → ${PREFIX} (Version $(version_of "${APP_DIR}"))"
	if [[ ${DRY_RUN} -eq 1 ]]; then
		log "[dry-run] $(payload_files "${APP_DIR}" | wc -l) Dateien"
		return 0
	fi
	sync_code "${APP_DIR}" "${PREFIX}"
	chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}/data"
}

phase_python_env() {
	if [[ ${SKIP_ENV} -eq 1 ]]; then
		log "Python-Umgebung übersprungen (--skip-env)"
		return 0
	fi
	run "${PREFIX}/scripts/setup-env.sh" --venv "${PREFIX}/runtime/venv" --no-pjsip --jobs "${JOBS}"
	run "$(PY)" -m compileall -q "${PREFIX}/moritz_agent" # code tree is read-only for the service
}

phase_pjsip() {
	if [[ ${SKIP_ENV} -eq 1 ]]; then return 0; fi
	run "${PREFIX}/scripts/build-pjsip.sh" --python "$(PY)" --jobs "${JOBS}" \
		--build-root "${PREFIX}/runtime/pjsip-build"
	if [[ ${DRY_RUN} -eq 0 ]]; then
		env_hash "${PREFIX}" >"${PREFIX}/runtime/.env-hash" # lets the updater skip an unneeded rebuild
	fi
	run chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}/runtime"
}

phase_koboldcpp() { log "KoboldCpp: gehört zu Ticket P1-02 und ist noch nicht Teil dieses Installers"; }

phase_searxng() {
	if [[ ${SKIP_ENV} -eq 1 ]]; then return 0; fi
	run "${PREFIX}/scripts/setup-searxng.sh" --venv "${PREFIX}/runtime/searxng-venv"
	run chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}/runtime/searxng-venv"
}

phase_models() {
	if [[ ${SKIP_MODELS} -eq 1 || ${SKIP_ENV} -eq 1 ]]; then
		log "Modell-Download übersprungen"
		return 0
	fi
	local args=(fetch --groups "stt,piper")
	if [[ ${NON_INTERACTIVE} -eq 1 ]]; then args+=(--yes); fi
	log "lade Modelle von Hugging Face (Whisper small ≈ 0,5 GB, Piper-Stimme ≈ 0,1 GB) …"
	run env HF_HOME="${PREFIX}/runtime/hf-home" PYTHONPATH="${PREFIX}" \
		"$(PY)" -m moritz_agent.phone.audio.models "${args[@]}"
	run chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}/models" "${PREFIX}/runtime"
}

phase_secrets() {
	local file="${PREFIX}/passwords.txt"
	if [[ -e "${file}" ]]; then
		log "passwords.txt existiert – bleibt unverändert"
	else
		log "lege passwords.txt aus der Vorlage an (SIP-Startwerte, Modus 0600)"
		if [[ ${DRY_RUN} -eq 0 ]]; then
			(
				umask 077
				cp "${PREFIX}/config/passwords.template.txt" "${file}"
			)
			chmod 0600 "${file}"
			chown "${SERVICE_USER}:${SERVICE_USER}" "${file}"
		fi
	fi
	if [[ ${DRY_RUN} -eq 0 ]] && grep -Eq '^[[:space:]]*password[[:space:]]*=[[:space:]]*agent[[:space:]]*$' "${file}"; then
		warn "SIP-Passwort ist noch der Startwert 'agent' – in Asterisk und passwords.txt ändern (empfohlen)"
	fi
}

phase_config() {
	local file="${PREFIX}/config/moritz-agent.toml"
	if [[ -e "${file}" ]]; then
		log "config/moritz-agent.toml existiert – bleibt unverändert"
		return 0
	fi
	log "lege config/moritz-agent.toml aus der Beispielkonfiguration an"
	if [[ ${DRY_RUN} -eq 0 ]]; then
		cp "${PREFIX}/config/moritz-agent.example.toml" "${file}"
		chmod 0640 "${file}"
		chown "${SERVICE_USER}:${SERVICE_USER}" "${file}"
	fi
}

phase_prompts() {
	if [[ ${SKIP_ENV} -eq 1 ]]; then return 0; fi
	log "rendere die Ansagen (landen in assets/audio/cache/)"
	if ! run runuser -u "${SERVICE_USER}" -- env -C "${PREFIX}" PYTHONPATH="${PREFIX}" HOME="${PREFIX}/runtime" \
		"$(PY)" -m moritz_agent.phone prompts; then
		warn "Ansagen konnten nicht vorgerendert werden – der Dienst rendert sie beim Start selbst"
	fi
}

render_unit() {
	sed -e "s#/opt/moritz-agent#${PREFIX}#g" -e "s#^User=.*#User=${SERVICE_USER}#" \
		-e "s#^Group=.*#Group=${SERVICE_USER}#" "${PREFIX}/deploy/systemd/moritz-agent.service"
}

phase_service() {
	if [[ ${NO_SERVICE} -eq 1 ]]; then
		log "systemd-Dienst übersprungen (--no-service). Start von Hand: ${PREFIX}/moritz-agent run"
		return 0
	fi
	if [[ ${DRY_RUN} -eq 0 && ! -d "${SYSTEMD_RUN_DIR}" ]]; then
		warn "systemd läuft hier nicht – Dienst nicht eingerichtet. Start von Hand: ${PREFIX}/moritz-agent run"
		NO_SERVICE=1
		return 0
	fi
	log "installiere den systemd-Dienst moritz-agent"
	if [[ ${DRY_RUN} -eq 0 ]]; then
		render_unit >"${UNIT_DIR}/moritz-agent.service"
		chmod 0644 "${UNIT_DIR}/moritz-agent.service"
	fi
	run systemctl daemon-reload
	run systemctl enable moritz-agent.service
	if [[ ${DRY_RUN} -eq 0 ]] && systemctl is-active --quiet moritz-agent.service; then
		log "Dienst läuft bereits – warte auf das Gesprächsende, dann Neustart"
		if ! drain_wait "${PREFIX}" "${DRAIN_TIMEOUT}"; then
			drain_stop "${PREFIX}"
			die "${EXIT_BUSY}" "es läuft noch ein Anruf – Neustart verschoben (später erneut ausführen)"
		fi
		drain_stop "${PREFIX}" # before the restart, so the new process does not start in drain mode
	fi
	run systemctl restart moritz-agent.service
}

phase_verify() {
	if [[ ${NO_SERVICE} -eq 1 || ${DRY_RUN} -eq 1 ]]; then return 0; fi
	log "warte auf den Dienst (bis zu ${VERIFY_TIMEOUT} s) …"
	local state
	if ! state="$(wait_running "${PREFIX}" "${VERIFY_TIMEOUT}")"; then
		warn "der Dienst meldet sich nicht – Log ansehen: journalctl -u moritz-agent -n 50"
		return 0
	fi
	log "Dienst läuft: ${state}"
	case "${state}" in
	*registration=registered*) log "SIP-Registrierung: ok" ;;
	*) warn "SIP noch nicht registriert (${state}) – Zugangsdaten in ${PREFIX}/passwords.txt und docs/asterisk-konfiguration.md prüfen" ;;
	esac
}

phase_testcall() {
	cat <<MSG

Fertig. Nächste Schritte:
  1. SIP-Zugangsdaten prüfen:   ${PREFIX}/passwords.txt   (Abschnitt [sip]), danach:
                                systemctl reload moritz-agent
  2. Asterisk einrichten:       docs/asterisk-konfiguration.md (Nebenstelle 999 → Konto agent)
  3. Testanruf:                 Nebenstelle 999 wählen – Begrüßung, Uhrzeit erfragen, auflegen
  4. Log ansehen:               journalctl -u moritz-agent -f
MSG
}

main() {
	parse_args "$@"
	if [[ ${DRY_RUN} -eq 0 && ${EUID} -eq 0 ]]; then
		install -d -m 0700 "${LOG_DIR}"
		local logfile
		logfile="${LOG_DIR}/install-$(date +%Y%m%d-%H%M%S).log"
		exec > >(tee -a "${logfile}") 2>&1
		log "Protokoll: ${logfile}"
	fi
	log "moritz-agent Installer – Quelle ${APP_DIR}, Ziel ${PREFIX}"
	local entry name
	for entry in "${PHASES[@]}"; do
		name="${entry%%:*}"
		if [[ -n "${PHASE_FILTER}" && ",${PHASE_FILTER}," != *",${name},"* ]]; then continue; fi
		log "── ${name}: ${entry#*:}"
		"phase_${name}"
	done
	log "Fertig."
}

main "$@"

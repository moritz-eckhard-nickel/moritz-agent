#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# Proxmox-host functions of install.sh and update.sh (ADR-028). Sourced after common.sh.
# shellcheck disable=SC2034 # the variables below are read by install.sh and update.sh
#
# What these scripts do on the Proxmox host – and nothing else:
#   * download an Ubuntu LXC template if it is missing (pveam),
#   * create ONE new unprivileged container for moritz-agent (pct create) – or, if it exists,
#     use it; optionally add the NVIDIA device nodes to this container,
#   * copy the program into the container and run moritz-install.sh / moritz-update.sh there,
#   * take a snapshot of this container before an update.
# Other containers, VMs, storages, network or firewall settings of the host are never touched.

# -- defaults (overridable by options) -------------------------------------------------------------
CTID=""
CT_HOSTNAME="moritz-agent"
ROOTFS_STORAGE=""
TEMPLATE_STORAGE=""
TEMPLATE=""
DISK_GB=80
MEMORY_MB=16384
SWAP_MB=2048
CORES=""
CPUUNITS=512
BRIDGE="vmbr0"
VLAN=""
IP_CONFIG="dhcp"
GATEWAY=""
NAMESERVER=""
SEARCHDOMAIN=""
GPU="auto"
SSH_KEY_FILE=""
TIMEZONE="Europe/Berlin"
START_AFTER=1
ASSUME_YES=0
DRY_RUN=0
KEEP_SNAPSHOTS=3
NO_SNAPSHOT=0
REMOTE=""
SSH_PORT=22
SSH_IDENTITY=""
PREFIX_IN_CT="/opt/moritz-agent"
STAGING_IN_CT="/root/moritz-agent-staging"
SKIP_MODELS=0
DRAIN_TIMEOUT=""
KEEP_BACKUPS=""
JOBS=""
REQUIRE_SNAPSHOT=0
CT_EXISTS=0
CREATION_OPTIONS_SET=0
FORWARD_ARGS=() # the original options without the --remote group (sent to the remote host)

# Plain ASCII: Proxmox URL-encodes other characters in the stored description.
CT_MARKER="managed-by-moritz-agent-install"
DEV_DIR="${MORITZ_DEV_DIR:-/dev}" # test hook: where the NVIDIA device nodes are looked up

# host_run CMD… – a command that changes something (only printed with --dry-run)
host_run() {
	if [[ ${DRY_RUN} -eq 1 ]]; then
		log "[dry-run] $*"
		return 0
	fi
	"$@"
}

# ct_run ARGS… – run a command inside the container
ct_run() { host_run pct exec "${CTID}" -- "$@"; }
# ct_query ARGS… – read-only command inside the container (also executed in --dry-run)
ct_query() { pct exec "${CTID}" -- "$@"; }

# confirm_or_die TEXT – no yes/no questions any more (Moritz, 21.10.2026): the plan is shown and done.
# Only a container that moritz-agent did not create is refused unless --yes says so (see refuse_foreign).
confirm_or_die() { log "$1 – ja"; }

# refuse_foreign TEXT – never touch someone else's container by accident: stop unless --yes was given
refuse_foreign() {
	[[ ${ASSUME_YES} -eq 1 || ${DRY_RUN} -eq 1 ]] && return 0
	die 2 "$1 – mit --yes trotzdem"
}

# -- environment -------------------------------------------------------------------------------------
require_proxmox() {
	local tool
	for tool in pct pveam pvesm; do
		command -v "${tool}" >/dev/null 2>&1 ||
			die 64 "'${tool}' nicht gefunden – dieses Skript muss auf dem Proxmox-VE-Host laufen (oder mit --remote von einem anderen Rechner)"
	done
	is_root || die 64 "bitte als root ausführen (sudo ./$(basename "$0"))"
}

pve_version() { # → "8.2"
	local line
	line="$(pveversion 2>/dev/null | head -1)"
	sed -n 's#^pve-manager/\([0-9]*\.[0-9]*\).*#\1#p' <<<"${line}"
}

# version_ge A B – true if version A >= B (both "major.minor")
version_ge() { [[ "$(printf '%s\n%s\n' "$1" "$2" | LC_ALL=C sort -V | head -1)" == "$2" ]]; }

default_cores() {
	local available
	available="$(nproc 2>/dev/null || echo 4)"
	if ((available < 18)); then echo "${available}"; else echo 18; fi
}

# first active storage that offers CONTENT (rootdir / vztmpl); prefers PREFERRED
find_storage() {
	local content="$1" preferred="$2" line name status found=""
	while IFS= read -r line; do
		name="$(awk '{print $1}' <<<"${line}")"
		status="$(awk '{print $3}' <<<"${line}")"
		[[ "${name}" == "Name" || "${status}" != "active" ]] && continue
		[[ -n "${found}" ]] || found="${name}"
		[[ "${name}" == "${preferred}" ]] && found="${name}"
	done < <(pvesm status --content "${content}" 2>/dev/null)
	printf '%s\n' "${found}"
}

# choose_template – newest preferred Ubuntu template (26.04 → 25.10 → 24.04 → newest available)
choose_template() {
	if [[ -n "${TEMPLATE}" ]]; then return 0; fi
	local available version wanted
	available="$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep -E '^ubuntu-[0-9.]+-standard_' || true)"
	[[ -n "${available}" ]] || die 64 "keine Ubuntu-Vorlage über 'pveam available' gefunden (pveam update? Internet am Host?)"
	for wanted in 26.04 25.10 24.04; do
		TEMPLATE="$(grep -E "^ubuntu-${wanted}-standard_" <<<"${available}" | LC_ALL=C sort -V | tail -1 || true)"
		[[ -n "${TEMPLATE}" ]] && return 0
	done
	version="$(LC_ALL=C sort -V <<<"${available}" | tail -1)"
	TEMPLATE="${version}"
	warn "keine der getesteten Ubuntu-Versionen (26.04, 25.10, 24.04) verfügbar – nehme ${TEMPLATE}"
}

ensure_template() {
	local present
	present="$(pveam list "${TEMPLATE_STORAGE}" 2>/dev/null | awk '{print $1}')"
	if grep -qxF "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" <<<"${present}"; then
		log "Vorlage ${TEMPLATE} ist schon auf ${TEMPLATE_STORAGE}"
		return 0
	fi
	log "lade Vorlage ${TEMPLATE} nach ${TEMPLATE_STORAGE} …"
	host_run pveam download "${TEMPLATE_STORAGE}" "${TEMPLATE}"
}

next_ctid() {
	local id
	if id="$(pvesh get /cluster/nextid 2>/dev/null)" && id="${id//\"/}" && [[ "${id}" =~ ^[0-9]+$ ]]; then
		printf '%s\n' "${id}"
		return 0
	fi
	id=100
	while pct status "${id}" >/dev/null 2>&1; do id=$((id + 1)); done
	printf '%s\n' "${id}"
}

# find_ct – sets CT_EXISTS (and CTID when the container is found by its hostname)
find_ct() {
	local matches count
	if [[ -n "${CTID}" ]]; then
		if pct status "${CTID}" >/dev/null 2>&1; then CT_EXISTS=1; fi
		return 0
	fi
	matches="$(pct list 2>/dev/null | awk -v name="${CT_HOSTNAME}" 'NR > 1 && $NF == name {print $1}')"
	count="$(wc -w <<<"${matches}")"
	if ((count > 1)); then
		die 2 "mehrere Container heißen '${CT_HOSTNAME}' (${matches//$'\n'/ }) – mit --ctid wählen"
	fi
	if ((count == 1)); then
		CTID="${matches//[[:space:]]/}"
		CT_EXISTS=1
	fi
}

# ct_is_ours – the container carries the marker written by create_container
ct_is_ours() { pct config "${CTID}" 2>/dev/null | grep -qE "${CT_MARKER}|^tags:.*moritz-agent"; }

ct_is_running() { [[ "$(pct status "${CTID}" 2>/dev/null)" == *running* ]]; }

wait_for_network() {
	[[ ${DRY_RUN} -eq 1 ]] && return 0
	local waited=0
	log "warte auf das Netzwerk im Container …"
	until ct_query getent hosts archive.ubuntu.com >/dev/null 2>&1; do
		((waited < ${MORITZ_NET_TIMEOUT:-120})) || die 1 "der Container hat nach ${waited} s kein Netzwerk (DNS/Gateway/Bridge prüfen: pct enter ${CTID})"
		sleep 2
		waited=$((waited + 2))
	done
}

ensure_running() {
	if ct_is_running; then return 0; fi
	log "starte Container ${CTID}"
	host_run pct start "${CTID}"
	wait_for_network
}

ct_address() {
	[[ ${DRY_RUN} -eq 1 ]] && return 0
	ct_query hostname -I 2>/dev/null | awk '{print $1}'
}

# -- creating the container ----------------------------------------------------------------------------
create_container() {
	local net="name=eth0,bridge=${BRIDGE},ip=${IP_CONFIG},firewall=0,type=veth"
	if [[ -n "${GATEWAY}" ]]; then net+=",gw=${GATEWAY}"; fi
	if [[ -n "${VLAN}" ]]; then net+=",tag=${VLAN}"; fi
	local args=(
		"${CTID}" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}"
		--hostname "${CT_HOSTNAME}" --ostype ubuntu --unprivileged 1
		--cores "${CORES}" --cpuunits "${CPUUNITS}" --memory "${MEMORY_MB}" --swap "${SWAP_MB}"
		--rootfs "${ROOTFS_STORAGE}:${DISK_GB}" --net0 "${net}"
		--features nesting=1 --onboot 1 --timezone "${TIMEZONE}"
		--description "moritz-agent Anton - ${CT_MARKER}"
	)
	if [[ -n "${NAMESERVER}" ]]; then args+=(--nameserver "${NAMESERVER}"); fi
	if [[ -n "${SEARCHDOMAIN}" ]]; then args+=(--searchdomain "${SEARCHDOMAIN}"); fi
	if [[ -n "${SSH_KEY_FILE}" ]]; then args+=(--ssh-public-keys "${SSH_KEY_FILE}"); fi
	if version_ge "$(pve_version || echo 0.0)" 7.3; then args+=(--tags moritz-agent); fi
	log "lege den Container ${CTID} (${CT_HOSTNAME}) an"
	host_run pct create "${args[@]}"
}

# configure_gpu – pass the NVIDIA device nodes of the host into the container (docs/plan/06 §4.2)
configure_gpu() {
	[[ "${GPU}" == "no" ]] && return 0
	if [[ ! -e "${DEV_DIR}/nvidia0" ]]; then
		[[ "${GPU}" == "yes" ]] && die 64 "--gpu yes, aber am Host gibt es kein ${DEV_DIR}/nvidia0 (NVIDIA-Treiber installiert? docs/plan/06 §4.1)"
		log "keine NVIDIA-GPU am Host – Telefon und Stimme brauchen keine (das Sprachmodell später schon)"
		return 0
	fi
	if ! version_ge "$(pve_version || echo 0.0)" 8.1; then
		[[ "${GPU}" == "yes" ]] && die 64 "GPU-Durchreichung per dev-Eintrag braucht Proxmox VE >= 8.1"
		warn "Proxmox VE < 8.1: GPU-Durchreichung wird übersprungen (docs/plan/06 §4.2)"
		return 0
	fi
	local video_gid index=0 node args
	if [[ ${DRY_RUN} -eq 1 ]]; then
		video_gid="<video-gid>"
	else
		video_gid="$(ct_query getent group video 2>/dev/null | cut -d: -f3)"
	fi
	[[ -n "${video_gid}" ]] || {
		warn "Gruppe 'video' im Container nicht gefunden – GPU-Durchreichung übersprungen"
		return 0
	}
	for node in "${DEV_DIR}"/nvidia[0-9]* "${DEV_DIR}/nvidiactl" "${DEV_DIR}/nvidia-uvm" "${DEV_DIR}/nvidia-uvm-tools" "${DEV_DIR}/nvidia-modeset"; do
		[[ -e "${node}" ]] || continue
		args="${node},gid=${video_gid}"
		host_run pct set "${CTID}" "-dev${index}" "${args}"
		index=$((index + 1))
	done
	log "GPU-Geräte eingetragen (${index}); starte den Container neu"
	host_run pct reboot "${CTID}"
	wait_for_network
	log "Hinweis: im Container fehlt noch der NVIDIA-Userspace-Treiber in GENAU der Version des Hosts ($(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || echo '?')) – docs/plan/06 §4.3; er wird erst für das Sprachmodell gebraucht"
}

# -- copying the program into the container --------------------------------------------------------------
# push_payload – archive of the program → container, unpacked into the staging directory
push_payload() {
	local archive
	archive="$(mktemp /tmp/moritz-agent-payload.XXXXXX.tgz)"
	log "packe das Programm (Version $(version_of "${ROOT}")) …"
	make_payload "${ROOT}" "${archive}" || {
		rm -f "${archive}"
		return 1
	}
	log "kopiere $(du -h "${archive}" | cut -f1) in den Container …"
	if ! host_run pct push "${CTID}" "${archive}" /root/moritz-agent-payload.tgz; then
		rm -f "${archive}"
		return 1
	fi
	rm -f "${archive}"
	ct_run bash -c "rm -rf '${STAGING_IN_CT}' && mkdir -p '${STAGING_IN_CT}' && tar -xzf /root/moritz-agent-payload.tgz -C '${STAGING_IN_CT}' && rm -f /root/moritz-agent-payload.tgz" || return 1
}

cleanup_staging() { ct_run rm -rf "${STAGING_IN_CT}" || true; }

ct_has_installation() {
	ct_query test -f "${PREFIX_IN_CT}/config/moritz-agent.example.toml" >/dev/null 2>&1
}

# -- install / update flows --------------------------------------------------------------------------------
inner_args() { # inner_args install|update → words for moritz-install.sh / moritz-update.sh
	local kind="$1"
	printf '%s\n' --non-interactive --prefix "${PREFIX_IN_CT}"
	if [[ ${SKIP_MODELS} -eq 1 ]]; then printf '%s\n' --skip-models; fi
	if [[ -n "${JOBS}" ]]; then printf '%s\n' --jobs "${JOBS}"; fi
	if [[ "${kind}" == "update" ]]; then
		if [[ -n "${DRAIN_TIMEOUT}" ]]; then printf '%s\n' --drain-timeout "${DRAIN_TIMEOUT}"; fi
		if [[ -n "${KEEP_BACKUPS}" ]]; then printf '%s\n' --keep-backups "${KEEP_BACKUPS}"; fi
	fi
}

do_install_in_container() {
	push_payload || return 1
	local args
	mapfile -t args < <(inner_args install)
	log "starte den Installer im Container (das dauert beim ersten Mal einige Minuten: Pakete, PJSIP-Build, Modelle) …"
	local rc=0
	ct_run "${STAGING_IN_CT}/moritz-install.sh" "${args[@]}" || rc=$?
	if [[ ${rc} -ne 0 ]]; then
		warn "der Installer im Container endete mit Code ${rc} – Protokoll: pct exec ${CTID} -- ls /var/log/moritz-agent/"
		warn "Nach der Fehlerbehebung dasselbe Kommando erneut ausführen: ./install.sh --ctid ${CTID} (setzt fort, nichts geht verloren)"
		return "${rc}"
	fi
	cleanup_staging
}

take_snapshot() {
	[[ ${NO_SNAPSHOT} -eq 1 ]] && return 0
	local name
	name="moritz-pre-update-$(date +%Y%m%d-%H%M%S)"
	log "Snapshot ${name} (Rückfallebene für den ganzen Container)"
	if ! host_run pct snapshot "${CTID}" "${name}" --description "vor moritz-agent Update ($(version_of "${ROOT}"))"; then
		if [[ ${REQUIRE_SNAPSHOT} -eq 1 ]]; then die 1 "Snapshot nicht möglich und --require-snapshot gesetzt – nichts wurde verändert"; fi
		warn "Snapshot nicht möglich (Speicher ohne Snapshot-Unterstützung?) – weiter ohne; --no-snapshot unterdrückt diese Meldung"
		return 0
	fi
	prune_snapshots
}

prune_snapshots() {
	[[ ${DRY_RUN} -eq 1 ]] && return 0
	local old
	while IFS= read -r old; do
		if [[ -n "${old}" ]]; then host_run pct delsnapshot "${CTID}" "${old}" || true; fi
	done < <(pct listsnapshot "${CTID}" 2>/dev/null | grep -oE 'moritz-pre-update-[0-9]{8}-[0-9]{6}' |
		LC_ALL=C sort -r | tail -n +$((KEEP_SNAPSHOTS + 1)))
}

do_update_in_container() {
	ensure_running || return 1
	take_snapshot || return 1
	push_payload || return 1
	local args
	mapfile -t args < <(inner_args update)
	log "starte den Updater im Container (Version $(version_of "${ROOT}")) …"
	local rc=0
	ct_run "${STAGING_IN_CT}/moritz-update.sh" "${args[@]}" || rc=$?
	case "${rc}" in
	0) cleanup_staging ;;
	75)
		warn "Update verschoben: im Container läuft ein Gespräch. Später erneut ausführen (oder --drain-timeout erhöhen)."
		;;
	70)
		warn "Update fehlgeschlagen, der alte Stand wurde im Container wiederhergestellt (Protokoll: /var/log/moritz-agent/ im Container)."
		;;
	71)
		warn "Update UND Rollback fehlgeschlagen. Ganzer Container zurück: pct rollback ${CTID} <moritz-pre-update-…> (pct listsnapshot ${CTID})"
		;;
	*) warn "der Updater endete mit Code ${rc}" ;;
	esac
	return "${rc}"
}

print_summary() {
	local address
	address="$(ct_address || true)"
	cat <<MSG

moritz-agent läuft im Container ${CTID} (${CT_HOSTNAME}), Adresse: ${address:-unbekannt}
  Konsole im Container:     pct enter ${CTID}
  Log:                      pct exec ${CTID} -- journalctl -u moritz-agent -n 50
  SIP-Zugangsdaten:         pct exec ${CTID} -- nano ${PREFIX_IN_CT}/passwords.txt
                            pct exec ${CTID} -- systemctl reload moritz-agent
  Asterisk (nur Ansicht):   Agent-IP ${address:-<AGENT_IP>} in docs/asterisk-konfiguration.md eintragen
  Update später:            sudo ./update.sh        (erneut aus dem aktuellen Programmordner)
MSG
	if [[ "${IP_CONFIG}" == "dhcp" ]]; then
		printf '  Hinweis: Der Container bekommt die Adresse per DHCP. Für Asterisk (ACL) besser eine feste Adresse:\n'
		printf '           pct set %s -net0 name=eth0,bridge=%s,ip=<IP>/<Maske>,gw=<Gateway>\n' "${CTID}" "${BRIDGE}"
	fi
}

# -- remote mode: copy this program to the Proxmox host and run the script there ----------------------------
# remote_run SCRIPT ARGS… – SCRIPT is install.sh or update.sh; ARGS exclude the --remote options
remote_run() {
	local script="$1"
	shift
	local archive remote_tmp="/tmp/moritz-agent-host-$$.tgz" ssh_opts=(-p "${SSH_PORT}") scp_opts=(-P "${SSH_PORT}") quoted="" arg
	if [[ -n "${SSH_IDENTITY}" ]]; then
		ssh_opts+=(-i "${SSH_IDENTITY}")
		scp_opts+=(-i "${SSH_IDENTITY}")
	fi
	archive="$(mktemp /tmp/moritz-agent-remote.XXXXXX.tgz)"
	make_payload "${ROOT}" "${archive}"
	log "kopiere das Programm nach ${REMOTE}:${remote_tmp} ($(du -h "${archive}" | cut -f1)) …"
	host_run scp "${scp_opts[@]}" "${archive}" "${REMOTE}:${remote_tmp}"
	for arg in "$@"; do quoted+=" $(printf '%q' "${arg}")"; done
	local remote_cmd
	remote_cmd="set -e; stage=\$(mktemp -d /tmp/moritz-agent-host.XXXXXX); trap 'rm -rf \"\$stage\" ${remote_tmp}' EXIT; tar -xzf ${remote_tmp} -C \"\$stage\"; SUDO=; [ \"\$(id -u)\" -eq 0 ] || SUDO=sudo; \$SUDO \"\$stage/${script}\" --local${quoted}"
	log "führe ${script} auf ${REMOTE} aus (bei Bedarf fragt sudo dort nach dem Passwort) …"
	local rc=0
	host_run ssh -t "${ssh_opts[@]}" "${REMOTE}" "${remote_cmd}" || rc=$?
	rm -f "${archive}"
	return "${rc}"
}

# -- options shared by install.sh and update.sh ---------------------------------------------------------------
# The calling script defines host_usage(); creation-only options set CREATION_OPTIONS_SET=1.
parse_host_args() {
	need_value() { [[ $# -ge 2 && -n "$2" ]] || die 2 "$1 braucht einen Wert"; }
	FORWARD_ARGS=()
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--remote)
			need_value "$@"
			REMOTE="$2"
			shift 2
			continue
			;;
		--ssh-port)
			need_value "$@"
			SSH_PORT="$2"
			shift 2
			continue
			;;
		--identity)
			need_value "$@"
			SSH_IDENTITY="$2"
			shift 2
			continue
			;;
		--local) REMOTE="" ;;
		esac
		FORWARD_ARGS+=("$1")
		case "$1" in
		--ctid) need_value "$@"; CTID="$2"; FORWARD_ARGS+=("$2"); shift ;;
		--hostname) need_value "$@"; CT_HOSTNAME="$2"; FORWARD_ARGS+=("$2"); shift ;;
		--yes | -y) ASSUME_YES=1 ;;
		--dry-run) DRY_RUN=1 ;;
		--skip-models) SKIP_MODELS=1 ;;
		--jobs) need_value "$@"; JOBS="$2"; FORWARD_ARGS+=("$2"); shift ;;
		--local) ;;
		--storage) need_value "$@"; ROOTFS_STORAGE="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--template-storage) need_value "$@"; TEMPLATE_STORAGE="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--os-template) need_value "$@"; TEMPLATE="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--disk) need_value "$@"; DISK_GB="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--memory) need_value "$@"; MEMORY_MB="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--swap) need_value "$@"; SWAP_MB="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--cores) need_value "$@"; CORES="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--cpuunits) need_value "$@"; CPUUNITS="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--bridge) need_value "$@"; BRIDGE="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--vlan) need_value "$@"; VLAN="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--ip) need_value "$@"; IP_CONFIG="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--gateway) need_value "$@"; GATEWAY="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--dns) need_value "$@"; NAMESERVER="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--search-domain) need_value "$@"; SEARCHDOMAIN="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--gpu)
			need_value "$@"
			[[ "$2" =~ ^(auto|yes|no)$ ]] || die 2 "--gpu erwartet auto, yes oder no"
			GPU="$2"
			CREATION_OPTIONS_SET=1
			FORWARD_ARGS+=("$2")
			shift
			;;
		--ssh-key) need_value "$@"; SSH_KEY_FILE="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--timezone) need_value "$@"; TIMEZONE="$2"; CREATION_OPTIONS_SET=1; FORWARD_ARGS+=("$2"); shift ;;
		--no-start) START_AFTER=0; CREATION_OPTIONS_SET=1 ;;
		--drain-timeout) need_value "$@"; DRAIN_TIMEOUT="$2"; FORWARD_ARGS+=("$2"); shift ;;
		--keep-backups) need_value "$@"; KEEP_BACKUPS="$2"; FORWARD_ARGS+=("$2"); shift ;;
		--keep-snapshots) need_value "$@"; KEEP_SNAPSHOTS="$2"; FORWARD_ARGS+=("$2"); shift ;;
		--no-snapshot) NO_SNAPSHOT=1 ;;
		--require-snapshot) REQUIRE_SNAPSHOT=1 ;;
		-h | --help) host_usage; exit 0 ;;
		*) host_usage >&2; die 2 "unbekannte Option: $1" ;;
		esac
		shift
	done
	[[ -z "${CTID}" || "${CTID}" =~ ^[0-9]+$ ]] || die 2 "--ctid erwartet eine Zahl"
	[[ -z "${JOBS}" || "${JOBS}" =~ ^[0-9]+$ ]] || die 2 "--jobs erwartet eine Zahl"
	[[ -z "${CORES}" ]] && CORES="$(default_cores)"
	return 0
}

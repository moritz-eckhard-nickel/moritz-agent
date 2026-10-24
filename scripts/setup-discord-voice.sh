#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# setup-discord-voice.sh – the Python environment that lets Anton LISTEN in Discord voice channels
# (spike P1-32, docs/plan/14 §9.5, ADR-036).
#
# Discord encrypts every voice channel end to end (DAVE, since March 2026). Receiving needs the
# fork zacker150/discord-ext-voice-recv, which brings its own discord.py fork. That conflicts with
# the pinned discord.py of requirements/discord.lock, so it gets an environment of its own,
# runtime/discord-venv, used only by the Discord worker (moritz_agent/supervisor.py picks it up).
# Everything else comes from the hash-checked lock files; only the two GitHub packages are pinned
# by commit instead of by hash (pip cannot hash-check VCS sources, ADR-019 exception).
#
# Usage: scripts/setup-discord-voice.sh [--venv DIR] [--python PYTHON] [--remove]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/runtime/discord-venv"
PYTHON="${MORITZ_PYTHON:-}"
# tested together (24.10.2026); the fork pins its discord.py fork itself
RECV="discord-ext-voice-recv @ git+https://github.com/zacker150/discord-ext-voice-recv@dcf543a1618d6212f10db5d5dbb7a45f76a955e9"
DAVEY="davey>=0.1.6,<0.2"

log() { printf '[discord-voice] %s\n' "$*"; }
die() {
	printf '[discord-voice] FEHLER: %s\n' "$*" >&2
	exit 1
}

remove=0
while [[ $# -gt 0 ]]; do
	case "$1" in
	--venv)
		[[ $# -ge 2 ]] || die "--venv braucht ein Verzeichnis"
		VENV="$2"
		shift 2
		;;
	--python)
		[[ $# -ge 2 ]] || die "--python braucht einen Pfad"
		PYTHON="$2"
		shift 2
		;;
	--remove)
		remove=1
		shift
		;;
	-h | --help)
		sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
		exit 0
		;;
	*) die "unbekannte Option: $1" ;;
	esac
done

if [[ ${remove} -eq 1 ]]; then
	rm -rf -- "${VENV}"
	log "entfernt – Anton spricht im Sprachkanal nur noch (ohne Zuhören)"
	exit 0
fi

command -v git >/dev/null 2>&1 || die "git fehlt (apt install git) – nötig für die Pakete von GitHub"
if [[ -z "${PYTHON}" ]]; then
	for candidate in python3.13 python3.12 python3; do
		if command -v "${candidate}" >/dev/null 2>&1; then
			PYTHON="$(command -v "${candidate}")"
			break
		fi
	done
fi
[[ -n "${PYTHON}" && -x "${PYTHON}" ]] || die "kein Python gefunden"

LOCKS=("${ROOT}/requirements/core.lock" "${ROOT}/requirements/phone.lock" "${ROOT}/requirements/discord.lock")
STAMP="${VENV}/.moritz-voice"
fingerprint="$({
	cat "${LOCKS[@]}"
	printf '%s\n%s\n' "${RECV}" "${DAVEY}"
	"${PYTHON}" --version 2>&1
} | sha256sum | cut -d' ' -f1)"
if [[ -f "${STAMP}" && "$(cat "${STAMP}")" == "${fingerprint}" ]]; then
	log "unverändert – vorhandene Umgebung wird weiter benutzt"
	exit 0
fi

VPY="${VENV}/bin/python"
[[ -x "${VPY}" ]] || "${PYTHON}" -m venv "${VENV}" || die "venv fehlgeschlagen (apt install python3-venv)"
rm -f "${STAMP}"
log "Pakete aus den Lock-Dateien (mit Prüfsummen) …"
"${VPY}" -m pip install --disable-pip-version-check --quiet --require-hashes \
	-r "${LOCKS[0]}" -r "${LOCKS[1]}" -r "${LOCKS[2]}" || die "Paketinstallation fehlgeschlagen"
log "Zuhören mit DAVE: discord-ext-voice-recv (Fork) + discord.py-Fork von GitHub …"
"${VPY}" -m pip install --disable-pip-version-check --quiet "${DAVEY}" "${RECV}" ||
	die "Installation von GitHub fehlgeschlagen – Anton spricht im Sprachkanal weiter nur"
"${VPY}" -c 'import davey, discord, discord.ext.voice_recv as r; assert hasattr(r, "VoiceRecvClient"); print("discord.py", discord.__version__)' ||
	die "Prüfung fehlgeschlagen – die Umgebung wird nicht benutzt"
printf '%s\n' "${fingerprint}" >"${STAMP}"
log "fertig: ${VENV} – der Discord-Teil nimmt sie beim nächsten Start automatisch"

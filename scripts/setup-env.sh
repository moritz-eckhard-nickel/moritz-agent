#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# setup-env.sh – create the Python environment of moritz-agent: virtual environment, pinned
# packages (requirements/*.lock, installed with hash checking) and the PJSIP binding.
#
# Shared by ./test-1.sh (any Linux box) and moritz-install.sh (LXC), so both set up exactly the
# same environment. Needs no root; run it as the user that owns the environment.
#
# Usage: scripts/setup-env.sh --venv DIR [--python PYTHON] [--jobs N] [--no-pjsip]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=""
PYTHON="${MORITZ_PYTHON:-}"
JOBS="${MORITZ_JOBS:-$(nproc 2>/dev/null || echo 2)}"
PJSIP=1

log() { printf '[setup-env] %s\n' "$*"; }
die() {
	printf '[setup-env] FEHLER: %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<USAGE
Usage: $(basename "$0") --venv DIR [--python PYTHON] [--jobs N] [--no-pjsip]

  --venv DIR        Zielverzeichnis der virtuellen Umgebung (z. B. runtime/venv)
  --python PYTHON   Interpreter >= 3.12 (Standard: python3.13, python3.12, python3)
  --jobs N          parallele Build-Prozesse für PJSIP (Standard: Anzahl der CPUs)
  --no-pjsip        PJSIP nicht bauen
USAGE
}

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
	--jobs)
		[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "--jobs braucht eine Zahl"
		JOBS="$2"
		shift 2
		;;
	--no-pjsip)
		PJSIP=0
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		usage >&2
		die "unbekannte Option: $1"
		;;
	esac
done
[[ -n "${VENV}" ]] || {
	usage >&2
	die "--venv fehlt"
}

if [[ -z "${PYTHON}" ]]; then
	for candidate in python3.13 python3.12 python3; do
		if command -v "${candidate}" >/dev/null 2>&1; then
			PYTHON="$(command -v "${candidate}")"
			break
		fi
	done
fi
[[ -n "${PYTHON}" && -x "${PYTHON}" ]] || die "kein Python gefunden (Ubuntu: apt install python3 python3-venv python3-dev)"
"${PYTHON}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
	die "Python >= 3.12 nötig (gefunden: $("${PYTHON}" --version 2>&1))"

VPY="${VENV}/bin/python"
if [[ ! -x "${VPY}" ]]; then
	log "lege ${VENV} an ($("${PYTHON}" --version 2>&1))"
	"${PYTHON}" -m venv "${VENV}" || die "venv fehlgeschlagen (Ubuntu: apt install python3-venv)"
fi

log "installiere Python-Pakete (exakte Versionen mit Prüfsummen, aus PyPI) …"
"${VPY}" -m pip install --disable-pip-version-check --quiet --require-hashes \
	-r "${ROOT}/requirements/core.lock" -r "${ROOT}/requirements/phone.lock" ||
	die "Paketinstallation fehlgeschlagen (Netzwerk? Python-Version für die Lock-Dateien: 3.12–3.13)"

if [[ ${PJSIP} -eq 1 ]]; then
	log "baue den SIP-Stack (PJSIP, einige Minuten beim ersten Mal) …"
	"${ROOT}/scripts/build-pjsip.sh" --python "${VPY}" --jobs "${JOBS}"
fi
log "Umgebung fertig: ${VENV}"

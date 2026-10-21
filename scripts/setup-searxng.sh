#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# setup-searxng.sh – separate Python environment of the internal SearXNG search worker (ADR-007,
# P1-08): virtual environment plus the pinned packages of requirements/searxng.lock (installed with
# hash checking, granian included). The SearXNG code itself comes unchanged from third_party/searxng.
#
# Idempotent: a fingerprint of the lock file and the Python version decides whether anything is to
# be done. Needs no root; run it as the user that owns the environment.
#
# Usage: scripts/setup-searxng.sh --venv DIR [--python PYTHON] [--force]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=""
PYTHON="${MORITZ_PYTHON:-}"
FORCE=0

log() { printf '[setup-searxng] %s\n' "$*"; }
die() {
	printf '[setup-searxng] FEHLER: %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<USAGE
Usage: $(basename "$0") --venv DIR [--python PYTHON] [--force]

  --venv DIR        Zielverzeichnis der SearXNG-Umgebung (z. B. runtime/searxng-venv)
  --python PYTHON   Interpreter >= 3.12 (Standard: python3.13, python3.12, python3)
  --force           Umgebung auch dann neu installieren, wenn nichts geändert ist
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
	--force)
		FORCE=1
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

LOCK="${ROOT}/requirements/searxng.lock"
[[ -f "${LOCK}" ]] || die "${LOCK} fehlt"
[[ -f "${ROOT}/third_party/searxng/searx/webapp.py" ]] || die "third_party/searxng fehlt (Quellcode von SearXNG)"

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

STAMP="${VENV}/.searxng-hash"
WANT="$({
	cat "${LOCK}"
	"${PYTHON}" --version 2>&1
} | sha256sum | cut -d' ' -f1)"
if [[ ${FORCE} -eq 0 && -x "${VENV}/bin/granian" && -f "${STAMP}" && "$(cat "${STAMP}")" == "${WANT}" ]]; then
	log "SearXNG-Umgebung ist aktuell: ${VENV}"
	exit 0
fi

if [[ ! -x "${VENV}/bin/python" ]]; then
	log "lege ${VENV} an ($("${PYTHON}" --version 2>&1))"
	"${PYTHON}" -m venv "${VENV}" || die "venv fehlgeschlagen (Ubuntu: apt install python3-venv)"
fi
log "installiere die SearXNG-Pakete (exakte Versionen mit Prüfsummen, aus PyPI) …"
"${VENV}/bin/python" -m pip install --disable-pip-version-check --quiet --require-hashes \
	-r "${LOCK}" ||
	die "Paketinstallation fehlgeschlagen (Netzwerk? Python-Version für die Lock-Datei: 3.12–3.13)"
[[ -x "${VENV}/bin/granian" ]] || die "granian fehlt nach der Installation"
printf '%s\n' "${WANT}" >"${STAMP}"
log "SearXNG-Umgebung fertig: ${VENV}"

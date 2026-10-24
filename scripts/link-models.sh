#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# link-models.sh – keep all models in one shared cache (Moritz, 24.10.2026: "das Modell auf
# /home/models … fürs Caching"): DIR/models becomes a link to the cache. Models that are already in
# DIR/models move into the cache (nothing there is overwritten), so nothing is downloaded twice –
# not after unpacking a new version over the old one, not for a second copy, not for the installer.
#
# Usage: scripts/link-models.sh [--cache DIR] [--owner USER] [APP_DIR]
#        cache: $MORITZ_MODELS_DIR or /home/models · APP_DIR: the folder of this script's parent
set -Eeuo pipefail

APP="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${MORITZ_MODELS_DIR:-/home/models}"
OWNER=""

log() { printf '[models] %s\n' "$*"; }
die() {
	printf '[models] FEHLER: %s\n' "$*" >&2
	exit 1
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--cache)
		[[ $# -ge 2 ]] || die "--cache braucht ein Verzeichnis"
		CACHE="$2"
		shift 2
		;;
	--owner)
		[[ $# -ge 2 ]] || die "--owner braucht einen Benutzer"
		OWNER="$2"
		shift 2
		;;
	-h | --help)
		sed -n '3,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
		exit 0
		;;
	-*) die "unbekannte Option: $1" ;;
	*)
		APP="$(cd -- "$1" && pwd)"
		shift
		;;
	esac
done
[[ "${CACHE}" == /* ]] || die "der Cache braucht einen absoluten Pfad (${CACHE})"

mkdir -p "${CACHE}" || die "kann ${CACHE} nicht anlegen (als root ausführen oder MORITZ_MODELS_DIR setzen)"
link="${APP}/models"
if [[ -L "${link}" ]]; then
	if [[ "$(readlink -f "${link}")" == "$(readlink -f "${CACHE}")" ]]; then
		log "models → ${CACHE} (schon verlinkt)"
	else
		ln -sfn "${CACHE}" "${link}"
		log "models → ${CACHE} (Link umgestellt)"
	fi
elif [[ -d "${link}" ]]; then
	if [[ -n "$(ls -A "${link}")" ]]; then
		log "verschiebe vorhandene Modelle nach ${CACHE} (nichts wird überschrieben) …"
		cp -a --update=none "${link}/." "${CACHE}/" 2>/dev/null || cp -a -n "${link}/." "${CACHE}/"
	fi
	rm -rf -- "${link}"
	ln -s "${CACHE}" "${link}"
	log "models → ${CACHE}"
else
	ln -s "${CACHE}" "${link}"
	log "models → ${CACHE}"
fi
if [[ -n "${OWNER}" ]]; then
	chown -R "${OWNER}" "${CACHE}"
fi
# readable for the service user, whoever downloaded
chmod -R a+rX "${CACHE}" 2>/dev/null || true
log "frei im Cache: $(df -h --output=avail "${CACHE}" | tail -1 | tr -d ' ')"

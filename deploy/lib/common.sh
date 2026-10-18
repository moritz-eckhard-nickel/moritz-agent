#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# Shared helpers of install.sh, update.sh, moritz-install.sh and moritz-update.sh (ADR-028).
# This file is sourced, never executed. The sourcing script sets LOG_PREFIX and (for the payload
# functions) works on a source tree that contains deploy/payload.txt.

# Files that must never travel with the code (user data, caches, VCS).
PAYLOAD_EXCLUDES=(
	--exclude='__pycache__'
	--exclude='*.pyc'
	--exclude='.git'
	--exclude='*.egg-info'
	--exclude='.pytest_cache'
	--exclude='.ruff_cache'
	--exclude='config/moritz-agent.toml'
	--exclude='config/*.local.*'
	--exclude='assets/audio/cache'
)

# Test hooks (environment): MORITZ_ALLOW_NON_ROOT=1 skips the root check, MORITZ_SYSTEMD_DIR and
# MORITZ_UNIT_DIR relocate the systemd directories. Production runs never set them.
# shellcheck disable=SC2034 # used by the scripts that source this file
SYSTEMD_RUN_DIR="${MORITZ_SYSTEMD_DIR:-/run/systemd/system}"
# shellcheck disable=SC2034
UNIT_DIR="${MORITZ_UNIT_DIR:-/etc/systemd/system}"

# is_root – true for root (or when the test hook allows running without).
is_root() { [[ ${EUID} -eq 0 || -n "${MORITZ_ALLOW_NON_ROOT:-}" ]]; }

log() { printf '[%s] %s\n' "${LOG_PREFIX:-moritz}" "$*"; }
warn() { printf '[%s] Hinweis: %s\n' "${LOG_PREFIX:-moritz}" "$*" >&2; }
die() {
	local code="$1"
	shift
	printf '[%s] FEHLER: %s\n' "${LOG_PREFIX:-moritz}" "$*" >&2
	exit "${code}"
}

# payload_paths SRC – the paths listed in SRC/deploy/payload.txt, one per line.
payload_paths() {
	local src="$1" line
	[[ -f "${src}/deploy/payload.txt" ]] || return 1
	while IFS= read -r line || [[ -n "${line}" ]]; do
		line="${line%%#*}"
		line="${line//[[:space:]]/}"
		[[ -n "${line}" ]] || continue
		case "${line}" in
		/* | *..*) return 2 ;; # absolute paths and parent references are never valid
		esac
		printf '%s\n' "${line}"
	done <"${src}/deploy/payload.txt"
}

# payload_files SRC – sorted list of the files that belong to the payload (no directories).
payload_files() {
	local src="$1" paths
	mapfile -t paths < <(payload_paths "${src}")
	((${#paths[@]})) || return 1
	(cd "${src}" && tar --create --file /dev/null --verbose "${PAYLOAD_EXCLUDES[@]}" -- "${paths[@]}") |
		grep -v '/$' | LC_ALL=C sort
}

# make_payload SRC OUT.tgz – archive of the payload with neutral ownership.
make_payload() {
	local src="$1" out="$2" paths
	mapfile -t paths < <(payload_paths "${src}")
	((${#paths[@]})) || return 1
	tar --create --gzip --file "${out}" --directory "${src}" \
		--owner=0 --group=0 --numeric-owner "${PAYLOAD_EXCLUDES[@]}" -- "${paths[@]}"
}

# sync_code SRC DST – copy the payload from SRC into DST and remove files that the previous
# payload had but this one no longer has (recorded in DST/data/state/payload-manifest.txt).
sync_code() {
	local src="$1" dst="$2" manifest="$2/data/state/payload-manifest.txt" new old stale path paths
	new="$(mktemp)"
	payload_files "${src}" >"${new}" || {
		rm -f "${new}"
		return 1
	}
	mapfile -t paths < <(payload_paths "${src}")
	mkdir -p "${dst}"
	(cd "${src}" && tar --create --file - "${PAYLOAD_EXCLUDES[@]}" -- "${paths[@]}") |
		tar --extract --file - --directory "${dst}" --same-permissions --overwrite
	if [[ -f "${manifest}" ]]; then
		old="$(mktemp)"
		LC_ALL=C sort "${manifest}" >"${old}"
		stale="$(LC_ALL=C comm -23 "${old}" "${new}")"
		rm -f "${old}"
		while IFS= read -r path; do
			[[ -n "${path}" ]] || continue
			case "${path}" in /* | *..*) continue ;; esac
			rm -f -- "${dst}/${path}"
		done <<<"${stale}"
	fi
	mkdir -p "$(dirname "${manifest}")"
	cp "${new}" "${manifest}"
	rm -f "${new}"
}

# version_of DIR – value of __version__ in DIR/moritz_agent/__init__.py ("unbekannt" if missing).
version_of() {
	local file="$1/moritz_agent/__init__.py" value
	value="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${file}" 2>/dev/null | head -1)"
	printf '%s\n' "${value:-unbekannt}"
}

# -- phone service state ------------------------------------------------------------------------
# phone_status PREFIX – prints "running registration=<state> in_call=<0|1> draining=<0|1>" and
# returns 0 while a live phone service publishes its status (data/run/phone-status.json, see
# moritz_agent/phone/control.py); returns 1 if the service is not running (no/stale/stopped status).
phone_status() {
	python3 - "$1/data/run/phone-status.json" <<'PY'
import json
import sys
import time

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, ValueError):
    sys.exit(1)
if data.get("state") != "running" or time.time() - float(data.get("updated", 0)) > 10:
    sys.exit(1)
print(
    "running registration=%s in_call=%d draining=%d"
    % (data.get("registration") or "unknown", bool(data.get("in_call")), bool(data.get("draining")))
)
PY
}

# drain_start PREFIX / drain_stop PREFIX – new calls get "busy" while the drain file exists.
drain_start() {
	mkdir -p "$1/data/run"
	: >"$1/data/run/drain"
}
drain_stop() { rm -f -- "$1/data/run/drain"; }

# drain_wait PREFIX TIMEOUT – start draining and wait until no call is active.
# Returns 0 when idle (or no live service), 1 when a call is still running after TIMEOUT seconds.
drain_wait() {
	local prefix="$1" timeout="$2" waited=0 state
	drain_start "${prefix}"
	while :; do
		state="$(phone_status "${prefix}")" || return 0
		[[ "${state}" == *"in_call=1"* ]] || return 0
		((waited < timeout)) || return 1
		sleep 2
		waited=$((waited + 2))
	done
}

# wait_running PREFIX TIMEOUT – wait for the service to publish a live status; prints it.
wait_running() {
	local prefix="$1" timeout="$2" waited=0 state
	while :; do
		if state="$(phone_status "${prefix}")"; then
			printf '%s\n' "${state}"
			return 0
		fi
		((waited < timeout)) || return 1
		sleep 2
		waited=$((waited + 2))
	done
}

# guarded FUNCTION [ARGS…] – run in a subshell with errexit active and return its status. (A plain
# "if ! function" would silently disable "set -e" inside the function.)
guarded() {
	local rc=0
	(
		set -Eeuo pipefail
		"$@"
	) &
	wait $! || rc=$?
	return "${rc}"
}

#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# test-clearup.sh – remove everything the test scripts (test-1.sh, test-2.sh, …) put into the
# repository folder: Python environments, the PJSIP build, downloaded models, announcement cache,
# test runs, database/logs under data/, Python and tool caches. passwords.txt and
# config/moritz-agent.toml stay (they hold your own values, e.g. the Discord token).
#
#   ./test-clearup.sh          everything listed above
#   ./test-clearup.sh --venv   only the Python environments (runtime/venv*, runtime/*-venv)
#
# No questions (CLAUDE.md): it shows what it removes and does it. It refuses to run inside an
# installed system (/opt/moritz-agent) – that is moritz-update.sh's business.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\033[1m[test-clearup]\033[0m %s\n' "$*"; }
die() {
	printf '\033[31m[test-clearup] FEHLER:\033[0m %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<'USAGE'
test-clearup.sh – alles entfernen, was die Testskripte angelegt haben

  ./test-clearup.sh          Python-Umgebungen, PJSIP-Build, Modelle, Ansagen-Cache, Testläufe,
                             data/ (Datenbank, Logs), Caches – passwords.txt und config/moritz-agent.toml bleiben
  ./test-clearup.sh --venv   nur die Python-Umgebungen (runtime/venv*, runtime/*-venv)
USAGE
}

only_venv=0
case "${1:-}" in
"") ;;
--venv) only_venv=1 ;;
-h | --help)
	usage
	exit 0
	;;
*)
	usage >&2
	die "unbekannte Option: $1"
	;;
esac

[[ "${ROOT}" != "/opt/moritz-agent" ]] || die "das ist eine Installation (${ROOT}) – hier wird nichts gelöscht"
[[ -f "${ROOT}/moritz_agent/__init__.py" ]] || die "${ROOT} ist kein moritz-agent-Ordner"

targets=()
shopt -s nullglob
targets+=("${ROOT}"/runtime/venv "${ROOT}"/runtime/venv.* "${ROOT}"/runtime/*-venv)
if [[ ${only_venv} -eq 0 ]]; then
	targets=("${ROOT}/runtime" "${ROOT}/models" "${ROOT}/assets/audio/cache" "${ROOT}/data"
		"${ROOT}/.pytest_cache" "${ROOT}/.ruff_cache" "${ROOT}"/*.egg-info)
fi
shopt -u nullglob

removed=0
for target in "${targets[@]}"; do
	[[ -e "${target}" ]] || continue
	log "entferne ${target#"${ROOT}"/} ($(du -sh -- "${target}" 2>/dev/null | cut -f1))"
	rm -rf -- "${target}"
	removed=$((removed + 1))
done
if [[ ${only_venv} -eq 0 ]]; then
	caches="$(find "${ROOT}" -path "${ROOT}/.git" -prune -o -type d -name __pycache__ -print | wc -l)"
	if ((caches > 0)); then
		log "entferne ${caches} __pycache__-Ordner"
		find "${ROOT}" -path "${ROOT}/.git" -prune -o -type d -name __pycache__ -prune -exec rm -rf -- {} +
		removed=$((removed + 1))
	fi
fi

if ((removed == 0)); then
	log "nichts zu tun – schon sauber"
elif [[ ${only_venv} -eq 1 ]]; then
	log "fertig – Python-Umgebungen entfernt (neu: ./test-2.sh setup)"
else
	log "fertig – passwords.txt und config/moritz-agent.toml sind geblieben (neu: ./test-2.sh setup)"
fi

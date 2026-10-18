#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# test-1.sh – Telefon- und Stimmenteil von moritz-agent ausprobieren, ganz ohne Systeminstallation.
#
# Läuft auf jedem Linux-Rechner (Arbeitsplatz, VM, Sophie-1-Konsole, LXC) – es setzt weder einen
# LXC noch Proxmox voraus. Alles landet im Repository-Ordner (runtime/, models/, assets/audio/cache/)
# und lässt sich durch Löschen dieser Ordner wieder entfernen. Es wird kein root gebraucht (nur
# einmalig apt für die Build-Werkzeuge, falls sie fehlen). Der Code, den dieses Skript startet, ist
# derselbe, der später im LXC als Dienst läuft (moritz_agent/phone/, ADR-027); den LXC samt Dienst
# richtet ./install.sh vom Proxmox-Host aus ein (ADR-028).
#
# Aufruf: ./test-1.sh <befehl> [optionen]      (./test-1.sh --help zeigt alles)
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${ROOT}/runtime"
VENV="${RUNTIME}/venv"
VPY="${VENV}/bin/python"
WORK="${RUNTIME}/test-1"
TEST_SIP_PORT="${MORITZ_TEST_SIP_PORT:-5062}"
CALLER_PORT="${MORITZ_TEST_CALLER_PORT:-5070}"

cd "${ROOT}"

log() { printf '\033[1m[test-1]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[test-1] Hinweis:\033[0m %s\n' "$*" >&2; }
die() {
	printf '\033[31m[test-1] FEHLER:\033[0m %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<'USAGE'
test-1.sh – Nikitas Telefon- und Stimmenteil testen (ohne Systeminstallation)

  ./test-1.sh setup [--yes] [--skip-models]
        Richtet alles unter runtime/ und models/ ein: Python-Umgebung, PJSIP (SIP-Stack, wird
        gebaut), Modelle (ca. 0,6 GB: Whisper small + Piper-Stimme „Hessisch“), Konfiguration.
        --yes            Modell-Download ohne Rückfrage
        --skip-models    keine Modelle laden
  ./test-1.sh check [--sip] [--fallback-ok]
        Selbsttest: Umgebung, SIP-Stack, Modelle, Stimmen, Ansagen, Ports (--sip: auch Anmeldung).
  ./test-1.sh speak "Text" [--out datei.wav] [--engine piper|espeak] [--play]
        Einen Satz mit Nikitas Stimme in eine WAV-Datei sprechen.
  ./test-1.sh prompts [--warm-times]
        Alle Ansagen vorrendern und im Cache ablegen (assets/audio/cache/).
  ./test-1.sh bench
        Geschwindigkeit von Spracherkennung und Stimme auf diesem Rechner messen.
  ./test-1.sh call [--quick] ["Satz" …]
        Testanruf ohne Telefonanlage: startet Nikita und ruft sich selbst an (Aufnahme in
        runtime/test-1/anruf.wav). --quick: nur Notstimme + festes Text-Skript, ohne Modelle.
  ./test-1.sh run [--no-register] [--engines …] …
        Nikita starten, bei der Telefonanlage anmelden (passwords.txt, [sip]) und Anrufe annehmen.
  ./test-1.sh models [status|fetch] [--groups stt,piper] [--yes]
        Modell-Download verwalten.

Umgebungsvariablen: MORITZ_PYTHON (Python-Interpreter), MORITZ_JOBS (Build-Prozesse),
MORITZ_TEST_SIP_PORT (Port für „call“, Standard 5062).
Hilfe zu einem Befehl: ./test-1.sh <befehl> --help
USAGE
}

# -- helpers -------------------------------------------------------------------------------------
pick_python() {
	local candidate
	if [[ -n "${MORITZ_PYTHON:-}" ]]; then
		printf '%s\n' "${MORITZ_PYTHON}"
		return
	fi
	for candidate in python3.13 python3.12 python3; do
		if command -v "${candidate}" >/dev/null 2>&1; then
			command -v "${candidate}"
			return
		fi
	done
}

need_env() {
	[[ -x "${VPY}" ]] || die "Die Umgebung fehlt – zuerst ./test-1.sh setup ausführen."
	"${VPY}" -c 'import pjsua2' >/dev/null 2>&1 || die "PJSIP (pjsua2) fehlt in der Umgebung – ./test-1.sh setup ausführen."
}

phone() { PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.phone "$@"; }

check_prereqs() {
	local python="$1" missing_apt=() optional_apt=()
	local pyinc
	"${python}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || die "Python >= 3.12 nötig (gefunden: $("${python}" --version 2>&1))"
	"${python}" -c 'import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)' ||
		warn "Python $("${python}" -c 'import sys; print("%d.%d" % sys.version_info[:2])') ist neuer als die getesteten 3.12–3.13 (MORITZ_PYTHON setzt einen anderen Interpreter)"
	"${python}" -c 'import venv, ensurepip' >/dev/null 2>&1 || missing_apt+=(python3-venv)
	pyinc="$("${python}" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
	[[ -f "${pyinc}/Python.h" ]] || missing_apt+=(python3-dev)
	local tool
	for tool in gcc g++ make; do
		command -v "${tool}" >/dev/null 2>&1 || {
			missing_apt+=(build-essential)
			break
		}
	done
	command -v swig >/dev/null 2>&1 || missing_apt+=(swig)
	command -v pkg-config >/dev/null 2>&1 || missing_apt+=(pkg-config)
	command -v espeak-ng >/dev/null 2>&1 || optional_apt+=(espeak-ng)
	if ((${#optional_apt[@]})); then
		warn "optional (Notstimme und Testanruf): sudo apt install ${optional_apt[*]}"
	fi
	if ((${#missing_apt[@]})); then
		die "fehlende Build-Voraussetzungen – bitte einmalig installieren: sudo apt install ${missing_apt[*]}"
	fi
}

ensure_user_files() {
	if [[ ! -f "${ROOT}/config/moritz-agent.toml" ]]; then
		cp "${ROOT}/config/moritz-agent.example.toml" "${ROOT}/config/moritz-agent.toml"
		log "config/moritz-agent.toml angelegt (Kopie der Beispielkonfiguration)"
	fi
	if [[ ! -f "${ROOT}/passwords.txt" ]]; then
		(
			umask 077
			cp "${ROOT}/config/passwords.template.txt" "${ROOT}/passwords.txt"
		)
		chmod 600 "${ROOT}/passwords.txt"
		log "passwords.txt angelegt (Modus 0600) – trage dort unter [sip] die Zugangsdaten deiner Telefonanlage ein"
	fi
}

# -- setup ---------------------------------------------------------------------------------------
cmd_setup() {
	local assume_yes=0 models=1
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--yes | -y) assume_yes=1 ;;
		--skip-models) models=0 ;;
		-h | --help)
			usage
			return 0
			;;
		*) die "unbekannte Option: $1" ;;
		esac
		shift
	done

	local python jobs="${MORITZ_JOBS:-$(nproc 2>/dev/null || echo 2)}"
	python="$(pick_python)"
	[[ -n "${python}" ]] || die "kein Python gefunden (sudo apt install python3 python3-venv python3-dev)"
	check_prereqs "${python}"

	mkdir -p "${RUNTIME}" "${ROOT}/models"
	"${ROOT}/scripts/setup-env.sh" --venv "${VENV}" --python "${python}" --jobs "${jobs}"
	ensure_user_files

	if [[ ${models} -eq 1 ]]; then
		local fetch_args=(fetch --groups "stt,piper")
		if [[ ${assume_yes} -eq 1 ]]; then fetch_args+=(--yes); fi
		log "lade Modelle (Whisper small, Piper-Stimme Hessisch) von Hugging Face …"
		PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.phone.audio.models "${fetch_args[@]}"
	fi

	log "Einrichtung abgeschlossen. Als Nächstes:"
	printf '  ./test-1.sh check              Selbsttest\n'
	printf '  ./test-1.sh speak "Hallo"      Nikitas Stimme hören\n'
	printf '  ./test-1.sh call               Testanruf ohne Telefonanlage\n'
	printf '  ./test-1.sh run                an der Telefonanlage anmelden (Nummer 999 anrufen)\n'
}

# -- call ----------------------------------------------------------------------------------------
agent_pid=""
stop_agent() {
	if [[ -n "${agent_pid}" ]] && kill -0 "${agent_pid}" 2>/dev/null; then
		kill -TERM "${agent_pid}" 2>/dev/null || true
		local waited=0
		while kill -0 "${agent_pid}" 2>/dev/null && ((waited < 150)); do
			sleep 0.1
			waited=$((waited + 1))
		done
		kill -KILL "${agent_pid}" 2>/dev/null || true
	fi
	agent_pid=""
}

cmd_call() {
	local quick=0 wait_s=1200 engines="" say=()
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--quick) quick=1 ;;
		--wait)
			[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "--wait braucht Sekunden"
			wait_s="$2"
			shift
			;;
		--engines)
			[[ $# -ge 2 ]] || die "--engines braucht eine Liste"
			engines="$2"
			shift
			;;
		-h | --help)
			usage
			return 0
			;;
		-*) die "unbekannte Option: $1" ;;
		*) say+=("$1") ;;
		esac
		shift
	done
	need_env
	command -v espeak-ng >/dev/null 2>&1 || die "Der Test-Anrufer braucht espeak-ng: sudo apt install espeak-ng"
	[[ ${#say[@]} -gt 0 ]] || say=("Wie viel Uhr haben wir?" "Welcher Tag ist heute?" "Tschüss")

	mkdir -p "${WORK}"
	ensure_user_files
	local run_args=(--no-register --allow 127.0.0.1 --sip-port "${TEST_SIP_PORT}")
	if [[ ${quick} -eq 1 ]]; then
		local script
		script="$(printf '%s|' "${say[@]}")"
		run_args+=(--engines espeak --stt "fake:${script%|}")
		log "Schnelltest: Notstimme espeak-ng, Spracherkennung durch festes Skript ersetzt"
	elif [[ -n "${engines}" ]]; then
		run_args+=(--engines "${engines}")
	fi

	trap stop_agent EXIT
	trap 'stop_agent; exit 130' INT TERM
	: >"${WORK}/agent.log"
	log "starte Nikita (Log: ${WORK}/agent.log) …"
	PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.phone run "${run_args[@]}" >"${WORK}/agent.log" 2>&1 &
	agent_pid=$!

	local waited=0
	until grep -q "Nikita ist bereit" "${WORK}/agent.log" 2>/dev/null; do
		kill -0 "${agent_pid}" 2>/dev/null || {
			tail -20 "${WORK}/agent.log" >&2
			die "Nikita ist nicht gestartet (siehe ${WORK}/agent.log)"
		}
		((waited < wait_s)) || die "Nikita ist nach ${wait_s} s nicht bereit (siehe ${WORK}/agent.log)"
		if ((waited > 0 && waited % 30 == 0)); then
			log "warte auf die Stimmen … ($(tail -1 "${WORK}/agent.log" | cut -c1-120))"
		fi
		sleep 1
		waited=$((waited + 1))
	done
	log "Nikita ist bereit nach ${waited} s – rufe an …"

	local say_args=() sentence rc=0
	for sentence in "${say[@]}"; do say_args+=(--say "${sentence}"); done
	PYTHONPATH="${ROOT}" "${VPY}" "${ROOT}/scripts/sip_testcall.py" \
		--to "sip:agent@127.0.0.1:${TEST_SIP_PORT}" --local-port "${CALLER_PORT}" \
		--out "${WORK}/anruf.wav" "${say_args[@]}" >"${WORK}/anrufer.log" 2>&1 || rc=$?
	grep -v '^[0-9][0-9]:[0-9][0-9]:' "${WORK}/anrufer.log" || true # PJSIP's own log lines stay in the file
	stop_agent
	trap - EXIT INT TERM

	log "Aufnahme von Nikitas Antworten: ${WORK}/anruf.wav"
	log "Verlauf des Anrufs: grep -E 'Runde|Anruf' ${WORK}/agent.log"
	return "${rc}"
}

# -- dispatch ------------------------------------------------------------------------------------
main() {
	local command="${1:-help}"
	[[ $# -gt 0 ]] && shift
	case "${command}" in
	setup) cmd_setup "$@" ;;
	check)
		need_env
		phone check "$@"
		;;
	speak)
		need_env
		phone speak "$@"
		;;
	prompts)
		need_env
		phone prompts "$@"
		;;
	bench)
		need_env
		phone bench "$@"
		;;
	call) cmd_call "$@" ;;
	run)
		need_env
		ensure_user_files
		exec env PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.phone run "$@"
		;;
	models)
		need_env
		local sub="status"
		if [[ $# -gt 0 && "$1" != -* ]]; then
			sub="$1"
			shift
		fi
		PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.phone.audio.models "${sub}" "$@"
		;;
	help | -h | --help) usage ;;
	*)
		usage >&2
		die "unbekannter Befehl: ${command}"
		;;
	esac
}

main "$@"

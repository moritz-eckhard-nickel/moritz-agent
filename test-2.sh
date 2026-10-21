#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# test-2.sh – alles, was Anton bis heute kann, in einem Durchgang testen (ohne Systeminstallation).
#
# test-2 umfasst test-1 (Telefon, Stimme) und alles, was danach kam: Sofortauskünfte, Wetter und
# Datendienste, Eieruhr, Discord (Textkanal, Befehle, Sprachnachrichten, Sprachkanal) und den
# kompletten Dienst mit Weboberfläche. Regel (CLAUDE.md): Jede große Erweiterung bekommt ein neues
# test-N.sh mit „setup“ und „run“, das alles Bisherige mit testet. Es gibt keine Ja/Nein-Fragen –
# Downloads laufen ohne Rückfrage; abgefragt werden nur Werte (Token, Kanäle).
#
# Aufruf: ./test-2.sh setup | run [--auto] [--no-call] [--no-discord] [--no-pytest]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${ROOT}/runtime"
VPY="${RUNTIME}/venv/bin/python"
WORK="${RUNTIME}/test-2"
AT="2026-10-21T19:12" # fixed time for the instant answers, so the expected answers never change

cd "${ROOT}"

log() { printf '\033[1m[test-2]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[test-2] Hinweis:\033[0m %s\n' "$*" >&2; }
die() {
	printf '\033[31m[test-2] FEHLER:\033[0m %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<'USAGE'
test-2.sh – alles testen, was Anton bis heute kann (Telefon, Stimme, Sofortauskünfte, Wetter, Discord)

  ./test-2.sh setup [--skip-models]
        Richtet alles ein, ohne Rückfragen: Python-Umgebung, PJSIP, Modelle (ca. 0,6 GB), Konfiguration
        und die Testwerkzeuge. Danach werden nur Werte abgefragt (Enter = überspringen/behalten):
          • Discord-Bot-Token (unsichtbar)
          • Textkanal für Nachrichten (Nummer aus der Liste oder Kanal-ID)
          • Sprachkanal für /joinvc (Nummer aus der Liste oder Kanal-ID)
  ./test-2.sh run [--auto] [--no-call] [--no-discord] [--no-pytest]
        1. Selbsttest (Umgebung, SIP-Stack, Modelle, Stimmen, Ansagen)
        2. Automatische Tests des ganzen Programms (pytest, ca. 4 Minuten)
        3. Sofortauskünfte: Testkorpus (über 800 Sätze) und Beispielfragen aus allen Bereichen
        4. Datendienste (Open-Meteo, Bright Sky, DWD, NINA, Pegel, EZB, …) – braucht Internet
        5. Testanruf mit echter Spracherkennung und Stimme (Uhrzeit, Wetter, Rechnen, Abschied)
        6. Discord: Token, Rechte und Kanäle prüfen, Befehle registrieren, Testnachricht schicken
        7. Live: Anton komplett starten (Telefon + Discord + Weboberfläche) mit Checkliste zum
           Ausprobieren – Strg+C beendet
        --auto        nur 1–6, ohne Live-Teil
        --no-call     ohne Testanruf      --no-discord  ohne Discord      --no-pytest  ohne Schritt 2

Einzelbefehle aus test-1 (speak, ask, call, discord …) gehen weiter mit ./test-1.sh.
USAGE
}

setup_py() { PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.setup "$@"; }
discord() { PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.discord "$@"; }
skills() { PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.skills "$@"; }

has_token() {
	[[ -f "${ROOT}/passwords.txt" ]] &&
		grep -Eq '^[[:space:]]*bot_token[[:space:]]*=[[:space:]]*[^[:space:]]' "${ROOT}/passwords.txt"
}

# ask PROMPT – one line from the terminal into $ANSWER (empty without a terminal)
ask() {
	ANSWER=""
	if [[ -r /dev/tty ]]; then
		read -r -p "$1" ANSWER </dev/tty || ANSWER=""
	fi
}

# -- setup ---------------------------------------------------------------------------------------
setup_discord() {
	if [[ ! -r /dev/tty ]]; then
		warn "kein Terminal – Discord später mit ./test-2.sh setup in einem Terminal einrichten"
		return 0
	fi
	cat <<'HINT'

  Discord (Anleitung: docs/discord-einrichtung.md). Im Developer Portal einmalig: Anwendung „Anton“,
  unter „Bot“: Public Bot AUS, Message Content Intent AN, „Reset Token“ → Token kopieren.
HINT
	local token="" keep="ohne Discord"
	has_token && keep="bisherigen behalten"
	read -r -s -p "  Bot-Token (unsichtbar; Enter = ${keep}): " token </dev/tty || token=""
	printf '\n'
	if [[ -n "${token}" ]]; then
		# the token travels through a pipe only: never as an argument, never in the environment
		if ! printf '%s\n' "${token}" | setup_py discord-token; then
			token=""
			warn "Token nicht übernommen – Discord bleibt, wie es war"
			return 0
		fi
		token=""
	fi
	if ! has_token; then
		log "Discord übersprungen"
		return 0
	fi

	local rc=0
	setup_py discord-channel || rc=$?
	if [[ ${rc} -eq 1 ]]; then
		discord invite || true
		ask "  Anton ist noch auf keinem Server: Server-Link oben öffnen, dann Enter … "
		rc=0
		setup_py discord-channel || rc=$?
	fi
	if [[ ${rc} -eq 3 ]]; then
		ask "  Textkanal für Nachrichten – Nummer oder Kanal-ID (Enter = bisheriger): "
		if [[ -n "${ANSWER}" ]]; then
			printf '%s\n' "${ANSWER}" | setup_py discord-channel --answer || warn "Textkanal nicht gespeichert"
		fi
	fi
	rc=0
	setup_py discord-voice || rc=$?
	if [[ ${rc} -eq 3 ]]; then
		ask "  Sprachkanal für /joinvc – Nummer oder Kanal-ID (Enter = bisheriger/keiner): "
		if [[ -n "${ANSWER}" ]]; then
			printf '%s\n' "${ANSWER}" | setup_py discord-voice --answer || warn "Sprachkanal nicht gespeichert"
		fi
	fi
}

cmd_setup() {
	local args=()
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--skip-models) args+=(--skip-models) ;;
		--yes | -y) ;; # there are no questions – accepted for old habits
		-h | --help)
			usage
			return 0
			;;
		*) die "unbekannte Option: $1" ;;
		esac
		shift
	done
	"${ROOT}/test-1.sh" setup "${args[@]}"
	log "Testwerkzeuge (pytest) in die Umgebung …"
	"${VPY}" -m pip install --quiet --disable-pip-version-check pytest ||
		warn "pytest ließ sich nicht installieren – Schritt 2 von run wird übersprungen"
	setup_py migrate >/dev/null
	setup_discord
	mkdir -p "${WORK}"
	log "Einrichtung fertig. Weiter mit:  ./test-2.sh run"
}

# -- run -----------------------------------------------------------------------------------------
RESULTS=()
FAILED=0

stage() { # stage NAME COMMAND… – run one step, remember ✔/✘
	local name="$1"
	shift
	printf '\n'
	log "── ${name}"
	if "$@"; then
		RESULTS+=("✔ ${name}")
	else
		RESULTS+=("✘ ${name}")
		FAILED=1
	fi
}

skip() { RESULTS+=("– $1 ($2)"); }

# expect QUESTION PART – an instant answer (offline, fixed time) must contain PART
expect() {
	local answer
	answer="$(skills ask "$1" --offline --at "${AT}" 2>&1 | tail -1 | sed 's/^ *//')"
	if [[ "${answer}" == *"$2"* ]]; then
		printf '  ✔ %-42s %s\n' "$1" "${answer}"
	else
		printf '  ✘ %-42s %s   (erwartet: „%s“)\n' "$1" "${answer}" "$2"
		return 1
	fi
}

instant_answers() {
	local wrong=0
	skills corpus || wrong=1
	log "Beispielfragen (Zeitpunkt ${AT}, ohne Netz):"
	expect "Wie spät ist es?" "19 Uhr 12" || wrong=1
	expect "Welcher Tag ist heute?" "Mittwoch" || wrong=1
	expect "Welche Kalenderwoche haben wir?" "43" || wrong=1
	expect "Wie viele Tage bis Weihnachten?" "64 Tage" || wrong=1
	expect "Ist der 3. Oktober ein Feiertag?" "Feiertag in Hessen" || wrong=1
	expect "Wann ist Ostern?" "28. März 2027" || wrong=1
	expect "Wann geht die Sonne unter?" "Uhr" || wrong=1
	expect "Was sind 19 Prozent von 250?" "47,5" || wrong=1
	expect "Was sind 100 Euro plus Mehrwertsteuer?" "119 Euro" || wrong=1
	expect "Was sind minus 40 Grad in Fahrenheit?" "minus 40 Grad Fahrenheit" || wrong=1
	expect "Wo liegt Gießen?" "Hessen" || wrong=1
	expect "Welche Postleitzahl hat Limburg?" "65549" || wrong=1
	expect "Wie weit ist es nach Frankfurt?" "Kilometer" || wrong=1
	expect "Buchstabier Lahn" "L wie Leipzig" || wrong=1
	expect "Stell einen Timer auf 5 Minuten" "5 Minuten" || wrong=1
	expect "Wer bist du?" "Anton" || wrong=1
	return "${wrong}"
}

data_services() {
	local rc=0
	skills providers || rc=$?
	log "Wetter jetzt (aus dem Netz):"
	skills ask "Wie wird das Wetter morgen?" "Gibt es Unwetterwarnungen?" "Wie ist der Pollenflug?" | sed 's/^/  /' || true
	return "${rc}"
}

discord_checks() {
	discord check || return 1
	discord sync-commands || return 1
	discord say "🧪 test-2 läuft – gleich bin ich ganz da. Schreib mir hier etwas oder komm in den Sprachkanal (/joinvc)."
}

live() {
	local web voice=""
	web="$(grep -E '^[[:space:]]*port[[:space:]]*=' config/moritz-agent.toml | head -1 | sed 's/[^0-9]//g')"
	if has_token; then
		voice="$(grep -E '^[[:space:]]*default_channel_id[[:space:]]*=' config/moritz-agent.toml | head -1 | sed 's/[^0-9]//g')"
	fi
	# shellcheck disable=SC1111  # German quotation marks in the text, not shell quotes
	cat <<CHECKLIST

  Live-Test – Anton läuft jetzt komplett (Strg+C beendet). Zum Ausprobieren:
    Telefon     Nebenstelle 999 anrufen (passwords.txt [sip] muss stimmen): „Wie wird das Wetter morgen?“,
                „Stell einen Timer auf eine Minute“, dazwischen reden (Unterbrechen), „Tschüss“
    Weboberfläche  https://<rechner>:${web:-3501}/ (ohne [web]-Login nur auf diesem Rechner)
CHECKLIST
	if has_token; then
		# shellcheck disable=SC1111
		cat <<CHECKLIST
    Discord     im Textkanal: „Wie spät ist es?“, „/wetter“, „/timer 1 min“, „/erinnere“, „/hilfe“
                eine Sprachnachricht schicken → Transkript und Antwort
                Sprachkanal${voice:+ (${voice})}: hineingehen, /joinvc – Begrüßung, Fragen ohne „Anton“, Unterbrechen,
                schweigen (Ruhe-Modus, „Anton“ weckt), „Tschüss“
CHECKLIST
	fi
	printf '\n'
	exec env PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent run
}

cmd_run() {
	local auto=0 call=1 with_discord=1 pytest=1
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--auto) auto=1 ;;
		--no-call) call=0 ;;
		--no-discord) with_discord=0 ;;
		--no-pytest) pytest=0 ;;
		-h | --help)
			usage
			return 0
			;;
		*) die "unbekannte Option: $1" ;;
		esac
		shift
	done
	[[ -x "${VPY}" ]] || die "Die Umgebung fehlt – zuerst ./test-2.sh setup ausführen."
	mkdir -p "${WORK}"
	setup_py migrate >/dev/null

	stage "Selbsttest" "${ROOT}/test-1.sh" check
	if [[ ${pytest} -eq 1 ]] && "${VPY}" -m pytest --version >/dev/null 2>&1; then
		stage "Automatische Tests (pytest)" env PYTHONPATH="${ROOT}" "${VPY}" -m pytest -q -p no:cacheprovider
	else
		skip "Automatische Tests (pytest)" "abgeschaltet oder pytest fehlt"
	fi
	stage "Sofortauskünfte" instant_answers
	stage "Datendienste (Internet)" data_services
	if [[ ${call} -eq 0 ]]; then
		skip "Testanruf" "--no-call"
	elif ! command -v espeak-ng >/dev/null 2>&1; then
		skip "Testanruf" "espeak-ng fehlt: sudo apt install espeak-ng"
	else
		stage "Testanruf" "${ROOT}/test-1.sh" call \
			"Wie spät ist es?" "Wie wird das Wetter morgen?" "Was sind neunzehn Prozent von zweihundertfünfzig?" "Tschüss"
	fi
	if [[ ${with_discord} -eq 0 ]]; then
		skip "Discord" "--no-discord"
	elif ! has_token; then
		skip "Discord" "kein Token – ./test-2.sh setup"
	else
		stage "Discord" discord_checks
	fi

	printf '\n'
	log "Ergebnis:"
	printf '  %s\n' "${RESULTS[@]}" | tee "${WORK}/ergebnis.txt"
	if [[ ${auto} -eq 1 ]]; then
		return "${FAILED}"
	fi
	[[ ${FAILED} -eq 0 ]] || warn "nicht alles grün (siehe oben) – der Live-Test startet trotzdem"
	live
}

# -- dispatch ------------------------------------------------------------------------------------
main() {
	local command="${1:-help}"
	[[ $# -gt 0 ]] && shift
	case "${command}" in
	setup) cmd_setup "$@" ;;
	run) cmd_run "$@" ;;
	help | -h | --help) usage ;;
	*)
		usage >&2
		die "unbekannter Befehl: ${command}"
		;;
	esac
}

main "$@"

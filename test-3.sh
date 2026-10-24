#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# test-3.sh – Part 1 komplett auf Sophie-1, bare metal (ADR-039): alles aus test-2 plus das
# Sprachmodell (KoboldCpp + Qwen3, Ticket P1-02) und das Zuhören im Discord-Sprachkanal (P1-32).
#
# Regel (CLAUDE.md): Jede große Erweiterung bekommt ein neues test-N.sh mit „setup“ und „run“, das
# alles Bisherige mit testet – test-3 ruft test-2 auf, statt es zu kopieren. Keine Ja/Nein-Fragen:
# Downloads und Builds laufen ohne Rückfrage. Alle Modelle liegen im gemeinsamen Cache /home/models
# (models/ ist nur ein Link darauf), damit nichts zweimal geladen wird.
#
# Aufruf: ./test-3.sh setup [Optionen] | run [Optionen] | live
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${ROOT}/runtime"
VPY="${RUNTIME}/venv/bin/python"
WORK="${RUNTIME}/test-3"
MODELS_DIR="${MORITZ_MODELS_DIR:-/home/models}"

cd "${ROOT}"

log() { printf '\033[1m[test-3]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[test-3] Hinweis:\033[0m %s\n' "$*" >&2; }
die() {
	printf '\033[31m[test-3] FEHLER:\033[0m %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<'USAGE'
test-3.sh – Part 1 komplett: alles aus test-2 plus Sprachmodell und Zuhören im Sprachkanal

  ./test-3.sh setup [--models-dir DIR] [--no-fallback] [--cpu] [--rebuild] [--no-voice-recv] [--skip-models]
        1. Modell-Cache: models/ → /home/models (vorhandene Modelle ziehen mit um)
        2. alles aus test-2 setup (Python, PJSIP, Stimme, Konfiguration, Discord-Werte)
        3. Sprachmodell Qwen3-30B-A3B (≈ 13,8 GB) und die Ersatzmodelle aus ADR-016 (≈ 41 GB, nur
           wenn genug Platz ist) nach /home/models
        4. KoboldCpp bauen (beim ersten Mal 15–40 Minuten, danach nur bei geänderten Quellen)
        5. Zuhören im Discord-Sprachkanal: eigene Umgebung runtime/discord-venv (P1-32)
        --models-dir DIR  anderer Cache statt /home/models      --no-fallback  nur das Hauptmodell
        --cpu             ohne NVIDIA-GPU bauen (sehr langsam)  --rebuild      KoboldCpp neu bauen
        --no-voice-recv   kein Zuhören im Sprachkanal           --skip-models  nichts herunterladen
  ./test-3.sh run [--auto] [--no-tune] [--no-call] [--no-discord] [--no-pytest]
        1. alles aus test-2 run --auto (Selbsttest, pytest, Sofortauskünfte, Daten, Testanruf, Discord)
        2. Sprachmodell: KoboldCpp gebaut, Modell da, GPU sichtbar
        3. Sprachmodell: --moecpu einstellen (≥ 600 MB VRAM frei) und 40 Telefonfragen messen
        4. Zuhören im Sprachkanal: Umgebung prüfen
        5. Abnahmeprotokoll schreiben: runtime/test-3/abnahme.md
        6. Live: Anton komplett starten, jetzt mit Sprachmodell – Checkliste abhaken, Strg+C beendet
        --auto  nur 1–5      --no-tune  --moecpu nicht neu suchen (nur messen)
  ./test-3.sh live
        nur Schritt 6
USAGE
}

setup_py() { PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.setup "$@"; }

# record NAME – everything from here on also goes to runtime/test-3/NAME.log (the whole run, for
# sending it along when something fails). Secrets never reach the terminal, so not the file either.
record() {
	mkdir -p "${WORK}"
	local file="${WORK}/$1.log"
	: >"${file}"
	exec > >(tee -a "${file}") 2>&1
	log "Mitschrift: ${file} ($(date '+%d.%m.%Y %H:%M'))"
}
models() { PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.phone.audio.models "$@"; }

# -- setup ---------------------------------------------------------------------------------------
cmd_setup() {
	local fallback=1 voice_recv=1 skip_models=0 kcpp=()
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--models-dir)
			[[ $# -ge 2 ]] || die "--models-dir braucht ein Verzeichnis"
			MODELS_DIR="$2"
			shift
			;;
		--no-fallback) fallback=0 ;;
		--cpu) kcpp+=(--cpu) ;;
		--rebuild) kcpp+=(--rebuild) ;;
		--no-voice-recv) voice_recv=0 ;;
		--skip-models) skip_models=1 ;;
		--yes | -y) ;; # there are no questions – accepted for old habits
		-h | --help)
			usage
			return 0
			;;
		*) die "unbekannte Option: $1" ;;
		esac
		shift
	done

	record setup
	log "── 1. Modell-Cache ${MODELS_DIR}"
	"${ROOT}/scripts/link-models.sh" --cache "${MODELS_DIR}" "${ROOT}"

	log "── 2. alles aus test-2"
	local t2=()
	[[ ${skip_models} -eq 0 ]] || t2+=(--skip-models)
	"${ROOT}/test-2.sh" setup "${t2[@]}"

	if [[ ${skip_models} -eq 0 ]]; then
		log "── 3. Sprachmodell (Hugging Face, ohne Rückfrage; abgebrochene Downloads laufen weiter)"
		models fetch --groups llm || die "Sprachmodell nicht geladen (Netz? Platz in ${MODELS_DIR}?)"
		if [[ ${fallback} -eq 1 ]]; then
			models fetch --groups llm-fallback --if-space || warn "Ersatzmodelle nicht (vollständig) geladen – kein Problem"
		fi
	else
		log "── 3. Modelle übersprungen (--skip-models)"
	fi

	log "── 4. KoboldCpp"
	local rc=0
	"${ROOT}/scripts/setup-koboldcpp.sh" "${kcpp[@]}" || rc=$?
	if [[ ${rc} -eq 3 ]]; then
		die "ohne NVIDIA-Treiber kein GPU-Build – Treiber installieren (docs/sophie-1-bare-metal.md) oder --cpu"
	elif [[ ${rc} -ne 0 ]]; then
		die "KoboldCpp ließ sich nicht bauen (Ausgabe oben)"
	fi

	if [[ ${voice_recv} -eq 1 ]]; then
		log "── 5. Zuhören im Discord-Sprachkanal"
		"${ROOT}/scripts/setup-discord-voice.sh" ||
			warn "Zuhören nicht eingerichtet – im Sprachkanal spricht Anton nur (Textnachrichten liest er vor)"
	else
		log "── 5. Zuhören im Sprachkanal übersprungen (--no-voice-recv)"
	fi
	mkdir -p "${WORK}"
	log "Einrichtung fertig. Weiter mit:  ./test-3.sh run"
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

llm_ready() {
	local rc=0
	PYTHONPATH="${ROOT}" "${VPY}" - <<'PY' || rc=$?
import sys
from pathlib import Path

from moritz_agent.config.settings import REPO_ROOT, load_settings
from moritz_agent.inference.process import koboldcpp_built, koboldcpp_python

settings = load_settings()
model = settings.resolve(settings.inference.model, REPO_ROOT)
ok = True
for label, good, detail in [
    ("Modell", model.is_file(), f"{model} ({model.stat().st_size / 1e9:.1f} GB)" if model.is_file() else f"{model} fehlt"),
    ("KoboldCpp gebaut", koboldcpp_built(settings, REPO_ROOT), "GPU" if settings.inference.use_cuda else "nur CPU"),
    ("Python für KoboldCpp", Path(koboldcpp_python(settings, REPO_ROOT)).exists(), koboldcpp_python(settings, REPO_ROOT)),
]:
    print(f"  {'✔' if good else '✘'} {label:22s} {detail}")
    ok = ok and good
sys.exit(0 if ok else 1)
PY
	if command -v nvidia-smi >/dev/null 2>&1; then
		printf '  ✔ %-22s %s\n' "GPU" "$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -1)"
	else
		printf '  – %-22s %s\n' "GPU" "keine (nvidia-smi fehlt)"
	fi
	return "${rc}"
}

llm_bench() {
	local args=(--out "${WORK}")
	[[ "${1:-1}" -eq 1 ]] && args+=(--tune)
	PYTHONPATH="${ROOT}" "${VPY}" "${ROOT}/scripts/bench_llm.py" "${args[@]}"
}

voice_recv() {
	local venv="${RUNTIME}/discord-venv"
	if [[ ! -f "${venv}/.moritz-voice" ]]; then
		printf '  ✘ runtime/discord-venv fehlt – ./test-3.sh setup (oder bewusst --no-voice-recv)\n'
		return 1
	fi
	if [[ -f "${venv}/.moritz-unstable" ]]; then
		printf '  ✘ abgeschaltet seit %s: die Verbindung zu Discord brach mit dem Fork immer wieder ab\n' "$(cat "${venv}/.moritz-unstable")"
		printf '    (Log: grep -E "discord.gateway|Verbindung verloren" runtime/test-3/run.log) – wieder an: ./test-3.sh setup\n'
		return 1
	fi
	"${venv}/bin/python" -c 'import davey, discord, discord.ext.voice_recv; print("  ✔ discord.py", discord.__version__, "mit DAVE-Empfang (voice_recv)")'
}

protocol() { # writes runtime/test-3/abnahme.md from the results of test-2 and test-3
	local out="${WORK}/abnahme.md" bench="${WORK}/llm-bench.json"
	{
		printf '# Abnahme Part 1 – Protokoll\n\n'
		printf 'Abnahme heißt: auf Sophie-1 nachweisen, dass Part 1 wirklich geht. Was ein Skript prüfen\n'
		printf 'kann, ist unten schon eingetragen. Den Live-Teil probierst du aus und hakst ab ([x]); dann\n'
		printf 'ist das Ticket erledigt (P1-02, P1-18, P1-30, P1-32, P1-42).\n\n'
		printf -- '- Datum: %s\n- Rechner: %s (%s)\n- Version: %s\n' "$(date '+%d.%m.%Y %H:%M')" \
			"$(hostname)" "$(uname -r)" "$(PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent --version 2>/dev/null || echo ?)"
		if command -v nvidia-smi >/dev/null 2>&1; then
			printf -- '- GPU: %s\n' "$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -1)"
		fi
		printf '\n## Automatisch geprüft\n\n'
		if [[ -f "${RUNTIME}/test-2/ergebnis.txt" ]]; then
			sed 's/^ *//; s/^/- /' "${RUNTIME}/test-2/ergebnis.txt"
		fi
		printf -- '- %s\n' "${RESULTS[@]}"
		if [[ -f "${bench}" ]]; then
			"${VPY}" - "${bench}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
s = data["summary"]
print(f"\n## Sprachmodell (P1-02)\n\n- Modell: `{data['model']}`, `--moecpu {data['moe_cpu_layers']}`")
for load in data["loads"]:
    if load["ready"]:
        print(f"- `--moecpu {load['moe_cpu_layers']}`: VRAM {load['vram_used_mb']}/{load['vram_total_mb']} MB (frei {load['vram_free_mb']}), RAM {load['ram_mb']} MB")
print(f"- 40 Telefonfragen: beantwortet {s['answered']}/{s['questions']}, richtiges Werkzeug {s['tool_ok']}/{s['tool_questions']}")
print(f"- erste Worte nach {s['median_first_ms']} ms, ganze Antwort {s['median_total_ms']} ms (Median), {s['median_tokens_per_s']} Tokens/s")
print("- Einzelwerte: runtime/test-3/llm-bench.md")
PY
		fi
		cat <<'LIVE'

## Live – zum Abhaken

Telefon (P1-18)
- [ ] 999 anrufen: Begrüßung kommt, „Wie spät ist es?“ stimmt auf die Minute
- [ ] eine Frage ans Sprachmodell („Erklär mir kurz, was ein Schaltjahr ist“) – Antwort in wenigen Sekunden
- [ ] eine Suchfrage („Wer ist gerade Bundeskanzler?“) – Antwort mit aktueller Info
- [ ] dazwischenreden unterbricht Anton; „Leg auf“ beendet höflich
- [ ] drei Runden hintereinander ohne Hänger

Sofortauskünfte (P1-30)
- [ ] Wetter morgen, Unwetterwarnungen, Pollen für Weilburg klingen plausibel
- [ ] Aussprache: Weilburg, Limburg, Lahn, Guude klingen richtig (Hörtest P1-29)

Discord (P1-42)
- [ ] im Textkanal eine freie Frage → Antwort vom Sprachmodell
- [ ] Sprachnachricht → Transkript und Antwort
- [ ] Rückruf: „Sag mir am Telefon, wie viel Uhr es ist“ → die 201 klingelt

Sprachkanal (P1-32)
- [ ] /joinvc → Anton sagt hallo
- [ ] Anton hört zu: eine Frage sprechen (ohne „Anton“) → er antwortet laut
- [ ] 10 Minuten im Kanal bleiben ohne Abbruch

Unterschrift: ____________________
LIVE
	} >"${out}"
	log "Abnahmeprotokoll: ${out}"
}

live() {
	if [[ -f "${WORK}/llm-bench.json" ]]; then
		# shellcheck disable=SC1111  # German quotation marks in the text, not shell quotes
		cat <<'CHECKLIST'

  Neu mit test-3 – das Sprachmodell läuft mit:
    Telefon     eine freie Frage: „Erklär mir kurz, was ein Schaltjahr ist“, „Wer ist gerade Bundeskanzler?“
    Discord     im Textkanal frei fragen; im Sprachkanal (/joinvc) einfach losreden – Anton hört zu
    Protokoll   runtime/test-3/abnahme.md – dort den Live-Teil abhaken
CHECKLIST
	fi
	exec "${ROOT}/test-2.sh" live
}

cmd_run() {
	local auto=0 tune=1 t2=()
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--auto) auto=1 ;;
		--no-tune) tune=0 ;;
		--no-call | --no-discord | --no-pytest) t2+=("$1") ;;
		-h | --help)
			usage
			return 0
			;;
		*) die "unbekannte Option: $1" ;;
		esac
		shift
	done
	[[ -x "${VPY}" ]] || die "Die Umgebung fehlt – zuerst ./test-3.sh setup ausführen."
	record run

	stage "Alles aus test-2" "${ROOT}/test-2.sh" run --auto "${t2[@]}"
	stage "Sprachmodell: bereit" llm_ready
	if [[ ${RESULTS[-1]} == ✔* ]]; then
		stage "Sprachmodell: --moecpu und 40 Telefonfragen" llm_bench "${tune}"
	else
		skip "Sprachmodell: Messung" "nicht bereit – ./test-3.sh setup"
	fi
	if [[ -d "${RUNTIME}/discord-venv" ]]; then
		stage "Zuhören im Sprachkanal (DAVE)" voice_recv
	else
		skip "Zuhören im Sprachkanal" "nicht eingerichtet (./test-3.sh setup)"
	fi

	printf '\n'
	log "Ergebnis:"
	printf '  %s\n' "${RESULTS[@]}" | tee "${WORK}/ergebnis.txt"
	protocol
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
	live)
		[[ -x "${VPY}" ]] || die "Die Umgebung fehlt – zuerst ./test-3.sh setup ausführen."
		live
		;;
	help | -h | --help) usage ;;
	*)
		usage >&2
		die "unbekannter Befehl: ${command}"
		;;
	esac
}

main "$@"

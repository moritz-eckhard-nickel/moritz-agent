#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# setup-koboldcpp.sh – build KoboldCpp (the language model engine, ADR-003/ADR-015, ticket P1-02)
# right here, bare metal on Sophie-1 (ADR-039), and say whether it uses the GPU.
#
# First time: ./koboldcpp.sh rebuild (upstream script: micromamba environment with the CUDA toolkit
# from conda under conda/, then make). After that only `make` runs again, and only when the C/C++
# sources changed (fingerprint in conda/.moritz-build) – a new version unpacked over the old one
# builds nothing if the engine is the same. Without an NVIDIA GPU (no nvidia-smi) it builds the CPU
# library with the system compiler and switches [inference] use_cuda off.
#
# Usage: scripts/setup-koboldcpp.sh [--rebuild] [--cpu] [--jobs N]
# Exit:  0 built or up to date · 1 build failed · 3 NVIDIA driver missing (and --cpu not given)
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VPY="${ROOT}/runtime/venv/bin/python"
JOBS="${MORITZ_JOBS:-$(nproc 2>/dev/null || echo 2)}"
MAMBA="${ROOT}/bin/micromamba"
ENV_PREFIX="${ROOT}/conda/envs/linux"
STAMP="${ROOT}/conda/.moritz-build"

log() { printf '[koboldcpp] %s\n' "$*"; }
warn() { printf '[koboldcpp] Hinweis: %s\n' "$*" >&2; }
die() {
	printf '[koboldcpp] FEHLER: %s\n' "$2" >&2
	exit "$1"
}

rebuild=0 cpu=0
while [[ $# -gt 0 ]]; do
	case "$1" in
	--rebuild) rebuild=1 ;;
	--cpu) cpu=1 ;;
	--jobs)
		[[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die 2 "--jobs braucht eine Zahl"
		JOBS="$2"
		shift
		;;
	-h | --help)
		sed -n '3,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
		exit 0
		;;
	*) die 2 "unbekannte Option: $1" ;;
	esac
	shift
done

config_set() {
	[[ -x "${VPY}" ]] || return 0
	PYTHONPATH="${ROOT}" "${VPY}" -m moritz_agent.setup config-set inference "$1" "$2" >/dev/null ||
		warn "konnte [inference] $1 nicht setzen"
}

gpu=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -qE '^GPU [0-9]+:'; then
	gpu=1
	log "GPU: $(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | head -1)"
elif [[ ${cpu} -eq 0 ]]; then
	die 3 "keine NVIDIA-GPU sichtbar (nvidia-smi fehlt oder findet nichts). Erst den Treiber installieren
           (docs/plan/06-infrastruktur.md §4.1, bare metal: apt install nvidia-driver, Neustart) –
           oder mit --cpu nur für die CPU bauen (sehr langsam)."
else
	warn "ohne GPU: KoboldCpp läuft nur auf der CPU (langsam)"
fi

# fingerprint of everything that goes into the engine (names and contents of the C/C++ sources)
fingerprint() {
	{
		printf 'gpu=%s\n' "${gpu}"
		(cd "${ROOT}" && find Makefile ggml src otherarch common include tools vendor kcpp_src \
			-type f \( -name '*.c' -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' -o -name '*.cu' \
			-o -name '*.cuh' -o -name '*.comp' -o -name 'Makefile' -o -name '*.mk' \) -print0 2>/dev/null |
			sort -z | xargs -0 sha256sum)
	} | sha256sum | cut -d' ' -f1
}

library="koboldcpp_cublas.so"
[[ ${gpu} -eq 1 ]] || library="koboldcpp_default.so"
current="$(fingerprint)"
if [[ ${rebuild} -eq 0 && -f "${ROOT}/${library}" && -f "${STAMP}" && "$(cat "${STAMP}")" == "${current}" ]]; then
	log "KoboldCpp ist gebaut und unverändert (${library}) – nichts zu tun"
else
	started=${SECONDS}
	mkdir -p "${ROOT}/conda"
	rm -f "${STAMP}"
	if [[ ${gpu} -eq 0 ]]; then
		if ! command -v make >/dev/null 2>&1 || ! command -v g++ >/dev/null 2>&1; then
			die 1 "Compiler fehlt: apt install build-essential"
		fi
		log "baue die CPU-Bibliothek (einige Minuten) …"
		make -C "${ROOT}" -j "${JOBS}" koboldcpp_default >/dev/null || die 1 "make fehlgeschlagen"
	elif [[ ${rebuild} -eq 1 || ! -x "${ENV_PREFIX}/bin/python" || ! -f "${ENV_PREFIX}/cudaver" || ! -x "${MAMBA}" ]]; then
		if ! command -v curl >/dev/null 2>&1 || ! command -v bzip2 >/dev/null 2>&1; then
			die 1 "curl und bzip2 nötig: apt install curl bzip2"
		fi
		log "erster Build: Umgebung mit CUDA-Toolkit (≈ 6–10 GB) und KoboldCpp – dauert 15–40 Minuten …"
		(cd "${ROOT}" && ./koboldcpp.sh rebuild) || die 1 "./koboldcpp.sh rebuild fehlgeschlagen (Ausgabe oben)"
	else
		log "Quellen geändert – baue KoboldCpp neu (die CUDA-Umgebung bleibt) …"
		"${MAMBA}" run -r "${ROOT}/conda" -p "${ENV_PREFIX}" make -C "${ROOT}" -j "${JOBS}" \
			LLAMA_CUBLAS=1 LLAMA_USE_BUNDLED_GLSLC=1 LLAMA_ADD_CONDA_PATHS=1 || die 1 "make fehlgeschlagen"
	fi
	[[ -f "${ROOT}/${library}" ]] || die 1 "${library} fehlt nach dem Build"
	printf '%s\n' "${current}" >"${STAMP}"
	log "gebaut in $(((SECONDS - started) / 60)) min: ${library}"
fi

if [[ ${gpu} -eq 1 ]]; then
	config_set use_cuda true
else
	config_set use_cuda false
fi

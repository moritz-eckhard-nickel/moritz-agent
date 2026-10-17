#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# setup-tts-venv.sh – create runtime/venv-tts, the environment of the CosyVoice worker
# (voice "Nikita", Thorsten-Voice CosyVoice3 Hessisch, ADR-027).
#
# torch / torchaudio come from the PyTorch CPU index (small CPU-only wheels, no NVIDIA
# libraries); everything else is installed from PyPI with the exact versions of
# requirements/tts.txt. Needs no root and does not touch the system.
#
# Usage: scripts/setup-tts-venv.sh [--python PYTHON] [--venv DIR] [--force]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/runtime/venv-tts"
PYTHON=""
FORCE=0
TORCH_VERSION="2.10.0"
TORCH_INDEX="${MORITZ_TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"

log() { printf '[tts-venv] %s\n' "$*"; }
die() {
	printf '[tts-venv] FEHLER: %s\n' "$*" >&2
	exit 1
}

usage() {
	cat <<USAGE
Usage: $(basename "$0") [--python PYTHON] [--venv DIR] [--force]

  --python PYTHON   Python >= 3.12 (Standard: python3.13, python3.12, python3)
  --venv DIR        Zielverzeichnis (Standard: runtime/venv-tts)
  --force           Umgebung löschen und neu anlegen
USAGE
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--python)
		[[ $# -ge 2 ]] || die "--python braucht einen Pfad"
		PYTHON="$2"
		shift 2
		;;
	--venv)
		[[ $# -ge 2 ]] || die "--venv braucht einen Pfad"
		VENV="$2"
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

if [[ -z "${PYTHON}" ]]; then
	for candidate in python3.13 python3.12 python3; do
		if command -v "${candidate}" >/dev/null 2>&1; then
			PYTHON="$(command -v "${candidate}")"
			break
		fi
	done
fi
[[ -n "${PYTHON}" && -x "${PYTHON}" ]] || die "kein Python gefunden (Ubuntu: apt install python3 python3-venv)"
"${PYTHON}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || die "Python >= 3.12 nötig: ${PYTHON}"
PYVER="$("${PYTHON}" -c 'import sys; print("cp%d%d" % sys.version_info[:2])')"
STAMP="${VENV}/.setup-complete-${TORCH_VERSION}-${PYVER}"

if [[ ${FORCE} -eq 0 && -f "${STAMP}" ]]; then
	log "Umgebung ${VENV} ist bereits eingerichtet (--force baut sie neu)."
	exit 0
fi

if [[ ${FORCE} -eq 1 && -d "${VENV}" ]]; then
	case "${VENV}" in
	"${ROOT}"/runtime/*) rm -rf -- "${VENV}" ;;
	*) die "--force löscht nur Verzeichnisse unter ${ROOT}/runtime/ (angegeben: ${VENV})" ;;
	esac
fi

if [[ ! -x "${VENV}/bin/python" ]]; then
	log "lege ${VENV} an ($("${PYTHON}" --version 2>&1))"
	"${PYTHON}" -m venv "${VENV}" || die "venv fehlgeschlagen (Ubuntu: apt install python3-venv)"
fi
VPY="${VENV}/bin/python"

# 1. torch + torchaudio, CPU only, from the PyTorch index (--no-deps: the pure-Python
#    dependencies are pinned in requirements/tts.txt).
log "installiere torch ${TORCH_VERSION} (CPU) von ${TORCH_INDEX} …"
"${VPY}" -m pip install --disable-pip-version-check --quiet --no-deps \
	--index-url "${TORCH_INDEX}" "torch==${TORCH_VERSION}" "torchaudio==${TORCH_VERSION}" ||
	die "torch ließ sich nicht von ${TORCH_INDEX} laden (Netzwerk? Proxy? – MORITZ_TORCH_INDEX setzt einen anderen Index)"

# 2. everything else with exact versions.
log "installiere die übrigen Pakete (requirements/tts.txt) …"
"${VPY}" -m pip install --disable-pip-version-check --quiet --no-deps -r "${ROOT}/requirements/tts.txt" ||
	die "Paketinstallation fehlgeschlagen"

# 3. smoke test: CPU build, the packages the worker imports first.
log "prüfe die Umgebung …"
"${VPY}" - <<'PYCHECK' || die "Import-Test fehlgeschlagen – die Umgebung ist unvollständig"
import importlib
import sys

import torch

if torch.version.cuda is not None:
    sys.exit("torch hat CUDA-Unterstützung – erwartet wird der CPU-Build")
for name in ("torchaudio", "transformers", "diffusers", "conformer", "hyperpyyaml", "onnxruntime", "librosa",
             "soundfile", "omegaconf", "hydra", "inflect", "x_transformers", "huggingface_hub"):
    importlib.import_module(name)
print(f"torch {torch.__version__}, Python {sys.version.split()[0]}: ok")
PYCHECK

: >"${STAMP}"
log "fertig: ${VENV}"

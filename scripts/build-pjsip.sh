#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# build-pjsip.sh – build pjproject (third_party/pjproject) and install the PJSUA2 Python
# binding into a virtual environment (ADR-005, ticket P1-11/P1-15).
#
# The vendored source tree is never modified: it is copied to runtime/pjsip-build/ first.
# Needs: gcc/g++/make, swig >= 4.0, pkg-config, Python headers for the target python
# (Ubuntu: apt install build-essential swig python3-dev pkg-config libssl-dev).
#
# Usage: scripts/build-pjsip.sh --python runtime/venv/bin/python [--jobs N] [--force]
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON=""
JOBS="$(nproc 2>/dev/null || echo 2)"
FORCE=0

usage() {
	cat <<USAGE
Usage: $(basename "$0") --python PYTHON [--jobs N] [--force]

  --python PYTHON   interpreter of the virtual environment that receives pjsua2
  --jobs N          parallel make jobs (default: number of CPUs)
  --force           rebuild even if an up-to-date build exists
USAGE
}

log() { printf '[build-pjsip] %s\n' "$*"; }
die() {
	printf '[build-pjsip] FEHLER: %s\n' "$*" >&2
	exit 1
}

while [[ $# -gt 0 ]]; do
	case "$1" in
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

[[ -n "${PYTHON}" ]] || {
	usage >&2
	die "--python fehlt"
}
PYTHON="$(cd -- "$(dirname -- "${PYTHON}")" && pwd)/$(basename -- "${PYTHON}")"
[[ -x "${PYTHON}" ]] || die "Python nicht gefunden: ${PYTHON}"

missing=()
for tool in gcc g++ make swig pkg-config; do
	command -v "${tool}" >/dev/null 2>&1 || missing+=("${tool}")
done
if ((${#missing[@]})); then
	die "fehlende Werkzeuge: ${missing[*]} – Ubuntu: sudo apt install build-essential swig pkg-config python3-dev libssl-dev"
fi
py_include="$("${PYTHON}" -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
[[ -f "${py_include}/Python.h" ]] || die "Python.h fehlt in ${py_include} – Ubuntu: sudo apt install python3-dev"

SRC="${ROOT}/third_party/pjproject"
BUILD_ROOT="${ROOT}/runtime/pjsip-build"
BUILD="${BUILD_ROOT}/pjproject"
py_tag="$("${PYTHON}" -c 'import sys; print("cp%d%d" % sys.version_info[:2])')"
version="$(sed -n 's/^export PJ_VERSION_MAJOR[[:space:]]*:\?=[[:space:]]*//p' "${SRC}/version.mak" | head -1).$(sed -n 's/^export PJ_VERSION_MINOR[[:space:]]*:\?=[[:space:]]*//p' "${SRC}/version.mak" | head -1)"
STAMP="${BUILD_ROOT}/.built-pjsip-${version}-${py_tag}"
site="$("${PYTHON}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"

if [[ "${FORCE}" -eq 0 && -f "${STAMP}" && -f "${site}/pjsua2.py" ]] && ls "${site}"/_pjsua2*.so >/dev/null 2>&1; then
	log "pjsua2 ${version} (${py_tag}) ist bereits gebaut und installiert – nichts zu tun (--force erzwingt Neubau)."
	exit 0
fi

# setuptools is needed by the binding's setup.py (distutils is gone in Python >= 3.12).
"${PYTHON}" -m pip install --quiet --disable-pip-version-check setuptools wheel

mkdir -p "${BUILD_ROOT}"
if [[ ! -f "${BUILD}/.copied-from-vendor" || "${FORCE}" -eq 1 ]]; then
	log "kopiere Quellcode nach ${BUILD} (Original bleibt unverändert)"
	rm -rf "${BUILD:?}"
	cp -a "${SRC}" "${BUILD}"
	touch "${BUILD}/.copied-from-vendor"
fi

cd "${BUILD}"
if [[ ! -f build.mak ]]; then
	log "configure (nur G.711/G.722, kein Video, kein Sound-Gerät, -fPIC)"
	CFLAGS="-O2 -fPIC" CXXFLAGS="-O2 -fPIC" ./configure \
		--disable-video --disable-sound \
		--disable-opencore-amr --disable-silk --disable-opus --disable-bcg729 \
		--disable-gsm-codec --disable-speex-codec --disable-speex-aec \
		--disable-ilbc-codec --disable-l16-codec --disable-g7221-codec \
		--disable-libyuv --disable-libwebrtc --disable-sdl --disable-ffmpeg \
		--disable-v4l2 --disable-openh264 --disable-vpx --disable-upnp \
		>"${BUILD_ROOT}/configure.log" 2>&1 || {
		tail -20 "${BUILD_ROOT}/configure.log" >&2
		die "configure fehlgeschlagen (Log: ${BUILD_ROOT}/configure.log)"
	}
fi

log "baue pjproject mit ${JOBS} Jobs (einige Minuten)"
make dep >"${BUILD_ROOT}/make-dep.log" 2>&1 || die "make dep fehlgeschlagen (Log: ${BUILD_ROOT}/make-dep.log)"
make -j"${JOBS}" >"${BUILD_ROOT}/make.log" 2>&1 || {
	tail -30 "${BUILD_ROOT}/make.log" >&2
	die "make fehlgeschlagen (Log: ${BUILD_ROOT}/make.log)"
}

log "baue Python-Binding (SWIG) für ${py_tag}"
cd "${BUILD}/pjsip-apps/src/swig/python"
make clean >/dev/null 2>&1 || true
make PYTHON_EXE="${PYTHON}" >"${BUILD_ROOT}/make-python.log" 2>&1 || {
	tail -30 "${BUILD_ROOT}/make-python.log" >&2
	die "Python-Binding fehlgeschlagen (Log: ${BUILD_ROOT}/make-python.log)"
}

so_file="$(find build -name '_pjsua2*.so' | head -1)"
[[ -n "${so_file}" && -f pjsua2.py ]] || die "Binding-Dateien nicht gefunden"
cp "${so_file}" pjsua2.py "${site}/"
log "installiert: ${site}/pjsua2.py und $(basename "${so_file}")"

if ! "${PYTHON}" - >"${BUILD_ROOT}/import-test.log" 2>&1 <<'PY'; then
import pjsua2

ep = pjsua2.Endpoint()
ep.libCreate()
cfg = pjsua2.EpConfig()
cfg.logConfig.level = 0
cfg.logConfig.consoleLevel = 0
ep.libInit(cfg)
print("[build-pjsip] Import-Test ok, PJSIP", ep.libVersion().full)
ep.libDestroy()
PY
	cat "${BUILD_ROOT}/import-test.log" >&2
	die "Import-Test von pjsua2 fehlgeschlagen"
fi
grep '^\[build-pjsip\]' "${BUILD_ROOT}/import-test.log" || true
touch "${STAMP}"
log "fertig."

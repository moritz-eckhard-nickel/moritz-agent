#!/usr/bin/env bash
# Thin wrapper (INST-01): the actual updater is moritz-update.sh.
set -Eeuo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/moritz-update.sh" "$@"

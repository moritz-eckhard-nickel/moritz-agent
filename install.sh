#!/usr/bin/env bash
# Thin wrapper (INST-01): the actual installer is moritz-install.sh.
set -Eeuo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/moritz-install.sh" "$@"

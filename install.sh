#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# Thin wrapper (INST-01): the actual installer is moritz-install.sh.
set -Eeuo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/moritz-install.sh" "$@"

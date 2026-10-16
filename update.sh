#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
# Thin wrapper (INST-01): the actual updater is moritz-update.sh.
set -Eeuo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/moritz-update.sh" "$@"

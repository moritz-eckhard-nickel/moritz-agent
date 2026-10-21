# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Self-signed certificate for the web interface (API-01, ADR-022)."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

from moritz_agent.logging_setup import get_logger

log = get_logger("system")


def ensure_certificate(cert: Path, key: Path, *, days: int = 3650) -> bool:
    """Create certificate and key with ``openssl`` if they do not exist yet (key mode 0600).

    Returns True when both files are usable afterwards.
    """
    if cert.is_file() and key.is_file():
        return True
    names = {"localhost", socket.gethostname()}
    alt = ",".join([f"DNS:{name}" for name in sorted(names)] + ["IP:127.0.0.1"])
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        "-nodes", "-days", str(days), "-subj", "/CN=moritz-agent",
        "-addext", f"subjectAltName={alt}",
        "-keyout", str(key), "-out", str(cert),
    ]  # fmt: skip
    old_umask = os.umask(0o077)
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        log.error("Zertifikat konnte nicht erzeugt werden (%s)", type(exc).__name__)
        return False
    finally:
        os.umask(old_umask)
    key.chmod(0o600)
    log.info("Selbstsigniertes Zertifikat erzeugt: %s", cert)
    return True

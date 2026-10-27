# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Certificates for the web interface (API-01, ADR-022, docs/plan/15 P2-01).

moritz-agent keeps its own small certificate authority (``ca.pem``). It signs the server certificate
for every address the web interface is reached by: ``localhost``, the host name, all own IPs and
``server.public_hosts``. Installed once on a device (``/ca.crt``, docs/webui.md), the browser trusts
``https://192.168.1.187:3501`` without a warning. A new IP or a certificate near its end leads to a
new server certificate from the same CA – the devices keep trusting it.

A certificate that moritz-agent did not make (an own one in ``tls_cert``) is never touched.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
import socket
import subprocess
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from moritz_agent.logging_setup import get_logger

log = get_logger("system")

OWNER = "moritz-agent"  # every certificate made here carries it in subject and issuer
SERVER_DAYS = 825  # the longest validity Apple devices accept for a server certificate
CA_DAYS = 3650
RENEW_BEFORE_S = 30 * 86400


def _openssl(*args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["openssl", *args], check=False, capture_output=True, text=True, timeout=timeout
    )


def _ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None


def local_addresses() -> set[str]:
    """The IPs this machine is reachable by (no link-local), loopback included."""
    found = {"127.0.0.1"}
    with suppress(OSError, subprocess.SubprocessError):
        out = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
        found.update(out.split())
    with suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))  # no packet is sent; it only picks the outgoing address
        found.add(probe.getsockname()[0])
    return {str(ip) for value in found if (ip := _ip(value)) is not None and not ip.is_link_local}


def wanted_names(hosts: Iterable[str] = ()) -> set[str]:
    """``DNS:…``/``IP:…`` entries the server certificate has to cover."""
    names = {"localhost", socket.gethostname(), *local_addresses(), *hosts}
    entries = set()
    for name in names:
        name = name.strip()
        if not name:
            continue
        ip = _ip(name)
        entries.add(f"IP:{ip}" if ip is not None else f"DNS:{name}")
    return entries


def certificate_names(cert: Path) -> set[str]:
    out = _openssl("x509", "-in", str(cert), "-noout", "-ext", "subjectAltName").stdout
    names = set()
    for part in out.replace("\n", ",").split(","):
        part = part.strip()
        if part.startswith("DNS:"):
            names.add(part)
        elif part.startswith("IP Address:"):
            ip = _ip(part.removeprefix("IP Address:"))
            if ip is not None:
                names.add(f"IP:{ip}")
    return names


def issuer(cert: Path) -> str:
    return _openssl("x509", "-in", str(cert), "-noout", "-issuer").stdout.strip()


def _expires_soon(cert: Path) -> bool:
    return (
        _openssl("x509", "-in", str(cert), "-noout", "-checkend", str(RENEW_BEFORE_S)).returncode
        != 0
    )


def _private(path: Path) -> None:
    with suppress(OSError):
        path.chmod(0o600)


def ensure_ca(ca_cert: Path, ca_key: Path) -> bool:
    """The own certificate authority; made once and then kept (devices trust exactly this one)."""
    if ca_cert.is_file() and ca_key.is_file():
        return True
    ca_cert.parent.mkdir(parents=True, exist_ok=True)
    ca_key.parent.mkdir(parents=True, exist_ok=True)
    subject = f"/O={OWNER}/CN={OWNER} CA ({socket.gethostname()})"
    old_umask = os.umask(0o077)
    try:
        result = _openssl(
            "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-days", str(CA_DAYS), "-sha256", "-subj", subject,
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", str(ca_key), "-out", str(ca_cert),
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError) as exc:
        log.error("Zertifizierungsstelle konnte nicht erzeugt werden (%s)", type(exc).__name__)
        return False
    finally:
        os.umask(old_umask)
    if result.returncode != 0:
        log.error(
            "Zertifizierungsstelle konnte nicht erzeugt werden (openssl %d)", result.returncode
        )
        return False
    _private(ca_key)
    ca_cert.chmod(0o644)
    log.info("Eigene Zertifizierungsstelle erzeugt: %s", ca_cert)
    return True


def _sign(cert: Path, key: Path, ca_cert: Path, ca_key: Path, names: set[str]) -> bool:
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    first = sorted(n.split(":", 1)[1] for n in names)[0]
    extensions = "\n".join(
        [
            "basicConstraints=critical,CA:FALSE",
            "keyUsage=critical,digitalSignature,keyEncipherment",
            "extendedKeyUsage=serverAuth",
            "subjectKeyIdentifier=hash",
            "authorityKeyIdentifier=keyid,issuer",
            "subjectAltName=" + ",".join(sorted(names)),
        ]
    )
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            csr, ext = Path(tmp) / "server.csr", Path(tmp) / "server.ext"
            ext.write_text(extensions + "\n", encoding="utf-8")
            request = _openssl(
                "req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                "-nodes", "-subj", f"/O={OWNER}/CN={first}", "-keyout", str(key), "-out", str(csr),
            )  # fmt: skip
            if request.returncode != 0:
                return False
            signed = _openssl(
                "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
                "-set_serial", "0x" + secrets.token_hex(16), "-days", str(SERVER_DAYS),
                "-sha256", "-extfile", str(ext), "-out", str(cert),
            )  # fmt: skip
            return signed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        os.umask(old_umask)
        _private(key)


def _self_signed(cert: Path, key: Path, names: set[str], days: int) -> bool:
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        result = _openssl(
            "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-days", str(days), "-subj", f"/CN={OWNER}",
            "-addext", "subjectAltName=" + ",".join(sorted(names)),
            "-keyout", str(key), "-out", str(cert),
        )  # fmt: skip
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        os.umask(old_umask)
        _private(key)


def ensure_certificate(
    cert: Path,
    key: Path,
    *,
    ca_cert: Path | None = None,
    ca_key: Path | None = None,
    hosts: Iterable[str] = (),
    days: int = 3650,
) -> bool:
    """Make sure ``cert``/``key`` exist and cover every address; True when both are usable.

    With ``ca_cert``/``ca_key`` the certificate is signed by the own CA, otherwise self-signed.
    """
    names = wanted_names(hosts)
    if cert.is_file() and key.is_file():
        made_by = issuer(cert)
        if OWNER not in made_by:
            return True  # an own certificate: never replaced
        signed_by_ca = f"{OWNER} CA" in made_by
        if (
            (signed_by_ca or ca_cert is None)
            and names <= certificate_names(cert)
            and not _expires_soon(cert)
        ):
            return True
        log.info("Zertifikat wird erneuert (neue Adresse, Ablauf oder eigene CA)")
    if ca_cert is not None and ca_key is not None:
        ok = ensure_ca(ca_cert, ca_key) and _sign(cert, key, ca_cert, ca_key, names)
    else:
        ok = _self_signed(cert, key, names, days)
    if not ok:
        log.error("Zertifikat konnte nicht erzeugt werden")
        return False
    cert.chmod(0o644)  # public; only the key stays private
    log.info("Zertifikat erzeugt für %s", ", ".join(sorted(names)))
    return True

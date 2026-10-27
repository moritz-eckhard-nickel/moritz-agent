# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""WebUI groundwork (docs/plan/15 P2-01): lasting sessions, the own CA, the CA download."""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from moritz_agent.api import tls
from moritz_agent.api.auth import Authenticator
from moritz_agent.config.settings import Settings
from moritz_agent.storage.web import SessionStore

from .system_util import WEB_PASSWORD, WEB_USER, running_system

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl fehlt")


def scenario(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return asyncio.run(go())


def restarted(system, **kwargs):
    """A new Authenticator on the same database: what a restart of the service looks like."""
    return Authenticator(
        lambda: system.config.current, store=SessionStore(system.runtime.db), **kwargs
    )


# -- sessions ---------------------------------------------------------------------------------------
def test_ten_days_is_the_default():
    assert Settings().server.session_ttl_hours == 240


def test_a_login_survives_a_restart_and_only_its_hash_is_stored(tmp_path):
    async def body(system):
        token = restarted(system).login(WEB_USER, WEB_PASSWORD, "10.0.0.1").token
        rows = system.runtime.db.query("SELECT token_hash FROM web_sessions")
        return token, [row["token_hash"] for row in rows], restarted(system).valid(token)

    token, stored, valid_after_restart = scenario(tmp_path, body)
    assert valid_after_restart and len(stored) == 1 and token not in stored[0]


def test_a_session_ends_after_ten_days_even_across_restarts(tmp_path):
    clock = [1_000_000.0]

    async def body(system):
        token = restarted(system, clock=lambda: clock[0]).login(WEB_USER, WEB_PASSWORD, "x").token
        clock[0] += 239 * 3600
        still = restarted(system, clock=lambda: clock[0]).valid(token)
        clock[0] += 2 * 3600
        return still, restarted(system, clock=lambda: clock[0]).valid(token)

    assert scenario(tmp_path, body) == (True, False)


def test_a_password_changed_while_the_service_was_down_ends_every_session(tmp_path):
    async def body(system):
        token = restarted(system).login(WEB_USER, WEB_PASSWORD, "x").token
        path = system.tree / "passwords.txt"
        path.write_text(
            path.read_text(encoding="utf-8").replace(WEB_PASSWORD, "Neu-Pw-77"), "utf-8"
        )
        assert system.config.reload().ok
        after = restarted(system)
        valid = after.valid(token)
        fresh = after.login(WEB_USER, "Neu-Pw-77", "x").token
        return valid, restarted(system).valid(fresh)

    assert scenario(tmp_path, body) == (False, True)


def test_logout_everywhere_ends_all_devices(tmp_path):
    async def body(system):
        other = restarted(system).login(WEB_USER, WEB_PASSWORD, "10.0.0.9").token
        async with system.client() as client:
            await system.login(client)
            done = await client.post("/api/logout-everywhere")
            mine = (await client.get("/api/system/status")).status_code
        return done.status_code, mine, restarted(system).valid(other)

    assert scenario(tmp_path, body) == (200, 401, False)


# -- certificates ----------------------------------------------------------------------------------
def verify(ca, cert):
    result = subprocess.run(
        ["openssl", "verify", "-CAfile", str(ca), str(cert)], capture_output=True, text=True
    )
    return result.returncode == 0


@needs_openssl
def test_the_server_certificate_is_signed_by_the_own_ca_and_covers_the_ip(tmp_path):
    cert, key, ca, ca_key = (tmp_path / n for n in ("cert.pem", "key.pem", "ca.pem", "ca-key.pem"))
    assert tls.ensure_certificate(cert, key, ca_cert=ca, ca_key=ca_key, hosts=["192.168.1.187"])
    names = tls.certificate_names(cert)
    assert {"IP:192.168.1.187", "IP:127.0.0.1", "DNS:localhost"} <= names
    assert verify(ca, cert) and "moritz-agent CA" in tls.issuer(cert)
    assert (
        oct(key.stat().st_mode & 0o777) == "0o600" and oct(ca_key.stat().st_mode & 0o777) == "0o600"
    )
    text = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-text"], capture_output=True, text=True
    ).stdout
    assert "TLS Web Server Authentication" in text and "CA:FALSE" in text


@needs_openssl
def test_a_new_address_gets_a_new_certificate_from_the_same_ca(tmp_path):
    cert, key, ca, ca_key = (tmp_path / n for n in ("cert.pem", "key.pem", "ca.pem", "ca-key.pem"))
    tls.ensure_certificate(cert, key, ca_cert=ca, ca_key=ca_key, hosts=["192.168.1.187"])
    ca_before, cert_before = ca.read_bytes(), cert.read_bytes()
    tls.ensure_certificate(cert, key, ca_cert=ca, ca_key=ca_key, hosts=["192.168.1.187"])
    assert cert.read_bytes() == cert_before  # nothing changed: nothing renewed
    tls.ensure_certificate(cert, key, ca_cert=ca, ca_key=ca_key, hosts=["10.1.2.3", "sophie-1"])
    assert cert.read_bytes() != cert_before and ca.read_bytes() == ca_before
    assert {"IP:10.1.2.3", "DNS:sophie-1"} <= tls.certificate_names(cert) and verify(ca, cert)


@needs_openssl
def test_the_old_self_signed_certificate_is_replaced_but_an_own_one_never(tmp_path):
    cert, key, ca, ca_key = (tmp_path / n for n in ("cert.pem", "key.pem", "ca.pem", "ca-key.pem"))
    assert tls.ensure_certificate(cert, key)  # Part 1: self-signed
    assert "moritz-agent CA" not in tls.issuer(cert)
    tls.ensure_certificate(cert, key, ca_cert=ca, ca_key=ca_key)
    assert verify(ca, cert)

    own_cert, own_key = tmp_path / "own.pem", tmp_path / "own-key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-days", "30", "-subj", "/CN=meins.example", "-keyout", str(own_key),
         "-out", str(own_cert)],
        check=True, capture_output=True,
    )  # fmt: skip
    before = own_cert.read_bytes()
    assert tls.ensure_certificate(own_cert, own_key, ca_cert=ca, ca_key=ca_key, hosts=["10.9.9.9"])
    assert own_cert.read_bytes() == before


@needs_openssl
def test_the_ca_certificate_can_be_downloaded_without_login_but_never_a_key(tmp_path):
    async def body(system):
        ca, ca_key = tmp_path / "tls" / "ca.pem", tmp_path / "tls" / "ca-key.pem"
        assert tls.ensure_ca(ca, ca_key)
        server = system.config.current.settings.server
        async with system.client() as client:
            server.tls_ca_cert = str(tmp_path / "nichts.pem")
            missing = await client.get("/ca.crt")
            server.tls_ca_cert = str(ca)
            found = await client.get("/ca.crt")
            server.tls_ca_cert = str(ca_key)
            key = await client.get("/ca.crt")
        return missing.status_code, found, key.status_code, ca.read_text()

    missing, found, key, pem = scenario(tmp_path, body)
    assert missing == 404 and key == 404
    assert found.status_code == 200 and found.text == pem
    assert found.headers["content-type"].startswith("application/x-x509-ca-cert")
    assert "m-agent-ca.crt" in found.headers["content-disposition"]

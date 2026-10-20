# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Supervisor: start order, internal wiring to the phone worker, reload, shutdown (P1-04)."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import stat
import sys
from pathlib import Path

import httpx

from moritz_agent.inference import InferenceClient
from moritz_agent.phone.control import read_status
from moritz_agent.process import ManagedProcess
from moritz_agent.runtime import Runtime
from moritz_agent.skills.clock import FixedClock
from moritz_agent.supervisor import Supervisor

from . import weather_fixtures as wf
from .fake_model import FakeModel
from .skills_util import SUNDAY_EVENING, default_routes
from .system_util import ROOT, SIP_PASSWORD, WEB_PASSWORD, WEB_USER, make_tree

FAKE_PHONE = Path(__file__).with_name("fake_phone.py")


def run(coro):
    return asyncio.run(coro)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def prepare(tmp_path: Path, *, tls: bool = False, web_login: bool = True) -> tuple[Path, int]:
    tree = make_tree(tmp_path, web_login=web_login)
    port = free_port()
    path = tree / "config" / "moritz-agent.toml"
    text = path.read_text(encoding="utf-8")
    text = text.replace("port = 3501", f"port = {port}", 1)
    if not tls:
        text = text.replace("tls = true", "tls = false", 1)
    else:
        text = text.replace(
            'tls_cert = "runtime/tls/cert.pem"', f'tls_cert = "{tree}/tls/cert.pem"'
        )
        text = text.replace('tls_key = "runtime/tls/key.pem"', f'tls_key = "{tree}/tls/key.pem"')
    path.write_text(text, encoding="utf-8")
    return tree, port


def make(
    tree: Path,
    *,
    phone_args: tuple[str, ...] = (),
    start_phone: bool = True,
    model: FakeModel | None = None,
    **kwargs,
) -> Supervisor:
    table = default_routes()
    options = {
        "clock": FixedClock(SUNDAY_EVENING),
        "providers_transport": wf.mock_transport(table),
        "providers_cache_dir": tree / "cache",
    }
    if model is not None:
        options["inference_client"] = InferenceClient(
            "http://127.0.0.1:1", transport=model.transport()
        )
    sup = Supervisor(
        ROOT,
        state_root=tree,
        settings_file=tree / "config" / "moritz-agent.toml",
        passwords_file=tree / "passwords.txt",
        manage_processes=False,
        start_phone=start_phone,
        phone_argv=[sys.executable, str(FAKE_PHONE), str(tree), *phone_args],
        runtime_options=options,
        **kwargs,
    )
    return sup


async def until(check, timeout=8.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


def lines(tree: Path) -> list[str]:
    path = tree / "data" / "run" / "fake-phone.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_a_broken_configuration_stops_the_start_with_clear_messages(tmp_path, capsys):
    tree, _ = prepare(tmp_path)
    (tree / "passwords.txt").write_text("[sip]\nusername = x\n", encoding="utf-8")
    sup = make(tree)
    assert run(sup.run()) == 2
    err = capsys.readouterr().err
    assert "Konfiguration fehlerhaft" in err and "passwords.txt" in err


def test_start_brings_up_api_phone_and_tokens_and_shutdown_removes_the_token(tmp_path):
    tree, port = prepare(tmp_path)

    async def scenario():
        sup = make(tree, phone_args=("--ask",))
        await sup.start()
        try:
            await until(lambda: any(line.startswith("reply") for line in lines(tree)))
            await until(lambda: read_status(tree) is not None)
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                health = await client.get("/api/system/health")
                login = await client.post(
                    "/api/login", json={"username": WEB_USER, "password": WEB_PASSWORD}
                )
                status = await client.get("/api/system/status")
            await until(lambda: any(line.startswith("reply") for line in lines(tree)))
            token_file = tree / "data" / "run" / "admin.token"
            token = token_file.read_text(encoding="utf-8")
            mode = stat.S_IMODE(token_file.stat().st_mode)
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                activity = await client.get(
                    "/api/system/activity", headers={"X-Admin-Token": token}
                )
            return sup, health, login, status, token, mode, activity
        finally:
            await sup.shutdown()

    _sup, health, login, status, _token, mode, activity = run(scenario())
    assert health.json() == {"ok": True} and login.status_code == 200
    data = status.json()
    assert data["web"]["state"] == "ready" and data["phone"]["state"] == "ready"
    assert data["children"]["phone"]["state"] in {"starting", "ready"}
    assert mode == 0o600 and activity.json()["in_call"] is False
    log_lines = lines(tree)
    assert (
        "env ok" in log_lines and "SIGTERM" in log_lines
    )  # token and url arrived, stop was polite
    assert any("19 Uhr 12" in line for line in log_lines if line.startswith("reply"))
    assert not (tree / "data" / "run" / "admin.token").exists()


def test_the_phone_worker_reaches_the_main_process_through_the_internal_api(tmp_path):
    tree, _ = prepare(tmp_path)

    async def scenario():
        sup = make(tree, phone_args=("--ask",))
        await sup.start()
        try:
            await until(lambda: any(line.startswith("reply") for line in lines(tree)))
            await until(
                lambda: sup.runtime.db.query("SELECT end_reason FROM calls WHERE id = 'fake-call'")
            )
            return [
                dict(r) for r in sup.runtime.db.query("SELECT codec, end_reason, turns FROM calls")
            ]
        finally:
            await sup.shutdown()

    assert run(scenario()) == [{"codec": "G722", "end_reason": "caller_hangup", "turns": 1}]


def test_without_a_web_login_the_interface_stays_on_the_loopback(tmp_path):
    tree, port = prepare(tmp_path, web_login=False)
    path = tree / "config" / "moritz-agent.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('host = "127.0.0.1"', 'host = "0.0.0.0"', 1),
        encoding="utf-8",
    )

    async def scenario():
        sup = make(tree, start_phone=False)
        await sup.start()
        try:
            async with httpx.AsyncClient() as client:
                local = await client.get(f"http://127.0.0.1:{port}/api/system/health")
            return sup.web_state, local.status_code, [s.config.host for s, _ in sup._servers]
        finally:
            await sup.shutdown()

    state, code, hosts = run(scenario())
    assert state.state == "degraded" and "kein Web-Login" in state.message
    assert code == 200 and hosts == ["127.0.0.1", "127.0.0.1"]


def test_https_with_a_generated_certificate(tmp_path):
    tree, port = prepare(tmp_path, tls=True)

    async def scenario():
        sup = make(tree, start_phone=False)
        await sup.start()
        try:
            async with httpx.AsyncClient(verify=False) as client:  # self-signed (ADR-022)
                response = await client.get(f"https://127.0.0.1:{port}/api/system/health")
            return (
                response.json(),
                sup.web_state.message,
                stat.S_IMODE((tree / "tls" / "key.pem").stat().st_mode),
            )
        finally:
            await sup.shutdown()

    body, message, key_mode = run(scenario())
    assert body == {"ok": True} and message.startswith("https://") and key_mode == 0o600


def test_a_busy_port_only_disables_the_web_interface(tmp_path):
    tree, port = prepare(tmp_path)

    async def scenario():
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", port))
            blocker.listen()
            sup = make(tree, phone_args=())
            await sup.start()
            try:
                await until(lambda: "env ok" in lines(tree))
                return sup.web_state, sup.phone.status().state
            finally:
                await sup.shutdown()

    state, phone = run(scenario())
    assert state.state == "failed" and phone in {"starting", "ready"}


def test_reload_tells_the_phone_only_when_it_matters(tmp_path):
    tree, _ = prepare(tmp_path)

    async def scenario():
        sup = make(tree)
        await sup.start()
        try:
            await until(lambda: sup.phone.status().state == "ready")
            path = tree / "config" / "moritz-agent.toml"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace("max_sentences = 3", "max_sentences = 2", 1), encoding="utf-8"
            )
            quiet = await sup.reload()
            await asyncio.sleep(0.4)
            before = lines(tree).count("SIGHUP")
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "rtp_port_start = 40000", "rtp_port_start = 41000"
                ),
                encoding="utf-8",
            )
            loud = await sup.reload()
            await until(lambda: lines(tree).count("SIGHUP") > before)
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "max_sentences = 2", "max_sentences = 99", 1
                ),
                encoding="utf-8",
            )
            bad = await sup.reload()
            return quiet, before, loud, bad
        finally:
            await sup.shutdown()

    quiet, before, loud, bad = run(scenario())
    assert quiet.ok and not quiet.events and before == 0
    assert loud.events == {"sip_changed"}
    assert not bad.ok


def test_shutdown_stops_the_phone_before_the_servers_and_the_runtime(tmp_path, monkeypatch):
    tree, _ = prepare(tmp_path)
    order: list[str] = []
    original_stop = ManagedProcess.stop
    original_runtime = Runtime.stop

    async def phone_stop(self, grace_s=10.0):
        order.append(f"process:{self.name}")
        await original_stop(self, grace_s)

    async def runtime_stop(self):
        order.append("runtime")
        await original_runtime(self)

    monkeypatch.setattr(ManagedProcess, "stop", phone_stop)
    monkeypatch.setattr(Runtime, "stop", runtime_stop)

    async def scenario():
        sup = make(tree)
        await sup.start()
        await until(lambda: "env ok" in lines(tree))
        servers = list(sup._servers)
        await sup.shutdown()
        return servers

    servers = run(scenario())
    assert order == ["process:phone", "runtime"]
    assert all(server.should_exit for server, _ in servers)


def test_run_stops_cleanly_on_sigterm_and_a_crashing_phone_comes_back(tmp_path):
    tree, _ = prepare(tmp_path)

    async def scenario():
        sup = make(tree)
        task = asyncio.create_task(sup.run())
        await until(lambda: sup.phone is not None and sup.phone.status().state == "ready", 15)
        pid = sup.phone.status().pid
        os.kill(pid, signal.SIGKILL)  # the worker dies
        await until(
            lambda: sup.phone.status().restarts >= 1 and sup.phone.status().state == "ready", 20
        )
        os.kill(os.getpid(), signal.SIGTERM)
        return await asyncio.wait_for(task, 20), sup.phone.status().restarts

    code, restarts = run(scenario())
    assert code == 0 and restarts >= 1


def test_secrets_never_reach_the_log(tmp_path):
    tree, _ = prepare(tmp_path)
    log_file = tree / "data" / "logs" / "test.log"
    path = tree / "config" / "moritz-agent.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'file = "data/logs/moritz-agent.log"', f'file = "{log_file}"'
        ),
        encoding="utf-8",
    )

    async def scenario():
        sup = make(tree, start_phone=False)
        await sup.start()
        try:
            import logging

            logging.getLogger("moritz.system").warning("das Passwort ist %s", SIP_PASSWORD)
        finally:
            await sup.shutdown()

    run(scenario())
    text = log_file.read_text(encoding="utf-8")
    assert SIP_PASSWORD not in text and "***" in text

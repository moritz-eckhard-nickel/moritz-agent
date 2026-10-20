# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""ManagedProcess: restart with backoff, health check, polite stop, log forwarding (P1-04)."""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
import time

from moritz_agent.process import ManagedProcess, ProcessStatus, find_free_port

PY = sys.executable


def run(coro):
    return asyncio.run(coro)


def script(code: str) -> list[str]:
    return [PY, "-I", "-c", code]


def test_free_ports_are_bindable_on_loopback():
    port = find_free_port()
    assert 1024 < port < 65536
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_a_process_that_crashes_is_restarted_with_growing_pauses():
    async def scenario():
        marker = []
        proc = ManagedProcess(
            "crasher",
            script("import sys; sys.exit(3)"),
            backoff=(0.05, 0.4),
            on_state=lambda s: marker.append((s.state, round(time.monotonic(), 2))),
        )
        await proc.start()
        await asyncio.sleep(1.2)
        status = ProcessStatus(**vars(proc.status()))
        await proc.stop(1)
        return status

    status = run(scenario())
    assert status.restarts >= 3 and status.last_exit == 3 and status.state in {"failed", "starting"}


def test_backoff_doubles_up_to_the_limit_and_resets_after_a_stable_run(caplog):
    caplog.set_level(logging.INFO, logger="moritz")

    async def scenario():
        proc = ManagedProcess(
            "crasher", script("import sys; sys.exit(1)"), backoff=(0.05, 0.2), stable_after_s=999
        )
        await proc.start()
        await asyncio.sleep(1.0)
        await proc.stop(1)

    run(scenario())
    pauses = [r.getMessage() for r in caplog.records if "Neustart in" in r.getMessage()]
    seconds = [float(m.rsplit("in ", 1)[1].split(" s")[0]) for m in pauses]
    assert seconds[:3] == [0.05, 0.1, 0.2] and max(seconds) <= 0.2


def test_a_missing_program_is_reported_not_raised():
    async def scenario():
        proc = ManagedProcess("nothing", ["/nonexistent/program"], backoff=(0.05, 0.1))
        await proc.start()
        await asyncio.sleep(0.3)
        status = ProcessStatus(**vars(proc.status()))
        await proc.stop(1)
        return status

    status = run(scenario())
    assert status.state in {"failed", "starting"} and status.pid is None


def test_output_goes_to_the_log_line_by_line(caplog):
    caplog.set_level(logging.INFO, logger="moritz")

    async def scenario():
        proc = ManagedProcess(
            "talker",
            script("import time; print('eins'); print('zwei', flush=True); time.sleep(30)"),
            category="inference",
        )
        await proc.start()
        await asyncio.sleep(0.6)
        await proc.stop(2)

    run(scenario())
    text = caplog.text
    assert "[talker] eins" in text and "[talker] zwei" in text and "moritz.inference" in text


def test_stop_sends_sigterm_first_and_lets_the_child_finish():
    async def scenario(tmp):
        code = (
            "import signal, sys, time, pathlib\n"
            "def bye(*a):\n"
            f"    pathlib.Path({str(tmp)!r}).write_text('sauber')\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, bye)\n"
            "print('bereit', flush=True)\n"
            "time.sleep(60)\n"
        )
        proc = ManagedProcess("polite", script(code))
        await proc.start()
        assert await proc.wait_ready(5)
        await asyncio.sleep(0.3)
        started = time.monotonic()
        await proc.stop(5)
        return time.monotonic() - started

    import tempfile
    from pathlib import Path

    marker = Path(tempfile.mkdtemp()) / "term"
    elapsed = run(scenario(marker))
    assert marker.read_text() == "sauber" and elapsed < 3


def test_stop_kills_a_child_that_ignores_sigterm():
    async def scenario():
        code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('x', flush=True); time.sleep(60)"
        proc = ManagedProcess("stubborn", script(code))
        await proc.start()
        assert await proc.wait_ready(5)
        await asyncio.sleep(0.3)
        started = time.monotonic()
        await proc.stop(0.5)
        return time.monotonic() - started, proc.running

    elapsed, running = run(scenario())
    assert elapsed < 4 and not running


def test_stop_also_kills_grandchildren():
    async def scenario(tmp):
        code = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(tmp)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        proc = ManagedProcess("parent", script(code))
        await proc.start()
        for _ in range(50):
            await asyncio.sleep(0.1)
            if tmp.exists() and tmp.read_text():
                break
        pid = int(tmp.read_text())
        await proc.stop(1)
        await asyncio.sleep(0.3)
        return pid

    import tempfile
    from pathlib import Path

    marker = Path(tempfile.mkdtemp()) / "pid"
    pid = run(scenario(marker))
    try:  # a dead child may linger as a zombie until its parent (here: init) reaps it
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        state = "gone"
    assert state in {"Z", "gone"}


def test_health_check_decides_when_the_child_is_ready():
    async def scenario():
        state = {"up": False}

        async def check():
            return state["up"]

        proc = ManagedProcess(
            "slow",
            script("import time; time.sleep(60)"),
            health_check=check,
            health_interval_s=0.05,
        )
        await proc.start()
        assert not await proc.wait_ready(0.3)
        assert proc.status().state == "starting"
        state["up"] = True
        assert await proc.wait_ready(2)
        await proc.stop(1)

    run(scenario())


def test_a_child_that_stops_answering_is_restarted():
    async def scenario():
        answers = {"ok": True}

        async def check():
            return answers["ok"]

        proc = ManagedProcess(
            "hanger",
            script("import time; time.sleep(60)"),
            health_check=check,
            health_interval_s=0.05,
            health_failures=3,
            backoff=(0.05, 0.1),
        )
        await proc.start()
        assert await proc.wait_ready(2)
        first_pid = proc.status().pid
        answers["ok"] = False
        await asyncio.sleep(0.6)
        degraded_seen = proc.status().restarts >= 1
        answers["ok"] = True
        assert await proc.wait_ready(3)
        second_pid = proc.status().pid
        await proc.stop(1)
        return degraded_seen, first_pid != second_pid

    restarted, new_pid = run(scenario())
    assert restarted and new_pid


def test_startup_that_takes_too_long_is_retried():
    async def scenario():
        async def never():
            return False

        proc = ManagedProcess(
            "never-ready",
            script("import time; time.sleep(60)"),
            health_check=never,
            health_interval_s=0.05,
            startup_timeout_s=0.3,
            backoff=(0.05, 0.1),
        )
        await proc.start()
        await asyncio.sleep(1.2)
        restarts = proc.status().restarts
        await proc.stop(1)
        return restarts

    assert run(scenario()) >= 1


def test_environment_is_passed_without_leaking_the_parents_secrets(monkeypatch):
    monkeypatch.setenv("PARENT_ONLY", "x")

    async def scenario(tmp):
        code = f"import os; open({str(tmp)!r}, 'w').write(os.environ.get('TOKEN', '-') + os.environ.get('PARENT_ONLY', '-'))"
        proc = ManagedProcess("env", script(code), env={"TOKEN": "t0k"}, backoff=(5, 5))
        await proc.start()
        await asyncio.sleep(0.6)
        await proc.stop(1)

    import tempfile
    from pathlib import Path

    marker = Path(tempfile.mkdtemp()) / "env"
    run(scenario(marker))
    assert marker.read_text().startswith("t0k")

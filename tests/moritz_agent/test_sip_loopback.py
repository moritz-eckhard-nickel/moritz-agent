# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Real SIP/RTP calls against a running phone worker on this machine (skipped without PJSIP/espeak-ng).

The worker runs in its own process with the emergency voice and a scripted speech recognizer, the
caller is scripts/sip_testcall.py. Covers what unit tests cannot: ringing before answering, a
caller who gives up while it rings, a busy line and the maintenance mode.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pjsua2", reason="PJSIP binding not built (scripts/build-pjsip.sh)")
pytestmark = pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng not installed")

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER = REPO_ROOT / "scripts" / "sip_testcall.py"


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Worker:
    def __init__(self, tmp_path: Path, ring_min: float, ring_max: float) -> None:
        self.tmp = tmp_path
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.port = free_udp_port()
        example = (REPO_ROOT / "config" / "moritz-agent.example.toml").read_text(encoding="utf-8")
        config = re.sub(r"(?m)^ring_seconds_min = .*$", f"ring_seconds_min = {ring_min}", example)
        config = re.sub(r"(?m)^ring_seconds_max = .*$", f"ring_seconds_max = {ring_max}", config)
        self.config = tmp_path / "moritz-agent.toml"
        self.config.write_text(config, encoding="utf-8")
        self.passwords = tmp_path / "passwords.txt"
        self.passwords.write_text(
            (REPO_ROOT / "config" / "passwords.template.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.log = tmp_path / "worker.log"
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        with self.log.open("w") as handle:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "moritz_agent.phone", "--config", str(self.config), "--passwords", str(self.passwords),
                 "run", "--stt", "fake:Tschüss", "--no-register", "--allow", "127.0.0.1", "--engines", "espeak",
                 "--sip-port", str(self.port)],
                cwd=REPO_ROOT,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )  # fmt: skip
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if "Anton ist bereit" in self.text():
                return
            if self.process.poll() is not None:
                break
            time.sleep(0.2)
        raise AssertionError("worker did not start:\n" + self.text())

    def text(self) -> str:
        return self.log.read_text(errors="replace") if self.log.exists() else ""

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def call(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CALLER), "--to", f"sip:agent@127.0.0.1:{self.port}", "--local-port", str(free_udp_port()),
             "--out", str(self.tmp / "call.wav"), *args],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=timeout, check=False,
        )  # fmt: skip


@pytest.fixture
def worker_factory(tmp_path):
    workers: list[Worker] = []

    def make(ring_min: float, ring_max: float | None = None) -> Worker:
        worker = Worker(
            tmp_path / f"w{len(workers)}", ring_min, ring_min if ring_max is None else ring_max
        )
        worker.start()
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.stop()


def greeting_delay(output: str) -> float:
    match = re.search(r"Begrüßung nach ([0-9.]+) s", output)
    assert match, output
    return float(match.group(1))


def test_anton_lets_it_ring_before_picking_up(worker_factory):
    worker = worker_factory(2.0)
    result = worker.call("--hangup-after-greeting")
    assert result.returncode == 0, result.stdout + result.stderr
    assert 2.0 <= greeting_delay(result.stdout) < 5.5  # ringing time plus a moment for the greeting
    assert "klingelt 2.0 s" in worker.text()


def test_ring_time_varies_within_the_configured_range(worker_factory):
    worker = worker_factory(1.0, 3.0)
    delays = []
    for _ in range(3):
        result = worker.call("--hangup-after-greeting")
        assert result.returncode == 0, result.stdout + result.stderr
        delays.append(greeting_delay(result.stdout))
    assert all(1.0 <= delay < 6.0 for delay in delays), delays
    rung = [float(m) for m in re.findall(r"klingelt ([0-9.]+) s", worker.text())]
    assert len(rung) == 3 and all(1.0 <= value <= 3.0 for value in rung), rung


def test_no_ringing_when_configured_to_zero(worker_factory):
    worker = worker_factory(0)
    result = worker.call("--hangup-after-greeting")
    assert result.returncode == 0, result.stdout + result.stderr
    assert greeting_delay(result.stdout) < 1.5


def test_caller_who_gives_up_while_it_rings_leaves_nothing_behind(worker_factory):
    worker = worker_factory(3.0)
    cancelled = worker.call("--cancel-after", "1")
    assert cancelled.returncode == 0, cancelled.stdout + cancelled.stderr
    time.sleep(3.5)  # the answer timer fires after the caller left: it must do nothing
    assert "Traceback" not in worker.text()
    again = worker.call("--hangup-after-greeting")  # the line is free again, Anton still works
    assert again.returncode == 0, again.stdout + again.stderr
    assert greeting_delay(again.stdout) >= 3.0


def test_a_second_caller_hears_busy_while_the_first_one_rings(worker_factory):
    worker = worker_factory(4.0)
    first = subprocess.Popen(
        [sys.executable, str(CALLER), "--to", f"sip:agent@127.0.0.1:{worker.port}", "--local-port", str(free_udp_port()),
         "--out", str(worker.tmp / "first.wav"), "--hangup-after-greeting"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO_ROOT,
    )  # fmt: skip
    try:
        time.sleep(1.5)
        second = worker.call("--timeout", "8")
        assert "SIP 486" in second.stdout, second.stdout
    finally:
        first.communicate(timeout=60)

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Client and process manager for the CosyVoice3 Hessisch worker (ADR-027, ADR-004).

The model lives in a child process (cosyvoice_worker.py, run with the TTS venv). Loading takes
a minute or more on the CPU, so the worker is started in the background; until it reports
"ready" the engine is simply not available and the TTS service uses a faster voice. If the
process dies it is restarted with a growing delay, and a running call never waits for it.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from moritz_agent.config.settings import CosyVoiceSettings
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.tts import TtsCancelled, TtsError, TtsUnavailable

log = get_logger("tts")
WORKER_SCRIPT = Path(__file__).with_name("cosyvoice_worker.py")
MODEL_FILES = ("cosyvoice3.yaml", "llm.pt", "flow.pt", "hift.pt", "campplus.onnx", "spk2info.pt")


def tts_python(settings: CosyVoiceSettings, repo_root: Path) -> Path:
    """Interpreter of the TTS venv (configured, else runtime/venv-tts)."""
    if settings.python:
        return Path(settings.python).expanduser()
    return repo_root / "runtime" / "venv-tts" / "bin" / "python"


def missing_model_files(model_dir: Path) -> list[str]:
    missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
    if not (model_dir / "CosyVoice-BlankEN" / "model.safetensors").is_file():
        missing.append("CosyVoice-BlankEN/model.safetensors")
    return missing


class CosyVoiceEngine:
    name = "cosyvoice"

    def __init__(self, settings: CosyVoiceSettings, repo_root: Path, threads: int) -> None:
        self.settings = settings
        self.repo_root = repo_root
        self.threads = threads
        configured = Path(settings.model_dir).expanduser()
        self.model_dir = configured if configured.is_absolute() else repo_root / configured
        self.voice_id = f"thorsten-hessisch/{settings.speaker}/{settings.seed}/{settings.speed}"
        self.token = secrets.token_urlsafe(32)
        self.worker_script = WORKER_SCRIPT  # tests substitute a fake worker
        self.state = "stopped"  # stopped | starting | ready | failed
        self.last_error = ""
        self.port = 0
        self.sample_rate = 24000
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------------------
    def start(self) -> None:
        """Launch the worker in the background and keep it alive."""
        if self._thread is not None:
            return
        problem = self._preflight()
        if problem:
            self.state, self.last_error = "failed", problem
            log.warning("CosyVoice nicht startbar: %s", problem)
            return
        self.state = "starting"
        self._thread = threading.Thread(
            target=self._supervise, name="cosyvoice-supervisor", daemon=True
        )
        self._thread.start()

    def _preflight(self) -> str:
        python = tts_python(self.settings, self.repo_root)
        if not python.is_file():
            return f"TTS-Python fehlt: {python} (./test-1.sh setup)"
        missing = missing_model_files(self.model_dir)
        if missing:
            return f"Modelldateien fehlen in {self.model_dir}: {', '.join(missing)} (./test-1.sh setup)"
        return ""

    def _supervise(self) -> None:
        delay = 5.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._run_once()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.error("CosyVoice-Worker: %s", self.last_error)
            self.state = "failed"
            if self._stop.is_set():
                break
            # a long healthy run resets the back-off
            delay = 5.0 if time.monotonic() - started > 300 else min(delay * 2, 120.0)
            log.warning("CosyVoice-Worker beendet – Neustart in %.0f s", delay)
            self._stop.wait(delay)
            self.state = "starting"

    def _run_once(self) -> None:
        python = tts_python(self.settings, self.repo_root)
        env = dict(os.environ)
        env.update(
            {
                "MORITZ_INTERNAL_TOKEN": self.token,
                "CUDA_VISIBLE_DEVICES": "",
                "OMP_NUM_THREADS": str(self.threads),
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        command = [
            str(python), str(self.worker_script),
            "--model-dir", str(self.model_dir),
            "--repo-root", str(self.repo_root),
            "--speaker", self.settings.speaker,
            "--threads", str(self.threads),
            "--seed", str(self.settings.seed),
        ]  # fmt: skip
        log.info("starte CosyVoice-Worker (Modell laden, das dauert)")
        self._proc = proc = subprocess.Popen(
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        threading.Thread(target=self._pump_stderr, args=(proc,), daemon=True).start()
        deadline = time.monotonic() + self.settings.startup_timeout_s
        ready = False
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break  # process ended
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "ready":
                self.port = int(event["port"])
                self.sample_rate = int(event.get("sample_rate", 24000))
                self.state, ready = "ready", True
                self.last_error = ""
                log.info(
                    "CosyVoice bereit (Port %d, Modell in %.0f s geladen)",
                    self.port,
                    event.get("load_seconds", 0),
                )
                break
            if event.get("event") == "error":
                self.last_error = str(event.get("error"))
        if not ready:
            proc.kill()
            raise TtsError(
                self.last_error or "CosyVoice-Worker wurde nicht bereit (Timeout oder Absturz)"
            )
        proc.wait()  # blocks until the worker exits
        raise TtsError(f"CosyVoice-Worker beendet (Code {proc.returncode})")

    @staticmethod
    def _pump_stderr(proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip()
            if line and "it/s]" not in line and "s/it]" not in line:  # skip tqdm progress noise
                log.debug("worker: %s", line)

    def available(self) -> bool:
        return self.state == "ready" and self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.state = "stopped"

    # -- requests ----------------------------------------------------------------------
    def _request(
        self, method: str, path: str, body: dict | None, timeout: float
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            return (
                response.status,
                {k.lower(): v for k, v in response.getheaders()},
                response.read(),
            )
        finally:
            connection.close()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        if not self.available():
            raise TtsUnavailable("CosyVoice nicht bereit")
        try:
            status, headers, data = self._request(
                "POST",
                "/synthesize",
                {"text": text, "seed": self.settings.seed, "speed": self.settings.speed},
                self.settings.request_timeout_s,
            )
        except (OSError, http.client.HTTPException) as exc:
            raise TtsError(f"CosyVoice nicht erreichbar: {exc}") from exc
        if status == 499:
            raise TtsCancelled()
        if status != 200:
            try:
                detail = json.loads(data).get("error", "")
            except json.JSONDecodeError:
                detail = data[:100].decode(errors="replace")
            raise TtsError(f"CosyVoice HTTP {status}: {detail}")
        rate = int(headers.get("x-sample-rate", self.sample_rate))
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        return samples, rate

    def cancel(self) -> None:
        if self.available():
            with contextlib.suppress(OSError, http.client.HTTPException):
                self._request("POST", "/cancel", {}, 2.0)

    def wait_ready(self, timeout: float) -> bool:
        """Block until the worker is ready (used by check/bench commands)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.available():
                return True
            if self.state == "failed" and self._thread is None:
                return False
            time.sleep(0.5)
        return self.available()

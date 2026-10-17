# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""CosyVoice3 "Hessisch" TTS worker (ADR-027).

Runs in its own virtual environment (runtime/venv-tts: torch CPU, transformers, …) as a child
process of the phone worker, so the heavy machine-learning stack never touches the SIP process
and a crash only costs one restart. Standard library only at import time.

Protocol (HTTP on 127.0.0.1, bearer token from the environment variable named by --token-env):
    GET  /health      -> {"ready": true, "sample_rate": 24000, "busy": false, ...}
    POST /synthesize  {"text": "...", "seed": 42, "speed": 1.0}
                      -> 200 raw PCM16 mono at X-Sample-Rate (X-Synth-Seconds, X-Audio-Seconds)
                      -> 499 when cancelled, 500 with {"error": "..."} on failure
    POST /cancel      -> aborts the running synthesis between model segments

The model runs on the CPU only (the GPU belongs to the LLM). The weights are the base model
FunAudioLLM/Fun-CosyVoice3-0.5B-2512 with the fine-tuned llm.pt / flow.pt / spk2info.pt of
Thorsten-Voice/CosyVoice3-Hessisch laid over it (see models.py). Usage follows the model card.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INSTRUCT_PROMPT = (
    "You are a helpful assistant.<|endofprompt|>"  # prevents hallucinations in SFT mode
)
MAX_TEXT_CHARS = 600


class Cancelled(Exception):
    """The running synthesis was cancelled."""


class Engine:
    """Loaded CosyVoice3 model plus a lock (one synthesis at a time)."""

    def __init__(
        self, model_dir: Path, repo_root: Path, speaker: str, threads: int, seed: int
    ) -> None:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU only, whatever the host offers
        sys.path.insert(0, str(repo_root / "third_party" / "cosyvoice"))
        sys.path.insert(0, str(repo_root / "third_party" / "Matcha-TTS"))
        import numpy as np
        import torch

        torch.set_num_threads(threads)
        self.np = np
        self.torch = torch
        self.speaker = speaker
        self.default_seed = seed
        self.lock = threading.Lock()
        self.cancel_flag = threading.Event()
        self.busy = False

        started = time.monotonic()
        from cosyvoice.cli.cosyvoice import CosyVoice3

        with _speech_tokenizer_stub(model_dir):
            self.model = CosyVoice3(str(model_dir), load_trt=False, load_vllm=False, fp16=False)
        self.sample_rate = int(self.model.sample_rate)
        if speaker not in self.model.frontend.spk2info:
            known = ", ".join(sorted(self.model.frontend.spk2info)) or "none"
            raise RuntimeError(f"speaker '{speaker}' not in spk2info.pt (available: {known})")
        self._patch_instruct_prompt()
        self.load_seconds = time.monotonic() - started

    def _patch_instruct_prompt(self) -> None:
        frontend = self.model.frontend
        original = frontend.frontend_sft

        def patched(tts_text, spk_id):
            model_input = original(tts_text, spk_id)
            token, length = frontend._extract_text_token(INSTRUCT_PROMPT)
            model_input["prompt_text"] = token
            model_input["prompt_text_len"] = length
            return model_input

        frontend.frontend_sft = patched

    def synthesize(self, text: str, seed: int | None, speed: float) -> tuple[bytes, float]:
        """Return (PCM16 mono bytes at self.sample_rate, seconds spent)."""
        from cosyvoice.utils.common import set_all_random_seed

        with self.lock:
            self.cancel_flag.clear()
            self.busy = True
            started = time.monotonic()
            try:
                set_all_random_seed(self.default_seed if seed is None else seed)
                parts = []
                with self.torch.inference_mode():
                    # text_frontend=False: the built-in frontend only knows Chinese/English;
                    # the caller already normalized the text to plain German words.
                    for output in self.model.inference_sft(
                        text, self.speaker, stream=False, speed=speed, text_frontend=False
                    ):
                        if self.cancel_flag.is_set():
                            raise Cancelled()
                        parts.append(output["tts_speech"])
                if not parts:
                    raise RuntimeError("model returned no audio")
                audio = self.torch.cat(parts, dim=1).numpy().flatten()
                pcm = self.np.clip(self.np.rint(audio * 32768.0), -32768, 32767).astype("<i2")
                return pcm.tobytes(), time.monotonic() - started
            finally:
                self.busy = False


class _speech_tokenizer_stub:  # used like a context manager
    """Skip the 1 GB speech tokenizer when its file is absent (it is unused for SFT inference).

    The frontend opens ``speech_tokenizer_v3.onnx`` at construction although only zero-shot
    cloning needs it. If the file is not downloaded, a stub that fails loudly on use takes its
    place, which saves about 1 GB of download and RAM.
    """

    def __init__(self, model_dir: Path) -> None:
        self.present = (model_dir / "speech_tokenizer_v3.onnx").is_file()

    def __enter__(self):
        if self.present:
            return self
        import onnxruntime

        self._ort = onnxruntime
        self._real = onnxruntime.InferenceSession

        class _Unused:
            def __getattr__(self, name):
                raise RuntimeError("speech tokenizer not installed (only needed for voice cloning)")

        real = self._real

        def patched(path, *args, **kwargs):
            if str(path).endswith("speech_tokenizer_v3.onnx"):
                return _Unused()
            return real(path, *args, **kwargs)

        onnxruntime.InferenceSession = patched
        return self

    def __exit__(self, *exc):
        if not self.present:
            self._ort.InferenceSession = self._real
        return False


def make_handler(engine: Engine, token: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet: the parent logs what matters
            return

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            return hmac.compare_digest(header, f"Bearer {token}")

        def _send_json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._authorized():
                return self._send_json(401, {"error": "unauthorized"})
            if self.path == "/health":
                return self._send_json(
                    200,
                    {
                        "ready": True,
                        "sample_rate": engine.sample_rate,
                        "speaker": engine.speaker,
                        "busy": engine.busy,
                        "load_seconds": round(engine.load_seconds, 1),
                    },
                )
            self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return self._send_json(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length", "0") or 0)
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send_json(400, {"error": "invalid JSON"})
            if self.path == "/cancel":
                engine.cancel_flag.set()
                return self._send_json(200, {"cancelled": engine.busy})
            if self.path != "/synthesize":
                return self._send_json(404, {"error": "not found"})
            text = str(request.get("text", "")).strip()
            if not text or len(text) > MAX_TEXT_CHARS:
                return self._send_json(
                    400, {"error": f"text must have 1..{MAX_TEXT_CHARS} characters"}
                )
            try:
                pcm, seconds = engine.synthesize(
                    text, request.get("seed"), float(request.get("speed", 1.0))
                )
            except Cancelled:
                return self._send_json(499, {"error": "cancelled"})
            except Exception as exc:  # report to the parent instead of dying
                return self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(pcm)))
            self.send_header("X-Sample-Rate", str(engine.sample_rate))
            self.send_header("X-Synth-Seconds", f"{seconds:.3f}")
            self.send_header("X-Audio-Seconds", f"{len(pcm) / 2 / engine.sample_rate:.3f}")
            self.end_headers()
            self.wfile.write(pcm)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CosyVoice3 Hessisch TTS worker")
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--speaker", default="thorsten_hessisch")
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    parser.add_argument("--token-env", default="MORITZ_INTERNAL_TOKEN")
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "")
    if len(token) < 16:
        print(f"{args.token_env} must hold a token of at least 16 characters", file=sys.stderr)
        return 2
    try:
        engine = Engine(args.model_dir, args.repo_root, args.speaker, args.threads, args.seed)
    except Exception as exc:
        print(json.dumps({"event": "error", "error": f"{type(exc).__name__}: {exc}"}), flush=True)
        raise
    server = ThreadingHTTPServer((args.host, args.port), make_handler(engine, token))
    server.daemon_threads = True
    print(
        json.dumps(
            {
                "event": "ready",
                "port": server.server_address[1],
                "sample_rate": engine.sample_rate,
                "load_seconds": round(engine.load_seconds, 1),
            }
        ),
        flush=True,
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

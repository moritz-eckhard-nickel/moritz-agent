# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The real worker logic against a stub of the cosyvoice package (needs torch; skipped without).

The stub mimics exactly the parts of the upstream API the worker touches (CosyVoice3, frontend,
inference_sft, set_all_random_seed); the real model is only exercised by ./test-1.sh check.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from moritz_agent.phone.audio import cosyvoice_worker  # noqa: E402

STUB = """
import torch

class _Frontend:
    def __init__(self):
        self.spk2info = {"thorsten_hessisch": {"embedding": torch.zeros(1, 4)}}
        self.sft_calls = 0
    def _extract_text_token(self, text):
        return torch.tensor([[1, 2, 3]]), torch.tensor([3])
    def frontend_sft(self, tts_text, spk_id):
        self.sft_calls += 1
        return {"text": tts_text}

class CosyVoice3:
    def __init__(self, model_dir, load_trt=False, load_vllm=False, fp16=False, trt_concurrent=1):
        self.sample_rate = 24000
        self.frontend = _Frontend()
    def inference_sft(self, tts_text, spk_id, stream=False, speed=1.0, text_frontend=True):
        assert text_frontend is False and spk_id in self.frontend.spk2info
        model_input = self.frontend.frontend_sft(tts_text, spk_id)
        assert "prompt_text" in model_input, "instruct prompt patch missing"
        for _ in range(3):
            yield {"tts_speech": torch.full((1, 2400), 0.25)}
"""


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    package = root / "third_party" / "cosyvoice" / "cosyvoice"
    (package / "cli").mkdir(parents=True)
    (package / "utils").mkdir(parents=True)
    (root / "third_party" / "Matcha-TTS").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli" / "__init__.py").write_text("")
    (package / "utils" / "__init__.py").write_text("")
    (package / "cli" / "cosyvoice.py").write_text(STUB)
    (package / "utils" / "common.py").write_text("def set_all_random_seed(seed):\n    pass\n")
    monkeypatch.setattr("sys.path", list(__import__("sys").path))
    for name in [
        m for m in list(__import__("sys").modules) if m == "cosyvoice" or m.startswith("cosyvoice.")
    ]:
        monkeypatch.delitem(__import__("sys").modules, name)
    return root


def test_engine_synthesizes_with_instruct_patch_and_speaker_check(fake_repo, tmp_path):
    engine = cosyvoice_worker.Engine(
        tmp_path / "model", fake_repo, "thorsten_hessisch", threads=1, seed=7
    )
    assert engine.sample_rate == 24000
    pcm, seconds = engine.synthesize("Hallo Welt", seed=None, speed=1.0)
    assert len(pcm) == 3 * 2400 * 2  # three segments of 2400 samples, 16 bit
    assert seconds >= 0
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""  # the GPU stays with the LLM


def test_engine_rejects_unknown_speaker(fake_repo, tmp_path):
    with pytest.raises(RuntimeError, match="not in spk2info"):
        cosyvoice_worker.Engine(tmp_path / "model", fake_repo, "gibt_es_nicht", threads=1, seed=1)


def test_engine_cancel_between_segments(fake_repo, tmp_path):
    engine = cosyvoice_worker.Engine(
        tmp_path / "model", fake_repo, "thorsten_hessisch", threads=1, seed=1
    )
    original = engine.model.inference_sft

    def cancelling(*args, **kwargs):
        for output in original(*args, **kwargs):
            engine.cancel_flag.set()  # the caller hangs up after the first segment
            yield output

    engine.model.inference_sft = cancelling
    with pytest.raises(cosyvoice_worker.Cancelled):
        engine.synthesize("Hallo", seed=None, speed=1.0)


def test_http_protocol_with_token(fake_repo, tmp_path):
    engine = cosyvoice_worker.Engine(
        tmp_path / "model", fake_repo, "thorsten_hessisch", threads=1, seed=1
    )
    token = "t" * 32
    server = cosyvoice_worker.ThreadingHTTPServer(
        ("127.0.0.1", 0), cosyvoice_worker.make_handler(engine, token)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:

        def call(path, body=None, auth=True):
            headers = {"Authorization": f"Bearer {token}"} if auth else {}
            data = json.dumps(body).encode() if body is not None else None
            request = urllib.request.Request(
                base + path,
                data=data,
                headers=headers,
                method="POST" if data is not None else "GET",
            )
            return urllib.request.urlopen(request, timeout=10)

        assert json.loads(call("/health").read())["ready"] is True
        response = call("/synthesize", {"text": "Hallo"})
        assert response.headers["X-Sample-Rate"] == "24000" and len(response.read()) == 14400
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            call("/health", auth=False)
        assert unauthorized.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as empty:
            call("/synthesize", {"text": "  "})
        assert empty.value.code == 400
    finally:
        server.shutdown()

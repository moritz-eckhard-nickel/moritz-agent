# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import json

import pytest

from moritz_agent.phone.audio import models
from moritz_agent.phone.audio.tts_cosyvoice import MODEL_FILES


def test_groups_cover_every_voice_and_recognizer():
    assert set(models.GROUPS) == {"stt", "piper", "cosyvoice"}


def test_cosyvoice_manifest_uses_the_hessisch_overlay_for_the_finetuned_weights():
    by_target = {f.target.rsplit("/", 1)[-1]: f for f in models.GROUPS["cosyvoice"]}
    for name in ("llm.pt", "flow.pt", "spk2info.pt"):
        assert by_target[name].repo == models.HESSISCH
    for name in ("hift.pt", "campplus.onnx", "cosyvoice3.yaml"):
        assert by_target[name].repo == models.BASE
    assert sum(f.size for f in models.GROUPS["cosyvoice"]) > 4_000_000_000


def test_engine_preflight_files_are_all_in_the_manifest():
    targets = {
        f.target.split("tts/cosyvoice3-hessisch/", 1)[-1] for f in models.GROUPS["cosyvoice"]
    }
    needed = {name for name in MODEL_FILES if name != "speech_tokenizer_v3.onnx"}
    assert needed <= targets, needed - targets


def test_missing_and_verify_with_trust_on_first_use(tmp_path):
    files = models.GROUPS["piper"]
    assert models.missing(["piper"], tmp_path) == files
    for item in files:
        path = tmp_path / "models" / item.target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * item.size)
    assert models.missing(["piper"], tmp_path) == []
    assert models.verify(files, tmp_path) == []  # first use: checksums are recorded
    recorded = json.loads((tmp_path / "models" / ".checksums.json").read_text())
    assert len(recorded) == len(files)
    changed = tmp_path / "models" / files[0].target
    changed.write_bytes(b"y" * files[0].size)  # same size, different content
    problems = models.verify(files, tmp_path)
    assert len(problems) == 1 and problems[0].startswith(files[0].target)


def test_unknown_group_is_rejected():
    with pytest.raises(ValueError, match="unbekannte Gruppe"):
        models.files_for(["nope"])

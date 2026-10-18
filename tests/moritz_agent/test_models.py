# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import json

import pytest

from moritz_agent.phone.audio import models


def test_groups_cover_voice_and_recognizer():
    assert set(models.GROUPS) == {"stt", "piper"}


def test_piper_manifest_is_the_hessisch_voice():
    files = {f.path: f for f in models.GROUPS["piper"]}
    model = files["Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx"]
    assert model.repo == "Thorsten-Voice/Hessisch"
    assert model.size == 113_800_453
    config = files["Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx.json"]
    assert config.target == model.target + ".json"  # Piper looks for <model>.json next to the model


def test_default_piper_voice_setting_points_into_the_manifest():
    from moritz_agent.config.settings import PiperSettings

    targets = {f"models/{f.target}" for f in models.GROUPS["piper"]}
    assert PiperSettings().voice in targets


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

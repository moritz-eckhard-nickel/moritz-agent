# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Piper engine (Nikita's voice) – everything that works without the 110 MB model file."""

from __future__ import annotations

import json

import pytest

from moritz_agent.config.settings import PiperSettings
from moritz_agent.phone.audio.tts import TtsError
from moritz_agent.phone.audio.tts_piper import PiperEngine

# Structure of Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx.json (shortened symbol table).
HESSISCH_CONFIG = {
    "audio": {"sample_rate": 22050},
    "espeak": {"voice": "de"},
    "inference": {"noise_scale": 0.667, "length_scale": 1, "noise_w": 0.8},
    "phoneme_type": "espeak",
    "phoneme_map": {},
    "phoneme_id_map": {"_": [0], "^": [1], "$": [2], " ": [3], "a": [14], "b": [15], "ə": [59]},
    "num_symbols": 256,
    "num_speakers": 1,
    "speaker_id_map": {},
    "piper_version": "1.0.0",
}


def engine_for(tmp_path, content: bytes | None = None) -> PiperEngine:
    model = tmp_path / "voice.onnx"
    if content is not None:
        model.write_bytes(content)
    return PiperEngine(PiperSettings(voice=str(model)), tmp_path, threads=1)


def test_missing_model_is_reported_not_raised(tmp_path):
    engine = engine_for(tmp_path)
    assert not engine.available()
    with pytest.raises(TtsError, match="fehlt"):
        engine.synthesize("Hallo")


def test_broken_model_does_not_crash_the_phone(tmp_path):
    pytest.importorskip("onnxruntime")
    (tmp_path / "voice.onnx.json").write_text(json.dumps(HESSISCH_CONFIG), encoding="utf-8")
    engine = engine_for(tmp_path, b"this is not an onnx model")
    assert not engine.available()
    with pytest.raises(TtsError):
        engine.synthesize("Hallo")


def test_voice_id_changes_with_the_model_file(tmp_path):
    first = engine_for(tmp_path, b"x" * 10).voice_id
    second = engine_for(tmp_path, b"x" * 11).voice_id
    assert first != second  # a replaced model must not reuse old cached announcements


def test_piper_understands_the_hessisch_voice_config():
    config_module = pytest.importorskip("piper.config")
    config = config_module.PiperConfig.from_dict(HESSISCH_CONFIG)
    assert config.sample_rate == 22050
    assert config.num_speakers == 1

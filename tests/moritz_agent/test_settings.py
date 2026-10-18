# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

from pathlib import Path

import pytest

from moritz_agent.config.settings import REPO_ROOT, SettingsError, load_settings, parse_settings


def example_text() -> str:
    return (REPO_ROOT / "config" / "moritz-agent.example.toml").read_text(encoding="utf-8")


def test_example_config_is_valid_and_has_the_voice_defaults():
    settings = load_settings(REPO_ROOT / "config" / "moritz-agent.example.toml")
    tts = settings.phone.tts
    assert tts.engine == "piper"
    assert tts.fallback_engines == ["espeak"]
    assert "Hessisch" in tts.piper.voice
    assert settings.phone.assistant_name == "Nikita"
    assert settings.phone.max_concurrent_calls == 1


def test_unknown_keys_are_rejected():
    with pytest.raises(SettingsError):
        parse_settings(example_text() + "\n[phone.tts]\nno_such_key = 1\n")


def test_invalid_toml_is_reported():
    with pytest.raises(SettingsError, match="not valid TOML"):
        parse_settings("[phone\n")


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(SettingsError):
        load_settings(tmp_path / "nope.toml")


def test_paths_resolve_relative_to_the_installation(tmp_path):
    settings = parse_settings(example_text())
    assert settings.resolve("models/x", tmp_path) == tmp_path / "models" / "x"
    assert settings.resolve("/abs/y", tmp_path) == Path("/abs/y")


def test_local_config_wins_over_the_example(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "moritz-agent.example.toml").write_text(example_text(), encoding="utf-8")
    local = example_text().replace('assistant_name = "Nikita"', 'assistant_name = "Anna"')
    (tmp_path / "config" / "moritz-agent.toml").write_text(local, encoding="utf-8")
    assert load_settings(root=tmp_path).phone.assistant_name == "Anna"


def test_example_config_documents_every_setting():
    """CLAUDE.md: every configuration key must appear in config/moritz-agent.example.toml."""
    import tomllib

    from pydantic import BaseModel

    from moritz_agent.config.settings import Settings

    data = tomllib.loads(example_text())
    missing: list[str] = []

    def walk(model: type[BaseModel], table: dict, path: list[str]) -> None:
        for name, field in model.model_fields.items():
            if name not in table:
                missing.append(".".join([*path, name]))
            elif isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
                walk(field.annotation, table[name], [*path, name])

    walk(Settings, data, [])
    assert not missing, missing

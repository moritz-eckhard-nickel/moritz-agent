"""Consistency checks for versioned templates and plan-relevant files."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from moritz_agent import __version__
from moritz_agent.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_toml(relative: str) -> dict:
    with (REPO_ROOT / relative).open("rb") as handle:
        return tomllib.load(handle)


def test_example_config_contains_plan_defaults():
    config = load_toml("config/moritz-agent.example.toml")
    assert config["general"]["timezone"] == "Europe/Berlin"
    assert config["server"]["host"] == "127.0.0.1"
    assert config["server"]["port"] == 5001
    assert config["inference"]["context_size"] == 4096
    assert config["phone"]["greeting_text"] == (
        "Hallo Moritz, hier ist Agent. Was kann ich für dich tun?"
    )
    assert config["phone"]["max_concurrent_calls"] == 1
    assert set(config["agent"]["phone"]["tools"]) == {"get_current_time", "web_search"}


def test_example_config_holds_no_credentials():
    text = (REPO_ROOT / "config/moritz-agent.example.toml").read_text(encoding="utf-8")
    for forbidden in ("password =", "passphrase =", "auth_username ="):
        assert forbidden not in text


def test_prompt_catalog_has_required_prompts():
    catalog = load_toml("assets/audio/prompts.de.toml")
    required = {
        "greeting",
        "not_understood",
        "still_there",
        "goodbye",
        "thinking",
        "error_generic",
        "starting_up",
        "timeout",
    }
    assert required <= set(catalog)
    assert all(catalog[name]["required"] for name in required)


def test_versions_lock_parses():
    lock = load_toml("config/versions.lock")
    assert {"koboldcpp", "pjproject", "searxng", "models"} <= set(lock)


@pytest.mark.parametrize(
    "path",
    ["passwords.txt", "passwords.txt.bak", "data/x", "backups/x", "config/moritz-agent.toml"],
)
def test_local_secrets_and_state_are_gitignored(path):
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, check=False)
    assert result.returncode == 0


def test_phone_system_prompt_is_packaged():
    prompt = REPO_ROOT / "moritz_agent/agent/prompts/phone.de.md"
    assert "get_current_time" in prompt.read_text(encoding="utf-8")


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_check_config_does_not_print_secrets():
    template = REPO_ROOT / "config/passwords.template.txt"
    result = subprocess.run(
        [sys.executable, "-m", "moritz_agent", "check-config", "--passwords", str(template)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert "password" not in result.stdout.lower().replace("passwords.txt", "")

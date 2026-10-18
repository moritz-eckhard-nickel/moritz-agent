# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Consistency checks for versioned templates and plan-relevant files."""

from __future__ import annotations

import os
import re
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
    assert config["server"]["host"] == "0.0.0.0"
    assert config["server"]["port"] == 3501
    assert config["server"]["tls"] is True
    assert config["storage"]["transcript_retention_hours"] == 24
    assert "Hessisch" in config["phone"]["tts"]["piper"]["voice"]
    assert config["search"]["backends"][0] == "searxng"
    assert config["inference"]["context_size"] == 4096
    assert config["phone"]["greeting_text"] == (
        "Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?"
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


def test_vendored_vad_model_matches_lock():
    import hashlib

    lock = load_toml("config/versions.lock")["models"]["vad"]
    data = (REPO_ROOT / lock["vendored"]).read_bytes()
    assert len(data) == lock["size_bytes"]
    assert hashlib.sha256(data).hexdigest() == lock["sha256"]


@pytest.mark.parametrize(
    "path",
    [
        "third_party/searxng/searx/webapp.py",
        "third_party/pjproject/pjsip-apps/src/swig/python/Makefile",
        "third_party/VENDORED.md",
        "assets/branding/m-agent-logo.svg",
    ],
)
def test_vendored_components_present(path):
    assert (REPO_ROOT / path).is_file()


def test_all_locks_are_hash_pinned():
    """Python dependencies come from PyPI, but only with exact versions and hashes (ADR-019)."""
    for lock in sorted((REPO_ROOT / "requirements").glob("*.lock")):
        text = lock.read_text(encoding="utf-8")
        pins = [line for line in text.splitlines() if "==" in line and not line.startswith(" ")]
        assert pins, lock.name
        assert text.count("--hash=sha256:") >= len(pins), lock.name


def test_python_packages_are_not_vendored():
    assert not (REPO_ROOT / "third_party/wheels").exists()


@pytest.mark.parametrize(
    "path",
    [
        "assets/branding/scribbles/scribbles-original.png",
        "assets/branding/scribbles/scribbles-black.svg",
        "assets/branding/scribbles/scribbles-white.svg",
        "assets/branding/README.md",
    ],
)
def test_scribbles_mascot_assets_present(path):
    assert (REPO_ROOT / path).is_file()


def test_logo_contains_scribbles_and_icons_match():
    logo = (REPO_ROOT / "assets/branding/m-agent-logo.svg").read_text(encoding="utf-8")
    assert "Scribbles" in logo
    icon = (REPO_ROOT / "assets/branding/m-agent.ico").read_bytes()
    assert (REPO_ROOT / "niko.ico").read_bytes() == icon
    assert (REPO_ROOT / "nikogreen.ico").read_bytes() == icon


def test_koboldcpp_web_uis_removed():
    for name in (
        "klite.embd",
        "kcpp_sdui.embd",
        "lcpp.gz.embd",
        "kcpp_musicui.embd",
        "kcpp_docs.embd",
    ):
        assert not (REPO_ROOT / "embd_res" / name).exists()


def test_msol_license_text_present():
    text = (REPO_ROOT / "LICENSE-MSOL.md").read_text(encoding="utf-8")
    assert text.startswith("MORITZSOFT OPEN LICENSE (MSOL)\nVersion 1.1, March 17, 2026")
    assert "END OF TERMS AND CONDITIONS" in text
    assert (REPO_ROOT / "LICENSE.md").is_file()  # upstream AGPL stays untouched


def own_source_files() -> list[Path]:
    files = [
        p
        for folder in ("moritz_agent", "tests/moritz_agent", "scripts")
        for p in (REPO_ROOT / folder).rglob("*.py")
    ]
    files += [
        REPO_ROOT / name
        for name in (
            "moritz-agent",
            "install.sh",
            "update.sh",
            "moritz-install.sh",
            "moritz-update.sh",
        )
    ]
    return files


def test_own_sources_carry_msol_spdx_header():
    missing = [
        str(p.relative_to(REPO_ROOT))
        for p in own_source_files()
        if "SPDX-License-Identifier: LicenseRef-MSOL-1.1"
        not in "".join(p.read_text(encoding="utf-8").splitlines(keepends=True)[:2])
    ]
    assert not missing, missing


def test_phone_defaults_hessisch_voice_and_hessen():
    config = load_toml("config/moritz-agent.example.toml")
    assert config["phone"]["tts"]["engine"] == "piper"
    assert config["phone"]["tts"]["fallback_engines"] == ["espeak"]
    assert config["fastpaths"]["state"] == "HE"


def test_polly_hans_and_cosyvoice_are_gone():
    assert not list((REPO_ROOT / "requirements").glob("polly.*"))
    assert not list((REPO_ROOT / "requirements").glob("tts.*"))
    assert not (REPO_ROOT / "docs" / "stimme-hans.md").exists()
    assert not (REPO_ROOT / "third_party" / "cosyvoice").exists()
    assert not (REPO_ROOT / "third_party" / "Matcha-TTS").exists()
    template = (REPO_ROOT / "config" / "passwords.template.txt").read_text(encoding="utf-8")
    assert "aws_" not in template
    lock = load_toml("config/versions.lock")
    assert lock["python"]["locks"] == [
        "requirements/core.lock",
        "requirements/phone.lock",
        "requirements/searxng.lock",
    ]
    assert "cosyvoice" not in lock
    for relative in ("core.lock", "phone.lock"):
        text = (REPO_ROOT / "requirements" / relative).read_text(encoding="utf-8")
        assert "\ntorch==" not in text and "\nboto3==" not in text, relative


def test_voice_in_versions_lock_matches_the_download_manifest():
    from moritz_agent.phone.audio import models

    voice = load_toml("config/versions.lock")["models"]["tts_voice"]
    manifest = {f.path: f for f in models.GROUPS["piper"]}
    assert {item["name"] for item in voice["files"]} == set(manifest)
    for item in voice["files"]:
        assert manifest[item["name"]].size == item["size_bytes"]
        assert (
            manifest[item["name"]].target
            == f"{voice['target_dir'].removeprefix('models/')}/{item['name']}"
        )
    assert voice["url_template"].startswith("https://huggingface.co/Thorsten-Voice/Hessisch/")


EXECUTABLE_SCRIPTS = (
    "test-1.sh",
    "install.sh",
    "update.sh",
    "moritz-install.sh",
    "moritz-update.sh",
    "scripts/build-pjsip.sh",
    "scripts/setup-env.sh",
)
LIBRARY_SCRIPTS = ("deploy/lib/common.sh", "deploy/lib/host.sh")  # sourced, not executed


def test_test_script_and_setup_scripts_are_executable_and_licensed():
    for relative in EXECUTABLE_SCRIPTS:
        path = REPO_ROOT / relative
        assert os.access(path, os.X_OK), relative
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("#!/usr/bin/env bash"), relative
        assert lines[1] == "# SPDX-License-Identifier: LicenseRef-MSOL-1.1", relative
    for relative in LIBRARY_SCRIPTS:
        lines = (REPO_ROOT / relative).read_text(encoding="utf-8").splitlines()
        assert lines[1] == "# SPDX-License-Identifier: LicenseRef-MSOL-1.1", relative


def test_shell_scripts_never_trace_commands():
    for relative in (*EXECUTABLE_SCRIPTS, *LIBRARY_SCRIPTS):
        code = [
            line
            for line in (REPO_ROOT / relative).read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        ]
        offending = [line for line in code if re.search(r"\bset\s+-\w*x|xtrace|bash\s+-x", line)]
        assert not offending, (relative, offending)


def test_test_script_help_lists_all_commands():
    result = subprocess.run(
        [str(REPO_ROOT / "test-1.sh"), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    for command in ("setup", "check", "speak", "prompts", "bench", "call", "run", "models"):
        assert f"./test-1.sh {command}" in result.stdout, command


def test_run_command_starts_the_phone_worker(monkeypatch):
    import moritz_agent.phone.__main__ as phone_cli

    seen = []
    monkeypatch.setattr(phone_cli, "main", lambda argv=None: seen.append(argv) or 0)
    assert main(["run"]) == 0
    assert seen == [["run"]]


def test_phone_subcommand_is_passed_through(monkeypatch):
    import moritz_agent.phone.__main__ as phone_cli

    seen = []
    monkeypatch.setattr(phone_cli, "main", lambda argv=None: seen.append(argv) or 0)
    assert main(["phone", "check", "--sip"]) == 0
    assert seen == [["check", "--sip"]]

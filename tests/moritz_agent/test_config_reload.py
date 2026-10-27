# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Validation of both config files and the atomic reload (P1-03, CFG-05, CFG-06, API-02)."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from moritz_agent.config.reload import ConfigError, ConfigManager, diff
from moritz_agent.config.validate import (
    effective_host,
    ensure_private,
    format_report,
    validate_files,
)

ROOT = Path(__file__).resolve().parents[2]
PASSWORDS = (ROOT / "config/passwords.template.txt").read_text(encoding="utf-8")
EXAMPLE = (ROOT / "config/moritz-agent.example.toml").read_text(encoding="utf-8")
SECRET = "Gehe1m!%x;#ü"


@pytest.fixture
def tree(tmp_path) -> Path:
    """A small installation: config, prompt, passwords with a web login, loopback binding."""
    (tmp_path / "config").mkdir()
    toml = EXAMPLE.replace('host = "0.0.0.0"', 'host = "127.0.0.1"')
    (tmp_path / "config" / "moritz-agent.toml").write_text(toml, encoding="utf-8")
    prompt = tmp_path / "moritz_agent" / "agent" / "prompts"
    prompt.mkdir(parents=True)
    shutil.copy2(ROOT / "moritz_agent/agent/prompts/phone.de.md", prompt / "phone.de.md")
    passwords = PASSWORDS.replace("password = agent", f"password = {SECRET}", 1)
    write_passwords(tmp_path, passwords)
    return tmp_path


def write_passwords(root: Path, text: str) -> Path:
    path = root / "passwords.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def edit_toml(root: Path, old: str, new: str) -> None:
    path = root / "config" / "moritz-agent.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def manager(root: Path) -> ConfigManager:
    return ConfigManager(root=root)


# -- validation -------------------------------------------------------------------------------------
def test_a_good_installation_has_no_errors(tree):
    report = validate_files(root=tree)
    assert report.ok, format_report(report)
    assert report.settings is not None and report.passwords is not None


def test_nothing_in_a_report_contains_a_secret(tree):
    write_passwords(tree, PASSWORDS.replace("password = agent", f"password = {SECRET}", 1))
    edit_toml(tree, "port = 3501", 'port = "kaputt"')
    report = validate_files(root=tree)
    assert not report.ok
    assert SECRET not in "\n".join(format_report(report))


@pytest.mark.parametrize("value", ["p%40ss%", "a;b#c", "Müller-Straße ü", "x=y", "[abc]"])
def test_special_characters_survive_the_round_trip(tree, value):
    write_passwords(tree, PASSWORDS.replace("password = agent", f"password = {value}", 1))
    report = validate_files(root=tree)
    assert report.ok and report.passwords.sip.password.reveal() == value


def test_missing_section_and_unknown_toml_key(tree):
    write_passwords(tree, PASSWORDS.replace("[web_login]", "[web_logon]"))
    report = validate_files(root=tree)
    assert any("web_login" in e.message for e in report.errors)
    edit_toml(tree, "[storage]", "[storage]\nbogus_key = 1")
    report = validate_files(root=tree)
    assert any("bogus_key" in e.message for e in report.errors)


def test_empty_sip_password_is_an_error(tree):
    write_passwords(tree, PASSWORDS.replace("password = agent", "password =", 1))
    assert any("password" in e.message for e in validate_files(root=tree).errors)


def test_unknown_timezone_and_bad_source_address(tree):
    edit_toml(tree, 'timezone = "Europe/Berlin"', 'timezone = "Mars/Olympus"')
    edit_toml(tree, 'allowed_source_ips = ["192.168.1.176"]', 'allowed_source_ips = ["nonsense"]')
    messages = [e.message for e in validate_files(root=tree).errors]
    assert any("Zeitzone" in m for m in messages) and any(
        "ungültige Adresse" in m for m in messages
    )


def test_a_reachable_interface_without_a_login_is_kept_local(tree):
    edit_toml(tree, 'host = "127.0.0.1"', 'host = "0.0.0.0"')
    report = validate_files(root=tree)
    assert report.ok and any("API-02" in w.message for w in report.warnings)
    assert effective_host(report.settings, report.passwords) == "127.0.0.1"
    login = PASSWORDS.replace(
        "[web_login]\nusername =\npassword =", "[web_login]\nusername = moritz\npassword = geheim-1"
    )
    write_passwords(tree, login)
    report = validate_files(root=tree)
    assert report.ok and not any("API-02" in w.message for w in report.warnings)
    assert effective_host(report.settings, report.passwords) == "0.0.0.0"


def test_a_loopback_interface_needs_no_login(tree):
    assert validate_files(root=tree).ok


def test_missing_model_and_prompt(tree):
    report = validate_files(root=tree)
    assert any(w.where == "inference" for w in report.warnings)  # the model is large: not shipped
    (tree / "moritz_agent/agent/prompts/phone.de.md").unlink()
    assert any(e.where == "agent" for e in validate_files(root=tree).errors)


def test_tls_files_that_do_not_exist_yet_are_only_a_note(tree):
    report = validate_files(root=tree)
    assert [i.level for i in report.issues if "tls_cert" in i.message] == ["info"]


# -- file permissions (CFG-06) ---------------------------------------------------------------
def test_open_permissions_are_corrected_and_reported(tree):
    path = tree / "passwords.txt"
    path.chmod(0o644)
    issue = ensure_private(path)
    assert issue is not None and issue.level == "warning" and "0644" in issue.message
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_checking_without_fixing_leaves_the_file_alone(tree):
    path = tree / "passwords.txt"
    path.chmod(0o640)
    issue = ensure_private(path, fix=False)
    assert issue is not None and "0640" in issue.message
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_private_files_raise_no_note(tree):
    assert ensure_private(tree / "passwords.txt") is None
    assert ensure_private(tree / "gibt-es-nicht") is None


def test_startup_validation_fixes_the_permissions(tree):
    (tree / "passwords.txt").chmod(0o666)
    report = validate_files(root=tree)
    assert any("0666" in w.message for w in report.warnings)
    assert stat.S_IMODE((tree / "passwords.txt").stat().st_mode) == 0o600


# -- reload ---------------------------------------------------------------------------------------
def test_first_load_failure_carries_the_report(tree):
    write_passwords(tree, "kein ini")
    with pytest.raises(ConfigError) as err:
        manager(tree).load()
    assert err.value.report.errors


def test_reload_swaps_the_snapshot_and_names_the_change(tree):
    cfg = manager(tree)
    first = cfg.load()
    edit_toml(tree, "max_sentences = 3", "max_sentences = 2")
    result = cfg.reload()
    assert result.ok and result.changed == {"settings.agent"} and not result.events
    assert cfg.settings.agent.phone.max_sentences == 2
    assert cfg.current.generation == first.generation + 1 and cfg.current is not first
    assert first.settings.agent.phone.max_sentences == 3  # the old snapshot is untouched


def test_an_invalid_file_is_refused_and_the_old_state_stays(tree):
    cfg = manager(tree)
    old = cfg.load()
    edit_toml(tree, "max_sentences = 3", "max_sentences = 99")
    result = cfg.reload()
    assert not result.ok and result.errors and cfg.current is old
    assert cfg.last_error and "max_sentences" in cfg.last_error
    write_passwords(tree, "[sip]\nusername = x\n")
    assert not cfg.reload().ok and cfg.current is old


def test_a_valid_file_after_an_invalid_one_recovers(tree):
    cfg = manager(tree)
    cfg.load()
    edit_toml(tree, "max_sentences = 3", "max_sentences = 99")
    assert not cfg.reload().ok
    edit_toml(tree, "max_sentences = 99", "max_sentences = 4")
    assert cfg.reload().ok and cfg.last_error is None
    assert cfg.settings.agent.phone.max_sentences == 4


def test_a_new_sip_password_raises_sip_changed(tree):
    cfg = manager(tree)
    cfg.load()
    write_passwords(tree, PASSWORDS.replace("password = agent", "password = anders-1", 1))
    result = cfg.reload()
    assert result.changed == {"passwords.sip"} and result.events == {"sip_changed"}


def test_phone_ports_raise_sip_changed_but_the_greeting_does_not(tree):
    cfg = manager(tree)
    cfg.load()
    edit_toml(tree, "rtp_port_start = 40000", "rtp_port_start = 41000")
    assert cfg.reload().events == {"sip_changed"}
    edit_toml(tree, "Was kann ich für dich tun?", "Wie kann ich helfen?")
    result = cfg.reload()
    assert result.changed == {"settings.phone"} and not result.events


def test_sections_that_need_a_restart_are_named(tree):
    cfg = manager(tree)
    cfg.load()
    edit_toml(tree, "context_size = 51200", "context_size = 65536")
    result = cfg.reload()
    assert result.ok and result.restart_required == {"inference"}


def test_listeners_get_old_new_and_the_diff(tree):
    cfg = manager(tree)
    cfg.load()
    seen = []
    cfg.on_change(
        lambda old, new, result: seen.append((old.generation, new.generation, result.changed))
    )

    async def late(old, new, result):
        seen.append(("async", new.generation))

    cfg.on_change(late)
    edit_toml(tree, "max_sentences = 3", "max_sentences = 2")

    async def scenario():
        cfg.reload()
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert seen == [(1, 2, {"settings.agent"}), ("async", 2)]


def test_polling_reloads_only_after_a_file_changed(tree):
    cfg = manager(tree)
    cfg.load()
    assert cfg.poll() is None
    path = tree / "config" / "moritz-agent.toml"
    edit_toml(tree, "max_sentences = 3", "max_sentences = 2")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    result = cfg.poll()
    assert result is not None and result.ok
    assert cfg.poll() is None


def test_diff_of_identical_snapshots_is_empty(tree):
    cfg = manager(tree)
    snapshot = cfg.load()
    result = diff(snapshot, snapshot)
    assert result.ok and not result.changed and not result.events


def test_summary_has_no_values(tree):
    write_passwords(tree, PASSWORDS)
    cfg = manager(tree)
    cfg.load()
    write_passwords(tree, PASSWORDS.replace("password = agent", f"password = {SECRET}", 1))
    summary = cfg.reload().summary()
    assert SECRET not in repr(summary) and summary["changed"] == ["passwords.sip"]


# -- the command line ---------------------------------------------------------------------------------
def check(tree: Path, passwords: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "-m", "moritz_agent", "check-config",
            "--config", str(tree / "config" / "moritz-agent.toml"),
            "--passwords", str(passwords or tree / "passwords.txt"),
        ],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_check_config_ok_and_without_values(tree):
    result = check(tree)
    assert result.returncode == 0, result.stderr
    assert "Konfiguration: OK" in result.stdout
    assert SECRET not in result.stdout + result.stderr


def test_check_config_reports_errors_without_values(tree):
    write_passwords(
        tree,
        PASSWORDS.replace("password = agent", "password =", 1).replace(
            "port = 5060", "port = 70000"
        ),
    )
    result = check(tree)
    assert result.returncode == 1 and "FEHLER" in result.stderr
    assert not re.search(r"70000", result.stdout + result.stderr)


def test_check_config_does_not_touch_permissions(tree):
    path = tree / "passwords.txt"
    path.chmod(0o644)
    result = check(tree)
    assert "0644" in result.stdout + result.stderr
    assert stat.S_IMODE(path.stat().st_mode) == 0o644

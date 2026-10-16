# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import json
from pathlib import Path

import pytest

from moritz_agent.config.secrets import (
    PasswordsFileError,
    Secret,
    load_passwords,
    parse_passwords,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "config" / "passwords.template.txt"


def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_template_matches_plan_start_values():
    passwords = load_passwords(TEMPLATE)
    sip = passwords.sip
    assert sip.username == "agent"
    assert sip.auth_username == "agent"
    assert sip.password.reveal() == "agent"
    assert sip.display_name == "Agent"
    assert sip.registrar == "192.168.1.176"
    assert sip.port == 5060
    assert sip.transport == "udp"
    assert sip.extension == "999"
    assert not passwords.web_login.enabled
    assert not passwords.sandbox_ssh.enabled
    assert passwords.sandbox_ssh.port == 22


@pytest.mark.parametrize(
    "value",
    ["p%40ss%", "100%sicher", "a;b#c", "Grüße=ÄÖÜß", "%(sip)s", "x" * 64, "with = equals"],
)
def test_special_characters_are_preserved(value):
    text = template_text().replace("password = agent", f"password = {value}", 1)
    assert parse_passwords(text).sip.password.reveal() == value


def test_secret_never_reveals_itself():
    secret = Secret("test-password-123")
    rendered = [str(secret), repr(secret), f"{secret}", f"{secret!r}", "%s" % secret]  # noqa: UP031
    assert all("test-password-123" not in r for r in rendered)
    with pytest.raises(TypeError):
        json.dumps({"password": secret})


def test_web_login_requires_both_values():
    text = template_text().replace("[web_login]\nusername =", "[web_login]\nusername = moritz")
    with pytest.raises(PasswordsFileError, match="both"):
        parse_passwords(text)


def test_web_login_enabled_with_both_values():
    text = template_text().replace(
        "[web_login]\nusername =\npassword =",
        "[web_login]\nusername = moritz\npassword = test-password-123",
    )
    assert parse_passwords(text).web_login.enabled


def test_enabled_sandbox_requires_connection_data():
    text = template_text().replace("enabled = false", "enabled = true")
    with pytest.raises(PasswordsFileError, match="sandbox_ssh"):
        parse_passwords(text)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("port = 5060", "port = abc", "number"),
        ("port = 5060", "port = 70000", "between"),
        ("transport = udp", "transport = carrier-pigeon", "transport"),
        ("registrar = 192.168.1.176", "registrar =", "registrar"),
        ("password = agent", "password =", "password"),
    ],
)
def test_invalid_sip_values_are_rejected(old, new, message):
    with pytest.raises(PasswordsFileError, match=message):
        parse_passwords(template_text().replace(old, new, 1))


def test_missing_section_is_rejected():
    text = template_text().replace("[web_login]", "[not_web_login]")
    with pytest.raises(PasswordsFileError, match=r"\[web_login\]"):
        parse_passwords(text)


@pytest.mark.parametrize(
    "replacement",
    [
        "password = test-password-123\n  continued",  # multi-line value
        "password = agent\ntest-password-123",  # line without "=" (ParsingError quotes it)
        "password = test-password-123\npassword = test-password-123",  # duplicate key
    ],
)
def test_error_messages_do_not_leak_values(replacement):
    text = template_text().replace("password = agent", replacement, 1)
    with pytest.raises(PasswordsFileError) as excinfo:
        parse_passwords(text)
    assert "test-password-123" not in str(excinfo.value)


def test_secret_values_lists_only_non_empty():
    assert parse_passwords(template_text()).secret_values() == ["agent"]


def test_missing_file(tmp_path):
    with pytest.raises(PasswordsFileError, match="does not exist"):
        load_passwords(tmp_path / "passwords.txt")

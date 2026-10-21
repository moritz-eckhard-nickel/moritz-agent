# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Installer helpers: passwords.txt and the configuration are edited line by line (CFG-09, P1-41)."""

from __future__ import annotations

import asyncio
import io
import stat
import sys

import httpx
import pytest

from moritz_agent.config.secrets import parse_passwords
from moritz_agent.config.settings import parse_settings
from moritz_agent.setup import __main__ as cli
from moritz_agent.setup import discord as setup_discord
from moritz_agent.setup import files

from .system_util import BOT_TOKEN, CHANNEL_ID, OWNER_ID, ROOT

OLD_PASSWORDS = """# meine Notizen
[sip]
username = agent
auth_username = agent
password = Sup3r%Geheim;
display_name = Anton
registrar = 192.168.1.176
port = 5060
transport = udp
extension = 999

[web_login]
username = moritz
password = Web#Pw

[sandbox_ssh]
enabled = false

[optional_services]
tankerkoenig_api_key = abc
"""


def template() -> str:
    return (ROOT / "config" / "passwords.template.txt").read_text(encoding="utf-8")


# -- appending and replacing -------------------------------------------------------------------------------
def test_an_old_passwords_file_gets_the_discord_section_appended_and_nothing_else_changes():
    new, added = files.migrate_passwords(OLD_PASSWORDS)
    assert added == ["discord"] and new.startswith(OLD_PASSWORDS)
    assert "[discord]" in new[len(OLD_PASSWORDS) :] and "bot_token =" in new
    parsed = parse_passwords(new)
    assert not parsed.discord.enabled and parsed.sip.password.reveal() == "Sup3r%Geheim;"
    again, nothing = files.migrate_passwords(new)
    assert again == new and nothing == []


def test_missing_keys_of_an_existing_section_are_added_in_place():
    text = OLD_PASSWORDS + f"\n[discord]\nbot_token = {BOT_TOKEN}\n\n[later]\nx = 1\n"
    new, added = files.migrate_passwords(text)
    assert added == ["discord.channel_id", "discord.admin_pin"]
    assert new.index("channel_id") < new.index("[later]") and f"bot_token = {BOT_TOKEN}" in new
    assert parse_passwords(new.split("[later]")[0]).discord.bot_token.reveal() == BOT_TOKEN


def test_set_value_replaces_one_line_and_keeps_everything_else():
    text = template()
    new = files.set_value(text, "discord", "bot_token", BOT_TOKEN)
    old_lines, new_lines = text.splitlines(), new.splitlines()
    changed = [(a, b) for a, b in zip(old_lines, new_lines, strict=True) if a != b]
    assert changed == [("bot_token =", f"bot_token = {BOT_TOKEN}")]
    assert parse_passwords(new).discord.bot_token.reveal() == BOT_TOKEN
    assert files.get_value(new, "discord", "bot_token") == BOT_TOKEN
    assert (
        files.get_value(new, "discord", "nope") is None
        and files.get_value(new, "gibtsnicht", "x") is None
    )


def test_set_value_adds_missing_keys_and_sections_without_touching_the_rest():
    new = files.set_value("[a]\nx = 1\n\n[b]\ny = 2\n", "a", "z", "3")
    assert new == "[a]\nx = 1\nz = 3\n\n[b]\ny = 2\n"
    assert files.set_value("[a]\nx = 1\n", "b", "y", "2") == "[a]\nx = 1\n\n[b]\ny = 2\n"
    assert files.set_value("", "b", "y", "2") == "\n[b]\ny = 2\n"


def test_writes_are_atomic_and_keep_mode(tmp_path):
    path = tmp_path / "passwords.txt"
    path.write_text(OLD_PASSWORDS, encoding="utf-8")
    path.chmod(0o600)
    setup_discord.store_token(path, BOT_TOKEN)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text(encoding="utf-8")
    assert text.startswith(OLD_PASSWORDS) and f"bot_token = {BOT_TOKEN}" in text
    assert not list(tmp_path.glob(".passwords.txt.*"))  # no temp file is left behind
    parsed = parse_passwords(text)
    assert parsed.sip.password.reveal() == "Sup3r%Geheim;" and parsed.discord.enabled


def test_enable_discord_changes_two_lines_of_the_configuration(tmp_path):
    example = (ROOT / "config" / "moritz-agent.example.toml").read_text(encoding="utf-8")
    config = tmp_path / "moritz-agent.toml"
    config.write_text(example, encoding="utf-8")
    config.chmod(0o640)
    assert setup_discord.enable_discord(config, [OWNER_ID])
    new = config.read_text(encoding="utf-8")
    changed = [
        (a, b) for a, b in zip(example.splitlines(), new.splitlines(), strict=True) if a != b
    ]
    assert len(changed) == 2 and stat.S_IMODE(config.stat().st_mode) == 0o640
    settings = parse_settings(new)
    assert settings.discord.enabled and settings.discord.owner_user_ids == [OWNER_ID]
    # a second run (or owners that are already there) changes nothing
    assert not setup_discord.enable_discord(config, ["999"])
    assert parse_settings(config.read_text(encoding="utf-8")).discord.owner_user_ids == [OWNER_ID]


def test_enable_discord_on_an_old_configuration_without_the_section(tmp_path):
    config = tmp_path / "moritz-agent.toml"
    config.write_text('# alt\n[general]\ntimezone = "Europe/Berlin"\n', encoding="utf-8")
    setup_discord.enable_discord(config, [OWNER_ID])
    settings = parse_settings(config.read_text(encoding="utf-8"))
    assert settings.discord.enabled and settings.general.timezone == "Europe/Berlin"


# -- the token and the channel through the (fake) REST API --------------------------------------------------------------
def api(handler=None):
    def default(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.headers["authorization"] != f"Bot {BOT_TOKEN}":
            return httpx.Response(401)
        if path.endswith("/users/@me"):
            return httpx.Response(200, json={"id": "7000", "username": "Anton"})
        if path.endswith("/applications/@me"):
            return httpx.Response(
                200,
                json={
                    "id": "7000",
                    "bot_public": False,
                    "flags": 1 << 19,
                    "owner": {"id": OWNER_ID},
                },
            )
        if path.endswith("/users/@me/guilds"):
            return httpx.Response(200, json=[{"id": "9000", "name": "Zuhause"}])
        if path.endswith("/guilds/9000/channels"):
            return httpx.Response(
                200,
                json=[
                    {"id": CHANNEL_ID, "type": 0, "name": "anton", "position": 0},
                    {"id": "5550002", "type": 0, "name": "allgemein", "position": 1},
                    {"id": "5550003", "type": 2, "name": "Sprache", "position": 2},
                ],
            )
        if path.endswith(f"/channels/{CHANNEL_ID}"):
            return httpx.Response(
                200, json={"id": CHANNEL_ID, "type": 0, "name": "anton", "guild_id": "9000"}
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler or default)


@pytest.fixture
def files_in(tmp_path):
    passwords = tmp_path / "passwords.txt"
    passwords.write_text(OLD_PASSWORDS, encoding="utf-8")
    passwords.chmod(0o600)
    config = tmp_path / "moritz-agent.toml"
    config.write_text((ROOT / "config" / "moritz-agent.example.toml").read_text(encoding="utf-8"))
    return passwords, config


def test_a_good_token_is_stored_checked_and_never_printed(files_in):
    passwords, config = files_in
    out = io.StringIO()
    code = asyncio.run(
        setup_discord.setup_token(passwords, config, BOT_TOKEN + "\n", out=out, transport=api())
    )
    shown = out.getvalue()
    assert code == 0 and BOT_TOKEN not in shown and "Anton" in shown and OWNER_ID in shown
    assert "client_id=7000" in shown
    assert (
        parse_passwords(passwords.read_text(encoding="utf-8")).discord.bot_token.reveal()
        == BOT_TOKEN
    )
    settings = parse_settings(config.read_text(encoding="utf-8"))
    assert settings.discord.enabled and settings.discord.owner_user_ids == [OWNER_ID]


def test_a_wrong_token_is_not_stored(files_in):
    passwords, config = files_in
    before = passwords.read_text(encoding="utf-8")
    out = io.StringIO()
    wrong = "x" * 40
    code = asyncio.run(
        setup_discord.setup_token(passwords, config, wrong, out=out, transport=api())
    )
    assert code == 1 and "abgelehnt" in out.getvalue() and wrong not in out.getvalue()
    assert passwords.read_text(encoding="utf-8") == before
    assert not parse_settings(config.read_text(encoding="utf-8")).discord.enabled


def test_nonsense_instead_of_a_token_is_refused_before_asking_discord(files_in):
    passwords, config = files_in
    for text in ("", "kurz", "mit Leerzeichen drin, das ist kein Token"):
        out = io.StringIO()
        called: list[httpx.Request] = []

        def handler(request: httpx.Request, seen: list[httpx.Request] = called) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        transport = api(handler)
        assert (
            asyncio.run(
                setup_discord.setup_token(passwords, config, text, out=out, transport=transport)
            )
            == 2
        )
        assert not called


def test_the_home_channel_is_chosen_by_list_number_or_id(files_in):
    passwords, _ = files_in
    setup_discord.store_token(passwords, BOT_TOKEN)

    def channel(answer):
        out = io.StringIO()
        code = asyncio.run(
            setup_discord.setup_channel(passwords, BOT_TOKEN, answer, out=out, transport=api())
        )
        return code, out.getvalue()

    code, listing = channel("")
    assert code == 3 and "Zuhause / #anton" in listing and "Sprache" not in listing
    assert files.get_value(passwords.read_text(encoding="utf-8"), "discord", "channel_id") == ""
    assert channel("1")[0] == 0
    assert parse_passwords(passwords.read_text(encoding="utf-8")).discord.channel_id == CHANNEL_ID
    assert channel("99")[0] == 3  # not on the list: show it again
    code, _ = channel("5550002")  # a channel id Anton cannot see
    assert code == 1


def test_command_line_migrate_token_and_pin(files_in, monkeypatch, capsys):
    passwords, config = files_in
    args = ["--passwords", str(passwords), "--config", str(config)]
    assert cli.main([*args, "migrate"]) == 0 and "discord" in capsys.readouterr().out
    assert cli.main([*args, "migrate"]) == 0 and "vollständig" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.StringIO(BOT_TOKEN + "\n"))
    assert cli.main([*args, "discord-token", "--no-check"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO("12 34\n"))
    assert cli.main([*args, "discord-pin"]) == 2
    monkeypatch.setattr(sys, "stdin", io.StringIO("4711\n"))
    assert cli.main([*args, "discord-pin"]) == 0
    printed = capsys.readouterr()
    assert BOT_TOKEN not in printed.out + printed.err and "4711" not in printed.out + printed.err
    parsed = parse_passwords(passwords.read_text(encoding="utf-8"))
    assert (
        parsed.discord.bot_token.reveal() == BOT_TOKEN
        and parsed.discord.admin_pin.reveal() == "4711"
    )
    assert cli.main([*args, "discord-channel"]) in {
        1,
        3,
    }  # needs the network – refused, not crashed


def test_old_default_names_switch_to_anton_but_own_choices_stay():
    from moritz_agent.setup.files import rename_assistant

    config = (
        'assistant_name = "Nikita"         # Name\n'
        'greeting_text = "Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?"\n'
        'initial_prompt = "Nikita, Moritz, Weilburg, Limburg."   # hilft\n'
        "name_trigger = true\n"
    )
    text, count = rename_assistant(config)
    assert count == 3
    assert 'assistant_name = "Anton"         # Name' in text
    assert "hier ist Anton. Was kann" in text and '"Anton, Moritz, Weilburg' in text
    own = 'assistant_name = "Nikita die Große"\ngreeting_text = "Servus, hier ist Nikita!"\n'
    assert rename_assistant(own) == (own, 0)
    passwords = "[sip]\nusername = agent\ndisplay_name = Nikita\n"
    assert rename_assistant(passwords) == (passwords.replace("= Nikita", "= Anton"), 1)

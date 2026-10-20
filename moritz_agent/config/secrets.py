# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Loader for passwords.txt, the single source of credentials (CFG-01 ... CFG-04, ADR-012).

The file is parsed strictly as data with configparser (no interpolation, no shell
sourcing), so percent signs and other special characters in values are preserved
(CFG-03). Secret values are wrapped in :class:`Secret` so they never end up in
logs, reprs or API responses by accident (PHONE-44, docs/plan/08-sicherheit.md §3).

Still open for ticket P1-03: file permission checks/fixes (CFG-06), reload handling
(CFG-05) and change detection for SIP re-registration (PHONE-08).
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

VALID_SIP_TRANSPORTS = ("udp", "tcp", "tls")
VALID_SSH_AUTH_METHODS = ("key", "password")


class PasswordsFileError(ValueError):
    """passwords.txt is missing, malformed or invalid. Messages never contain secret values."""


class Secret:
    """A credential value that refuses to reveal itself in str/repr/format."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the plain value. Call only where the credential is actually used."""
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return "Secret('***')"

    def __str__(self) -> str:
        return "***"

    def __format__(self, format_spec: str) -> str:
        return "***"


@dataclass(frozen=True)
class SipCredentials:
    username: str
    auth_username: str
    password: Secret
    display_name: str
    registrar: str
    port: int
    transport: str
    extension: str


@dataclass(frozen=True)
class WebLogin:
    username: str
    password: Secret

    @property
    def enabled(self) -> bool:
        """Web login is usable only when both values are set (CFG-04)."""
        return bool(self.username) and bool(self.password)


@dataclass(frozen=True)
class SandboxSsh:
    enabled: bool
    host: str
    port: int
    username: str
    auth_method: str
    password: Secret
    private_key_path: str
    private_key_passphrase: Secret
    host_key_fingerprint: str


@dataclass(frozen=True)
class DiscordCredentials:
    """``[discord]``: the token of the bot and the default text channel (ids are no secrets)."""

    bot_token: Secret = field(default_factory=lambda: Secret(""))
    channel_id: str = ""
    admin_pin: Secret = field(default_factory=lambda: Secret(""))

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)


@dataclass(frozen=True)
class Passwords:
    sip: SipCredentials
    web_login: WebLogin
    sandbox_ssh: SandboxSsh
    optional_services: dict[str, Secret]
    discord: DiscordCredentials = field(default_factory=DiscordCredentials)

    def secret_values(self) -> list[str]:
        """All non-empty secret values, e.g. to feed the log redaction filter."""
        values = [
            self.sip.password,
            self.web_login.password,
            self.sandbox_ssh.password,
            self.sandbox_ssh.private_key_passphrase,
            self.discord.bot_token,
            self.discord.admin_pin,
            *self.optional_services.values(),
        ]
        return [s.reveal() for s in values if s]


def _new_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        interpolation=None,
        strict=True,
        empty_lines_in_values=False,
        comment_prefixes=("#", ";"),
        inline_comment_prefixes=None,
    )
    parser.optionxform = str  # type: ignore[assignment,method-assign]  # keep key case
    return parser


def _get(section: configparser.SectionProxy, key: str, default: str | None = None) -> str:
    if key in section:
        value = section[key].strip()
        if "\n" in value:
            # configparser joins indented follow-up lines into multi-line values.
            raise PasswordsFileError(f"[{section.name}] {key} must be a single line")
        return value
    if default is not None:
        return default
    raise PasswordsFileError(f"[{section.name}] is missing the key '{key}'")


def _port(section: configparser.SectionProxy, key: str, default: str) -> int:
    raw = _get(section, key, default)
    try:
        port = int(raw)
    except ValueError:
        raise PasswordsFileError(f"[{section.name}] {key} must be a number") from None
    if not 1 <= port <= 65535:
        raise PasswordsFileError(f"[{section.name}] {key} must be between 1 and 65535")
    return port


def _bool(section: configparser.SectionProxy, key: str, default: str) -> bool:
    raw = _get(section, key, default).lower()
    if raw in ("true", "yes", "1", "on"):
        return True
    if raw in ("false", "no", "0", "off", ""):
        return False
    raise PasswordsFileError(f"[{section.name}] {key} must be true or false")


def _section(parser: configparser.ConfigParser, name: str) -> configparser.SectionProxy:
    if not parser.has_section(name):
        raise PasswordsFileError(f"section [{name}] is missing")
    return parser[name]


def parse_passwords(text: str, source: str = "passwords.txt") -> Passwords:
    """Parse and validate the content of passwords.txt."""
    parser = _new_parser()
    try:
        parser.read_string(text, source=source)
    except configparser.Error as exc:
        # configparser messages may quote the offending line, which can contain a secret.
        raise PasswordsFileError(f"{source} is not valid INI ({type(exc).__name__})") from None

    sip_section = _section(parser, "sip")
    sip = SipCredentials(
        username=_get(sip_section, "username"),
        auth_username=_get(sip_section, "auth_username", "") or _get(sip_section, "username"),
        password=Secret(_get(sip_section, "password")),
        display_name=_get(sip_section, "display_name", ""),
        registrar=_get(sip_section, "registrar"),
        port=_port(sip_section, "port", "5060"),
        transport=_get(sip_section, "transport", "udp").lower(),
        extension=_get(sip_section, "extension", ""),
    )
    for key in ("username", "registrar"):
        if not getattr(sip, key):
            raise PasswordsFileError(f"[sip] {key} must not be empty")
    if not sip.password:
        raise PasswordsFileError("[sip] password must not be empty")
    if sip.transport not in VALID_SIP_TRANSPORTS:
        raise PasswordsFileError(
            f"[sip] transport must be one of {', '.join(VALID_SIP_TRANSPORTS)}"
        )

    web_section = _section(parser, "web_login")
    web = WebLogin(
        username=_get(web_section, "username", ""),
        password=Secret(_get(web_section, "password", "")),
    )
    if bool(web.username) != bool(web.password):
        raise PasswordsFileError("[web_login] username and password must both be set or both empty")

    ssh_section = _section(parser, "sandbox_ssh")
    ssh = SandboxSsh(
        enabled=_bool(ssh_section, "enabled", "false"),
        host=_get(ssh_section, "host", ""),
        port=_port(ssh_section, "port", "22"),
        username=_get(ssh_section, "username", ""),
        auth_method=_get(ssh_section, "auth_method", "").lower(),
        password=Secret(_get(ssh_section, "password", "")),
        private_key_path=_get(ssh_section, "private_key_path", ""),
        private_key_passphrase=Secret(_get(ssh_section, "private_key_passphrase", "")),
        host_key_fingerprint=_get(ssh_section, "host_key_fingerprint", ""),
    )
    if ssh.enabled:
        for key in ("host", "username", "host_key_fingerprint"):
            if not getattr(ssh, key):
                raise PasswordsFileError(f"[sandbox_ssh] {key} is required when enabled = true")
        if ssh.auth_method not in VALID_SSH_AUTH_METHODS:
            raise PasswordsFileError(
                f"[sandbox_ssh] auth_method must be one of {', '.join(VALID_SSH_AUTH_METHODS)}"
            )
        if ssh.auth_method == "password" and not ssh.password:
            raise PasswordsFileError(
                "[sandbox_ssh] password is required for auth_method = password"
            )
        if ssh.auth_method == "key" and not ssh.private_key_path:
            raise PasswordsFileError(
                "[sandbox_ssh] private_key_path is required for auth_method = key"
            )

    optional: dict[str, Secret] = {}
    if parser.has_section("optional_services"):
        optional = {k: Secret(v.strip()) for k, v in parser["optional_services"].items()}

    discord = DiscordCredentials()
    if parser.has_section("discord"):
        section = parser["discord"]
        token = _get(section, "bot_token", "")
        channel = _get(section, "channel_id", "")
        if any(char.isspace() for char in token):
            raise PasswordsFileError("[discord] bot_token must not contain blanks")
        if channel and not channel.isdigit():
            raise PasswordsFileError("[discord] channel_id must be the numeric id of the channel")
        discord = DiscordCredentials(
            bot_token=Secret(token),
            channel_id=channel,
            admin_pin=Secret(_get(section, "admin_pin", "")),
        )

    return Passwords(
        sip=sip, web_login=web, sandbox_ssh=ssh, optional_services=optional, discord=discord
    )


def load_passwords(path: Path) -> Passwords:
    """Read and validate passwords.txt from disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PasswordsFileError(f"{path} does not exist") from None
    except UnicodeDecodeError:
        raise PasswordsFileError(f"{path} is not valid UTF-8") from None
    return parse_passwords(text, source=str(path))

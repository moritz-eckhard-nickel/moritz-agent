# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Setting up the bot: check the token, read the application, invite links, home channel (docs/plan/14 §14).

Talks to the Discord REST API with ``httpx`` – no gateway, no discord.py needed. The token is only
ever put into the ``Authorization`` header; it is never printed, logged or put in an error message.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

API = "https://discord.com/api/v10"
INVITE = "https://discord.com/oauth2/authorize"

# Bit positions of the permissions Anton asks for (docs/plan/14 §14.1) – no admin rights.
PERMISSION_BITS = {
    "add_reactions": 6,
    "view_channel": 10,
    "send_messages": 11,
    "embed_links": 14,
    "attach_files": 15,
    "read_message_history": 16,
    "connect": 20,
    "speak": 21,
    "use_voice_activation": 25,
    "create_public_threads": 35,
    "send_messages_in_threads": 38,
    "send_voice_messages": 46,
}
FLAG_MESSAGE_CONTENT = 1 << 18  # application flags: Message Content Intent (approved bots)
FLAG_MESSAGE_CONTENT_LIMITED = 1 << 19  # … switched on in the Developer Portal (small bots)
TEXT_CHANNEL_TYPES = {0, 5}  # text, announcement
VOICE_CHANNEL_TYPES = {2, 13}  # voice, stage
BIO = (
    "Guude! Ich bin Anton ✨ Moritz’ kleiner Helfer aus Weilburg – Telefon 999, Wetter, Uhrzeit & "
    "ganz viel Quatsch. Frag mich einfach 🐾"
)


def permissions_value() -> int:
    return sum(1 << bit for bit in PERMISSION_BITS.values())


def invite_links(application_id: int | str) -> list[str]:
    """Invite links for the server installation and the user installation."""
    guild = urlencode(
        {
            "client_id": application_id,
            "scope": "bot applications.commands",
            "permissions": permissions_value(),
        }
    )
    user = urlencode(
        {"client_id": application_id, "scope": "applications.commands", "integration_type": 1}
    )
    return [
        f"Server (Anton holen): {INVITE}?{guild}",
        f"Benutzer-App (nur Befehle überall, NICHT für deinen Server): {INVITE}?{user}",
    ]


class DiscordApiError(RuntimeError):
    """The Discord API refused or could not be reached. Never contains the token."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Check:
    """One line of the self-check: ``level`` is ok, warn or error."""

    level: str
    text: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    application_id: str = ""
    owner_ids: list[str] = field(default_factory=list)
    guilds: dict[str, str] = field(default_factory=dict)  # id → name

    def add(self, level: str, text: str) -> None:
        self.checks.append(Check(level, text))

    @property
    def ok(self) -> bool:
        return not any(c.level == "error" for c in self.checks)


class DiscordRest:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=API,
            headers={"Authorization": f"Bot {token}", "User-Agent": "moritz-agent (setup)"},
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> DiscordRest:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DiscordApiError(f"Discord nicht erreichbar ({type(exc).__name__})") from None
        if response.status_code == 401:
            raise DiscordApiError("Der Bot-Token wurde abgelehnt", 401)
        if response.status_code == 429:
            raise DiscordApiError(
                "Discord bremst gerade (zu viele Anfragen), bitte gleich noch einmal", 429
            )
        if response.status_code >= 400:
            raise DiscordApiError(
                f"Discord antwortet mit {response.status_code}", response.status_code
            )
        return response.json() if response.content else {}

    # -- reading ------------------------------------------------------------------------------------
    async def me(self) -> dict[str, Any]:
        return await self.call("GET", "/users/@me")  # type: ignore[no-any-return]

    async def application(self) -> dict[str, Any]:
        return await self.call("GET", "/applications/@me")  # type: ignore[no-any-return]

    async def guilds(self) -> list[dict[str, Any]]:
        return await self.call("GET", "/users/@me/guilds")  # type: ignore[no-any-return]

    async def channel(self, channel_id: str) -> dict[str, Any]:
        return await self.call("GET", f"/channels/{channel_id}")  # type: ignore[no-any-return]

    async def text_channels(self, guild_id: str) -> list[dict[str, Any]]:
        channels = await self.call("GET", f"/guilds/{guild_id}/channels")
        return sorted(
            (c for c in channels if c.get("type") in TEXT_CHANNEL_TYPES),
            key=lambda c: (c.get("position", 0), c["name"]),
        )

    async def voice_channels(self, guild_id: str) -> list[dict[str, Any]]:
        channels = await self.call("GET", f"/guilds/{guild_id}/channels")
        return sorted(
            (c for c in channels if c.get("type") in VOICE_CHANNEL_TYPES),
            key=lambda c: (c.get("position", 0), c["name"]),
        )

    # -- writing ---------------------------------------------------------------------------------------
    async def say(self, channel_id: str, text: str) -> dict[str, Any]:
        body = {"content": text[:2000], "allowed_mentions": {"parse": []}}
        return await self.call("POST", f"/channels/{channel_id}/messages", json=body)  # type: ignore[no-any-return]

    async def set_profile(self, avatar_png: bytes | None, bio: str | None) -> None:
        if avatar_png is not None:
            image = "data:image/png;base64," + base64.b64encode(avatar_png).decode("ascii")
            await self.call("PATCH", "/users/@me", json={"avatar": image})
        if bio is not None:
            await self.call("PATCH", "/applications/@me", json={"description": bio})


def no_server_hint(application: dict[str, Any]) -> str:
    """Why Anton sees no server – the usual reason is the wrong one of the two invite links."""
    if application.get("approximate_user_install_count") and not application.get(
        "approximate_guild_count"
    ):
        return (
            "Anton ist nur als Benutzer-App installiert, auf keinem Server. Für deinen Server den "
            "Link „Server (Anton holen)“ öffnen – nicht „Benutzer-App“."
        )
    return (
        "Anton ist noch auf keinem Server – den Link „Server (Anton holen)“ öffnen und deinen "
        "Server auswählen (invite zeigt ihn)."
    )


def owner_ids_of(application: dict[str, Any]) -> list[str]:
    """The person (or the team members) behind the application – candidates for ``owner_user_ids``."""
    team = application.get("team")
    if team:
        return [
            str(m["user"]["id"]) for m in team.get("members", []) if m.get("membership_state") == 2
        ]
    owner = application.get("owner")
    return [str(owner["id"])] if owner else []


async def check(
    token: str,
    channel_id: str = "",
    configured_owners: list[str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Report:
    """Token, application settings, servers and home channel – in plain German."""
    report = Report()
    async with DiscordRest(token, transport=transport) as rest:
        try:
            me = await rest.me()
        except DiscordApiError as exc:
            report.add("error", str(exc))
            return report
        report.add("ok", f"Token gültig: Bot „{me.get('username', '?')}“")
        try:
            app = await rest.application()
        except DiscordApiError as exc:
            report.add("warn", f"Anwendungsdaten nicht lesbar ({exc})")
            app = {}
        report.application_id = str(app.get("id", me.get("id", "")))
        report.owner_ids = owner_ids_of(app)
        if app:
            if app.get("bot_public"):
                report.add(
                    "warn",
                    "„Public Bot“ ist an – jeder könnte Anton auf seinen Server holen. "
                    "Im Developer Portal unter Bot ausschalten.",
                )
            else:
                report.add("ok", "„Public Bot“ ist aus")
            flags = int(app.get("flags", 0))
            if flags & (FLAG_MESSAGE_CONTENT | FLAG_MESSAGE_CONTENT_LIMITED):
                report.add("ok", "Message Content Intent ist an")
            else:
                report.add(
                    "error",
                    "Der Message Content Intent ist aus – ohne ihn sieht Anton keine Nachrichten. "
                    "Im Developer Portal unter Bot einschalten.",
                )
            if configured_owners is not None and report.owner_ids:
                missing = [o for o in report.owner_ids if o not in configured_owners]
                if missing and not configured_owners:
                    report.add(
                        "warn",
                        "owner_user_ids ist leer – Besitzer der Anwendung: "
                        + ", ".join(report.owner_ids),
                    )
        try:
            report.guilds = {str(g["id"]): g["name"] for g in await rest.guilds()}
        except DiscordApiError as exc:
            # never report "no server" when the list simply could not be read
            report.add("error", f"Die Serverliste ist nicht lesbar ({exc})")
            report.guilds = {}
        else:
            if report.guilds:
                report.add("ok", "Anton ist auf: " + ", ".join(report.guilds.values()))
            else:
                report.add("warn", no_server_hint(app))
        if channel_id:
            try:
                channel = await rest.channel(channel_id)
            except DiscordApiError as exc:
                report.add(
                    "error", f"Standardkanal nicht erreichbar ({exc}) – ID und Rechte prüfen"
                )
            else:
                if channel.get("type") not in TEXT_CHANNEL_TYPES:
                    report.add("error", "Die Kanal-ID gehört nicht zu einem Textkanal")
                elif str(channel.get("guild_id")) not in report.guilds:
                    report.add("error", "Der Kanal liegt auf einem Server, auf dem Anton nicht ist")
                else:
                    report.add("ok", f"Standardkanal: #{channel.get('name', '?')}")
        else:
            report.add(
                "warn", "Kein Standardkanal (channel_id) – Hinweise gehen dann per Direktnachricht"
            )
    return report

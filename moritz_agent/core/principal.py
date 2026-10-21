# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Who is asking: role, identity and personal settings (docs/plan/14 §5.1, ADR-035).

Roles hang on the unchangeable Discord user id, never on names or server roles.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from moritz_agent.config.settings import Discord


class Role(StrEnum):
    OWNER = "owner"
    TRUSTED = "trusted"
    GUEST = "guest"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        return {"owner": 3, "trusted": 2, "guest": 1, "unknown": 0}[self.value]

    def at_least(self, other: Role) -> bool:
        return self.rank >= other.rank


@dataclass(frozen=True)
class Principal:
    id: str  # "discord:123…", "phone:20", "web:moritz"
    role: Role
    channel: str  # phone | discord | web
    name: str = ""
    home_postal_code: str | None = None
    home_name: str | None = None
    quiet_hours: str | None = None
    voice_reply: str | None = None

    @property
    def user_id(self) -> str:
        return self.id.split(":", 1)[-1]

    def short(self) -> str:
        """For logs: only the last four characters of the id."""
        return "…" + self.user_id[-4:]


# Whoever owns the Discord application (or its team) is always an owner – also when
# ``owner_user_ids`` is empty or out of date (Moritz, 21.10.2026). The Discord worker learns it at
# login and tells the main process (``/internal/discord/app-owners``); each process keeps it here.
_APP_OWNERS: set[str] = set()


def remember_app_owners(ids: list[str] | set[str] | tuple[str, ...]) -> None:
    _APP_OWNERS.clear()
    _APP_OWNERS.update(str(i) for i in ids if str(i).isdigit())


def owner_ids(cfg: Discord) -> list[str]:
    """Configured owners first, then the owner(s) of the Discord application."""
    return [*cfg.owner_user_ids, *sorted(_APP_OWNERS - set(cfg.owner_user_ids))]


def discord_role(cfg: Discord, user_id: str) -> Role:
    """Owner / trusted by the configured lists and the application owner; guests only if
    ``guest_mode`` allows them."""
    if user_id in cfg.owner_user_ids or user_id in _APP_OWNERS:
        return Role.OWNER
    if user_id in cfg.trusted_user_ids:
        return Role.TRUSTED
    return Role.GUEST if cfg.guest_mode == "skills" else Role.UNKNOWN

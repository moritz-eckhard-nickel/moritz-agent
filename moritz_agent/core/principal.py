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


def discord_role(cfg: Discord, user_id: str) -> Role:
    """Owner / trusted by the configured lists; guests only if ``guest_mode`` allows them."""
    if user_id in cfg.owner_user_ids:
        return Role.OWNER
    if user_id in cfg.trusted_user_ids:
        return Role.TRUSTED
    return Role.GUEST if cfg.guest_mode == "skills" else Role.UNKNOWN

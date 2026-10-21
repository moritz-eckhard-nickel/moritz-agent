# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Names of the conversations: one per DM, text channel, thread and voice session (docs/plan/14 §4.3)."""

from __future__ import annotations


def dm(user_id: str | int) -> str:
    return f"discord:dm:{user_id}"


def channel(channel_id: str | int) -> str:
    return f"discord:ch:{channel_id}"


def thread(thread_id: str | int) -> str:
    return f"discord:th:{thread_id}"


def voice(channel_id: str | int) -> str:
    return f"discord:vc:{channel_id}"


def reply_target(
    kind: str, *, user_id: str | int = "", channel_id: str | int = "", default_id: str = ""
) -> str:
    """Where a reminder asked for here is delivered later."""
    if kind == "dm":
        return f"dm:{user_id}"
    if kind in {"guild", "thread"} and str(channel_id) != str(default_id):
        return f"channel:{channel_id}"
    return "default"

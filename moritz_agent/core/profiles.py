# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Output profiles per surface (docs/plan/14 §4.1): how long, whether markdown is allowed."""

from __future__ import annotations

from dataclasses import dataclass

from moritz_agent.core.surface import Surface


@dataclass(frozen=True)
class OutputProfile:
    name: str
    surface: Surface
    max_answer_tokens: int
    max_sentences: int | None  # None = no sentence limit
    markdown: bool
    prompt_file: str


PHONE = OutputProfile(
    "phone", Surface.SPOKEN, 160, 3, False, "moritz_agent/agent/prompts/phone.de.md"
)
DISCORD_VOICE = OutputProfile(
    "discord_voice", Surface.SPOKEN, 160, 3, False, "moritz_agent/agent/prompts/phone.de.md"
)
DISCORD_CHAT = OutputProfile(
    "discord_chat", Surface.CHAT, 600, None, True, "moritz_agent/agent/prompts/discord_chat.de.md"
)

PROFILES = {p.name: p for p in (PHONE, DISCORD_VOICE, DISCORD_CHAT)}

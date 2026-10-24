# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Agent profiles: one model, different instructions, tools and limits (AGENT-02, PHONE-45)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from moritz_agent.config.settings import Settings

# tools no profile of Part 1 may use (PHONE-45: no shell, no SSH, no sandbox)
FORBIDDEN_TOOLS = frozenset({"shell", "ssh", "sandbox", "run_command", "write_file"})
# only where something is spoken: the phone and the Discord voice channel can hang up, a chat cannot
SPOKEN_TOOLS = frozenset({"end_call"})


@dataclass(frozen=True)
class Profile:
    name: str
    system_prompt: str
    tools: frozenset[str]
    max_tool_steps: int = 3
    max_answer_tokens: int = 160
    temperature: float = 0.3
    deadline_s: float = 15.0  # AGENT-04: the whole turn, tool calls included
    max_sentences: int = 3  # AGENT-07
    max_chars: int = 450
    invalid_retries: int = 2  # AGENT-03
    speak: bool = True  # clean the answer for speech
    notes: list[str] = field(default_factory=list)


CUTE_STYLE = (
    "Schreib wie ein guter Kumpel, frech und ein bisschen süß, ohne Emojis – höchstens ein Textsmiley wie :) oder :3; "
    "die Fakten bleiben exakt; "
    "bei Warnungen und Fehlern sachlich."
)


def render_prompt(text: str, settings: Settings, **extra: str) -> str:
    """Fill the few variables of a prompt file ({assistant}, {home_name}, {home_postal_code}, …)."""
    home = settings.skills.home
    values = {
        "assistant": settings.phone.assistant_name,
        "home_name": home.name,
        "home_postal_code": home.postal_code,
        **extra,
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text.strip()


def phone_profile(settings: Settings, root: Path) -> Profile:
    cfg = settings.agent.phone
    path = settings.resolve(cfg.system_prompt_file, root)
    prompt = render_prompt(path.read_text(encoding="utf-8"), settings)
    tools = (frozenset(cfg.tools) | SPOKEN_TOOLS) - FORBIDDEN_TOOLS
    return Profile(
        name="phone",
        system_prompt=prompt,
        tools=tools,
        max_tool_steps=cfg.max_tool_steps,
        max_answer_tokens=cfg.max_answer_tokens,
        temperature=cfg.temperature,
        deadline_s=cfg.deadline_s,
        max_sentences=cfg.max_sentences,
    )


def chat_profile(settings: Settings, root: Path) -> Profile:
    """Discord text and web: markdown allowed, longer answers, sources as links (docs/plan/14 §4.1)."""
    from moritz_agent.core.profiles import DISCORD_CHAT

    cfg = settings.agent.phone
    path = settings.resolve(DISCORD_CHAT.prompt_file, root)
    style = CUTE_STYLE if settings.discord.style == "cute" else ""
    prompt = render_prompt(path.read_text(encoding="utf-8"), settings, style=style)
    return Profile(
        name=DISCORD_CHAT.name,
        system_prompt=prompt,
        tools=frozenset(cfg.tools) - FORBIDDEN_TOOLS - SPOKEN_TOOLS,
        max_tool_steps=cfg.max_tool_steps,
        max_answer_tokens=DISCORD_CHAT.max_answer_tokens,
        temperature=cfg.temperature,
        deadline_s=max(cfg.deadline_s, 30.0),
        max_sentences=12,
        max_chars=1800,
        speak=False,
    )

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Agent profiles: one model, different instructions, tools and limits (AGENT-02, PHONE-45)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from moritz_agent.config.settings import Settings

# tools no profile of Part 1 may use (PHONE-45: no shell, no SSH, no sandbox)
FORBIDDEN_TOOLS = frozenset({"shell", "ssh", "sandbox", "run_command", "write_file"})


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


def render_prompt(text: str, settings: Settings) -> str:
    """Fill the few variables of a prompt file ({assistant}, {home_name}, {home_postal_code})."""
    home = settings.skills.home
    values = {
        "assistant": settings.phone.assistant_name,
        "home_name": home.name,
        "home_postal_code": home.postal_code,
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text.strip()


def phone_profile(settings: Settings, root: Path) -> Profile:
    cfg = settings.agent.phone
    path = settings.resolve(cfg.system_prompt_file, root)
    prompt = render_prompt(path.read_text(encoding="utf-8"), settings)
    tools = frozenset(cfg.tools) - FORBIDDEN_TOOLS
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

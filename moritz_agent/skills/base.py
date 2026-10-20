# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Types shared by all instant-answer skills (docs/plan/13 §3.3)."""

from __future__ import annotations

import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from moritz_agent.config.settings import Settings, Skills
from moritz_agent.skills.clock import Clock
from moritz_agent.skills.text.normalize import Utterance

if TYPE_CHECKING:
    from moritz_agent.skills.geo.gazetteer import Gazetteer, Place


# -- results -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Source:
    """Where a fact came from (shown on request and in the footer of Discord cards)."""

    name: str
    url: str = ""
    license: str = ""
    retrieved: datetime | None = None


@dataclass(frozen=True)
class Action:
    """A follow-up the user can trigger with one tap (Discord button) or by saying it."""

    label: str
    say: str  # the utterance that would trigger it, e.g. "und morgen"


@dataclass(frozen=True)
class Card:
    """Structured result for chat surfaces (Discord embed, web card)."""

    title: str
    description: str = ""
    fields: tuple[tuple[str, str, bool], ...] = ()  # (name, value, inline)
    color: str = "neutral"  # neutral|good|info|warn|alert|danger
    footer: str = ""


@dataclass(frozen=True)
class Option:
    label: str
    params: dict[str, Any]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Clarification:
    """A question back to the user with a few options ("Welches Neustadt meinst du?")."""

    question: str
    options: tuple[Option, ...]
    skill_id: str = ""


@dataclass
class FollowupState:
    """What a follow-up question ("Und morgen?") may inherit from the last answer."""

    skill_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    text: str | None = None  # spoken form (digits are fine, the voice front end spells them out)
    prompt: str | None = None  # or a pre-recorded announcement
    hangup: bool = False
    data: dict[str, Any] | None = None
    sources: tuple[Source, ...] = ()
    followup: FollowupState | None = None
    detail: str | None = None  # the answer to "Mehr Details"
    stale_s: int | None = None
    markdown: str | None = None
    card: Card | None = None
    actions: tuple[Action, ...] = ()
    clarify: Clarification | None = None
    tempo: float | None = None  # new speaking speed factor for the rest of the call
    loudness_db: float | None = None
    start_timer: tuple[float, str] | None = None  # (seconds, label)
    serious: bool = False  # chat surfaces: no jokes, no emojis (warnings, errors)
    thinking_prompt: str | None = None  # announcement to play first while data is fetched
    reminder: tuple[datetime, str] | None = (
        None  # (when, text): chat surfaces keep it, restart-proof
    )


# -- context -------------------------------------------------------------------------------
@dataclass
class SkillContext:
    """State of one conversation (one call, one chat) for follow-ups and small helpers."""

    started: float
    seed: int = 0
    turn: int = 0
    last: FollowupState | None = None
    last_turn: int = -99
    last_at: float = -1e9
    pending: Clarification | None = None
    last_text: str = ""
    last_detail: str | None = None
    last_sources: tuple[Source, ...] = ()
    tempo: float = 1.0
    loudness_db: float = 0.0
    used: set[str] = field(default_factory=set)  # jokes etc. already told in this conversation
    timers: list[tuple[float, str]] = field(default_factory=list)  # (monotonic deadline, label)
    place_mentions: int = 0
    heard: list[str] = field(default_factory=list)  # what the user said, newest last
    home: Place | None = None  # personal home town (Discord users), None = skills.home
    thinking_prompt: str | None = None  # announcement for "Moment, ich schaue nach" this turn
    role: str = "owner"  # owner | trusted | guest: who asks (notes are Moritz' only)
    user_id: str | None = None  # Discord user id (reminders belong to a person)
    rng: random.Random = field(default_factory=random.Random)


# -- request -------------------------------------------------------------------------------
@dataclass
class Services:
    """Everything a skill may use besides the utterance."""

    settings: Settings
    clock: Clock
    root: Path
    rng: random.Random = field(default_factory=random.Random)
    gazetteer: Gazetteer | None = None
    providers: Any = None  # moritz_agent.skills.providers.Providers (None = offline)
    status_fn: Callable[[], dict[str, Any]] | None = None
    version: str = ""
    started_at: float = 0.0
    assistant_name: str = "Nikita"
    store: Any = None  # notes / reminders store (P1-27)
    db: Any = None  # moritz_agent.storage.Database
    repo: Any = None  # moritz_agent.storage.Repo (calls, tool calls, missed questions)
    secrets: dict[str, Any] = field(default_factory=dict)  # optional_services of passwords.txt

    @property
    def cfg(self) -> Skills:
        return self.settings.skills

    @property
    def timezone(self) -> str:
        return self.settings.general.timezone

    def now(self) -> datetime:
        return self.clock.now(self.timezone)


@dataclass
class Request:
    utt: Utterance
    match: re.Match[str]
    ctx: SkillContext
    svc: Services
    skill: Skill
    overrides: dict[str, Any] = field(default_factory=dict)
    surface: str = "spoken"  # "spoken" | "chat"

    @property
    def now(self) -> datetime:
        return self.svc.now()

    @property
    def text(self) -> str:
        return self.utt.text

    def pick(self, options: tuple[str, ...] | list[str]) -> str:
        """Deterministic variation per conversation and turn (stable in tests)."""
        if len(options) == 1 or not self.svc.cfg.answer_variation:
            return options[0]
        return options[(self.ctx.seed + self.ctx.turn) % len(options)]


Handler = Callable[[Request], Awaitable[SkillResult | None]]
FollowupFn = Callable[[str, SkillContext, Services, "FollowupState"], dict[str, Any] | None]


@dataclass(frozen=True)
class Skill:
    id: str
    group: str
    patterns: tuple[tuple[re.Pattern[str], float], ...]
    handler: Handler
    exclude: tuple[re.Pattern[str], ...] = ()
    examples: tuple[str, ...] = ()
    online: bool = False
    priority: str = "S"  # M (must) / S (should) / K (could)
    max_words: int = 16
    help: str = ""  # short German name for the help text, e.g. "Wetter"
    followup: FollowupFn | None = None
    chat_only: bool = False


class SkillProtocol(Protocol):  # documentation of the public surface
    id: str
    group: str

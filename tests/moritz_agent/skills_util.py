# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Helpers for the instant-answer tests: a fixed clock and a synchronous ``ask``."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from moritz_agent.config.settings import Settings, load_settings
from moritz_agent.skills.base import Services, SkillContext
from moritz_agent.skills.clock import FixedClock
from moritz_agent.skills.router import Outcome, Router, new_context
from moritz_agent.skills.services import build_services

BERLIN = ZoneInfo("Europe/Berlin")
# Sunday, 18 October 2026, 19:12 – the day the plan examples use
SUNDAY_EVENING = datetime(2026, 10, 18, 19, 12, tzinfo=BERLIN)


class Session:
    """One conversation with a fixed clock; ``say`` returns the spoken text (or None)."""

    def __init__(
        self,
        at: datetime = SUNDAY_EVENING,
        settings: Settings | None = None,
        providers: object | None = None,
        surface: str = "spoken",
        seed: int = 1,
    ) -> None:
        self.clock = FixedClock(at)
        self.svc: Services = build_services(
            settings or load_settings(), clock=self.clock, seed=seed, providers=providers
        )
        self.router = Router(self.svc)
        self.ctx: SkillContext = new_context(self.svc, seed=seed)
        self.surface = surface
        self.last: Outcome | None = None

    def route(self, text: str) -> Outcome:
        self.last = asyncio.run(self.router.route(text, self.ctx, surface=self.surface))
        return self.last

    def say(self, text: str) -> str | None:
        outcome = self.route(text)
        if outcome.result is None:
            return None
        return outcome.result.text or outcome.result.prompt

    def skill(self, text: str) -> str | None:
        outcome = self.route(text)
        return outcome.skill_id if outcome.result is not None else None


def ask(text: str, at: datetime = SUNDAY_EVENING) -> str | None:
    return Session(at).say(text)

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


def weather_session(
    routes: dict | None = None,
    at: datetime = SUNDAY_EVENING,
    *,
    calls: list | None = None,
    settings: Settings | None = None,
    cache_dir=None,
    surface: str = "spoken",
) -> Session:
    """A session whose data services answer from the weather fixtures (no network)."""
    import tempfile
    from pathlib import Path

    from moritz_agent.skills.providers import Providers

    from . import weather_fixtures as wf

    table = {
        "api.open-meteo.com/v1/forecast": wf.open_meteo_answer(),
        "api.brightsky.dev/alerts": wf.alerts_answer(),
        "api.brightsky.dev/current_weather": wf.bright_sky_current(),
        "api.brightsky.dev/weather": wf.bright_sky_weather(),
        "opendata.dwd.de/climate_environment/health/alerts/s31fg.json": wf.pollen_answer(),
        "warnung.bund.de/api31/dashboard/065330000000.json": wf.nina_answer(),
        "air-quality-api.open-meteo.com/v1/air-quality": wf.air_quality_answer(),
        "www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml": wf.ecb_xml(),
        "api.energy-charts.info/price": wf.energy_charts_answer(),
        "creativecommons.tankerkoenig.de/json/list.php": wf.tankerkoenig_answer(),
        "www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json": wf.pegel_answer(),
        "api.openligadb.de/getmatchdata/bl1/2026": wf.liga_matches(),
        "api.openligadb.de/getbltable/bl1/2026": wf.liga_table(),
        "www.tagesschau.de/api2u/homepage/": wf.news_answer(),
    }
    table.update(routes or {})
    directory = Path(cache_dir) if cache_dir else Path(tempfile.mkdtemp(prefix="skills-cache-"))

    def make(svc: Services):
        return Providers(svc, transport=wf.mock_transport(table, calls), cache_dir=directory)

    return Session(at, settings=settings, providers=make, surface=surface)

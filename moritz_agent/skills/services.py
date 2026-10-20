# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Build the shared services of the skills (clock, settings, places, data services)."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path

from moritz_agent import __version__
from moritz_agent.config.settings import REPO_ROOT, Settings, load_settings
from moritz_agent.skills.base import Services
from moritz_agent.skills.clock import Clock, SystemClock


def build_services(
    settings: Settings | None = None,
    root: Path = REPO_ROOT,
    *,
    clock: Clock | None = None,
    seed: int | None = None,
    load_places: bool = True,
    providers: object | Callable[[Services], object] | None = None,
    database: object | None = None,
) -> Services:
    settings = settings or load_settings(root=root)
    clock = clock or SystemClock()
    svc = Services(
        settings=settings,
        clock=clock,
        root=root,
        rng=random.Random(seed),
        version=__version__,
        started_at=clock.monotonic(),
        assistant_name=settings.phone.assistant_name,
        providers=None if callable(providers) else providers,
    )
    if load_places:
        try:
            from moritz_agent.skills.geo.gazetteer import Gazetteer

            svc.gazetteer = Gazetteer.load(root)
            home = settings.skills.home
            svc.gazetteer.set_home(home.postal_code, home.name, home.latitude, home.longitude)
        except ModuleNotFoundError:
            svc.gazetteer = None
    from moritz_agent.skills.store import NotesStore
    from moritz_agent.storage import Database, Repo

    svc.db = database or Database(root / settings.storage.database)
    svc.store = NotesStore(svc.db)
    svc.repo = Repo(svc.db, store_transcripts=settings.storage.store_transcripts)
    if callable(providers):
        svc.providers = providers(svc)
    return svc

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The schema watchdog: ask the real data services once and check only shape and plausibility.

Not part of the normal run (marker ``network``): ``pytest -m network tests/moritz_agent/test_skills_network.py``.
Meant for a weekly manual or CI run – it tells when Open-Meteo, Bright Sky, DWD, NINA, Pegelonline, the ECB
or Energy-Charts change their answers, long before a caller notices (docs/plan/13 §12, risk R14).
A service that is down is reported as a skip, a changed shape as a failure.
"""

from __future__ import annotations

import asyncio

import pytest

from moritz_agent.config.settings import REPO_ROOT, load_settings
from moritz_agent.skills.providers import Providers, ProviderUnavailable
from moritz_agent.skills.providers.http import HttpError
from moritz_agent.skills.services import build_services
from moritz_agent.skills.slots.where import home_place
from moritz_agent.storage import Database

pytestmark = pytest.mark.network


@pytest.fixture
def svc(tmp_path):
    settings = load_settings(root=REPO_ROOT)
    settings.skills.online = True
    return build_services(
        settings, REPO_ROOT, providers=Providers, database=Database(tmp_path / "net.sqlite3")
    )


def ask(coroutine):
    try:
        return asyncio.run(coroutine)
    except (HttpError, ProviderUnavailable) as exc:
        pytest.skip(f"Dienst nicht erreichbar: {exc}")


def test_every_configured_service_answers_in_the_expected_shape(svc):
    results = ask(svc.providers.check_all())
    assert results, "check_all() lieferte nichts"
    broken = [(name, detail) for name, ok, _ms, detail in results if not ok]
    markers = (
        "unreachable",
        "nicht erreichbar",
        "offline",
        "ProxyError",
        "ConnectError",
        "Timeout",
    )
    unreachable = [item for item in broken if any(word in item[1] for word in markers)]
    if len(unreachable) == len(results):
        pytest.skip("kein Internet")
    assert not [item for item in broken if item not in unreachable], broken


def test_the_forecast_is_plausible(svc):
    home = home_place(svc)
    pack = ask(svc.providers.weather(home, need="forecast")).data
    assert len(pack.days) >= 7 and len(pack.hours) >= 24
    for day in pack.days[:7]:
        assert -40 <= day.tmin <= day.tmax <= 50
        assert 0 <= (day.precipitation_sum or 0) < 400
    current = pack.current
    assert current is not None and -40 <= current.temperature <= 50
    assert 800 <= (current.pressure or 1000) <= 1100


def test_the_warnings_have_levels_and_times(svc):
    warnings = ask(svc.providers.alerts(home_place(svc))).data
    for warning in warnings:
        assert 1 <= warning.level <= 4 and warning.event
        assert warning.end is None or warning.end >= warning.start


def test_pollen_air_and_water_levels(svc):
    home = home_place(svc)
    pollen = ask(svc.providers.pollen(home)).data
    assert pollen.partregion and pollen.today
    air = ask(svc.providers.air_quality(home)).data
    assert air.aqi is None or 0 <= air.aqi <= 500
    gauges = ask(svc.providers.water_levels(home)).data
    assert all(0 <= gauge.level_cm < 2000 for gauge in gauges if gauge.level_cm is not None)


def test_exchange_rates_and_power_prices(svc):
    rates = ask(svc.providers.exchange_rates()).data
    assert 0.2 < rates.rate("USD") < 5
    today = svc.now().date()
    prices = ask(svc.providers.power_prices(today)).data
    assert prices and all(-500 < p.eur_per_mwh < 3000 for p in prices)

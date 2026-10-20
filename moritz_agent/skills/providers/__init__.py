# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The data services behind the skills: one container with cache, status and fallbacks.

``Providers`` is what ``Services.providers`` holds. Every method returns ``Fetched`` (data plus
where it came from and how old it is) or raises ``ProviderUnavailable`` – the skills turn that into
an honest answer (docs/plan/13 §3.7).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from zoneinfo import ZoneInfo

import httpx

from moritz_agent.logging_setup import get_logger
from moritz_agent.skills.geo.gazetteer import Place, fold
from moritz_agent.skills.providers import brightsky, open_meteo
from moritz_agent.skills.providers.brightsky import Warning
from moritz_agent.skills.providers.cache import Cache
from moritz_agent.skills.providers.http import HttpClient, HttpError
from moritz_agent.skills.weather.model import WeatherPack

if TYPE_CHECKING:
    from moritz_agent.skills.base import Services

log = get_logger("skill")
T = TypeVar("T")

GEOCODE_TTL_S = 30 * 24 * 3600
BACKOFF_429_S = 15 * 60


class ProviderUnavailable(Exception):
    """No data: ``reason`` is ``disabled`` (skills.online = false), ``offline`` or ``empty``."""

    def __init__(self, service: str, reason: str) -> None:
        super().__init__(f"{service}: {reason}")
        self.service = service
        self.reason = reason


@dataclass
class Fetched(Generic[T]):
    data: T
    source: str  # open-meteo | brightsky | …
    cache: str = "miss"  # hit | miss | stale
    age_s: float = 0.0
    fell_back: bool = False  # the fallback service answered


@dataclass
class ServiceStatus:
    state: str = "ready"  # ready | degraded | disabled
    last_ok: float | None = None  # unix time
    last_error: str = ""
    failures: int = 0


@dataclass
class _Flight:
    task: asyncio.Task[Any]
    waiters: int = 0


def _place_to_dict(place: Place) -> dict[str, Any]:
    data = asdict(place)
    data["postal_codes"] = list(place.postal_codes)
    return data


def _place_from_dict(data: dict[str, Any]) -> Place:
    data = dict(data)
    data["postal_codes"] = tuple(data.get("postal_codes", ()))
    return Place(**data)


class Providers:
    def __init__(
        self,
        svc: Services,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.svc = svc
        self.http = HttpClient(svc.cfg, transport=transport)
        if cache_dir is None:
            cache_dir = svc.root / svc.cfg.cache_dir
        self.cache = Cache(cache_dir, svc.clock)
        self.status: dict[str, ServiceStatus] = {}
        self._blocked_until: dict[str, float] = {}
        self._flights: dict[str, _Flight] = {}
        self._parsed: dict[tuple[str, float], WeatherPack] = {}
        self._prefetch_task: asyncio.Task[None] | None = None
        self._extra_prefetch: list[Callable[[Place], Awaitable[str]]] = []
        self._checks: dict[str, Callable[[Place], Awaitable[str]]] = {}

    # -- configuration ------------------------------------------------------------------------
    @property
    def cfg(self):
        return self.svc.cfg

    def refresh_config(self) -> None:
        self.http.configure(self.cfg)

    @property
    def online(self) -> bool:
        return self.cfg.online

    # -- bookkeeping --------------------------------------------------------------------------
    def _state(self, service: str) -> ServiceStatus:
        return self.status.setdefault(service, ServiceStatus())

    def _ok(self, service: str) -> None:
        state = self._state(service)
        if state.state == "degraded":
            log.info("Datendienst %s ist wieder erreichbar", service)
        state.state, state.failures, state.last_error = "ready", 0, ""
        state.last_ok = self.svc.clock.now("UTC").timestamp()

    def _failed(self, service: str, exc: Exception) -> None:
        state = self._state(service)
        if state.state != "degraded":
            log.warning("Datendienst %s nicht erreichbar: %s", service, exc)
        state.state = "degraded"
        state.failures += 1
        state.last_error = str(exc)[:200]
        if isinstance(exc, HttpError) and exc.status == 429:
            self._blocked_until[service] = self.svc.clock.monotonic() + BACKOFF_429_S

    def _blocked(self, service: str) -> bool:
        return self._blocked_until.get(service, 0.0) > self.svc.clock.monotonic()

    def snapshot(self) -> dict[str, Any]:
        """Status for the status file and the CLI (no URLs, no query strings)."""
        now = self.svc.clock.now("UTC").timestamp()
        out: dict[str, Any] = {}
        for name, state in sorted(self.status.items()):
            out[name] = {
                "state": "disabled" if not self.online else state.state,
                "last_ok": state.last_ok,
                "age_s": None if state.last_ok is None else round(now - state.last_ok),
                "last_error": state.last_error,
            }
        return out

    async def _once(self, key: str, make: Callable[[], Awaitable[T]]) -> T:
        """Concurrent identical requests share one fetch."""
        flight = self._flights.get(key)
        if flight is None:
            task = asyncio.ensure_future(make())
            flight = self._flights[key] = _Flight(task)
            task.add_done_callback(lambda _t, k=key: self._flights.pop(k, None))
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        flight.waiters += 1
        try:
            return await asyncio.shield(flight.task)
        finally:
            flight.waiters -= 1

    # -- weather ------------------------------------------------------------------------------
    def _weather_key(self, provider: str, place: Place) -> str:
        cfg = self.cfg.weather
        return f"{provider}:{place.lat:.{cfg.coordinate_decimals}f},{place.lon:.{cfg.coordinate_decimals}f}:{cfg.model}"

    def _parse_cached(
        self, entry_value: dict[str, Any], stored_at: float, place: Place
    ) -> WeatherPack:
        provider = entry_value["provider"]
        tz = place.tz if place.tz else self.svc.timezone
        marker = (f"{provider}:{place.lat:.2f},{place.lon:.2f}", stored_at)
        pack = self._parsed.get(marker)
        if pack is not None:
            return pack
        fetched = datetime.fromtimestamp(stored_at, ZoneInfo(tz))
        if provider == "open-meteo":
            pack = open_meteo.parse_forecast(entry_value["raw"], fetched, tz)
        else:
            pack = brightsky.parse_weather(entry_value["raw"], fetched, tz, place)
        if len(self._parsed) > 16:
            self._parsed.clear()
        self._parsed[marker] = pack
        return pack

    async def weather(
        self, place: Place, *, need: str = "forecast", on_miss: Callable[[], None] | None = None
    ) -> Fetched[WeatherPack]:
        """Weather pack for ``place``: fresh cache, else network (with fallback), else stale cache."""
        cfg = self.cfg.weather
        fresh_s = (
            cfg.cache_current_minutes if need == "current" else cfg.cache_forecast_minutes
        ) * 60
        stale_s = cfg.max_stale_hours * 3600
        providers = [cfg.provider] + ([cfg.fallback_provider] if cfg.fallback_provider else [])
        entry = None
        for name in providers:
            found = self.cache.get(
                "weather", self._weather_key(name, place), fresh_s=fresh_s, stale_s=stale_s
            )
            if found and (entry is None or found.stored_at > entry.stored_at):
                entry, _used = found, name
        if entry is not None and entry.fresh:
            try:
                pack = self._parse_cached(entry.value, entry.stored_at, place)
                return Fetched(pack, pack.source, "hit", entry.age_s)
            except HttpError:
                entry = None
        if not self.online:
            if entry is not None:
                return self._stale(entry, place)
            raise ProviderUnavailable("weather", "disabled")
        if on_miss is not None:
            on_miss()  # the caller may play "Moment, ich schaue nach dem Wetter"
        try:
            return await self._once(
                f"weather:{self._weather_key('any', place)}", lambda: self._fetch_weather(place)
            )
        except ProviderUnavailable:
            if entry is not None:
                return self._stale(entry, place)
            raise

    def _stale(self, entry, place: Place) -> Fetched[WeatherPack]:
        pack = self._parse_cached(entry.value, entry.stored_at, place)
        return Fetched(pack, pack.source, "stale", entry.age_s)

    async def _fetch_weather(self, place: Place) -> Fetched[WeatherPack]:
        cfg = self.cfg.weather
        tz = place.tz or self.svc.timezone
        now = self.svc.clock.now(tz)
        names = [cfg.provider] + ([cfg.fallback_provider] if cfg.fallback_provider else [])
        errors: list[str] = []
        for index, name in enumerate(names):
            if self._blocked(name):
                errors.append(f"{name}: wartet nach zu vielen Anfragen")
                continue
            try:
                if name == "open-meteo":
                    raw = await open_meteo.fetch_forecast(self.http, place, cfg, tz)
                    pack = open_meteo.parse_forecast(raw, now, tz)
                else:
                    raw = await brightsky.fetch_weather(self.http, place, cfg, tz, now.date())
                    pack = brightsky.parse_weather(raw, now, tz, place)
            except HttpError as exc:
                self._failed(name, exc)
                errors.append(f"{name}: {exc}")
                continue
            self._ok(name)
            self.cache.put(
                "weather", self._weather_key(name, place), {"provider": name, "raw": raw}
            )
            return Fetched(pack, name, "miss", 0.0, fell_back=index > 0)
        raise ProviderUnavailable("weather", "offline")

    async def observed(self, place: Place) -> tuple[Any, str, float | None]:
        """Latest DWD station measurement near ``place`` (Bright Sky): (values, station, km)."""
        if not self.online:
            raise ProviderUnavailable("observed", "disabled")
        tz = place.tz or self.svc.timezone
        try:
            raw = await self.http.get_json(
                self.cfg.weather.brightsky_url.rstrip("/") + "/current_weather",
                {"lat": f"{place.lat:.2f}", "lon": f"{place.lon:.2f}", "tz": tz, "units": "dwd"},
            )
        except HttpError as exc:
            self._failed("brightsky", exc)
            raise ProviderUnavailable("observed", "offline") from exc
        self._ok("brightsky")
        return brightsky.parse_current(raw, tz)

    # -- warnings -----------------------------------------------------------------------------
    async def alerts(self, place: Place) -> Fetched[list[Warning]]:
        cfg = self.cfg.warnings
        key = f"alerts:{place.lat:.2f},{place.lon:.2f}"
        fresh_s, stale_s = cfg.refresh_minutes * 60, 30 * 60
        entry = self.cache.get("alerts", key, fresh_s=fresh_s, stale_s=stale_s)
        tz = place.tz or self.svc.timezone
        if entry is not None and entry.fresh:
            return Fetched(brightsky.parse_alerts(entry.value, tz), "dwd", "hit", entry.age_s)
        if not self.online:
            if entry is not None:
                return Fetched(brightsky.parse_alerts(entry.value, tz), "dwd", "stale", entry.age_s)
            raise ProviderUnavailable("alerts", "disabled")
        if not self._blocked("brightsky-alerts"):
            try:
                raw = await brightsky.fetch_alerts(self.http, place, self.cfg.weather, tz)
            except HttpError as exc:
                self._failed("brightsky-alerts", exc)
            else:
                self._ok("brightsky-alerts")
                self.cache.put("alerts", key, raw)
                return Fetched(brightsky.parse_alerts(raw, tz), "dwd", "miss", 0.0)
        if entry is not None:
            return Fetched(brightsky.parse_alerts(entry.value, tz), "dwd", "stale", entry.age_s)
        raise ProviderUnavailable("alerts", "offline")

    # -- geocoding ----------------------------------------------------------------------------
    async def geocode(self, name: str) -> Place | None:
        """Online fallback for names the gazetteer does not know (cached for 30 days)."""
        key = fold(name)
        if not key:
            return None
        entry = self.cache.get("geocode", key, fresh_s=GEOCODE_TTL_S, stale_s=GEOCODE_TTL_S)
        if entry is not None:
            return _place_from_dict(entry.value) if entry.value else None
        if not self.online or self._blocked("geocoding"):
            return None
        try:
            place = await open_meteo.geocode(self.http, name)
        except HttpError as exc:
            self._failed("geocoding", exc)
            return None
        self._ok("geocoding")
        self.cache.put("geocode", key, _place_to_dict(place) if place else None)
        return place

    async def check_all(self) -> list[tuple[str, bool, float, str]]:
        """Ask every data service once (``./test-1.sh providers``): (name, ok, ms, detail)."""
        from moritz_agent.skills.slots.where import home_place

        home = home_place(self.svc)
        results: list[tuple[str, bool, float, str]] = []
        cfg = self.cfg.weather

        async def timed(name: str, call: Callable[[], Awaitable[str]]) -> None:
            started = time.perf_counter()
            try:
                detail = await call()
                ok = True
            except (HttpError, ProviderUnavailable) as exc:
                detail, ok = str(exc), False
            except Exception as exc:  # a schema change must not stop the check
                detail, ok = f"{type(exc).__name__}: {exc}", False
            results.append((name, ok, (time.perf_counter() - started) * 1000, detail))

        async def forecast() -> str:
            tz = home.tz or self.svc.timezone
            now = self.svc.clock.now(tz)
            raw = await open_meteo.fetch_forecast(self.http, home, cfg, tz)
            pack = open_meteo.parse_forecast(raw, now, tz)
            return f"{len(pack.hours)} Stunden, {len(pack.days)} Tage"

        async def fallback() -> str:
            tz = home.tz or self.svc.timezone
            now = self.svc.clock.now(tz)
            raw = await brightsky.fetch_weather(self.http, home, cfg, tz, now.date())
            pack = brightsky.parse_weather(raw, now, tz, home)
            return f"{len(pack.hours)} Stunden, Station {pack.station or '?'}"

        async def warnings() -> str:
            tz = home.tz or self.svc.timezone
            raw = await brightsky.fetch_alerts(self.http, home, cfg, tz)
            return f"{len(brightsky.parse_alerts(raw, tz))} Warnungen, Zelle {brightsky.warn_cell(raw) or '?'}"

        async def geocoding() -> str:
            place = await open_meteo.geocode(self.http, "Weilburg")
            return place.name if place else "nichts gefunden"

        await timed("open-meteo (Vorhersage)", forecast)
        if cfg.fallback_provider:
            await timed("brightsky (Rückfall, Messwerte)", fallback)
        if self.cfg.warnings.enabled:
            await timed("brightsky (DWD-Warnungen)", warnings)
        await timed("open-meteo (Ortssuche)", geocoding)
        for name, check in self._checks.items():
            await timed(name, lambda c=check: c(home))
        return results

    # -- prefetch -----------------------------------------------------------------------------
    async def prefetch_once(self) -> dict[str, str]:
        """Warm the cache for the home place; returns what happened per service."""
        from moritz_agent.skills.slots.where import home_place

        result: dict[str, str] = {}
        if not self.online:
            return {"all": "skills.online ist aus"}
        home = home_place(self.svc)
        try:
            fetched = await self.weather(home)
            result["weather"] = f"{fetched.source} ({fetched.cache})"
        except ProviderUnavailable as exc:
            result["weather"] = f"nicht erreichbar ({exc.reason})"
        if self.cfg.warnings.enabled:
            try:
                fetched_alerts = await self.alerts(home)
                result["warnings"] = (
                    f"{len(fetched_alerts.data)} Warnungen ({fetched_alerts.cache})"
                )
            except ProviderUnavailable as exc:
                result["warnings"] = f"nicht erreichbar ({exc.reason})"
        for extra in self._extra_prefetch:
            try:
                result[extra.__name__] = await extra(home)
            except Exception as exc:  # never let the loop die
                result[extra.__name__] = f"Fehler ({type(exc).__name__})"
        return result

    def start_prefetch(self) -> None:
        """Background task: keep the home weather and warnings warm (13 §3.5)."""
        if self._prefetch_task is None or self._prefetch_task.done():
            self._prefetch_task = asyncio.ensure_future(self._prefetch_loop())

    async def _prefetch_loop(self) -> None:
        while True:
            interval = max(5, self.cfg.weather.prefetch_interval_minutes) * 60
            try:
                if self.online and self.cfg.weather.prefetch_home:
                    await self.prefetch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Vorabruf fehlgeschlagen")
            await asyncio.sleep(interval)

    async def aclose(self) -> None:
        if self._prefetch_task:
            self._prefetch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._prefetch_task
        await self.http.aclose()


__all__ = ["Fetched", "ProviderUnavailable", "Providers", "ServiceStatus", "Warning"]

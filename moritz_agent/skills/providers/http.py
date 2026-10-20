# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The only door to the internet for the data services (docs/plan/13 §3.5, §12, ADR-032).

* HTTPS only, and only to hosts on the allowlist (plus the addresses an admin wrote into
  ``skills.weather.open_meteo_url`` / ``brightsky_url`` – those may be in the LAN and use ``http://``)
* no redirects, answers capped at 2 MB, connect timeout 1.5 s and 3 s in total (configurable)
* nothing from the query string reaches a log line or an error message
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx

from moritz_agent import __version__
from moritz_agent.config.settings import Skills
from moritz_agent.logging_setup import get_logger

log = get_logger("skill")

MAX_BYTES = 2 * 1024 * 1024
DEFAULT_HOSTS = frozenset(
    {
        "api.open-meteo.com",
        "air-quality-api.open-meteo.com",
        "geocoding-api.open-meteo.com",
        "archive-api.open-meteo.com",
        "api.brightsky.dev",
        "opendata.dwd.de",
        "warnung.bund.de",
        "www.pegelonline.wsv.de",
        "api.energy-charts.info",
        "www.ecb.europa.eu",
        "api.openligadb.de",
        "creativecommons.tankerkoenig.de",
    }
)


class HttpError(Exception):
    """A request failed. ``kind``: blocked | offline | timeout | status | too_large | bad_data."""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, (parts.hostname or "").lower()


class HttpClient:
    """A small async client; ``transport`` lets tests answer from fixtures."""

    def __init__(
        self,
        cfg: Skills,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        extra_hosts: Iterable[str] = (),
    ) -> None:
        self.cfg = cfg
        self.extra_hosts = {h.lower() for h in extra_hosts}
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            headers={
                "User-Agent": f"moritz-agent/{__version__} (+https://github.com/moritz-eckhard-nickel/moritz-agent)",
                "Accept": "application/json",
            },
        )

    def configure(self, cfg: Skills) -> None:
        self.cfg = cfg

    # -- policy ------------------------------------------------------------------------------
    def _self_hosted(self) -> dict[str, str]:
        """Hosts the admin configured explicitly → the scheme they chose."""
        found: dict[str, str] = {}
        for url in (self.cfg.weather.open_meteo_url, self.cfg.weather.brightsky_url):
            scheme, host = _origin(url)
            if host and url.rstrip("/") not in {
                "https://api.open-meteo.com",
                "https://api.brightsky.dev",
            }:
                found[host] = scheme
        return found

    def check(self, url: str) -> None:
        scheme, host = _origin(url)
        own = self._self_hosted()
        if host in own:
            if scheme not in {"https", "http"}:
                raise HttpError("blocked", f"scheme {scheme} not allowed")
            return
        if scheme != "https":
            raise HttpError("blocked", "only https is allowed")
        if host not in DEFAULT_HOSTS and host not in self.extra_hosts:
            raise HttpError("blocked", f"host {host} is not on the allowlist")

    # -- requests ----------------------------------------------------------------------------
    async def get_bytes(self, url: str, params: dict[str, Any] | None = None) -> bytes:
        self.check(url)
        host = _origin(url)[1]
        path = urlsplit(url).path
        timeout = httpx.Timeout(
            self.cfg.http_timeout_s, connect=self.cfg.http_connect_timeout_s, pool=1.0
        )
        try:
            async with asyncio.timeout(self.cfg.http_timeout_s + 0.5):
                async with self._client.stream(
                    "GET", url, params=params, timeout=timeout
                ) as response:
                    if response.status_code >= 400 or response.is_redirect:
                        raise HttpError(
                            "status",
                            f"{host}{path} answered {response.status_code}",
                            response.status_code,
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise HttpError("too_large", f"{host}{path} answered more than 2 MB")
                    return bytes(data)
        except HttpError:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise HttpError("timeout", f"{host}{path} did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise HttpError("offline", f"{host}{path} unreachable ({type(exc).__name__})") from exc

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        raw = await self.get_bytes(url, params)
        try:
            return json.loads(raw)
        except ValueError as exc:
            host, path = _origin(url)[1], urlsplit(url).path
            raise HttpError("bad_data", f"{host}{path} sent invalid JSON") from exc

    async def aclose(self) -> None:
        await self._client.aclose()

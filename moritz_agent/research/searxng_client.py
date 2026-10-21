# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Client for the internal SearXNG instance (JSON format, loopback only; ADR-007, P1-08)."""

from __future__ import annotations

from typing import Any

import httpx

from moritz_agent.research.search import (
    SearchError,
    SearchHit,
    clean_text,
    domain_of,
)

MAX_BYTES = 1024 * 1024


class SearxngClient:
    name = "searxng"

    def __init__(
        self,
        base_url: str,
        *,
        language: str = "de-DE",
        safesearch: int = 0,
        timeout_s: float = 6.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.safesearch = safesearch
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout_s, connect=1.5),
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> bool:
        try:
            response = await self._client.get("/healthz", timeout=2.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        params = {
            "q": query,
            "format": "json",
            "language": self.language,
            "safesearch": str(self.safesearch),
        }
        try:
            response = await self._client.get("/search", params=params)
        except httpx.TimeoutException as exc:
            raise SearchError("timeout") from exc
        except httpx.HTTPError as exc:
            raise SearchError("offline", type(exc).__name__) from exc
        if response.status_code >= 400:
            raise SearchError("offline", f"status {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise SearchError("bad_data", "answer too large")
        try:
            data = response.json()
        except ValueError as exc:
            raise SearchError("bad_data", "no JSON") from exc
        return parse_results(data, limit * 3)


def parse_results(data: Any, limit: int) -> list[SearchHit]:
    """The ``results`` of a SearXNG JSON answer as hits (ranking of SearXNG is kept)."""
    if not isinstance(data, dict):
        raise SearchError("bad_data", "unexpected answer")
    rows = data.get("results")
    if not isinstance(rows, list):
        raise SearchError("bad_data", "no results list")
    hits: list[SearchHit] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        title = clean_text(row.get("title"), 160)
        if not title or not url.startswith(("http://", "https://")) or not domain_of(url):
            continue
        engines = row.get("engines")
        if not isinstance(engines, list):
            engines = [row["engine"]] if row.get("engine") else []
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=clean_text(row.get("content")),
                domain=domain_of(url),
                backend="searxng",
                engines=tuple(str(engine) for engine in engines),
                published=str(row.get("publishedDate") or "")[:10],
            )
        )
        if len(hits) >= limit:
            break
    return hits

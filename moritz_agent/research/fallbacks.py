# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Fallback search stages: KoboldCpp web search and the German Wikipedia (ADR-020, P1-08)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from moritz_agent import __version__
from moritz_agent.inference.client import InferenceClient, InferenceError
from moritz_agent.research.search import SearchError, SearchHit, clean_text, domain_of

WIKIPEDIA_API = "https://de.wikipedia.org/w/api.php"
MAX_BYTES = 1024 * 1024


class KoboldWebSearch:
    """``/api/extra/websearch`` of the model server (DuckDuckGo, top three with page text)."""

    name = "koboldcpp"

    def __init__(self, client: InferenceClient) -> None:
        self.client = client

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        try:
            rows = await self.client.websearch(query)
        except InferenceError as exc:
            raise SearchError("offline", str(exc)) from exc
        hits: list[SearchHit] = []
        for row in rows:
            url = str(row.get("url") or "")
            title = clean_text(row.get("title"), 160)
            if not title or not url.startswith(("http://", "https://")):
                continue
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=clean_text(row.get("desc")),
                    domain=domain_of(url),
                    backend="koboldcpp",
                    engines=("duckduckgo",),
                    content=clean_text(row.get("content"), 1200),
                )
            )
            if len(hits) >= limit:
                break
        return hits


class WikipediaSearch:
    """Intro extracts of the best matching articles of de.wikipedia.org (one request)."""

    name = "wikipedia"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(8.0, connect=2.0),
            headers={
                "User-Agent": f"moritz-agent/{__version__} (+https://github.com/moritz-eckhard-nickel/moritz-agent)",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": str(min(limit, 3)),
            "prop": "extracts|info",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": "3",
            "exlimit": "max",
            "inprop": "url",
            "redirects": "1",
        }
        try:
            response = await self._client.get(WIKIPEDIA_API, params=params)
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
        return parse_wikipedia(data, limit)


def parse_wikipedia(data: Any, limit: int) -> list[SearchHit]:
    pages = (data.get("query") or {}).get("pages") if isinstance(data, dict) else None
    if pages is None:
        return []  # "no hit" has no ``query`` key at all
    if not isinstance(pages, list):
        raise SearchError("bad_data", "unexpected answer")
    pages = sorted((p for p in pages if isinstance(p, dict)), key=lambda p: p.get("index", 99))
    hits: list[SearchHit] = []
    for page in pages:
        title = clean_text(page.get("title"), 120)
        extract = clean_text(page.get("extract"), 600)
        if not title or not extract:
            continue
        url = str(page.get("fullurl") or f"https://de.wikipedia.org/wiki/{quote(title)}")
        hits.append(
            SearchHit(
                title=f"{title} – Wikipedia",
                url=url,
                snippet=extract,
                domain="de.wikipedia.org",
                backend="wikipedia",
                content=extract,
            )
        )
        if len(hits) >= limit:
            break
    return hits

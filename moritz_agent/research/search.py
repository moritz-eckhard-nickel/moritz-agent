# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Web search with a fallback chain: SearXNG → KoboldCpp web search → Wikipedia (ADR-020, P1-08).

Every hit names the backend that delivered it (and, for SearXNG, the engines), so the agent only
cites a source that really answered (SEARCH-02). When nothing answers, the outcome says so and the
agent tells Moritz honestly (PHONE-32).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

from moritz_agent.config.settings import Search
from moritz_agent.logging_setup import get_logger

log = get_logger("search")

MAX_QUERY_CHARS = 300
SNIPPET_CHARS = 400
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


class SearchError(Exception):
    """A backend could not answer (``kind``: offline | timeout | bad_data | disabled)."""

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    domain: str
    backend: str
    engines: tuple[str, ...] = ()
    published: str = ""
    content: str = ""

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "domain": self.domain,
            "backend": self.backend,
        }
        if self.engines:
            data["engines"] = list(self.engines)
        if self.published:
            data["published"] = self.published
        return data


@dataclass
class SearchOutcome:
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    backend: str | None = None
    tried: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.hits)


class SearchBackend(Protocol):
    name: str

    async def search(self, query: str, limit: int) -> list[SearchHit]: ...


def clean_text(text: object, limit: int = SNIPPET_CHARS) -> str:
    """Plain text from a search snippet: no tags, entities or runs of blanks, shortened."""
    from html import unescape

    value = _SPACES.sub(" ", unescape(_TAGS.sub(" ", str(text or "")))).strip()
    if len(value) > limit:
        value = value[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"
    return value


def domain_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:  # e.g. "https://[broken/x" – one odd hit must not break the search
        return ""
    return host.removeprefix("www.")


def dedupe_by_domain(hits: list[SearchHit], limit: int) -> list[SearchHit]:
    """First hit per domain (the ranking of the backend decides), at most ``limit`` hits.

    Wikipedia articles all share one domain, so they are told apart by their address.
    """
    seen: set[str] = set()
    result: list[SearchHit] = []
    for hit in hits:
        key = hit.url if hit.backend == "wikipedia" else hit.domain
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
        if len(result) >= limit:
            break
    return result


# Questions about "now" cannot be answered by an encyclopedia.
_TIME_SENSITIVE = re.compile(
    r"\b(aktuell\w*|heute|gestern|morgen|jetzt|gerade|neueste\w*|nachrichten|news|preis\w*|kurs\w*|"
    r"wetter|ergebnis\w*|spielstand|tabelle|live|wer hat gewonnen|im moment)\b",
    re.IGNORECASE,
)


def encyclopedic(query: str) -> bool:
    """Looks like a question about a person, place or term – not about something happening now."""
    return not _TIME_SENSITIVE.search(query)


class SearchService:
    """Runs the backends of ``[search] backends`` in order until one has hits."""

    def __init__(self, cfg: Search, backends: dict[str, SearchBackend]) -> None:
        self.cfg = cfg
        self.backends = backends

    def configure(self, cfg: Search) -> None:
        self.cfg = cfg

    async def search(self, query: str, max_results: int | None = None) -> SearchOutcome:
        query = _SPACES.sub(" ", query).strip()[:MAX_QUERY_CHARS]
        outcome = SearchOutcome(query=query)
        limit = max(1, min(max_results or self.cfg.max_results, self.cfg.max_results))
        if not self.cfg.enabled:
            outcome.errors["search"] = "disabled"
            return outcome
        if not query:
            outcome.errors["search"] = "empty_query"
            return outcome
        for name in self.cfg.backends:
            backend = self.backends.get(name)
            if backend is None:
                continue
            if name == "wikipedia" and not encyclopedic(query):
                outcome.errors[name] = "skipped"
                continue
            outcome.tried.append(name)
            timeout = self.cfg.timeout_s if name == "searxng" else self.cfg.fallback_timeout_s
            try:
                async with asyncio.timeout(timeout):
                    hits = await backend.search(query, limit)
            except TimeoutError:
                outcome.errors[name] = "timeout"
                log.warning("Suche: %s hat nicht rechtzeitig geantwortet", name)
                continue
            except SearchError as exc:
                outcome.errors[name] = exc.kind
                log.warning("Suche: %s nicht erreichbar (%s)", name, exc.kind)
                continue
            except Exception as exc:  # an unexpected answer: try the next backend
                outcome.errors[name] = "failed"
                log.warning("Suche: %s fehlgeschlagen (%s)", name, type(exc).__name__)
                continue
            hits = dedupe_by_domain(hits, limit)
            if not hits:
                outcome.errors[name] = "empty"
                continue
            outcome.hits = hits
            outcome.backend = name
            return outcome
        return outcome

    async def aclose(self) -> None:
        for backend in self.backends.values():
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()

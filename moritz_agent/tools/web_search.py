# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The ``web_search`` tool: current events, prices, news and everything the model does not know."""

from __future__ import annotations

from typing import Any, ClassVar

from moritz_agent.research.search import SearchOutcome, SearchService
from moritz_agent.tools.base import BaseTool, ToolContext, ToolResult

_UNAVAILABLE = "Die Websuche ist gerade nicht erreichbar. Sag ehrlich, dass du gerade nichts nachschlagen kannst."
_BROKEN = {"offline", "timeout", "bad_data", "disabled", "empty_query"}


class WebSearch(BaseTool):
    name = "web_search"
    description = (
        "Sucht im Internet nach aktuellen Ereignissen, Preisen, Nachrichten oder Fakten, die du nicht "
        "sicher weißt. Nicht für Wetter, Warnungen, Pollen, Sonne und Mond – dafür gibt es eigene Werkzeuge. "
        "Nenne in der Antwort kurz die Quelle."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Suchanfrage auf Deutsch, kurz und konkret",
                "maxLength": 200,
                "minLength": 2,
            },
            "max_results": {
                "type": "integer",
                "description": "Anzahl der Treffer (1 bis 5)",
                "minimum": 1,
                "maximum": 5,
                "default": 5,
            },
        },
        "required": ["query"],
    }
    timeout_s = 20.0

    def __init__(self, search: SearchService) -> None:
        self.search = search

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        outcome = await self.search.search(args["query"], args.get("max_results"))
        return outcome_to_result(outcome)


def outcome_to_result(outcome: SearchOutcome) -> ToolResult:
    if outcome.ok:
        results = [hit.as_dict() for hit in outcome.hits]
        # a Wikipedia hit carries the answer itself; the others only a snippet
        for row, hit in zip(results, outcome.hits, strict=True):
            if hit.content and hit.content != hit.snippet:
                row["content"] = hit.content
        sources = [
            {"name": hit.domain, "url": hit.url, "backend": hit.backend} for hit in outcome.hits
        ]
        return ToolResult.success({"backend": outcome.backend, "results": results}, sources=sources)
    if any(reason in _BROKEN for reason in outcome.errors.values()):
        return ToolResult.failure("search_unavailable", _UNAVAILABLE)
    return ToolResult.success(
        {
            "backend": None,
            "results": [],
            "note": "Zu dieser Suche gab es keine Treffer. Sag das ehrlich und rate nicht.",
        }
    )

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Headlines from the tagesschau API (off by default; the terms of use are checked in P1-27)."""

from __future__ import annotations

from typing import Any

from moritz_agent.skills.providers.brightsky import clean_text
from moritz_agent.skills.providers.http import HttpClient, HttpError

URL = "https://www.tagesschau.de/api2u/homepage/"
HOST = "www.tagesschau.de"


async def fetch(http: HttpClient) -> dict[str, Any]:
    raw = await http.get_json(URL)
    if not isinstance(raw, dict) or not isinstance(raw.get("news"), list):
        raise HttpError("bad_data", "news: unexpected answer")
    return raw


def headlines(raw: dict[str, Any], limit: int) -> list[str]:
    """Titles only (free text from outside is cleaned and never read as an instruction)."""
    titles = []
    for item in raw.get("news", []):
        if not isinstance(item, dict) or item.get("type") not in {"story", "video", None}:
            continue
        title = clean_text(item.get("title"), 140)
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles

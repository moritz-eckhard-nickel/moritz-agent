# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Time zone of a named place ("Wie spät ist es in New York?")."""

from __future__ import annotations

import re
from functools import lru_cache

from moritz_agent.skills.data import load_toml


@lru_cache(maxsize=1)
def _places() -> list[tuple[str, str]]:
    table = load_toml("geo/zeitzonen.toml")["orte"]
    return sorted(table.items(), key=lambda kv: -len(kv[0]))


def find_zone(text: str) -> tuple[str, str] | None:
    """(place name as spoken, IANA zone) of the longest known place in ``text``."""
    for name, zone in _places():
        if re.search(rf"(?<![\wäöüß-]){re.escape(name)}(?![\wäöüß-])", text):
            return name, zone
    return None


def display_name(name: str) -> str:
    """ "new york" → "New York", "neu-delhi" → "Neu-Delhi"."""
    return re.sub(r"(^|[ -])([a-zäöüßé])", lambda m: m.group(1) + m.group(2).upper(), name)

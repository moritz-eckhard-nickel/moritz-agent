# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Hessian dialect and colloquial speech → standard German (docs/plan/13 §9.1)."""

from __future__ import annotations

import re
from functools import lru_cache

from moritz_agent.skills.data import load_toml


@lru_cache(maxsize=1)
def _tables() -> tuple[list[tuple[re.Pattern[str], str]], dict[str, str]]:
    data = load_toml("sprache/hessisch.toml")
    phrases = sorted(data.get("phrases", {}).items(), key=lambda kv: -len(kv[0]))
    compiled = [(re.compile(rf"(?<![\w']){re.escape(src)}(?![\w'])"), dst) for src, dst in phrases]
    return compiled, dict(data.get("words", {}))


def entries() -> dict[str, str]:
    """All dictionary entries (phrases and words) – used by the tests."""
    data = load_toml("sprache/hessisch.toml")
    return {**data.get("phrases", {}), **data.get("words", {})}


def to_standard(text: str) -> str:
    """Replace dialect phrases and words; ``text`` is already lower case and punctuation-free."""
    phrases, words = _tables()
    for pattern, replacement in phrases:
        text = pattern.sub(replacement, text)
    tokens = [words.get(token, token) for token in text.split()]
    return " ".join(token for token in tokens if token)

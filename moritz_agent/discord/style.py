# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Anton, a little sweet (docs/plan/14 §8.2, ADR-037).

The core answer stays neutral. This adds the sugar *around* it – one emoji that fits the topic, now
and then a kaomoji – and nothing at all for warnings, errors and admin messages. Every choice comes
from the message id, so tests are stable.
"""

from __future__ import annotations

import random
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STYLE_FILE = "assets/data/discord/stil.de.toml"
_HAS_EMOJI = re.compile(r"[\U0001f000-\U0001faff☀-➿]")
KAOMOJI_EVERY = 5


@dataclass
class StyleState:
    """What the styler remembers about one conversation: no kaomoji twice in a row."""

    last_kaomoji: bool = False
    count: int = 0


def load(root: Path) -> dict[str, Any]:
    with (root / STYLE_FILE).open("rb") as handle:
        return tomllib.load(handle)


class Styler:
    def __init__(self, data: dict[str, Any], style: str = "cute") -> None:
        self.data = data
        self.style = style

    @classmethod
    def from_root(cls, root: Path, style: str = "cute") -> Styler:
        return cls(load(root), style)

    @property
    def cute(self) -> bool:
        return self.style == "cute"

    # -- pieces ------------------------------------------------------------------------------------
    def emoji_for(self, text: str, skill_id: str | None, rng: random.Random) -> str:
        for pattern, emoji in self.data["emoji_text"].items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                return str(emoji)
        group = (skill_id or "").split(".")[0]
        choices = self.data["emoji"].get(group) or self.data["emoji"]["default"]
        return str(rng.choice(choices))

    def phrase(self, name: str, seed: int = 0, **values: str) -> str:
        """A fixed phrase of the list ``[phrases]`` (or the single text), formatted."""
        entry = self.data["phrases"][name]
        text = entry if isinstance(entry, str) else entry[seed % len(entry)]
        return str(text).format(**values)

    def error(self, kind: str) -> str:
        """Friendly error text; "normal" style drops the emoji."""
        text = str(self.data["errors"].get(kind, self.data["errors"]["generic"]))
        return text if self.cute else _HAS_EMOJI.sub("", text).replace("  ", " ").strip()

    # -- the main entry ----------------------------------------------------------------------------
    def decorate(
        self,
        text: str,
        *,
        skill_id: str | None,
        serious: bool,
        seed: int,
        state: StyleState | None = None,
    ) -> str:
        """``text`` with the sugar around it; unchanged for serious answers and the "normal" style."""
        state = state or StyleState()
        state.count += 1
        if not self.cute or serious or not text.strip() or _HAS_EMOJI.search(text):
            state.last_kaomoji = False
            return text
        rng = random.Random(seed)
        out = f"{text.rstrip()} {self.emoji_for(text, skill_id, rng)}"
        give_kaomoji = seed % KAOMOJI_EVERY == 0 and not state.last_kaomoji
        if give_kaomoji:
            out += " " + str(rng.choice(self.data["kaomoji"]["happy"]))
        state.last_kaomoji = give_kaomoji
        return out

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Anton, a little sweet (docs/plan/14 §8.2, ADR-037).

The core answer stays neutral. This adds the sugar *around* it – one text smiley that fits the topic
(":)", ":(", ":3", "^^") – and nothing at all for warnings, errors and admin messages. No emoji, ever
(Moritz, 21.10.2026): :func:`no_emoji` takes them out of everything Anton sends. Every choice comes
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
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\u231a\u231b\u23e9-\u23fa"
    "\U0001f1e6-\U0001f1ff\ufe0f\u200d\u20e3]+"
)
SMILEY = re.compile(r"(?<!\S)(?:>?[:;][)(3DPO/]|\^\^|<3|xD)(?!\S)")


def no_emoji(text: str) -> str:
    """``text`` without emoji (and without the space an emoji leaves behind)."""
    if not _EMOJI.search(text):
        return text
    text = _EMOJI.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,!?;“)])", r"\1", text)  # not before ":" – ":)" is a smiley
    text = re.sub(r"([„(])[ \t]+", r"\1", text)
    return "\n".join(line.strip(" \t") for line in text.split("\n"))


@dataclass
class StyleState:
    """What the styler remembers about one conversation."""

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
    def smiley_for(self, text: str, skill_id: str | None, rng: random.Random) -> str:
        for pattern, smiley in self.data["smiley_text"].items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                return str(smiley)
        group = (skill_id or "").split(".")[0]
        choices = self.data["smiley"].get(group) or self.data["smiley"]["default"]
        return str(rng.choice(choices))

    def phrase(self, name: str, seed: int = 0, **values: str) -> str:
        """A fixed phrase of the list ``[phrases]`` (or the single text), formatted."""
        entry = self.data["phrases"][name]
        text = entry if isinstance(entry, str) else entry[seed % len(entry)]
        text = str(text).format(**values)
        return text if self.cute else plain(text)

    def error(self, kind: str) -> str:
        """Friendly error text; "normal" style drops the smiley."""
        text = str(self.data["errors"].get(kind, self.data["errors"]["generic"]))
        return text if self.cute else plain(text)

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
        text = no_emoji(text)
        if not self.cute or serious or not text.strip() or SMILEY.search(text):
            return text
        rng = random.Random(seed)
        return f"{text.rstrip()} {self.smiley_for(text, skill_id, rng)}"


def plain(text: str) -> str:
    """Without smileys – the "normal" style."""
    return re.sub(r"[ \t]{2,}", " ", SMILEY.sub("", no_emoji(text))).replace(" .", ".").strip()

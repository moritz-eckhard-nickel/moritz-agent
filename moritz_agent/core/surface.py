# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Forms of output: spoken (telephone, Discord voice) or chat (Discord text, web)."""

from __future__ import annotations

from enum import StrEnum


class Surface(StrEnum):
    SPOKEN = "spoken"  # short, no markdown, read out by the voice
    CHAT = "chat"  # markdown, links, cards, longer answers

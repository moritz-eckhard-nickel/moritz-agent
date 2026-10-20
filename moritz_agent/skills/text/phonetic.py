# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Kölner Phonetik: German phonetic code for fuzzy place names ("Weilborg" ≈ "Weilburg")."""

from __future__ import annotations

import re

_UMLAUT = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e"})


def _code(letter: str, prev: str, nxt: str, first: bool) -> str:
    if letter in "aeijouy":
        return "0"
    if letter == "h":
        return ""
    if letter == "b":
        return "1"
    if letter == "p":
        return "3" if nxt == "h" else "1"
    if letter in "dt":
        return "8" if nxt in "csz" else "2"
    if letter in "fvw":
        return "3"
    if letter in "gkq":
        return "4"
    if letter == "c":
        if first:
            return "4" if nxt in "ahkloqrux" else "8"
        if prev in "sz":
            return "8"
        return "4" if nxt in "ahkoqux" else "8"
    if letter == "x":
        return "8" if prev in "ckq" else "48"
    if letter == "l":
        return "5"
    if letter in "mn":
        return "6"
    if letter == "r":
        return "7"
    if letter in "sz":
        return "8"
    return ""


def phonetic_code(word: str) -> str:
    """Kölner Phonetik code of ``word`` (digits only; empty for words without letters)."""
    text = re.sub(r"[^a-zäöüß]", "", word.lower()).translate(_UMLAUT)
    if not text:
        return ""
    codes: list[str] = []
    for index, letter in enumerate(text):
        prev = text[index - 1] if index else ""
        nxt = text[index + 1] if index + 1 < len(text) else ""
        codes.append(_code(letter, prev, nxt, index == 0))
    collapsed: list[str] = []
    for chunk in "".join(codes):
        if not collapsed or collapsed[-1] != chunk:
            collapsed.append(chunk)
    result = "".join(collapsed)
    return result[0] + result[1:].replace("0", "") if result else ""

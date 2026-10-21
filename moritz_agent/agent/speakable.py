# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""From the model's answer to something that can be read out (AGENT-07, PHONE-25).

Structure only: reasoning blocks, code, links, lists and the length limit. Pronunciation of numbers,
dates, units and abbreviations is the job of ``phone.audio.textnorm`` right before the voice – the
same answer stays usable as text for Discord and the web interface.
"""

from __future__ import annotations

import re

_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_SPECIAL = re.compile(r"<\|[^|>]*\|>")
_CODE_BLOCK = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://)?[^)\s]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MONTH_NAMES = (
    "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
    "|Jan|Feb|Mär|Apr|Jun|Jul|Aug|Sep|Sept|Okt|Nov|Dez"
)
# "1. " starts a list item – but "3. Oktober" at the start of a line is a date, not a list marker
_BULLET = re.compile(
    rf"^\s*(?:[-*•]|\d{{1,2}}\)|\d{{1,2}}\.(?!\s*(?:{_MONTH_NAMES})\b))\s+", re.MULTILINE
)
_EMPHASIS = re.compile(r"(\*\*|__|\*|(?<!\w)_|_(?!\w))")
_SPACES = re.compile(r"[ \t]+")
_EMOJI = re.compile(r"[\U0001f000-\U0001faff\u2600-\u27bf\U0001f1e6-\U0001f1ff\ufe0f\u200d]")

_ABBREVIATIONS = {
    "ca", "bzw", "usw", "ggf", "evtl", "dr", "prof", "nr", "str", "tel", "inkl", "max", "min",
    "mio", "mrd", "etc", "vgl", "sog", "std", "co", "vs", "ev", "geb", "gem", "zzgl",
}  # fmt: skip
_SENTENCE_END = re.compile(r"([.!?…]+[\"“”)]*)\s+(?=[A-ZÄÖÜ„\"“(0-9])")


def strip_reasoning(text: str) -> str:
    """Only the model's hidden reasoning and special tokens go; markdown and links stay (chat)."""
    return _SPECIAL.sub("", _THINK.sub("", text)).strip()


def clean(text: str) -> str:
    """The answer without reasoning, code, links, emoji and list markers – in plain sentences."""
    text = _THINK.sub("", text)
    text = _SPECIAL.sub("", text)
    text = _CODE_BLOCK.sub(" ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _HEADING.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _EMOJI.sub("", text)
    lines = []
    for raw in text.splitlines():
        line = _SPACES.sub(" ", _BULLET.sub("", raw)).strip()
        if not line:
            continue
        if lines and not re.search(r"[.!?…:]$", lines[-1]):
            lines[-1] += "."  # a list item or a heading is a sentence of its own
        lines.append(line)
    return re.sub(r"\s+([.,!?;:])", r"\1", " ".join(lines)).strip()


def sentences(text: str) -> list[str]:
    """Split into sentences without breaking at "18. Oktober", "z. B." or "Dr. Müller"."""
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        before = text[start : match.start(1) + 1].rstrip()
        last = re.split(r"\s+", before)[-1].rstrip('.!?…"“”)').lower()
        if match.group(1) == "." and (
            last.isdigit() or len(last) == 1 or last.replace(".", "") in _ABBREVIATIONS
        ):
            continue
        parts.append(text[start : match.end(1)].strip())
        start = match.end()
    rest = text[start:].strip()
    if rest:
        parts.append(rest)
    return parts


def make_speakable(text: str, *, max_sentences: int = 3, max_chars: int = 450) -> str:
    """Cleaned answer, at most ``max_sentences`` sentences and ``max_chars`` characters."""
    cleaned = clean(text)
    if not cleaned:
        return ""
    result: list[str] = []
    total = 0
    for sentence in sentences(cleaned)[:max_sentences]:
        if result and total + len(sentence) > max_chars:
            break
        result.append(sentence)
        total += len(sentence) + 1
    answer = " ".join(result)
    if len(answer) > max_chars:
        answer = answer[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return answer

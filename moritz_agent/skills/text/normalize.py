# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""From a recognized sentence to something the router can read (docs/plan/13 §4.1).

Order: lower case and punctuation → contractions → dialect → number words → clock phrases →
polite filler. The result keeps digits, ``:`` ``.`` ``,`` between digits and the math symbols.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from moritz_agent.skills.text.dialect import to_standard
from moritz_agent.skills.text.numbers import clock_phrases, words_to_digits

_NAME = r"n[iy][kg]h?[iy][dt]{1,2}h?[ae]"  # Nikita, Nikida, Nikitta, Nigita …
_ADDRESS = re.compile(rf"^(?:(?:hey|hallo|hi|ok|okay|na|also)\s+)*{_NAME}\b[,:!.\s]*")
_NAME_ONLY = re.compile(rf"^(?:hey |hallo |hi )?{_NAME}$")
_CONTRACTION = re.compile(
    r"\b(gibt|wird|geht|ist|scheint|regnet|schneit|stürmt|gewittert|bleibt|kommt|wär|wäre|hat|war|sieht|schaut|läuft|steht)'?s\b"
)
_FILLER_PREFIX = re.compile(r"^(?:(?:äh|ähm|ehm|öh|hm|naja|na ja|ja|also|ok|okay|und dann)\s+)+")
_POLITE = (
    re.compile(
        r"\b(?:kannst|könntest|würdest|magst) du (?:mir |uns )?(?:vielleicht |eben |mal )*(?:kurz )?(?:sagen|verraten|nachschauen|nachsehen|schauen|gucken|erzählen)\b"
    ),
    re.compile(
        r"\b(?:sag|sage|verrate|erzähl|erzähle|schau|schaue|guck|gucke)(?: mir| uns| mal| mal eben| doch| bitte)+\b"
    ),
    re.compile(r"\bweißt du(?: vielleicht| zufällig)?\b"),
    re.compile(
        r"\bich (?:möchte|will|würde gern|würde gerne|hätte gern|hätte gerne|wüsste gern|wüsste gerne)(?: mal)?(?: gern| gerne)? wissen\b"
    ),
    re.compile(r"\b(?:ich )?(?:möchte|will) (?:mal )?wissen\b"),
)
_SOFT_WORDS = re.compile(r"\b(?:bitte|eigentlich|eben|doch|denn|bloß|nur mal|mal kurz|kurz mal)\b")
_MAL_FILLER = re.compile(r"(?<![\d] )\bmal\b(?! \d)")


@dataclass(frozen=True)
class Utterance:
    raw: str
    text: str  # prepared text: lower case, dialect resolved, digits instead of number words
    stt_logprob: float | None = None
    addressed: bool = False  # started with "Nikita, …"

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(self.text.split())

    @property
    def words(self) -> int:
        return len(self.tokens)


def basic_clean(raw: str) -> str:
    """Lower case, one kind of apostrophe, punctuation out (digits keep their ``. , :``)."""
    text = raw.lower().replace("’", "'").replace("`", "'").replace("´", "'")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^\w\s'.,:%€$°/+*×÷^()-]", " ", text)
    text = re.sub(
        r"(?<!\d)[.,:;!?]+|[.,:;!?]+(?!\d)(?=\s|$)",
        lambda m: " " if m.group(0) != "." else m.group(0),
        text,
    )
    # keep "24." (ordinal after a digit) but drop sentence dots after words
    text = re.sub(r"(?<=[^\W\d])\.(?=\s|$)", " ", text)
    text = re.sub(r"(?<=\s)-|-(?=\s)", " - ", text)
    return re.sub(r"\s+", " ", text).strip()


def prepare(
    raw: str, *, stt_logprob: float | None = None, quarter_dialect: bool = True
) -> Utterance:
    """Normalize ``raw`` for the router."""
    text = basic_clean(raw)
    text = _CONTRACTION.sub(lambda m: f"{m.group(1)} es", text)
    addressed = False
    if _NAME_ONLY.match(text):
        return Utterance(raw, "nikita", stt_logprob, addressed=True)
    stripped = _ADDRESS.sub("", text, count=1)
    if stripped != text and stripped:
        addressed, text = True, stripped
    text = to_standard(text)
    text = words_to_digits(text)
    text = re.sub(r"\bein uhr\b", "1 uhr", text)
    text = clock_phrases(text, quarter_dialect=quarter_dialect)
    before = text
    text = _FILLER_PREFIX.sub("", text, count=1) or text
    text = re.sub(r"\s+", " ", _SOFT_WORDS.sub(" ", text))
    for pattern in _POLITE:
        text = re.sub(r"\s+", " ", pattern.sub(" ", text))
    text = _MAL_FILLER.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip() or before
    return Utterance(raw, text, stt_logprob, addressed=addressed)

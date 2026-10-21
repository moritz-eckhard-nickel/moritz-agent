# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Anton calls back on the phone (Moritz, 21.10.2026).

Written on Discord – never said in a call or in the voice channel – "Sag mir am Telefon, wie viel Uhr
es ist" makes Anton call the internal extension (201), let it ring 10–15 s and, once somebody picks
up, say the answer one second later, say goodbye and hang up without listening. Nobody picks up:
that's it – no message elsewhere.

This module only finds such a request in a text and keeps the queue of calls to make; the phone
worker fetches them (``/internal/phone/callback``) and places the call.
"""

from __future__ import annotations

import itertools
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field

_PHONE = r"(?:am|ans|übers|über das|per|auf dem|aufs) (?:telefon|handy|festnetz)"
_SAY = r"(?:sag|sage|sags|sag's|erzähl|erzähle|teil|teile|sprich)"
_PATTERNS = (
    # "sag mir am Telefon, wie viel Uhr es ist" / "sag mir bitte übers Telefon …"
    re.compile(
        rf"^(?:bitte |kannst du |könntest du |anton,? )*{_SAY} (?:es |das )?mir (?:bitte |mal |doch )*{_PHONE}(?: mit)?,?:? (?P<what>.+)$"
    ),
    # "ruf mich an und sag mir, wie das Wetter wird"
    re.compile(
        rf"^(?:bitte |kannst du |könntest du |anton,? )*ruf(?:e)? mich (?:bitte |mal |doch )*(?:an|auf der \d+ an) und {_SAY} mir,?:? (?P<what>.+)$"
    ),
    # "wie viel Uhr ist es? Sag's mir am Telefon" / "…, aber sag es mir am Telefon"
    re.compile(
        rf"^(?P<what>.+?)[,.?!–-]* (?:aber |und )?{_SAY} (?:es |das )?mir (?:bitte |mal |doch )*{_PHONE}\W*$"
    ),
)


def phone_request(text: str) -> str | None:
    """The question to answer on the phone, or ``None`` if the text asks for no call."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    for pattern in _PATTERNS:
        match = pattern.match(cleaned)
        if match:
            what = match.group("what").strip(" ,.:;!–-")
            return what or None
    return None


@dataclass
class Callback:
    id: int
    text: str  # what Anton says when somebody picks up
    extension: str
    ring_s: float
    speak_after_s: float
    created: float = field(default_factory=time.monotonic)


class CallbackQueue:
    """Calls the phone worker still has to make. At most a few, and old ones expire."""

    MAX_WAITING = 3
    EXPIRE_S = 300.0

    def __init__(self) -> None:
        self._waiting: deque[Callback] = deque()
        self._ids = itertools.count(1)
        self.asked: dict[int, Callback] = {}  # handed to the phone, waiting for the outcome

    def add(
        self,
        text: str,
        extension: str,
        ring_s: tuple[float, float],
        speak_after_s: float,
    ) -> Callback | None:
        self._expire()
        if len(self._waiting) >= self.MAX_WAITING:
            return None
        low, high = sorted(ring_s)
        call = Callback(next(self._ids), text, extension, random.uniform(low, high), speak_after_s)
        self._waiting.append(call)
        return call

    def take(self) -> Callback | None:
        self._expire()
        if not self._waiting:
            return None
        call = self._waiting.popleft()
        self.asked[call.id] = call
        return call

    def done(self, call_id: int) -> Callback | None:
        return self.asked.pop(call_id, None)

    def _expire(self) -> None:
        now = time.monotonic()
        while self._waiting and now - self._waiting[0].created > self.EXPIRE_S:
            self._waiting.popleft()
        for key in [k for k, c in self.asked.items() if now - c.created > self.EXPIRE_S]:
            del self.asked[key]

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Stateless ``custom_id``s of buttons and menus, and the short-lived confirmations (docs/plan/14 §4.4).

A button carries its intent in the id ("a:<asker>:<what to say>"), so it keeps working after a
restart. Only the person who asked – or the owner – may press it.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

MAX_ID = 100
ACTION = "a"  # follow-up button: say a sentence again in the same conversation
PICK = "c"  # a choice out of a question back
CONFIRM = "x"  # confirmation of an admin command


def encode_action(user_id: str, say: str) -> str:
    prefix = f"{ACTION}:{user_id}:"
    return prefix + say[: MAX_ID - len(prefix)]


def encode_pick(user_id: str) -> str:
    return f"{PICK}:{user_id}"


def encode_confirm(action: str, nonce: str, answer: str) -> str:
    return f"{CONFIRM}:{action}:{nonce}:{answer}"


@dataclass(frozen=True)
class Decoded:
    kind: str
    user_id: str = ""
    payload: str = ""
    nonce: str = ""
    answer: str = ""


def decode(custom_id: str) -> Decoded | None:
    """Understand a ``custom_id``; ``None`` for anything that is not ours."""
    kind, _, rest = custom_id.partition(":")
    if kind == ACTION:
        user, _, say = rest.partition(":")
        return Decoded(ACTION, user_id=user, payload=say) if user.isdigit() and say else None
    if kind == PICK:
        return Decoded(PICK, user_id=rest) if rest.isdigit() else None
    if kind == CONFIRM:
        parts = rest.split(":")
        if len(parts) == 3:
            return Decoded(CONFIRM, payload=parts[0], nonce=parts[1], answer=parts[2])
    return None


def may_press(presser_id: str, asker_id: str, owner_ids: list[str]) -> bool:
    return presser_id == asker_id or presser_id in owner_ids


@dataclass
class Pending:
    action: str
    user_id: str
    expires: float
    needs_pin: bool = False


class Confirmations:
    """Admin commands wait 60 seconds for a button press (and a PIN, if one is set)."""

    TTL_S = 60.0
    PIN_ATTEMPTS = 3

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._pending: dict[str, Pending] = {}
        self._failures: dict[str, list[float]] = {}

    def ask(self, action: str, user_id: str, *, needs_pin: bool = False) -> str:
        nonce = secrets.token_hex(4)
        self._pending[nonce] = Pending(action, user_id, self._clock() + self.TTL_S, needs_pin)
        for key in [k for k, p in self._pending.items() if p.expires < self._clock()]:
            del self._pending[key]
        return nonce

    def peek(self, nonce: str, user_id: str) -> Pending | None:
        """The pending action without using it up (the PIN dialog comes first)."""
        pending = self._pending.get(nonce)
        if pending is None or pending.expires < self._clock() or pending.user_id != user_id:
            return None
        return pending

    def take(self, nonce: str, user_id: str) -> Pending | None:
        """The pending action if it is still valid and belongs to this person (single use)."""
        pending = self._pending.get(nonce)
        if pending is None or pending.expires < self._clock() or pending.user_id != user_id:
            return None
        del self._pending[nonce]
        return pending

    def pin_blocked(self, user_id: str) -> bool:
        """Three wrong PINs in ten minutes lock the PIN entry for that person."""
        now = self._clock()
        recent = [t for t in self._failures.get(user_id, []) if now - t < 600]
        self._failures[user_id] = recent
        return len(recent) >= self.PIN_ATTEMPTS

    def pin_failed(self, user_id: str) -> None:
        self._failures.setdefault(user_id, []).append(self._clock())

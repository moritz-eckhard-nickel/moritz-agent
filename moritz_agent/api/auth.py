# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Login of the web interface: scrypt-checked password, session cookie, rate limit (API-05, ADR-013).

The login comes from ``passwords.txt``. Only a scrypt hash of it is kept in memory and compared in
constant time; a wrong user name costs the same time as a wrong password. A session is a random
token held on the server; the cookie is ``HttpOnly``, ``SameSite=Strict`` and ``Secure`` with TLS.
With a :class:`SessionStore` the sessions (their sha256, never the token) survive a restart.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from moritz_agent.config.reload import RuntimeConfig

if TYPE_CHECKING:
    from moritz_agent.storage.web import SessionStore

COOKIE = "magent_session"
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _hash(value: str, salt: bytes) -> bytes:
    return hashlib.scrypt(value.encode("utf-8"), salt=salt, **SCRYPT)  # type: ignore[arg-type]


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    token: str | None = None
    retry_after_s: int = 0  # > 0: too many attempts, try again after this many seconds
    reason: str = ""  # "not_configured" | "locked" | "wrong"


class Authenticator:
    def __init__(
        self,
        config: Callable[[], RuntimeConfig],
        *,
        clock: Callable[[], float] = time.time,  # wall time: stored sessions outlive the process
        store: SessionStore | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._store = store
        self._salt = os.urandom(16)
        self._known: tuple[str, str] | None = None  # (username, password) the hashes belong to
        self._user_hash = b""
        self._pass_hash = b""
        self._dummy = _hash("x", self._salt)
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    # -- configuration --------------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._config().passwords.web_login.enabled

    def _refresh(self) -> bool:
        login = self._config().passwords.web_login
        if not login.enabled:
            if self._known is not None and self._store is not None:
                self._store.clear()
            self._known = None
            self._sessions.clear()
            return False
        current = (login.username, login.password.reveal())
        if current != self._known:
            first = self._known is None
            if self._store is not None:
                if not self._store.same_login(*current):  # changed, maybe while we were down
                    self._store.clear()
                    self._sessions.clear()
                elif first:
                    self._sessions = self._store.load(self._clock())
            elif not first:  # the password changed: nobody stays logged in
                self._sessions.clear()
            self._known = current
            self._user_hash = _hash(current[0], self._salt)
            self._pass_hash = _hash(current[1], self._salt)
        return True

    @property
    def _limits(self) -> tuple[int, float]:
        server = self._config().settings.server
        return server.login_max_attempts, server.login_window_minutes * 60.0

    # -- login ------------------------------------------------------------------------------------
    def _locked_for(self, ip: str) -> int:
        attempts, window = self._limits
        failures = self._failures[ip]
        now = self._clock()
        while failures and now - failures[0] > window:
            failures.popleft()
        if len(failures) >= attempts:
            return max(1, int(window - (now - failures[0])) + 1)
        return 0

    def login(self, username: str, password: str, ip: str) -> LoginResult:
        if not self._refresh():
            return LoginResult(False, reason="not_configured")
        wait = self._locked_for(ip)
        if wait:
            return LoginResult(False, retry_after_s=wait, reason="locked")
        user_ok = hmac.compare_digest(_hash(username, self._salt), self._user_hash)
        pass_ok = hmac.compare_digest(_hash(password, self._salt), self._pass_hash)
        if not (user_ok and pass_ok):
            self._failures[ip].append(self._clock())
            return LoginResult(False, reason="wrong", retry_after_s=self._locked_for(ip))
        self._failures.pop(ip, None)
        token = secrets.token_urlsafe(32)
        ttl = self._config().settings.server.session_ttl_hours * 3600.0
        key, expires = self._digest(token), self._clock() + ttl
        self._sessions[key] = expires
        if self._store is not None:
            self._store.add(key, expires)
        self._purge()
        return LoginResult(True, token=token)

    # -- sessions -----------------------------------------------------------------------------------
    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def valid(self, token: str | None) -> bool:
        if not token or not self._refresh():
            return False
        key = self._digest(token)
        expires = self._sessions.get(key)
        if expires is None:
            return False
        if expires < self._clock():
            self._forget(key)
            return False
        return True

    def logout(self, token: str | None) -> None:
        if token:
            self._forget(self._digest(token))

    def logout_everywhere(self) -> None:
        """End every session on every device."""
        self._sessions.clear()
        if self._store is not None:
            self._store.clear()

    def _forget(self, key: str) -> None:
        self._sessions.pop(key, None)
        if self._store is not None:
            self._store.remove(key)

    def _purge(self) -> None:
        now = self._clock()
        for key in [k for k, expires in self._sessions.items() if expires < now]:
            del self._sessions[key]

    @property
    def session_count(self) -> int:
        return len(self._sessions)

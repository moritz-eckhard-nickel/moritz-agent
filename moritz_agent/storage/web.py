# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Web sessions in SQLite, so a login lasts across restarts (docs/plan/15 P2-01, API-05).

Only the sha256 of a session token is stored. The login itself is represented by a scrypt tag with a
random salt: when the user name or password in ``passwords.txt`` changed while the service was down,
the tag no longer matches and every stored session is dropped.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from moritz_agent.storage.db import Database

SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _tag(username: str, password: str, salt: bytes) -> bytes:
    value = f"{username}\0{password}".encode()
    return hashlib.scrypt(value, salt=salt, **SCRYPT)  # type: ignore[arg-type]


class SessionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def load(self, now: float) -> dict[str, float]:
        self.db.execute("DELETE FROM web_sessions WHERE expires_at < ?", (now,))
        rows = self.db.query("SELECT token_hash, expires_at FROM web_sessions")
        return {row["token_hash"]: float(row["expires_at"]) for row in rows}

    def add(self, token_hash: str, expires_at: float) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO web_sessions (token_hash, expires_at, created_at) "
            "VALUES (?, ?, ?)",
            (token_hash, expires_at, time.time()),
        )

    def remove(self, token_hash: str) -> None:
        self.db.execute("DELETE FROM web_sessions WHERE token_hash = ?", (token_hash,))

    def clear(self) -> None:
        self.db.execute("DELETE FROM web_sessions")

    def same_login(self, username: str, password: str) -> bool:
        """True when the stored sessions belong to this login; otherwise remember it and say False."""
        row = self.db.query("SELECT salt, tag FROM web_login_tag WHERE id = 1")
        if row and hmac.compare_digest(_tag(username, password, row[0]["salt"]), row[0]["tag"]):
            return True
        salt = os.urandom(16)
        self.db.execute(
            "INSERT OR REPLACE INTO web_login_tag (id, salt, tag) VALUES (1, ?, ?)",
            (salt, _tag(username, password, salt)),
        )
        return False

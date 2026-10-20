# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Notes and shopping list (docs/plan/13 §6.13) in a small local SQLite file.

The only thing the instant answers ever write. Off by default (``skills.notes.enabled``); anyone
who can call extension 999 can read the lists – see docs/plan/13 §12.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path


class NotesStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, list TEXT NOT NULL, text TEXT NOT NULL, "
            "created REAL NOT NULL)"
        )
        return conn

    def add(self, list_name: str, text: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO notes (list, text, created) VALUES (?, ?, ?)",
                (list_name, text.strip()[:200], time.time()),
            )

    def read(self, list_name: str) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT text FROM notes WHERE list = ? ORDER BY id", (list_name,)
            ).fetchall()
        return [row[0] for row in rows]

    def clear(self, list_name: str) -> int:
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM notes WHERE list = ?", (list_name,)).rowcount

    def purge(self, retention_days: int) -> int:
        """Delete entries older than ``retention_days``; returns how many."""
        cutoff = time.time() - retention_days * 86400
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM notes WHERE created < ?", (cutoff,)).rowcount

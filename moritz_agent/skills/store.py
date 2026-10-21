# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Notes and shopping list (docs/plan/13 §6.13) in the program's SQLite database.

The only thing the instant answers ever write. Off by default (``skills.notes.enabled``); anyone
who can call extension 999 can read the lists – see docs/plan/13 §12.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from moritz_agent.storage.db import Database, now_iso


class NotesStore:
    def __init__(self, database: Database | Path) -> None:
        self.db = database if isinstance(database, Database) else Database(database)

    def add(self, list_name: str, text: str) -> None:
        self.db.execute(
            "INSERT INTO notes (list, text, created_at) VALUES (?, ?, ?)",
            (list_name, text.strip()[:200], now_iso()),
        )

    def read(self, list_name: str) -> list[str]:
        rows = self.db.query(
            "SELECT text FROM notes WHERE list = ? AND done_at IS NULL ORDER BY id", (list_name,)
        )
        return [row["text"] for row in rows]

    def clear(self, list_name: str) -> int:
        return self.db.execute("DELETE FROM notes WHERE list = ?", (list_name,)).rowcount

    def purge(self, retention_days: int) -> int:
        """Delete entries older than ``retention_days``; returns how many."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        return self.db.execute("DELETE FROM notes WHERE created_at < ?", (cutoff,)).rowcount

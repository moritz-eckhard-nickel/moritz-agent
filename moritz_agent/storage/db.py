# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""SQLite in WAL mode with versioned, transactional migrations (STORE-01, STORE-02, UPD-06)."""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from moritz_agent.logging_setup import get_logger

log = get_logger("storage")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class StorageError(RuntimeError):
    """The database cannot be opened or migrated."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise StorageError("duplicate migration version")
    return found


class Database:
    """One shared connection (SQLite serialises writers anyway) guarded by a lock."""

    def __init__(self, path: Path, *, migrations: Path = MIGRATIONS_DIR) -> None:
        self.path = Path(path)
        self.migrations = migrations
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._migrated = False

    # -- connection -------------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
                except (OSError, sqlite3.Error) as exc:
                    raise StorageError(f"cannot open database ({type(exc).__name__})") from exc
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._conn = conn
                with suppress(OSError):
                    self.path.chmod(0o600)
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                self._migrated = False

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """``BEGIN IMMEDIATE … COMMIT``; rolls back on any exception."""
        with self._lock:
            conn = self.ensure()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def ensure(self) -> sqlite3.Connection:
        """The connection, with all migrations applied (done once)."""
        with self._lock:
            conn = self.connect()
            if not self._migrated:
                self.migrate()
            return conn

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.ensure().execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.ensure().execute(sql, params).fetchall()

    # -- migrations ---------------------------------------------------------------------------
    def current_version(self) -> int:
        conn = self.connect()
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return 0
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)

    def migrate(self) -> list[int]:
        """Apply the missing migrations in order, each in its own transaction."""
        with self._lock:
            conn = self.connect()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            files = migration_files(self.migrations)
            newest = max((v for v, _ in files), default=0)
            if done and max(done) > newest:
                raise StorageError(
                    f"database is newer (version {max(done)}) than this program (version {newest})"
                )
            applied: list[int] = []
            for version, path in files:
                if version in done:
                    continue
                script = path.read_text(encoding="utf-8")
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    for statement in _statements(script):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (version, now_iso()),
                    )
                    conn.execute("COMMIT")
                except sqlite3.Error as exc:
                    conn.execute("ROLLBACK")
                    raise StorageError(f"migration {path.name} failed ({exc})") from exc
                applied.append(version)
                log.info("Datenbank-Migration %04d angewendet", version)
            self._migrated = True
            return applied

    # -- backup ---------------------------------------------------------------------------------
    def backup(self, target: Path) -> Path:
        """Consistent copy of the live database (for the updater, UPD-02)."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with self._lock:
            source = self.ensure()
            destination = sqlite3.connect(tmp)
            try:
                source.backup(destination)
            finally:
                destination.close()
        tmp.replace(target)
        return target


def _statements(script: str) -> list[str]:
    """Split a migration script at semicolons that end a statement (no triggers/strings with ';')."""
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]

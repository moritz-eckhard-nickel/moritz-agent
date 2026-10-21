# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""SQLite storage: migrations, repo, retention, backup (P1-06)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

import pytest

from moritz_agent.storage import Database, Repo, StorageError
from moritz_agent.storage.db import migration_files


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "data" / "agent.sqlite3")
    yield database
    database.close()


def test_the_first_use_creates_and_migrates_the_database(db):
    assert not db.path.exists()
    assert db.query("SELECT version FROM schema_migrations") and db.current_version() == 2
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "calls",
        "call_turns",
        "tool_calls",
        "notes",
        "skill_misses",
        "schema_migrations",
    } <= tables
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"
    assert oct(db.path.stat().st_mode & 0o777) == "0o600"


def test_migrations_run_once_and_in_order(db, tmp_path):
    assert db.migrate() == [1] or db.migrate() == []
    assert db.migrate() == []
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (folder / "0002_b.sql").write_text(
        "-- comment\nCREATE TABLE b (y INTEGER);\nINSERT INTO b VALUES (7);"
    )
    other = Database(tmp_path / "other.sqlite3", migrations=folder)
    assert other.migrate() == [1, 2]
    assert other.query("SELECT y FROM b")[0][0] == 7
    (folder / "0003_c.sql").write_text("CREATE TABLE c (z INTEGER);")
    assert other.migrate() == [3]


def test_a_failing_migration_rolls_back_completely(tmp_path):
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
    (folder / "0002_bad.sql").write_text(
        "CREATE TABLE b (y INTEGER);\nINSERT INTO nowhere VALUES (1);"
    )
    database = Database(tmp_path / "x.sqlite3", migrations=folder)
    with pytest.raises(StorageError, match=r"0002_bad\.sql"):
        database.migrate()
    assert database.current_version() == 1
    names = {r["name"] for r in database.connect().execute("SELECT name FROM sqlite_master")}
    assert "a" in names and "b" not in names


def test_a_newer_database_is_refused(db, tmp_path):
    db.migrate()
    db.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (99, 'x')")
    again = Database(db.path)
    with pytest.raises(StorageError, match="newer"):
        again.migrate()


def test_duplicate_migration_versions_are_refused(tmp_path):
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;")
    with pytest.raises(StorageError):
        migration_files(tmp_path)


def test_unusable_paths_give_a_clean_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(StorageError):
        Database(blocker / "sub" / "db.sqlite3").connect()


def test_transactions_commit_and_roll_back(db):
    db.migrate()
    with db.transaction() as conn:
        conn.execute("INSERT INTO notes (list, text, created_at) VALUES ('a', 'x', 't')")
    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("INSERT INTO notes (list, text, created_at) VALUES ('a', 'y', 't')")
        raise RuntimeError("boom")
    assert [r["text"] for r in db.query("SELECT text FROM notes")] == ["x"]


def test_concurrent_writers_do_not_lose_rows(db):
    repo = Repo(db)
    repo.start_call("c1")

    def write(n):
        for i in range(25):
            repo.add_turn("c1", n * 100 + i, user_text="u", agent_text="a", path="agent")

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert db.query("SELECT COUNT(*) FROM call_turns")[0][0] == 100


def test_calls_turns_and_tool_calls(db):
    repo = Repo(db)
    repo.start_call("call-1", "sip:20@192.168.1.176", "PCMA")
    turn = repo.add_turn(
        "call-1",
        1,
        user_text="wie spät",
        agent_text="Es ist …",
        path="skill",
        timings={"total": 120, "stt": 800},
    )
    repo.add_tool_call(
        "skill:time.now", args={"x": 1}, ok=True, duration_ms=3, call_id="call-1", turn_id=turn
    )
    repo.add_tool_call("skill:weather.now", ok=False, error="offline", duration_ms=1200)
    repo.end_call("call-1", "goodbye", 1)
    call = db.query("SELECT * FROM calls WHERE id='call-1'")[0]
    assert (call["end_reason"], call["turns"], call["codec"]) == ("goodbye", 1, "PCMA")
    assert db.query("SELECT t_total_ms, t_stt_ms, channel FROM call_turns")[0][:] == (
        120,
        800,
        "phone",
    )
    stats = {row["tool"]: row for row in repo.skill_stats()}
    assert stats["skill:time.now"]["ok"] == 1 and stats["skill:weather.now"]["ok"] == 0
    assert repo.recent_tool_calls(1)[0]["tool"] == "skill:weather.now"


def test_transcripts_can_be_switched_off(db):
    repo = Repo(db, store_transcripts=False)
    repo.start_call("c")
    repo.add_turn("c", 1, user_text="geheim", agent_text="auch geheim", path="agent")
    repo.add_miss("geheim", None)
    row = db.query("SELECT user_text, agent_text, path FROM call_turns")[0]
    assert (row["user_text"], row["agent_text"], row["path"]) == (None, None, "agent")
    assert repo.recent_misses() == []


def test_retention_blanks_old_transcripts_and_deletes_misses(db):
    repo = Repo(db)
    repo.start_call("c")
    repo.add_turn("c", 1, user_text="alt", agent_text="alt", path="agent")
    repo.add_turn("c", 2, user_text="neu", agent_text="neu", path="agent")
    repo.add_miss("alte frage", "weather.now", 0.6)
    repo.add_miss("neue frage", None)
    old = (datetime.now(UTC) - timedelta(hours=30)).isoformat(timespec="seconds")
    db.execute("UPDATE call_turns SET created_at = ? WHERE idx = 1", (old,))
    db.execute("UPDATE skill_misses SET created_at = ? WHERE text = 'alte frage'", (old,))
    assert repo.purge(24) == {"turns": 1, "misses": 1}
    rows = db.query("SELECT idx, user_text FROM call_turns ORDER BY idx")
    assert [(r["idx"], r["user_text"]) for r in rows] == [(1, None), (2, "neu")]
    assert [m["text"] for m in repo.recent_misses()] == ["neue frage"]
    assert repo.purge(24) == {"turns": 0, "misses": 0}


def test_backup_is_a_consistent_copy(db, tmp_path):
    repo = Repo(db)
    repo.start_call("c1")
    target = db.backup(tmp_path / "backup" / "agent.bak")
    copy = sqlite3.connect(target)
    try:
        assert copy.execute("SELECT id FROM calls").fetchone()[0] == "c1"
        assert copy.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
    finally:
        copy.close()
    assert not list((tmp_path / "backup").glob("*.tmp"))

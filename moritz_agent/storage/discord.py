# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Tables of the Discord integration and the scheduler (docs/plan/14 §16): people, subscriptions,
reminders, the outbox for the worker and small pieces of scheduler state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from moritz_agent.storage.db import Database

OUTBOX_KEEP_DAYS = 7
MAX_ATTEMPTS = 8
RETRY_FIRST_S = (
    20  # a failed delivery waits 20 s, 40 s, 80 s … (at most RETRY_MAX_S) – ~40 min in all
)
RETRY_MAX_S = 30 * 60


def retry_delay(attempts: int) -> timedelta:
    """The pause after the ``attempts``-th failed delivery (exponential, capped)."""
    return timedelta(seconds=min(RETRY_FIRST_S * 2 ** max(attempts - 1, 0), RETRY_MAX_S))


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


class DiscordStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- people -----------------------------------------------------------------------------------
    def principal(self, user_id: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM discord_principals WHERE user_id = ?", (user_id,))
        return dict(rows[0]) if rows else None

    def save_principal(self, user_id: str, role: str, **fields: str | None) -> dict[str, Any]:
        """Create or update; ``fields``: home_postal_code, home_name, quiet_hours, voice_reply."""
        allowed = {"home_postal_code", "home_name", "quiet_hours", "voice_reply"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown field {sorted(unknown)[0]}")
        now = iso(datetime.now(UTC))
        current = self.principal(user_id)
        if current is None:
            columns = ["user_id", "role", "created_at", "updated_at", *fields]
            values = [user_id, role, now, now, *fields.values()]
            marks = ",".join("?" for _ in columns)
            self.db.execute(
                f"INSERT INTO discord_principals ({','.join(columns)}) VALUES ({marks})",
                tuple(values),
            )
        else:
            changes = {"role": role, "updated_at": now, **fields}
            sets = ",".join(f"{column} = ?" for column in changes)
            self.db.execute(
                f"UPDATE discord_principals SET {sets} WHERE user_id = ?",
                (*changes.values(), user_id),
            )
        principal = self.principal(user_id)
        assert principal is not None
        return principal

    # -- subscriptions ------------------------------------------------------------------------------
    def set_subscription(
        self, user_id: str, kind: str, params: dict[str, Any] | None = None
    ) -> None:
        self.db.execute(
            "INSERT INTO discord_subscriptions (user_id, kind, params_json, created_at) "
            "VALUES (?,?,?,?) ON CONFLICT(user_id, kind) DO UPDATE SET params_json = excluded.params_json",
            (user_id, kind, json.dumps(params or {}, ensure_ascii=False), iso(datetime.now(UTC))),
        )

    def remove_subscription(self, user_id: str, kind: str) -> bool:
        cursor = self.db.execute(
            "DELETE FROM discord_subscriptions WHERE user_id = ? AND kind = ?", (user_id, kind)
        )
        return cursor.rowcount > 0

    def subscriptions(
        self, kind: str | None = None, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM discord_subscriptions WHERE 1=1", []
        if kind is not None:
            sql, args = sql + " AND kind = ?", [*args, kind]
        if user_id is not None:
            sql, args = sql + " AND user_id = ?", [*args, user_id]
        rows = self.db.query(sql + " ORDER BY id", tuple(args))
        return [{**dict(row), "params": json.loads(row["params_json"])} for row in rows]

    # -- reminders ----------------------------------------------------------------------------------
    def add_reminder(self, user_id: str | None, target: str, due: datetime, text: str) -> int:
        cursor = self.db.execute(
            "INSERT INTO reminders (channel, user_id, target, due_at, text, created_at) "
            "VALUES ('discord',?,?,?,?,?)",
            (user_id, target, iso(due), text[:500], iso(datetime.now(UTC))),
        )
        return int(cursor.lastrowid or 0)

    def open_reminders(self, user_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM reminders WHERE delivered_at IS NULL", ()
        if user_id is not None:
            sql, args = sql + " AND user_id = ?", (user_id,)
        return [dict(r) for r in self.db.query(sql + " ORDER BY due_at", args)]

    def due_reminders(self, now: datetime) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM reminders WHERE delivered_at IS NULL AND due_at <= ? ORDER BY due_at",
            (iso(now),),
        )
        return [dict(r) for r in rows]

    def mark_reminder_delivered(self, reminder_id: int, now: datetime) -> None:
        self.db.execute(
            "UPDATE reminders SET delivered_at = ? WHERE id = ?", (iso(now), reminder_id)
        )

    def cancel_reminder(self, reminder_id: int, user_id: str | None = None) -> bool:
        sql, args = "DELETE FROM reminders WHERE id = ? AND delivered_at IS NULL", (reminder_id,)
        if user_id is not None:
            sql, args = sql + " AND user_id = ?", (reminder_id, user_id)
        return self.db.execute(sql, args).rowcount > 0

    # -- outbox ---------------------------------------------------------------------------------------
    def enqueue(
        self,
        kind: str,
        target: str,
        payload: dict[str, Any],
        *,
        user_id: str | None = None,
        serious: bool = False,
        dedupe_key: str | None = None,
        not_before: datetime | None = None,
    ) -> int | None:
        """Queue a message; ``None`` when an open message with the same ``dedupe_key`` exists."""
        if dedupe_key is not None:
            rows = self.db.query(
                "SELECT 1 FROM outbox WHERE dedupe_key = ? AND delivered_at IS NULL LIMIT 1",
                (dedupe_key,),
            )
            if rows:
                return None
        cursor = self.db.execute(
            "INSERT INTO outbox (kind, target, user_id, payload_json, serious, dedupe_key, "
            "not_before, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                kind,
                target,
                user_id,
                json.dumps(payload, ensure_ascii=False),
                1 if serious else 0,
                dedupe_key,
                iso(not_before) if not_before else None,
                iso(datetime.now(UTC)),
            ),
        )
        return int(cursor.lastrowid or 0)

    def pending(self, now: datetime, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM outbox WHERE delivered_at IS NULL AND attempts < ? "
            "AND (not_before IS NULL OR not_before <= ?) ORDER BY id LIMIT ?",
            (MAX_ATTEMPTS, iso(now), limit),
        )
        return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows]

    def ack(self, outbox_id: int, delivered: bool, now: datetime) -> None:
        if delivered:
            self.db.execute(
                "UPDATE outbox SET delivered_at = ? WHERE id = ?", (iso(now), outbox_id)
            )
        else:
            rows = self.db.query("SELECT attempts FROM outbox WHERE id = ?", (outbox_id,))
            if not rows:
                return
            attempts = int(rows[0]["attempts"]) + 1
            # the next try waits (not_before is past anyway once an item was handed out)
            self.db.execute(
                "UPDATE outbox SET attempts = ?, not_before = ? WHERE id = ?",
                (attempts, iso(now + retry_delay(attempts)), outbox_id),
            )

    def purge_outbox(self, now: datetime) -> int:
        cutoff = iso(now - timedelta(days=OUTBOX_KEEP_DAYS))
        cursor = self.db.execute(
            "DELETE FROM outbox WHERE created_at < ? AND (delivered_at IS NOT NULL OR attempts >= ?)",
            (cutoff, MAX_ATTEMPTS),
        )
        return cursor.rowcount

    # -- scheduler state ----------------------------------------------------------------------------------
    def state(self, key: str) -> str | None:
        rows = self.db.query("SELECT value FROM scheduler_state WHERE key = ?", (key,))
        return str(rows[0]["value"]) if rows else None

    def set_state(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO scheduler_state (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, iso(datetime.now(UTC))),
        )

    def drop_state(self, key: str) -> bool:
        return self.db.execute("DELETE FROM scheduler_state WHERE key = ?", (key,)).rowcount > 0

    def states(self, prefix: str) -> dict[str, str]:
        rows = self.db.query(
            "SELECT key, value FROM scheduler_state WHERE substr(key, 1, ?) = ?",
            (len(prefix), prefix),
        )
        return {r["key"]: r["value"] for r in rows}

    # -- command registry (docs/plan/14 §7) ------------------------------------------------------------------
    def registered_hash(self) -> str | None:
        rows = self.db.query("SELECT hash FROM command_registry ORDER BY rowid DESC LIMIT 1")
        return str(rows[0]["hash"]) if rows else None

    def save_registered_hash(self, digest: str) -> None:
        self.db.execute("DELETE FROM command_registry")
        self.db.execute(
            "INSERT INTO command_registry (hash, registered_at) VALUES (?,?)",
            (digest, iso(datetime.now(UTC))),
        )

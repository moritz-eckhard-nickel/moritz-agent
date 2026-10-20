-- SPDX-License-Identifier: LicenseRef-MSOL-1.1
-- Discord and scheduled messages (docs/plan/14-discord.md §16).

CREATE TABLE discord_principals (
    user_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    home_postal_code TEXT,
    home_name TEXT,
    quiet_hours TEXT,
    voice_reply TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE discord_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (user_id, kind)
);

CREATE TABLE reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT 'discord',
    user_id TEXT,
    target TEXT NOT NULL,
    due_at TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX reminders_due ON reminders(delivered_at, due_at);

-- Messages the main process wants the Discord worker to send (reminders, warnings, briefings …).
CREATE TABLE outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL DEFAULT 'discord',
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    user_id TEXT,
    payload_json TEXT NOT NULL,
    serious INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT,
    not_before TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX outbox_open ON outbox(delivered_at, id);
CREATE INDEX outbox_dedupe ON outbox(dedupe_key);

-- What was announced already (warnings are announced once per change, briefings once per day).
CREATE TABLE scheduler_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE command_registry (
    hash TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

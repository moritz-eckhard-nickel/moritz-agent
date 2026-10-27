-- SPDX-License-Identifier: LicenseRef-MSOL-1.1
-- Conversations of every channel for the WebUI history, and the runs behind web answers
-- (docs/plan/15 P2-04, ADR-041). Kept 15 days unless pinned.

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,                 -- h-<hex>
    source TEXT NOT NULL,                -- web | phone | discord | voice
    external_id TEXT NOT NULL,           -- web:w-…, the call id, the Discord conversation
    title TEXT NOT NULL DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,   -- saved by Moritz: never deleted automatically
    created_at REAL NOT NULL,            -- unix time
    updated_at REAL NOT NULL
);

CREATE INDEX conversations_external ON conversations (external_id, updated_at);

CREATE INDEX conversations_updated ON conversations (updated_at);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role TEXT NOT NULL,                  -- user | assistant
    text TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}', -- skill, tools, sources
    created_at REAL NOT NULL
);

CREATE INDEX messages_conversation ON messages (conversation_id, id);

-- full text search; kept in step by HistoryStore (the migration runner cannot create triggers)
CREATE VIRTUAL TABLE messages_fts USING fts5 (
    text,
    conversation_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    message_id INTEGER,                  -- the answer it made (none when cancelled early)
    status TEXT NOT NULL,                -- done | cancelled | error
    started_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE run_events (
    run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

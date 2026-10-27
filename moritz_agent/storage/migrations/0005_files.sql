-- SPDX-License-Identifier: LicenseRef-MSOL-1.1
-- Files dropped into a chat of the WebUI (docs/plan/15 P2-05). The bytes and the extracted text lie in
-- data/files/; they go with the conversation.

CREATE TABLE files (
    id TEXT PRIMARY KEY,                 -- f-<hex>, also the file name on disk
    external_id TEXT NOT NULL,           -- the chat: web:w-…
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                  -- text | pdf
    size INTEGER NOT NULL,
    pages INTEGER,
    chars INTEGER NOT NULL,
    truncated INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX files_external ON files (external_id);

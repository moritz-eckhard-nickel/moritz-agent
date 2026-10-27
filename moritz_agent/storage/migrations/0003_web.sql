-- SPDX-License-Identifier: LicenseRef-MSOL-1.1
-- Web interface: sessions that survive a restart (docs/plan/15 P2-01).

CREATE TABLE web_sessions (
    token_hash TEXT PRIMARY KEY,      -- sha256 of the cookie value, never the value itself
    expires_at REAL NOT NULL,         -- unix time
    created_at REAL NOT NULL
);

-- one row: scrypt tag of the web login the sessions belong to (a changed login ends them)
CREATE TABLE web_login_tag (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    salt BLOB NOT NULL,
    tag BLOB NOT NULL
);

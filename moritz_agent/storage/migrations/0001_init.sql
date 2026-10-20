-- SPDX-License-Identifier: LicenseRef-MSOL-1.1
-- Part 1 schema (docs/plan/02-architektur.md §8).

CREATE TABLE calls (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    answered_at TEXT,
    ended_at TEXT,
    remote_uri TEXT,
    codec TEXT,
    end_reason TEXT,
    turns INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE call_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT REFERENCES calls(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL DEFAULT 'phone',
    user_text TEXT,
    agent_text TEXT,
    path TEXT,
    t_vad_end_ms INTEGER,
    t_stt_ms INTEGER,
    t_llm_first_ms INTEGER,
    t_llm_total_ms INTEGER,
    t_tools_ms INTEGER,
    t_tts_first_ms INTEGER,
    t_total_ms INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX call_turns_call ON call_turns(call_id, idx);
CREATE INDEX call_turns_created ON call_turns(created_at);

CREATE TABLE tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    turn_id INTEGER,
    channel TEXT NOT NULL DEFAULT 'phone',
    tool TEXT NOT NULL,
    args_json TEXT,
    ok INTEGER NOT NULL,
    error TEXT,
    result_summary TEXT,
    sources_json TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX tool_calls_tool ON tool_calls(tool, created_at);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    done_at TEXT
);

CREATE TABLE skill_misses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    best_skill TEXT,
    score REAL,
    created_at TEXT NOT NULL
);

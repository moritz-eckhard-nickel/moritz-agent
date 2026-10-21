# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""What the program stores: calls, turns, tool calls, notes, missed questions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from moritz_agent.storage.db import Database, now_iso


class Repo:
    def __init__(self, db: Database, *, store_transcripts: bool = True) -> None:
        self.db = db
        self.store_transcripts = store_transcripts

    # -- calls ---------------------------------------------------------------------------------
    def start_call(
        self, call_id: str, remote_uri: str = "", codec: str = "", *, answered: bool = True
    ) -> None:
        now = now_iso()
        self.db.execute(
            "INSERT OR REPLACE INTO calls (id, started_at, answered_at, remote_uri, codec) "
            "VALUES (?, ?, ?, ?, ?)",
            (call_id, now, now if answered else None, remote_uri, codec),
        )

    def end_call(self, call_id: str, reason: str, turns: int) -> None:
        self.db.execute(
            "UPDATE calls SET ended_at = ?, end_reason = ?, turns = ? WHERE id = ?",
            (now_iso(), reason, turns, call_id),
        )

    def add_turn(
        self,
        call_id: str | None,
        idx: int,
        *,
        user_text: str | None,
        agent_text: str | None,
        path: str,
        channel: str = "phone",
        timings: dict[str, int] | None = None,
    ) -> int:
        timings = timings or {}
        keep = self.store_transcripts
        cursor = self.db.execute(
            "INSERT INTO call_turns (call_id, idx, channel, user_text, agent_text, path, "
            "t_vad_end_ms, t_stt_ms, t_llm_first_ms, t_llm_total_ms, t_tools_ms, t_tts_first_ms, "
            "t_total_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                call_id,
                idx,
                channel,
                user_text if keep else None,
                agent_text if keep else None,
                path,
                timings.get("vad_end"),
                timings.get("stt"),
                timings.get("llm_first"),
                timings.get("llm_total"),
                timings.get("tools"),
                timings.get("tts_first"),
                timings.get("total_ms", timings.get("total")),
                now_iso(),
            ),
        )
        return int(cursor.lastrowid or 0)

    def add_tool_call(
        self,
        tool: str,
        *,
        args: dict[str, Any] | None = None,
        ok: bool,
        error: str | None = None,
        summary: str = "",
        sources: list[dict[str, Any]] | None = None,
        duration_ms: int = 0,
        call_id: str | None = None,
        turn_id: int | None = None,
        channel: str = "phone",
    ) -> None:
        self.db.execute(
            "INSERT INTO tool_calls (call_id, turn_id, channel, tool, args_json, ok, error, "
            "result_summary, sources_json, duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                call_id,
                turn_id,
                channel,
                tool,
                json.dumps(args or {}, ensure_ascii=False),
                1 if ok else 0,
                error,
                summary[:300],
                json.dumps(sources, ensure_ascii=False) if sources else None,
                duration_ms,
                now_iso(),
            ),
        )

    # -- missed questions ------------------------------------------------------------------------
    def add_miss(self, text: str, best_skill: str | None, score: float = 0.0) -> None:
        if self.store_transcripts:
            self.db.execute(
                "INSERT INTO skill_misses (text, best_skill, score, created_at) VALUES (?,?,?,?)",
                (text[:300], best_skill, score, now_iso()),
            )

    def recent_misses(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT text, best_skill, score, created_at FROM skill_misses ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # -- statistics -------------------------------------------------------------------------------
    def skill_stats(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT tool, COUNT(*) AS calls, SUM(ok) AS ok, AVG(duration_ms) AS avg_ms "
            "FROM tool_calls WHERE tool LIKE 'skill:%' GROUP BY tool ORDER BY calls DESC"
        )
        return [dict(row) for row in rows]

    def recent_tool_calls(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT tool, ok, duration_ms, created_at, channel FROM tool_calls "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    # -- retention ----------------------------------------------------------------------------------
    def purge(self, transcript_retention_hours: int) -> dict[str, int]:
        """Blank transcripts and delete missed questions older than the retention time."""
        cutoff = (datetime.now(UTC) - timedelta(hours=transcript_retention_hours)).isoformat(
            timespec="seconds"
        )
        with self.db.transaction() as conn:
            turns = conn.execute(
                "UPDATE call_turns SET user_text = NULL, agent_text = NULL "
                "WHERE created_at < ? AND (user_text IS NOT NULL OR agent_text IS NOT NULL)",
                (cutoff,),
            ).rowcount
            misses = conn.execute(
                "DELETE FROM skill_misses WHERE created_at < ?", (cutoff,)
            ).rowcount
            # tool arguments (a search query) and the summary (the answer) are transcript text too
            tools = conn.execute(
                "UPDATE tool_calls SET args_json = NULL, result_summary = NULL "
                "WHERE created_at < ? AND (args_json IS NOT NULL OR result_summary IS NOT NULL)",
                (cutoff,),
            ).rowcount
        return {"turns": turns, "misses": misses, "tools": tools}

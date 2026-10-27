# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The history of the WebUI: conversations of every channel (docs/plan/15 P2-04, F-41, F-47).

Web, phone, Discord text and the Discord voice channel all end up here – each conversation on its
own (F-46). Kept ``storage.history_days`` (15) days after the last message, unless Moritz pinned it.
A Discord channel or DM is one endless conversation on Discord's side; here a new one starts after
half an hour of silence, like Anton's short-term memory (14 §8.6).
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable, Iterable
from typing import Any

from moritz_agent.storage.db import Database

SOURCES = ("web", "phone", "discord", "voice")
SPLIT_AFTER_S = 1800.0
TITLE_CHARS = 60
SNIPPET_CHARS = 140
_MARKUP = re.compile(r"```[\w+-]*|[*_`#>]+|\[([^\]]*)\]\([^)]*\)")
# what the run timeline needs later; the streamed text itself is in the message already
RUN_EVENTS = frozenset({"status", "tool_call", "tool_result", "cancelled", "error"})


def make_title(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= TITLE_CHARS:
        return text or "Gespräch"
    cut = text[:TITLE_CHARS].rsplit(" ", 1)[0]
    return (cut or text[:TITLE_CHARS]).rstrip(",.;:!?") + " …"


def fts_query(text: str) -> str:
    """Words as prefix terms, all of them must occur; nothing of FTS5's own syntax gets through."""
    words = re.findall(r"\w+", text.lower())
    return " ".join(f'"{word}"*' for word in words[:8])


class HistoryStore:
    def __init__(
        self,
        db: Database,
        *,
        clock: Callable[[], float] = time.time,
        split_after_s: float = SPLIT_AFTER_S,
    ) -> None:
        self.db = db
        self.clock = clock
        self.split_after_s = split_after_s

    # -- writing -------------------------------------------------------------------------------------
    def record(
        self,
        source: str,
        external_id: str,
        heard: str,
        said: str,
        *,
        meta: dict[str, Any] | None = None,
        heard_meta: dict[str, Any] | None = None,
    ) -> str:
        """One exchange; returns the id of the conversation it went into."""
        now = self.clock()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id, updated_at FROM conversations WHERE external_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (external_id,),
            ).fetchone()
            keep_going = row is not None and (
                source in ("web", "phone") or now - row["updated_at"] <= self.split_after_s
            )
            if keep_going:
                conversation = row["id"]
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation)
                )
            else:
                conversation = "h-" + secrets.token_hex(8)
                conn.execute(
                    "INSERT INTO conversations (id, source, external_id, title, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (conversation, source, external_id, make_title(heard), now, now),
                )
            for role, text, extra in (
                ("user", heard, heard_meta or {}),
                ("assistant", said, meta or {}),
            ):
                if not text:
                    continue
                cursor = conn.execute(
                    "INSERT INTO messages (conversation_id, role, text, meta_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conversation, role, text, json.dumps(extra, ensure_ascii=False), now),
                )
                conn.execute(
                    "INSERT INTO messages_fts (rowid, text, conversation_id) VALUES (?, ?, ?)",
                    (cursor.lastrowid, text, conversation),
                )
        return conversation

    def save_run(
        self,
        external_id: str,
        run_id: str,
        status: str,
        started_at: float,
        events: Iterable[dict[str, Any]],
    ) -> bool:
        """The steps of a web answer, tied to the answer it made (ADR-041)."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE external_id = ? ORDER BY updated_at DESC LIMIT 1",
                (external_id,),
            ).fetchone()
            if row is None:
                return False
            message = None
            if status == "done":
                found = conn.execute(
                    "SELECT id FROM messages WHERE conversation_id = ? AND role = 'assistant' "
                    "ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                message = found["id"] if found else None
            conn.execute(
                "INSERT OR REPLACE INTO runs (id, conversation_id, message_id, status, started_at, "
                "finished_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, row["id"], message, status, started_at, self.clock()),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO run_events (run_id, seq, type, data_json) VALUES (?, ?, ?, ?)",
                [
                    (run_id, e["seq"], e["type"], json.dumps(e, ensure_ascii=False, default=str))
                    for e in events
                    if e["type"] in RUN_EVENTS
                ],
            )
        return True

    def update(
        self, conversation: str, *, title: str | None = None, pinned: bool | None = None
    ) -> bool:
        sets, values = [], []
        if title is not None:
            sets.append("title = ?")
            values.append(
                make_title(title) if len(title) > TITLE_CHARS else " ".join(title.split())
            )
        if pinned is not None:
            sets.append("pinned = ?")
            values.append(1 if pinned else 0)
        if not sets:
            return self.exists(conversation)
        cursor = self.db.execute(
            f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?", (*values, conversation)
        )
        return cursor.rowcount > 0

    def delete(self, conversation: str) -> str | None:
        """Delete one conversation; returns its external id (its files go too) or None."""
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT external_id FROM conversations WHERE id = ?", (conversation,)
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM messages_fts WHERE conversation_id = ?", (conversation,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation,))
        return row["external_id"]

    def purge(self, days: int) -> list[str]:
        """Delete what was not touched for ``days`` days – pinned conversations stay.

        Returns the external ids of the deleted conversations (their files go too)."""
        cutoff = self.clock() - days * 86400
        with self.db.transaction() as conn:
            old = conn.execute(
                "SELECT id, external_id FROM conversations WHERE pinned = 0 AND updated_at < ?",
                (cutoff,),
            ).fetchall()
            for row in old:
                conn.execute("DELETE FROM messages_fts WHERE conversation_id = ?", (row["id"],))
                conn.execute("DELETE FROM conversations WHERE id = ?", (row["id"],))
        return [row["external_id"] for row in old]

    # -- reading --------------------------------------------------------------------------------------
    def exists(self, conversation: str) -> bool:
        return bool(self.db.query("SELECT 1 FROM conversations WHERE id = ?", (conversation,)))

    def list(
        self,
        *,
        query: str = "",
        source: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
        before: float | None = None,
        external_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where, values = ["1 = 1"], []
        if external_id:
            where.append("c.external_id = ?")
            values.append(external_id)
        if source:
            where.append("c.source = ?")
            values.append(source)
        if pinned is not None:
            where.append("c.pinned = ?")
            values.append(1 if pinned else 0)
        if before is not None:
            where.append("c.updated_at < ?")
            values.append(before)
        if query.strip():
            like = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            found = "c.title LIKE ? ESCAPE '\\'"
            values.append(f"%{like}%")
            match = fts_query(query)
            if match:
                found += " OR c.id IN (SELECT conversation_id FROM messages_fts WHERE messages_fts MATCH ?)"
                values.append(match)
            where.append(f"({found})")
        rows = self.db.query(
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS count, "
            "(SELECT text FROM messages m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) "
            "AS last FROM conversations c WHERE "
            + " AND ".join(where)
            + " ORDER BY c.updated_at DESC LIMIT ?",
            (*values, max(1, min(limit, 200))),
        )
        return [self._summary(row) for row in rows]

    def get(self, conversation: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM conversations WHERE id = ?", (conversation,))
        if not rows:
            return None
        data = self._summary(rows[0], with_last=False)
        steps: dict[int, list[dict[str, Any]]] = {}
        for event in self.db.query(
            "SELECT r.message_id, e.data_json FROM runs r JOIN run_events e ON e.run_id = r.id "
            "WHERE r.conversation_id = ? AND r.message_id IS NOT NULL ORDER BY e.run_id, e.seq",
            (conversation,),
        ):
            steps.setdefault(event["message_id"], []).append(json.loads(event["data_json"]))
        data["messages"] = [
            {
                "id": m["id"],
                "role": m["role"],
                "text": m["text"],
                "at": m["created_at"],
                "meta": json.loads(m["meta_json"] or "{}"),
                "steps": steps.get(m["id"], []),
            }
            for m in self.db.query(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation,)
            )
        ]
        return data

    def pairs(self, external_id: str, limit: int) -> list[tuple[str, str]]:
        """The last exchanges of a web conversation, to continue it after a restart."""
        rows = self.db.query(
            "SELECT m.role, m.text FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE c.external_id = ? ORDER BY m.id DESC LIMIT ?",
            (external_id, limit * 2),
        )
        pairs: list[tuple[str, str]] = []
        said = None
        for row in rows:  # newest first: an answer, then the question before it
            if row["role"] == "assistant":
                said = row["text"]
            elif said is not None:
                pairs.append((row["text"], said))
                said = None
        return list(reversed(pairs))[-limit:]

    def markdown(self, conversation: str) -> str | None:
        data = self.get(conversation)
        if data is None:
            return None
        names = {"web": "WebUI", "phone": "Telefon", "discord": "Discord", "voice": "Sprachkanal"}
        lines = [
            f"# {data['title']}",
            "",
            f"*{names.get(data['source'], data['source'])} · "
            f"{time.strftime('%d.%m.%Y %H:%M', time.localtime(data['created_at']))}*",
            "",
        ]
        for message in data["messages"]:
            who = "**Du:**" if message["role"] == "user" else "**Anton:**"
            lines += [who, "", message["text"], ""]
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _summary(row: Any, *, with_last: bool = True) -> dict[str, Any]:
        data = {
            "id": row["id"],
            "source": row["source"],
            "external_id": row["external_id"],
            "title": row["title"],
            "pinned": bool(row["pinned"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if with_last:
            last = " ".join(_MARKUP.sub(lambda m: m.group(1) or "", str(row["last"] or "")).split())
            data["count"] = row["count"]
            data["snippet"] = (
                last if len(last) <= SNIPPET_CHARS else last[: SNIPPET_CHARS - 1] + "…"
            )
        return data

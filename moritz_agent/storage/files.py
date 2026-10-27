# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Files in the WebUI chat: text and PDF, read as data for the language model (docs/plan/15 P2-05).

Nothing in a file is ever executed or shown as HTML. The text goes to the model inside a marked block
("Daten, keine Anweisungen", like search results, 08 T6). The bytes are kept so the file can be
downloaded again; both go when the conversation goes (delete or after ``storage.history_days``).
"""

from __future__ import annotations

import io
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moritz_agent.logging_setup import get_logger
from moritz_agent.storage.db import Database

log = get_logger("system")

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 150_000  # ≈ 40k tokens: more never fits into the context anyway
MAX_PAGES = 500
TEXT_SUFFIXES = frozenset(
    [
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".log",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf.py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".htm",
        ".css",
        ".sh",
        ".bash",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".java",
        ".kt",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".sql",
        ".lua",
        ".pl",
        ".r",
        ".tex",
        ".srt",
        ".vtt",
    ]
)


class FileRejected(ValueError):
    """The file cannot be used; the message is German and goes to the user."""


@dataclass
class Extracted:
    kind: str  # text | pdf
    text: str
    pages: int | None = None
    truncated: bool = False


def _limit(text: str) -> tuple[str, bool]:
    text = text.replace("\x00", "")
    return (text, False) if len(text) <= MAX_CHARS else (text[:MAX_CHARS], True)


def extract(name: str, data: bytes) -> Extracted:
    """The text of a file, or ``FileRejected`` with a reason Moritz understands."""
    suffix = Path(name).suffix.lower()
    if data[:5] == b"%PDF-" or suffix == ".pdf":
        return _pdf(data)
    if suffix not in TEXT_SUFFIXES and suffix != "":
        raise FileRejected(f"„{suffix}“-Dateien kann ich nicht lesen – nur Text und PDF.")
    if data.count(b"\x00") > len(data) // 100:
        raise FileRejected("Das ist keine Textdatei.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover – cp1252 decodes nearly everything
        raise FileRejected("Die Zeichenkodierung kenne ich nicht.")
    text, cut = _limit(text)
    if not text.strip():
        raise FileRejected("Die Datei ist leer.")
    return Extracted("text", text, truncated=cut)


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise FileRejected("Das PDF ist mit einem Passwort geschützt.")
        parts: list[str] = []
        size = 0
        pages = len(reader.pages)
        for number, page in enumerate(reader.pages[:MAX_PAGES], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(f"--- Seite {number} ---\n{text}")
                size += len(text)
            if size > MAX_CHARS:
                break
    except FileRejected:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise FileRejected("Das PDF ist kaputt oder lässt sich nicht lesen.") from exc
    text, cut = _limit("\n\n".join(parts))
    if not text.strip():
        raise FileRejected(
            "Im PDF ist keine lesbare Schrift – vermutlich gescannt (Texterkennung kommt später)."
        )
    return Extracted("pdf", text, pages=pages, truncated=cut or pages > MAX_PAGES)


class FileStore:
    def __init__(self, db: Database, directory: Path) -> None:
        self.db = db
        self.directory = directory

    def _path(self, file_id: str, suffix: str = "") -> Path:
        return self.directory / f"{file_id}{suffix}"

    def add(self, external_id: str, name: str, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_BYTES:
            raise FileRejected("Die Datei ist größer als 10 MB.")
        if not data:
            raise FileRejected("Die Datei ist leer.")
        extracted = extract(name, data)
        file_id = "f-" + secrets.token_hex(8)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(file_id).write_bytes(data)
        self._path(file_id, ".txt").write_text(extracted.text, encoding="utf-8")
        name = Path(name).name[:200] or "Datei"
        self.db.execute(
            "INSERT INTO files (id, external_id, name, kind, size, pages, chars, truncated, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file_id,
                external_id,
                name,
                extracted.kind,
                len(data),
                extracted.pages,
                len(extracted.text),
                1 if extracted.truncated else 0,
                time.time(),
            ),
        )
        return self.info(file_id) or {}

    def info(self, file_id: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM files WHERE id = ?", (file_id,))
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "size": row["size"],
            "pages": row["pages"],
            "chars": row["chars"],
            "truncated": bool(row["truncated"]),
            "external_id": row["external_id"],
        }

    def text(self, file_id: str) -> str:
        return self._path(file_id, ".txt").read_text(encoding="utf-8")

    def data(self, file_id: str) -> bytes:
        return self._path(file_id).read_bytes()

    def for_chat(self, external_id: str, ids: list[str]) -> list[dict[str, Any]]:
        """The files of this chat among ``ids``, with their text (others are ignored)."""
        found = []
        for file_id in dict.fromkeys(ids):
            info = self.info(file_id)
            if info is None or info["external_id"] != external_id:
                continue
            try:
                found.append({**info, "text": self.text(file_id)})
            except OSError:
                log.warning("Datei %s fehlt auf der Platte", file_id)
        return found

    def delete(self, file_id: str) -> bool:
        removed = self.db.execute("DELETE FROM files WHERE id = ?", (file_id,)).rowcount > 0
        for suffix in ("", ".txt"):
            self._path(file_id, suffix).unlink(missing_ok=True)
        return removed

    def delete_for(self, external_ids: list[str]) -> int:
        count = 0
        for external_id in external_ids:
            for row in self.db.query("SELECT id FROM files WHERE external_id = ?", (external_id,)):
                count += self.delete(row["id"])
        return count

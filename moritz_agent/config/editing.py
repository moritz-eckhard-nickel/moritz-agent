# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Change single values of the configuration files, line by line (docs/plan/15 P2-08, P2-09).

Both files are edited, never re-serialised: comments, order and every other line stay as they are
(CLAUDE.md). ``passwords.txt`` is written with the same care – the new value goes into its one line,
it is never logged and never returned.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from moritz_agent.setup import files


class EditError(ValueError):
    """The value cannot be written; the message is German and names no secret."""


def toml_value(value: Any) -> str:
    """A Python value as a TOML value (strings in double quotes, lists inline)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EditError("Zahl ungültig")
        return repr(value)
    if isinstance(value, str):
        if "\n" in value or "\r" in value:
            raise EditError("Zeilenumbrüche sind hier nicht erlaubt")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    raise EditError(f"Wert vom Typ {type(value).__name__} kann ich nicht schreiben")


def _write(path: Path, text: str) -> None:
    """Replace the file in one step, keeping its permissions."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    tmp = path.with_name(f".{path.name}.edit")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def set_settings(path: Path, changes: Iterable[tuple[str, str, Any]]) -> str:
    """Write ``(section, key, value)`` into the TOML file; returns the old text (to undo)."""
    old = path.read_text(encoding="utf-8")
    text = old
    for section, key, value in changes:
        text = files.set_value(text, section, key, toml_value(value), keep_comment=True)
    if text != old:
        _write(path, text)
    return old


def set_secret(path: Path, section: str, key: str, value: str) -> str:
    """One value in ``passwords.txt``: its line is replaced or added, nothing else changes."""
    if value != value.strip() or "\n" in value or "\r" in value:
        raise EditError("Ohne Leerzeichen am Anfang/Ende und ohne Zeilenumbruch, bitte")
    old = path.read_text(encoding="utf-8")
    _write(path, files.set_value(old, section, key, value))
    return old


def restore(path: Path, text: str) -> None:
    _write(path, text)

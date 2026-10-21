# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Line-based edits of ``passwords.txt`` (INI) and ``config/moritz-agent.toml`` for the installer.

Neither file is ever parsed and written back (CFG-09): a missing section or key is *appended*, a
single value is replaced in its own line, everything else – comments, order, spacing, the values of
other keys – stays byte for byte. Writes are atomic and keep the file mode (passwords.txt: 0600).
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from pathlib import Path

DISCORD_PASSWORDS = (
    (
        "bot_token",
        "Bot-Token aus dem Discord Developer Portal (Anwendung → Bot → Reset Token). Leer = Discord aus.",
    ),
    (
        "channel_id",
        "ID des Standard-Textkanals (Entwicklermodus → Rechtsklick auf den Kanal → Kanal-ID kopieren).",
    ),
    ("admin_pin", "Optional: PIN für gefährliche Admin-Befehle (/admin neustart)."),
)
_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*(?:#.*)?$")


def _bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    """Line numbers of the header and the end (exclusive) of ``[section]``."""
    start = None
    for number, line in enumerate(lines):
        match = _SECTION.match(line)
        if match is None:
            continue
        if start is not None:
            return start, number
        if match.group("name").strip() == section:
            start = number
    return (start, len(lines)) if start is not None else None


def has_key(text: str, section: str, key: str) -> bool:
    lines = text.splitlines()
    bounds = _bounds(lines, section)
    if bounds is None:
        return False
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*[=:]")
    return any(pattern.match(line) for line in lines[bounds[0] + 1 : bounds[1]])


def get_value(text: str, section: str, key: str, *, comments: bool = False) -> str | None:
    """The value of a key; ``comments=True`` cuts a trailing ``# …`` (TOML, never for passwords)."""
    lines = text.splitlines()
    bounds = _bounds(lines, section)
    if bounds is None:
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*[=:]\s*(.*?)\s*$")
    for line in lines[bounds[0] + 1 : bounds[1]]:
        match = pattern.match(line)
        if match:
            value = match.group(1)
            return re.sub(r"\s+#.*$", "", value) if comments else value
    return None


def set_value(text: str, section: str, key: str, value: str, *, keep_comment: bool = False) -> str:
    """``key = value`` inside ``[section]``: replaces the line, or adds it (and the section).
    ``keep_comment=True`` keeps a trailing ``# …`` of the replaced line (TOML)."""
    lines = text.splitlines()
    new_line = f"{key} = {value}"
    bounds = _bounds(lines, section)
    if bounds is None:
        body = text if text.endswith("\n") or not text else text + "\n"
        return f"{body}\n[{section}]\n{new_line}\n"
    start, end = bounds
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*[=:]")
    for number in range(start + 1, end):
        if pattern.match(lines[number]):
            comment = re.search(r"\s+(#.*)$", lines[number]) if keep_comment else None
            lines[number] = new_line + (f"   {comment.group(1)}" if comment else "")
            return "\n".join(lines) + "\n"
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1  # before the empty lines that separate the next section
    lines.insert(insert_at, new_line)
    return "\n".join(lines) + "\n"


def migrate_passwords(text: str) -> tuple[str, list[str]]:
    """Add the ``[discord]`` section and any of its missing keys, with explaining comments."""
    added: list[str] = []
    lines = text.splitlines()
    if _bounds(lines, "discord") is None:
        body = text if text.endswith("\n") or not text else text + "\n"
        block = ["", "[discord]"]
        for key, comment in DISCORD_PASSWORDS:
            block += [f"# {comment}", f"{key} ="]
        text = body + "\n".join(block) + "\n"
        return text, ["discord"]
    for key, comment in DISCORD_PASSWORDS:
        if not has_key(text, "discord", key):
            lines = text.splitlines()
            start, end = _bounds(lines, "discord") or (0, len(lines))
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines[insert_at:insert_at] = [f"# {comment}", f"{key} ="]
            text = "\n".join(lines) + "\n"
            added.append(f"discord.{key}")
    return text, added


# The assistant was called "Nikita" until 21.10.2026 (ADR-026). Installed files that still carry the
# old *default* values get the new name; anything chosen by hand stays as it is.
OLD_NAME, NEW_NAME = "Nikita", "Anton"
_RENAMES = (
    re.compile(rf'^(\s*assistant_name\s*=\s*"){OLD_NAME}(".*)$'),
    re.compile(rf'^(\s*greeting_text\s*=\s*"Hallo Moritz, hier ist ){OLD_NAME}(\. .*)$'),
    re.compile(rf'^(\s*initial_prompt\s*=\s*"){OLD_NAME}(, Moritz, .*)$'),
    re.compile(rf"^(\s*display_name\s*=\s*){OLD_NAME}(\s*)$"),
)


def rename_assistant(text: str) -> tuple[str, int]:
    """Old default names → new name, line by line (nothing else is touched)."""
    lines = text.split("\n")
    changed = 0
    for index, line in enumerate(lines):
        for pattern in _RENAMES:
            if pattern.match(line):
                lines[index] = pattern.sub(rf"\g<1>{NEW_NAME}\g<2>", line)
                changed += 1
                break
    return "\n".join(lines), changed


def write_atomic(path: Path, text: str, *, default_mode: int = 0o600) -> None:
    """Replace ``path`` in one step; mode and owner of an existing file are kept."""
    try:
        info = path.stat()
        mode, owner = info.st_mode & 0o7777, (info.st_uid, info.st_gid)
    except FileNotFoundError:
        mode, owner = default_mode, None
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        if owner is not None:
            with contextlib.suppress(PermissionError):
                os.chown(tmp, *owner)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def update_file(path: Path, edit, *, default_mode: int = 0o600) -> bool:
    """Apply ``edit(text) -> text`` to a file; ``True`` if the content changed."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    new = edit(old)
    if new == old:
        return False
    write_atomic(path, new, default_mode=default_mode)
    return True


def toml_list(values: list[str]) -> str:
    return "[" + ", ".join(f'"{v}"' for v in values) + "]"

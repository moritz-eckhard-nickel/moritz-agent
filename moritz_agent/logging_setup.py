# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Logging with category tags and secret redaction (LOG-01, LOG-02).

Loggers are named ``moritz.<category>`` (phone, sip, tts, stt, vad, agent, system, ...). The
category shows up in brackets, e.g. ``[Phone]``. Secret values of at least 8 characters are
replaced in every line; shorter secrets are protected structurally (see redaction.py).
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import Iterable
from pathlib import Path

from moritz_agent.redaction import redact

ROOT_LOGGER = "moritz"
_FORMAT = "%(asctime)s %(levelname)-5s [%(category)s] %(message)s"


class _RedactingFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.secrets: list[str] = []

    def filter(self, record: logging.LogRecord) -> bool:
        parts = record.name.split(".")
        record.category = parts[1].capitalize() if len(parts) > 1 else "System"
        if self.secrets:
            record.msg = redact(record.getMessage(), self.secrets)
            record.args = ()
        return True


_filter = _RedactingFilter()


def get_logger(category: str) -> logging.Logger:
    """Logger for a category, e.g. ``get_logger("phone")``."""
    return logging.getLogger(f"{ROOT_LOGGER}.{category}")


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    secrets: Iterable[str] = (),
    max_bytes: int = 10_485_760,
    backup_count: int = 10,
    stream=None,
) -> None:
    """Configure the moritz logger tree (idempotent)."""
    _filter.secrets = [s for s in secrets if s]
    root = logging.getLogger(ROOT_LOGGER)
    root.setLevel(level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(_filter)
    root.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(_filter)
        root.addHandler(rotating)

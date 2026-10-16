# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Textual secret redaction for log lines (LOG-02, docs/plan/08-sicherheit.md §3).

This is the secondary safety net. The primary protection is structural: secrets are
held in :class:`moritz_agent.config.secrets.Secret` and never formatted into messages.
Short secrets (like the default SIP password "agent", which also occurs in the product
name) cannot be replaced textually without destroying logs, so only values of at least
``MIN_REDACT_LENGTH`` characters are replaced here.
"""

from __future__ import annotations

from collections.abc import Iterable

MIN_REDACT_LENGTH = 8
REDACTED = "***"


def redact(text: str, secrets: Iterable[str], min_length: int = MIN_REDACT_LENGTH) -> str:
    """Replace every occurrence of a sufficiently long secret value in ``text``."""
    # Longest first, so a secret that contains another secret is fully replaced.
    for value in sorted({s for s in secrets if len(s) >= min_length}, key=len, reverse=True):
        text = text.replace(value, REDACTED)
    return text

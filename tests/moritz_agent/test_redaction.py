# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

from moritz_agent.redaction import REDACTED, redact


def test_long_secrets_are_redacted():
    line = "login ok for moritz with test-password-123 from 10.0.0.5"
    assert (
        redact(line, ["test-password-123"]) == f"login ok for moritz with {REDACTED} from 10.0.0.5"
    )


def test_short_secrets_are_left_to_structural_protection():
    # "agent" is the default SIP password and part of the product name (08-sicherheit.md §3).
    line = "moritz-agent registered as agent"
    assert redact(line, ["agent"]) == line


def test_overlapping_secrets_longest_first():
    line = "token=abcdefgh-ijklmnop"
    assert redact(line, ["abcdefgh", "abcdefgh-ijklmnop"]) == f"token={REDACTED}"

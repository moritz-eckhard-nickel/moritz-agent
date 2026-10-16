"""Supervisor: startup order, child processes, health and restart backoff (P1-04).

Startup order (docs/plan/02-architektur.md, section 4):
config -> logging -> storage -> internal API -> inference + search (async)
-> agent runtime -> web API -> phone worker (prompt cache first, then SIP registration).
"""

from __future__ import annotations


def run() -> int:
    """Start moritz-agent. Not implemented yet (ticket P1-04)."""
    raise NotImplementedError("supervisor is implemented in ticket P1-04")

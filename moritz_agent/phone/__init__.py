"""Phone worker: SIP via PJSUA2, call state machine, prompts (P1-11, P1-12, P1-13).

Runs as a separate child process (python -m moritz_agent.phone.worker) and talks to the
main process over the authenticated loopback API (ADR-004)."""

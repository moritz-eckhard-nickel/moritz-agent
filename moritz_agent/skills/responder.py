# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The instant-answer responder: plugs into the phone (and later every channel) – docs/plan/13 §3.1."""

from __future__ import annotations

import time

from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import Reply, Responder, TestResponder, TurnContext
from moritz_agent.skills.base import Services, SkillContext
from moritz_agent.skills.router import Outcome, Router, new_context

log = get_logger("skill")
_CONTEXT_KEY = "skills"


class SkillResponder:
    """Skills first; everything they do not answer goes to ``fallback`` (the test answer today, the
    language model from P1-09 on)."""

    def __init__(
        self, svc: Services, fallback: Responder | None = None, router: Router | None = None
    ) -> None:
        self.svc = svc
        self.fallback: Responder = fallback or TestResponder()
        self.router = router or Router(svc)
        self.misses: list[tuple[str, str | None]] = []  # (text, best guess), newest last

    def context_for(self, context: TurnContext) -> SkillContext:
        ctx: SkillContext | None = context.extras.get(_CONTEXT_KEY)
        if ctx is None:
            ctx = new_context(self.svc)
            if context.started_at is not None:
                ctx.started = self.svc.clock.monotonic() - (time.monotonic() - context.started_at)
            context.extras[_CONTEXT_KEY] = ctx
        return ctx

    async def greeting_hint(self, context: TurnContext) -> str | None:
        """A sentence after the greeting when a serious warning is in force (docs/plan/13 §7.6)."""
        from moritz_agent.skills.catalog.warnungen import greeting_hint

        try:
            return await greeting_hint(self.svc, self.context_for(context))
        except Exception:  # a hint must never get in the way of the call
            log.exception("Warnhinweis fehlgeschlagen")
            return None

    async def respond(self, text: str, context: TurnContext) -> Reply:
        ctx = self.context_for(context)
        ctx.thinking_prompt = None
        if context.extras.get("force_agent"):  # a file came with the question (P2-05)
            reply = await self.fallback.respond(text, context)
            ctx.last_text = reply.text or ctx.last_text
            return reply
        surface = context.extras.get("surface", "spoken")  # "chat" for the web and Discord
        outcome: Outcome = await self.router.route(text, ctx, surface=surface)
        self._log(outcome)
        self._record(outcome, text)
        if outcome.result is not None:
            result = outcome.result
            ctx.last_text = result.text or ctx.last_text
            return Reply(
                text=result.text,
                prompt=result.prompt,
                hangup=result.hangup,
                result=result,
                skill_id=outcome.skill_id,
            )
        self._miss(text, outcome)
        reply = await self.fallback.respond(text, context)
        ctx.last_text = reply.text or ctx.last_text
        return reply

    def _log(self, outcome: Outcome) -> None:
        if outcome.result is None:
            log.debug("Keine Sofortauskunft (%s, %.0f ms)", outcome.reason, outcome.ms)
            return
        log.info(
            "Sofortauskunft skill=%s score=%.2f %s %.0f ms",
            outcome.skill_id,
            outcome.score,
            outcome.reason,
            outcome.ms,
        )

    def _record(self, outcome: Outcome, text: str) -> None:
        """Statistics: one tool_calls row per answered skill (never the sentence itself)."""
        repo = self.svc.repo
        if repo is None or outcome.result is None:
            return
        try:
            repo.add_tool_call(
                f"skill:{outcome.skill_id}",
                args={"reason": outcome.reason},
                ok=not outcome.result.serious or outcome.reason != "error",
                summary=(outcome.result.data or {}).get("place", "") if outcome.result.data else "",
                sources=[{"name": s.name} for s in outcome.result.sources] or None,
                duration_ms=round(outcome.ms),
            )
        except Exception:  # statistics must never get in the way of an answer
            log.debug("Statistik nicht geschrieben", exc_info=True)

    def _miss(self, text: str, outcome: Outcome) -> None:
        if self.svc.cfg.store_misses:
            self.misses.append((text, outcome.best_guess))
            del self.misses[:-50]
            if self.svc.repo is not None:
                try:
                    self.svc.repo.add_miss(text, outcome.best_guess, outcome.score)
                except Exception:
                    log.debug("Fehltreffer nicht geschrieben", exc_info=True)

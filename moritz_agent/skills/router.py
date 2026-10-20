# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Finding the skill for an utterance (docs/plan/13 §4.2).

Rules instead of a model: every skill has patterns with weights and exclusion lists. The score is
the best pattern weight times how much of the sentence it explains. Only a clear winner answers;
long or compound sentences, ties and skills whose slots do not fit fall through to the next
stage (today the test answer, from P1-09 on the language model).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from moritz_agent.logging_setup import get_logger
from moritz_agent.skills.base import (
    Clarification,
    FollowupState,
    Option,
    Request,
    Services,
    Skill,
    SkillContext,
    SkillResult,
)
from moritz_agent.skills.registry import all_skills
from moritz_agent.skills.text.normalize import Utterance, prepare

log = get_logger("skill")

ACCEPT = 0.7
MAX_WORDS_ANY = 20
FOLLOWUP_TURNS = 3
FOLLOWUP_SECONDS = 120.0
PRIORITY_RANK = {"M": 0, "S": 1, "K": 2}
_COMPOUND = re.compile(r"\b(weil|dass|obwohl|damit|außerdem|trotzdem|sondern|nachdem|bevor)\b")
_ORDINALS = {
    "erste": 1, "ersten": 1, "erstes": 1, "1": 1, "zweite": 2, "zweiten": 2, "zweites": 2, "2": 2,
    "dritte": 3, "dritten": 3, "drittes": 3, "3": 3, "vierte": 4, "vierten": 4, "4": 4,
    "letzte": -1, "letzten": -1,
}  # fmt: skip
_YES = {
    "ja",
    "jo",
    "jawohl",
    "klar",
    "ok",
    "okay",
    "genau",
    "mach das",
    "ja bitte",
    "ja klar",
    "gerne",
}
_NO = {"nein", "nee", "nö", "lieber nicht", "bloß nicht", "nein danke", "auf keinen fall"}
_CANCEL = re.compile(r"\b(vergiss es|abbrechen|egal|lass gut sein|nicht wichtig|schon gut|stopp)\b")


@dataclass
class Candidate:
    score: float
    skill: Skill
    match: re.Match[str]


@dataclass
class Outcome:
    result: SkillResult | None = None
    skill_id: str | None = None
    score: float = 0.0
    reason: str = "nomatch"  # matched | nomatch | ambiguous | error | followup | clarified
    ms: float = 0.0
    best_guess: str | None = None  # nearest skill when nothing was accepted (for the miss log)
    extra: dict[str, Any] = field(default_factory=dict)


def new_context(svc: Services, seed: int | None = None) -> SkillContext:
    import random

    rng = random.Random(seed)
    return SkillContext(started=svc.clock.monotonic(), seed=rng.randrange(1 << 30), rng=rng)


class Router:
    def __init__(self, svc: Services, skills: dict[str, Skill] | None = None) -> None:
        self.svc = svc
        self.skills = skills if skills is not None else all_skills()

    # -- switches --------------------------------------------------------------------------
    def enabled(self, skill: Skill, surface: str = "spoken") -> bool:
        cfg = self.svc.cfg
        if skill.chat_only and surface != "chat":
            return False
        if not cfg.enabled and skill.group not in {"zeit", "gespraech"}:
            return False
        return not (skill.id in cfg.disabled or skill.group in cfg.disabled)

    # -- scoring ---------------------------------------------------------------------------
    @staticmethod
    def _score(skill: Skill, utt: Utterance) -> Candidate | None:
        text = utt.text
        if utt.words > skill.max_words:
            return None
        best, best_match = 0.0, None
        for pattern, weight in skill.patterns:
            match = pattern.search(text)
            if match and weight > best:
                best, best_match = weight, match
        if best_match is None:
            return None
        if any(ex.search(text) for ex in skill.exclude):
            return None
        coverage = len(best_match.group(0).split()) / max(1, utt.words)
        return Candidate(best * (0.65 + 0.35 * min(1.0, coverage * 1.5)), skill, best_match)

    def candidates(self, utt: Utterance, surface: str = "spoken") -> list[Candidate]:
        found = [
            c
            for skill in self.skills.values()
            if self.enabled(skill, surface)
            for c in [self._score(skill, utt)]
            if c is not None
        ]
        found.sort(
            key=lambda c: (
                -round(c.score, 3),
                PRIORITY_RANK.get(c.skill.priority, 1),
                -len(c.match.group(0)),
            )
        )
        return found

    # -- routing ---------------------------------------------------------------------------
    async def route(
        self,
        raw: str,
        ctx: SkillContext,
        *,
        surface: str = "spoken",
        stt_logprob: float | None = None,
    ) -> Outcome:
        started = time.perf_counter()
        ctx.turn += 1
        ctx.heard.append(raw)
        del ctx.heard[:-20]
        utt = prepare(
            raw, stt_logprob=stt_logprob, quarter_dialect=self.svc.cfg.time.quarter_dialect
        )
        outcome = await self._route(utt, ctx, surface)
        outcome.ms = (time.perf_counter() - started) * 1000
        if outcome.result is not None:
            self._remember(ctx, outcome)
        return outcome

    async def _route(self, utt: Utterance, ctx: SkillContext, surface: str) -> Outcome:
        # 1. an open question ("Welches Neustadt meinst du?")
        if ctx.pending is not None:
            pending, ctx.pending = ctx.pending, None
            if _CANCEL.search(utt.text):
                return Outcome(SkillResult(text="Alles klar."), "talk.cancel", 1.0, "matched")
            option = resolve_option(utt, pending)
            if option is not None:
                skill = self.skills.get(pending.skill_id)
                if skill is not None:
                    result = await self._run(
                        skill, utt, ctx, surface, overrides=dict(option.params)
                    )
                    if result is not None:
                        return Outcome(result, skill.id, 1.0, "clarified")
        # 2. a follow-up to the last answer ("Und morgen?")
        follow = await self._followup(utt, ctx, surface)
        if follow is not None:
            return follow
        # 3. an ordinary request
        if utt.words > MAX_WORDS_ANY:
            return Outcome(reason="nomatch")
        if _COMPOUND.search(utt.text) and utt.words > 8:
            return Outcome(reason="nomatch")
        # 4. two requests in one sentence ("Wie spät ist es und wie wird das Wetter?")
        if utt.words >= 6:
            combo = await self._combo(utt, ctx, surface)
            if combo is not None:
                return combo
        ranked = self.candidates(utt, surface)
        outcome = await self._try(ranked, utt, ctx, surface)
        if outcome.result is not None or outcome.reason in {"error", "ambiguous"}:
            return outcome
        if ranked:
            outcome.best_guess = ranked[0].skill.id
        return outcome

    async def _try(
        self, ranked: list[Candidate], utt: Utterance, ctx: SkillContext, surface: str
    ) -> Outcome:
        for index, candidate in enumerate(ranked):
            if candidate.score < ACCEPT:
                break
            try:
                result = await self._run(candidate.skill, utt, ctx, surface, match=candidate.match)
            except Exception:
                log.exception("Skill %s ist fehlgeschlagen", candidate.skill.id)
                return Outcome(
                    SkillResult(text="Das kann ich gerade nicht beantworten.", serious=True),
                    candidate.skill.id,
                    candidate.score,
                    "error",
                )
            if result is None:
                continue  # the skill declined (slots did not fit): next candidate
            rival = ranked[index + 1] if index + 1 < len(ranked) else None
            if (
                rival is not None
                and not candidate.skill.online
                and not rival.skill.online
                and abs(candidate.score - rival.score) < 0.005
                and candidate.skill.group != rival.skill.group
                and len(candidate.match.group(0)) == len(rival.match.group(0))
            ):
                try:
                    other = await self._run(rival.skill, utt, ctx, surface, match=rival.match)
                except Exception:
                    other = None
                if other is not None and other.text != result.text:
                    log.debug("mehrdeutig: %s ≈ %s", candidate.skill.id, rival.skill.id)
                    return Outcome(
                        reason="ambiguous", score=candidate.score, best_guess=candidate.skill.id
                    )
            return Outcome(result, candidate.skill.id, candidate.score, "matched")
        return Outcome(reason="nomatch")

    async def _run(
        self,
        skill: Skill,
        utt: Utterance,
        ctx: SkillContext,
        surface: str,
        *,
        match: re.Match[str] | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> SkillResult | None:
        if match is None:
            match = next((m for p, _ in skill.patterns if (m := p.search(utt.text))), None)
        if match is None:
            match = re.compile(r"").search("")  # type: ignore[assignment]
        request = Request(utt, match, ctx, self.svc, skill, overrides or {}, surface)  # type: ignore[arg-type]
        return await skill.handler(request)

    # -- follow-ups ------------------------------------------------------------------------
    async def _followup(self, utt: Utterance, ctx: SkillContext, surface: str) -> Outcome | None:
        last = ctx.last
        if last is None:
            return None
        if (
            ctx.turn - ctx.last_turn > FOLLOWUP_TURNS
            or self.svc.clock.monotonic() - ctx.last_at > FOLLOWUP_SECONDS
        ):
            return None
        skill = self.skills.get(last.skill_id)
        if skill is None or skill.followup is None or not self.enabled(skill, surface):
            return None
        rest = re.sub(
            r"^(?:und|dann|oder|aber|wie ist es mit|wie sieht es aus mit|wie siehts aus mit)\s+",
            "",
            utt.text,
        )
        starts_with_and = rest != utt.text
        if not starts_with_and and utt.words > 4:
            return None
        params = skill.followup(rest, ctx, self.svc, last)
        if params is None:
            return None
        target = self.skills.get(params.pop("skill", skill.id), skill)
        merged = {**last.params, **params}
        sub = prepare(rest)
        try:
            result = await self._run(target, sub, ctx, surface, overrides=merged)
        except Exception:
            log.exception("Folgefrage zu %s fehlgeschlagen", target.id)
            return None
        if result is None:
            return None
        return Outcome(result, target.id, 1.0, "followup")

    # -- two skills in one sentence --------------------------------------------------------
    async def _combo(self, utt: Utterance, ctx: SkillContext, surface: str) -> Outcome | None:
        if " und " not in f" {utt.text} ":
            return None
        words = utt.text.split()
        for index, word in enumerate(words):
            if word != "und" or index < 2 or index > len(words) - 3:
                continue
            first, second = " ".join(words[:index]), " ".join(words[index + 1 :])
            results = []
            for part in (first, second):
                sub = prepare(part)
                ranked = [c for c in self.candidates(sub, surface) if c.score >= 0.8]
                if not ranked:
                    results = []
                    break
                result = await self._run(ranked[0].skill, sub, ctx, surface, match=ranked[0].match)
                if result is None or result.clarify is not None or result.hangup:
                    results = []
                    break
                results.append((ranked[0].skill.id, result))
            if len(results) == 2:
                (id1, r1), (id2, r2) = results
                merged = SkillResult(
                    text=" ".join(t for t in (r1.text, r2.text) if t),
                    sources=r1.sources + r2.sources,
                    markdown="\n".join(
                        t for t in (r1.markdown or r1.text, r2.markdown or r2.text) if t
                    ),
                    followup=r2.followup,
                    detail=r2.detail,
                    serious=r1.serious or r2.serious,
                )
                return Outcome(merged, f"{id1}+{id2}", 0.8, "matched")
        return None

    # -- bookkeeping -----------------------------------------------------------------------
    def _remember(self, ctx: SkillContext, outcome: Outcome) -> None:
        result = outcome.result
        assert result is not None
        ctx.last_turn = ctx.turn
        ctx.last_at = self.svc.clock.monotonic()
        if result.followup is not None:
            ctx.last = result.followup
        if result.clarify is not None:
            ctx.pending = Clarification(
                result.clarify.question,
                result.clarify.options,
                result.clarify.skill_id or (outcome.skill_id or ""),
            )
        if result.detail is not None:
            ctx.last_detail = result.detail
        if result.sources:
            ctx.last_sources = result.sources
        if result.text:
            ctx.last_text = result.text
        if result.tempo is not None:
            ctx.tempo = result.tempo
        if result.loudness_db is not None:
            ctx.loudness_db = result.loudness_db
        if result.start_timer is not None:
            seconds, label = result.start_timer
            ctx.timers.append((self.svc.clock.monotonic() + seconds, label))


def resolve_option(utt: Utterance, pending: Clarification) -> Option | None:
    """Which option did the user choose? ("das erste", "die in hessen", "weinstraße")"""
    text = utt.text
    spoken = text.strip(" .!?")
    if spoken in _YES:
        yes = next((o for o in pending.options if o.params.get("yes")), None)
        if yes is not None:
            return yes
    if spoken in _NO:
        no = next((o for o in pending.options if o.params.get("no")), None)
        if no is not None:
            return no
    for token in text.split():
        index = _ORDINALS.get(token)
        if index is not None:
            if index == -1:
                return pending.options[-1]
            if 1 <= index <= len(pending.options):
                return pending.options[index - 1]
    scored: list[tuple[int, Option]] = []
    for option in pending.options:
        names = (option.label, *option.aliases)
        hits = 0
        for name in names:
            low = name.lower()
            for word in re.findall(r"[\wäöüß]{3,}", low):
                if re.search(rf"\b{re.escape(word)}\b", text):
                    hits += 1
        if hits:
            scored.append((hits, option))
    if scored:
        scored.sort(key=lambda pair: -pair[0])
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1]
    return None


def followup_state(skill_id: str, **params: Any) -> FollowupState:
    return FollowupState(skill_id, dict(params))

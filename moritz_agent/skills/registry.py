# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Registry of all skills; the decorator is used by the modules in ``catalog/``."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from moritz_agent.skills.base import FollowupFn, Handler, Skill

_SKILLS: dict[str, Skill] = {}

Pattern = str | tuple[str, float]


def _compile(
    patterns: Iterable[Pattern], default_weight: float
) -> tuple[tuple[re.Pattern[str], float], ...]:
    compiled = []
    for item in patterns:
        text, weight = (item, default_weight) if isinstance(item, str) else item
        compiled.append((re.compile(text), weight))
    return tuple(compiled)


def skill(
    skill_id: str,
    *,
    group: str,
    patterns: Iterable[Pattern],
    exclude: Iterable[str] = (),
    examples: Iterable[str] = (),
    online: bool = False,
    priority: str = "S",
    max_words: int = 16,
    help: str = "",
    followup: FollowupFn | None = None,
    chat_only: bool = False,
    weight: float = 1.0,
) -> Callable[[Handler], Handler]:
    """Register ``handler`` as skill ``skill_id`` (patterns match the prepared utterance)."""

    def register(handler: Handler) -> Handler:
        if skill_id in _SKILLS:
            raise ValueError(f"duplicate skill id {skill_id}")
        _SKILLS[skill_id] = Skill(
            id=skill_id,
            group=group,
            patterns=_compile(patterns, weight),
            handler=handler,
            exclude=tuple(re.compile(p) for p in exclude),
            examples=tuple(examples),
            online=online,
            priority=priority,
            max_words=max_words,
            help=help,
            followup=followup,
            chat_only=chat_only,
        )
        return handler

    return register


def all_skills() -> dict[str, Skill]:
    from moritz_agent.skills.catalog import load_all

    load_all()
    return dict(_SKILLS)


def get(skill_id: str) -> Skill | None:
    return all_skills().get(skill_id)


def groups() -> dict[str, list[Skill]]:
    result: dict[str, list[Skill]] = {}
    for item in all_skills().values():
        result.setdefault(item.group, []).append(item)
    return result

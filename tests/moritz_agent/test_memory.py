# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Anton's short-term memory (Moritz, 24.10.2026): instant answers count, a quiet chat is emptied
after 30 minutes with a note, "/flushcontext" empties it at once."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from moritz_agent.core.chat import HISTORY_TURNS
from moritz_agent.core.principal import Role
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn
from moritz_agent.discord.commands.spec import SPECS
from moritz_agent.discord.render import render_notification

from .skills_util import Session
from .system_util import OWNER_ID, running_system


def run(coro):
    return asyncio.run(coro)


def _turn(system, text, *, place="dm", surface=Surface.CHAT):
    person = system.runtime.chat.principal(OWNER_ID, Role.OWNER, "Moritz")
    return Turn(
        text,
        person,
        surface,
        f"discord:{place}:{OWNER_ID}",
        place=place,
        reply_target=f"dm:{OWNER_ID}",
    )


def _conversation(system, place="dm"):
    return system.runtime.chat._conversations[f"discord:{place}:{OWNER_ID}"]


def test_instant_answers_are_part_of_the_memory_and_a_quiet_chat_is_emptied_with_a_note(tmp_path):
    async def body(system):
        runtime = system.runtime
        await runtime.chat.run(_turn(system, "Wie spät ist es?"))
        await runtime.chat.run(_turn(system, "Was sind 19 Prozent von 250?"))
        history = list(_conversation(system).context.history)
        later = _conversation(system).touched + 31 * 60
        runtime.sweep_chat_memory(now=later - 2 * 60)  # 29 minutes: not yet
        kept = len(_conversation(system).context.history)
        runtime.sweep_chat_memory(now=later)
        emptied = list(_conversation(system).context.history)
        runtime.sweep_chat_memory(now=later + 60)  # already empty: no second note
        notes = [
            p
            for p in runtime.discord_store.pending(runtime.svc.now() + timedelta(days=1), limit=10)
            if p["kind"] == "note"
        ]
        return history, kept, emptied, notes

    history, kept, emptied, notes = run(_in(tmp_path, body))
    assert [heard for heard, _ in history] == ["Wie spät ist es?", "Was sind 19 Prozent von 250?"]
    assert "19 Uhr 12" in history[0][1] and "47,5" in history[1][1]
    assert kept == 2 and emptied == []
    assert len(notes) == 1 and notes[0]["target"] == f"dm:{OWNER_ID}"
    assert "Kurzzeitgedächtnis" in notes[0]["payload"]["text"]
    assert render_notification(notes[0], secrets=[]).content == notes[0]["payload"]["text"]


def test_flushcontext_and_vergiss_empty_the_memory_at_once(tmp_path):
    async def body(system):
        runtime = system.runtime
        await runtime.chat.run(_turn(system, "Wie spät ist es?"))
        before = len(_conversation(system).context.history)
        answer = await runtime.chat.run(_turn(system, "Vergiss unser Gespräch"))
        return before, answer, list(_conversation(system).context.history)

    before, answer, after = run(_in(tmp_path, body))
    assert before == 1 and after == [] and "Kurzzeitgedächtnis" in answer.text
    spec = next(s for s in SPECS if s.name == "flushcontext")
    assert Session().skill(spec.say({})) == "talk.forget"


def test_the_voice_channel_and_the_phone_get_no_note(tmp_path):
    async def body(system):
        await system.runtime.chat.run(
            _turn(system, "Wie spät ist es?", place="voice", surface=Surface.SPOKEN)
        )
        later = _conversation(system, "voice").touched + 31 * 60
        return system.runtime.chat.sweep_idle(30, now=later)

    assert run(_in(tmp_path, body)) == []


def test_a_call_remembers_long_enough():
    assert HISTORY_TURNS >= 30  # the context builder drops what does not fit into 8192 tokens


async def _in(tmp_path, body):
    async with running_system(tmp_path, discord=True) as system:
        return await body(system)


def test_calls_use_a_small_part_of_the_big_context(tmp_path):
    """P2-03: the chat may use all 51200 tokens, phone and voice channel only 8192."""

    async def body(system):
        runtime = system.runtime
        return (
            runtime.agent_loop.context_size,
            runtime.agent_voice.loop.context_size,
            runtime.agent_chat.loop.context_size,
        )

    async def go():
        async with running_system(tmp_path, model=True) as system:
            return await body(system)

    assert asyncio.run(go()) == (8192, 8192, 51200)

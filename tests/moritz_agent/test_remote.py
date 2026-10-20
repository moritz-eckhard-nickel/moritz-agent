# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""RemoteResponder: the phone worker's client for the internal API of the main process."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from moritz_agent.phone.remote import ENV_TOKEN, ENV_URL, RemoteResponder, from_environment
from moritz_agent.phone.responder import ResponderUnavailable, TurnContext

from .fake_model import text_chunks
from .system_util import running_system


def run(coro):
    return asyncio.run(coro)


def remote_for(system, *, token: str | None = None) -> RemoteResponder:
    transport = httpx.ASGITransport(app=system.internal_app, client=("127.0.0.1", 1))
    return RemoteResponder("http://main", token or system.ctx.internal_token, transport=transport)


def test_environment_decides_whether_a_worker_is_remote(monkeypatch):
    monkeypatch.delenv(ENV_URL, raising=False)
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    assert from_environment() is None
    monkeypatch.setenv(ENV_URL, "http://127.0.0.1:1234")
    assert from_environment() is None  # the token is missing
    monkeypatch.setenv(ENV_TOKEN, "t")
    assert isinstance(from_environment(), RemoteResponder)


def test_an_answer_comes_back_as_a_reply(tmp_path):
    async def go():
        async with running_system(tmp_path) as system:
            remote = remote_for(system)
            context = TurnContext(call_id="r1")
            reply = await remote.respond("Wie spät ist es?", context)
            await remote.aclose()
            return reply

    reply = run(go())
    assert "19 Uhr 12" in reply.text and reply.skill_id == "time.now" and not reply.hangup


def test_a_goodbye_hangs_up(tmp_path):
    async def go():
        async with running_system(tmp_path) as system:
            remote = remote_for(system)
            reply = await remote.respond("Tschüss", TurnContext(call_id="r2"))
            await remote.aclose()
            return reply

    assert run(go()).hangup is True


def test_the_weather_announcement_is_visible_while_the_answer_is_pending(tmp_path):
    async def go():
        async with running_system(tmp_path, delay_s=0.5) as system:
            remote = remote_for(system)
            context = TurnContext(call_id="r3")
            task = asyncio.create_task(
                remote.respond("Wie wird das Wetter morgen in Frankfurt?", context)
            )
            seen = None
            for _ in range(60):
                await asyncio.sleep(0.02)
                state = context.extras.get("skills")
                seen = getattr(state, "thinking_prompt", None)
                if seen:
                    break
            reply = await task
            await remote.aclose()
            return seen, reply

    seen, reply = run(go())
    assert seen == "thinking_weather" and "Frankfurt" in reply.text


def test_a_wrong_token_is_unavailable_not_a_crash(tmp_path):
    async def go():
        async with running_system(tmp_path) as system:
            remote = remote_for(system, token="falsch")
            try:
                await remote.respond("Hallo", TurnContext(call_id="r4"))
            finally:
                await remote.aclose()

    with pytest.raises(ResponderUnavailable):
        run(go())


def test_an_unreachable_main_process_is_unavailable():
    async def go():
        def refuse(request):
            raise httpx.ConnectError("down")

        remote = RemoteResponder("http://main", "t", transport=httpx.MockTransport(refuse))
        try:
            await remote.respond("Hallo", TurnContext(call_id="r5"))
        finally:
            await remote.aclose()

    with pytest.raises(ResponderUnavailable):
        run(go())


def test_a_model_error_event_is_unavailable(tmp_path):
    async def go():
        async with running_system(tmp_path, model=True) as system:
            system.model.script = [503]
            remote = remote_for(system)
            try:
                await remote.respond("Erzähl mir etwas über Giraffen", TurnContext(call_id="r6"))
            finally:
                await remote.aclose()

    with pytest.raises(ResponderUnavailable):
        run(go())


def test_cancelling_the_wait_tells_the_main_process_to_stop(tmp_path):
    async def go():
        async with running_system(tmp_path, model=True) as system:
            system.model.gate = True
            remote = remote_for(system)
            task = asyncio.create_task(
                remote.respond("Erzähl mir etwas über Giraffen", TurnContext(call_id="r7"))
            )
            await system.model.wait_for_running()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            for _ in range(100):
                if system.model.abort_calls:
                    break
                await asyncio.sleep(0.02)
            await remote.aclose()
            return system.model.abort_calls

    assert len(run(go())) == 1


def test_a_reply_from_the_model_goes_through(tmp_path):
    async def go():
        async with running_system(tmp_path, model=True) as system:
            system.model.script = [text_chunks("Giraffen sind groß.")]
            remote = remote_for(system)
            reply = await remote.respond(
                "Erzähl mir etwas über Giraffen", TurnContext(call_id="r8")
            )
            await remote.aclose()
            return reply

    assert run(go()).text == "Giraffen sind groß."


def test_greeting_hint_failures_are_silent():
    async def go():
        def refuse(request):
            raise httpx.ConnectError("down")

        remote = RemoteResponder("http://main", "t", transport=httpx.MockTransport(refuse))
        hint = await remote.greeting_hint(TurnContext(call_id="r9"))
        remote.call_started("r9", "sip:x", "G722")  # must not raise
        remote.call_ended("r9", "x")
        await asyncio.sleep(0.05)
        await remote.aclose()
        return hint

    assert run(go()) is None

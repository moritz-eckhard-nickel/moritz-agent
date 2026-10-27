# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Runs of the WebUI (ADR-041, docs/plan/15 P2-02): SSE stream, tools, follow again, cancel."""

from __future__ import annotations

import asyncio
import dataclasses
import json

from moritz_agent.api.routes_chat import ChatBody, web_turn
from moritz_agent.core.runs import RunBusy
from moritz_agent.tools.base import BaseTool, ToolContext, ToolResult
from moritz_agent.tools.registry import ToolRegistry

from .fake_model import text_chunks, tool_chunks
from .system_util import running_system


def scenario(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return asyncio.run(go())


def parse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        data = json.loads(lines["data"])
        assert lines["event"] == data["type"] and int(lines["id"]) == data["seq"]
        events.append(data)
    return events


async def stream(system, client, message, conversation="t1"):
    response = await client.post(
        "/api/chat/stream", json={"message": message, "conversation_id": conversation}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse(response.text)


def test_an_instant_answer_is_a_run_with_one_result(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            return await stream(system, client, "Was ist 17 mal 23?")

    events = scenario(tmp_path, body)
    assert [e["type"] for e in events] == ["run", "done"]
    assert events[0]["conversation_id"] == "web:t1" and events[0]["run_id"].startswith("r-")
    assert events[-1]["result"]["text"] == "17 mal 23 ist 391."
    assert [e["seq"] for e in events] == [1, 2]


def test_the_model_answer_streams_and_tool_calls_show_up(tmp_path):
    async def body(system):
        system.model.script = [
            tool_chunks("get_current_time", '{"kind": "time"}'),
            text_chunks("Es ist ", "19 Uhr 12, ", "Zeit fürs Abendessen."),
        ]
        system.model.gate = True

        async def trickle():  # one chunk every 80 ms, like a real model
            while True:
                await asyncio.sleep(0.08)
                system.model.release()

        feeder = asyncio.ensure_future(trickle())
        try:
            async with system.client() as client:
                await system.login(client)
                return await stream(system, client, "Erzähl mir etwas über Giraffen")
        finally:
            feeder.cancel()

    events = scenario(tmp_path, body, model=True)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run" and kinds[-1] == "done"
    call = next(e for e in events if e["type"] == "tool_call")
    result = next(e for e in events if e["type"] == "tool_result")
    assert call["tool"] == "get_current_time" and call["args"] == {"kind": "time"}
    assert (
        result["ok"] is True
        and result["ms"] >= 0
        and kinds.index("tool_call") < kinds.index("tool_result")
    )
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed and "Abendessen" in events[-1]["result"]["text"]


def test_a_finished_run_can_be_followed_again_from_any_event(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            first = await stream(system, client, "Was ist 17 mal 23?")
            run_id = first[0]["run_id"]
            again = await client.get(f"/api/runs/{run_id}/events?after=1")
            unknown = await client.get("/api/runs/r-nope/events")
        return first, parse(again.text), unknown.status_code

    first, again, unknown = scenario(tmp_path, body)
    assert again == first[1:] and unknown == 404


def test_cancel_stops_the_model_and_ends_the_run(tmp_path):
    async def body(system):
        system.model.gate = True  # the model waits after every chunk
        runs = system.runtime.runs
        run = runs.start(
            web_turn(ChatBody(message="Erzähl mir was über Giraffen", conversation_id="c"))
        )
        await system.model.wait_for_running()
        try:
            runs.start(web_turn(ChatBody(message="Und noch was", conversation_id="c")))
            busy = False
        except RunBusy:
            busy = True
        async with system.client() as client:
            await system.login(client)
            cancelled = (await client.post(f"/api/runs/{run.id}/cancel")).json()
        events = [e async for e in runs.follow(run.id)]
        system.model.release_all()
        return busy, cancelled, events, runs.active("web:c")

    busy, cancelled, events, active = scenario(tmp_path, body, model=True)
    assert busy and cancelled == {"cancelled": True}
    assert events[-1]["type"] == "cancelled" and active is None


def test_an_unreachable_model_ends_the_run_with_an_error(tmp_path):
    async def body(system):
        system.model.script = [503]
        async with system.client() as client:
            await system.login(client)
            return await stream(system, client, "Erzähl mir etwas über Giraffen")

    events = scenario(tmp_path, body, model=True)
    assert events[-1] == {**events[-1], "type": "error", "error": "model_unavailable"}


def test_runs_need_the_login(tmp_path):
    async def body(system):
        async with system.client() as client:
            return [
                (await client.post("/api/chat/stream", json={"message": "hi"})).status_code,
                (await client.get("/api/runs/r-1/events")).status_code,
                (await client.post("/api/runs/r-1/cancel")).status_code,
            ]

    assert scenario(tmp_path, body) == [401, 401, 401]


# -- approvals (ADR-041 Nr. 4) ------------------------------------------------------------------------
class Danger(BaseTool):
    """A tool that changes something: it only runs after Moritz said yes."""

    name = "danger_test"
    description = "Testwerkzeug, das etwas verändert."
    risk = "execute"
    needs_approval = True

    def __init__(self) -> None:
        self.ran = 0

    async def run(self, args, ctx):
        self.ran += 1
        return ToolResult.success({"done": True}, speakable="Erledigt.")


def with_danger(system) -> Danger:
    tool = Danger()
    system.runtime.registry.register(tool)
    loop = system.runtime.agent_chat.loop
    loop.profile = dataclasses.replace(loop.profile, tools=loop.profile.tools | {tool.name})
    system.model.script = [tool_chunks("danger_test", "{}"), text_chunks("Fertig.")]
    return tool


async def answer_when_asked(system, run, allow):
    runs = system.runtime.runs
    events = []
    async for event in runs.follow(run.id):
        events.append(event)
        if event["type"] == "approval_request" and allow is not None:
            assert runs.approve(run.id, event["id"], allow)
            assert not runs.approve(run.id, event["id"], allow)  # only once
    return events


def test_a_risky_tool_runs_after_moritz_says_yes(tmp_path):
    async def body(system):
        tool = with_danger(system)
        run = system.runtime.runs.start(
            web_turn(ChatBody(message="Lösch den Ordner", conversation_id="d1"))
        )
        events = await answer_when_asked(system, run, True)
        return tool.ran, events

    ran, events = scenario(tmp_path, body, model=True)
    kinds = [e["type"] for e in events]
    request = next(e for e in events if e["type"] == "approval_request")
    assert request["tool"] == "danger_test" and request["risk"] == "execute"
    assert (
        kinds.index("approval_request")
        < kinds.index("approval_response")
        < kinds.index("tool_result")
    )
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is True
    assert events[-1]["type"] == "done" and ran == 1


def test_a_no_or_no_answer_means_the_tool_never_runs(tmp_path, monkeypatch):
    from moritz_agent.core import runs as runs_module

    monkeypatch.setattr(runs_module, "APPROVAL_TIMEOUT_S", 0.2)

    async def body(system):
        tool = with_danger(system)
        denied = await answer_when_asked(
            system,
            system.runtime.runs.start(web_turn(ChatBody(message="Mach!", conversation_id="d2"))),
            False,
        )
        system.model.script = [tool_chunks("danger_test", "{}"), text_chunks("Ok.")]
        silent = await answer_when_asked(
            system,
            system.runtime.runs.start(web_turn(ChatBody(message="Mach!", conversation_id="d3"))),
            None,
        )
        return tool.ran, denied, silent

    ran, denied, silent = scenario(tmp_path, body, model=True)
    assert ran == 0
    for events in (denied, silent):
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["ok"] is False and result["error"] == "denied"
    assert next(e for e in silent if e["type"] == "approval_response")["by"] == "timeout"


def test_without_anyone_to_ask_a_risky_tool_is_refused(tmp_path):
    async def body(system):
        tool = Danger()
        registry = ToolRegistry()
        registry.register(tool)
        result = await registry.call("danger_test", {}, ToolContext(), allowed={"danger_test"})
        return tool.ran, result

    ran, result = scenario(tmp_path, body)
    assert ran == 0 and result.error == "denied"


def test_the_approval_endpoint(tmp_path):
    async def body(system):
        with_danger(system)
        run = system.runtime.runs.start(web_turn(ChatBody(message="Mach!", conversation_id="d4")))
        request = None
        async for event in system.runtime.runs.follow(run.id):
            if event["type"] == "approval_request":
                request = event
                break
        async with system.client() as client:
            await system.login(client)
            bad = await client.post(
                f"/api/runs/{run.id}/approval", json={"id": "a-00", "allow": True}
            )
            good = await client.post(
                f"/api/runs/{run.id}/approval", json={"id": request["id"], "allow": True}
            )
        events = [e async for e in system.runtime.runs.follow(run.id)]
        return bad.status_code, good.json(), events

    bad, good, events = scenario(tmp_path, body, model=True)
    assert bad == 409 and good == {"ok": True} and events[-1]["type"] == "done"

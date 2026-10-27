# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Live view of the WebUI (docs/plan/15 P2-07): status as SSE, the end of the log."""

from __future__ import annotations

import asyncio
import json

import httpx
import uvicorn

from moritz_agent.api import routes_live
from moritz_agent.api.routes_live import tail
from moritz_agent.process import find_free_port

from .system_util import CREDENTIALS, WEB_PASSWORD, WEB_USER, running_system


def scenario(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return asyncio.run(go())


def test_tail_reads_only_the_end_and_filters_by_category(tmp_path, monkeypatch):
    log = tmp_path / "moritz-agent.log"
    lines = [f"2026-10-27 [{'Phone' if i % 2 else 'Agent'}] Zeile {i}" for i in range(2000)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert tail(log, 3) == lines[-3:]
    assert tail(log, 2, "[Phone]") == [lines[-3], lines[-1]]
    monkeypatch.setattr(routes_live, "TAIL_BYTES", 100)
    end = tail(log, 50)
    assert end and all(line in lines for line in end)  # no half line from the cut
    assert tail(tmp_path / "fehlt.log", 5) == []


def test_logs_need_the_login_and_come_filtered(tmp_path):
    async def body(system):
        log = tmp_path / "web.log"
        log.write_text("a [System] start\nb [Phone] klingelt\nc [Agent] denkt\n", encoding="utf-8")
        system.config.current.settings.logging.file = str(log)
        async with system.client() as client:
            anonymous = (await client.get("/api/system/logs")).status_code
            await system.login(client)
            every = (await client.get("/api/system/logs?lines=2")).json()
            phone = (await client.get("/api/system/logs?category=phone")).json()
            bad = (await client.get("/api/system/logs?category=../x")).status_code
        return anonymous, every, phone, bad

    anonymous, every, phone, bad = scenario(tmp_path, body)
    assert anonymous == 401 and bad == 422
    assert every == {"lines": ["b [Phone] klingelt", "c [Agent] denkt"]}
    assert phone == {"lines": ["b [Phone] klingelt"]}


def test_events_send_the_status_at_once_and_again_when_a_call_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_live, "POLL_S", 0.05)

    async def body(system):
        port = find_free_port()
        server = uvicorn.Server(
            uvicorn.Config(system.app, host="127.0.0.1", port=port, log_config=None, lifespan="off")
        )
        task = asyncio.ensure_future(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        base = f"http://127.0.0.1:{port}"
        received = []
        try:
            async with httpx.AsyncClient(base_url=base, timeout=5) as client:
                denied = (await client.get("/api/events")).status_code
                await client.post(
                    "/api/login", json={"username": WEB_USER, "password": WEB_PASSWORD}
                )
                async with client.stream("GET", "/api/events") as response:
                    kind = response.headers["content-type"]
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            received.append(json.loads(line[6:]))
                            if len(received) == 1:
                                system.runtime.call_started("call-live", "sip:201@pbx")
                            else:
                                break
        finally:
            server.should_exit = True
            await task
        return denied, kind, received

    denied, kind, received = scenario(tmp_path, body)
    assert denied == 401 and kind.startswith("text/event-stream")
    assert received[0]["active_calls"] == 0 and received[1]["active_calls"] == 1
    assert "components" in received[0]
    for secret in CREDENTIALS:
        assert secret not in json.dumps(received)

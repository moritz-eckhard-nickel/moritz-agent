# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Web interface and internal API: login, status, chat, reload, admin, phone worker (P1-14)."""

from __future__ import annotations

import asyncio
import json

import pytest

from moritz_agent.api.auth import Authenticator

from .fake_model import text_chunks, tool_chunks
from .system_util import (
    CREDENTIALS,
    WEB_PASSWORD,
    WEB_USER,
    running_system,
)


def run(coro):
    return asyncio.run(coro)


def scenario(tmp_path, body, **options):
    """Run ``body(system)`` inside a started system."""

    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return run(go())


# -- health and sessions -------------------------------------------------------------------------
def test_health_needs_no_login_and_says_nothing_else(tmp_path):
    async def body(system):
        async with system.client() as client:
            response = await client.get("/api/system/health")
        return response

    response = scenario(tmp_path, body)
    assert response.status_code == 200 and response.json() == {"ok": True}


def test_protected_endpoints_need_the_login(tmp_path):
    async def body(system):
        async with system.client() as client:
            return [
                (await client.get("/api/system/status")).status_code,
                (await client.get("/api/phone/status")).status_code,
                (await client.post("/api/system/reload")).status_code,
                (await client.post("/api/chat", json={"message": "hallo"})).status_code,
            ]

    assert scenario(tmp_path, body) == [401, 401, 401, 401]


def test_without_a_configured_login_nothing_is_open(tmp_path):
    async def body(system):
        async with system.client() as client:
            status = await client.get("/api/system/status")
            session = await client.get("/api/session")
            login = await client.post("/api/login", json={"username": "a", "password": "b"})
            return status, session, login

    status, session, login = scenario(tmp_path, body, web_login=False)
    assert status.status_code == 403 and login.status_code == 403
    assert session.json() == {"login_configured": False, "authenticated": False}


def test_login_sets_a_strict_http_only_cookie(tmp_path):
    async def body(system):
        system.ctx.secure_cookie = True
        async with system.client() as client:
            wrong = await client.post(
                "/api/login", json={"username": WEB_USER, "password": "falsch"}
            )
            wrong_user = await client.post(
                "/api/login", json={"username": "nobody", "password": WEB_PASSWORD}
            )
            right = await system.login(client)
            return wrong, wrong_user, right

    wrong, wrong_user, right = scenario(tmp_path, body)
    assert wrong.status_code == 401 and wrong_user.status_code == 401
    cookie = right.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" in cookie
    assert WEB_PASSWORD not in cookie


def test_a_session_lets_you_in_and_logout_ends_it(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            before = await client.get("/api/system/status")
            session = await client.get("/api/session")
            await client.post("/api/logout")
            after = await client.get("/api/system/status")
            return before, session, after

    before, session, after = scenario(tmp_path, body)
    assert before.status_code == 200 and session.json()["authenticated"] is True
    assert after.status_code == 401


def test_five_wrong_attempts_lock_the_address_for_five_minutes(tmp_path):
    clock = [1000.0]

    async def body(system):
        async with system.client(ip="10.0.0.5") as client:
            codes = [
                (
                    await client.post(
                        "/api/login", json={"username": WEB_USER, "password": f"x{i}"}
                    )
                ).status_code
                for i in range(5)
            ]
            locked = await system.login(client)  # even the right password is refused now
            other = system.client(ip="10.0.0.6")
            async with other:
                fine = await system.login(other)
            clock[0] += 301
            later = await system.login(client)
            return codes, locked, fine, later

    codes, locked, fine, later = scenario(tmp_path, body, auth_clock=lambda: clock[0])
    assert codes == [401] * 5  # five failures are allowed, the next attempt is locked out
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0
    assert fine.status_code == 200 and later.status_code == 200


def test_changing_the_password_ends_all_sessions(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            assert (await client.get("/api/system/status")).status_code == 200
            text = (system.tree / "passwords.txt").read_text(encoding="utf-8")
            (system.tree / "passwords.txt").write_text(
                text.replace(WEB_PASSWORD, "Neu-Pw-77"), encoding="utf-8"
            )
            assert system.config.reload().ok
            return (await client.get("/api/system/status")).status_code

    assert scenario(tmp_path, body) == 401


def test_session_expires(tmp_path):
    clock = [0.0]

    async def body(system):
        async with system.client() as client:
            await system.login(client)
            clock[0] += 240 * 3600 + 5  # 10 days (F-49)
            return (await client.get("/api/system/status")).status_code

    assert scenario(tmp_path, body, auth_clock=lambda: clock[0]) == 401


# -- status ----------------------------------------------------------------------------------------
def test_status_shows_every_component_and_no_credential(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            status = (await client.get("/api/system/status")).text
            phone = (await client.get("/api/phone/status")).text
            return status, phone

    status, phone = scenario(tmp_path, body)
    data = json.loads(status)
    assert set(data["components"]) >= {
        "storage",
        "inference",
        "search",
        "skills",
        "agent",
        "config",
    }
    assert data["components"]["storage"]["state"] == "ready"
    assert data["components"]["inference"] == {"state": "disabled", "message": "Modelldatei fehlt"}
    assert data["phone"]["state"] == "failed"  # no phone worker in this test
    for secret in CREDENTIALS:
        assert secret not in status + phone


def test_status_with_a_model_and_a_phone(tmp_path):
    import time

    async def body(system):
        run_dir = system.tree / "data" / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "phone-status.json").write_text(
            json.dumps(
                {
                    "state": "running",
                    "updated": time.time(),
                    "registration": "registered",
                    "in_call": False,
                    "calls_total": 3,
                    "pid": 1,
                    "version": "x",
                }
            )
        )
        async with system.client() as client:
            await system.login(client)
            return (await client.get("/api/system/status")).json(), (
                await client.get("/api/phone/status")
            ).json()

    status, phone = scenario(tmp_path, body, model=True)
    assert status["components"]["inference"]["state"] == "ready"
    assert status["components"]["agent"]["state"] == "ready"
    assert status["phone"]["state"] == "ready" and phone["registration"] == "registered"
    assert phone["running"] is True and "pid" not in phone


# -- chat ---------------------------------------------------------------------------------------
async def ask(system, client, text, conversation="web"):
    response = await client.post(
        "/api/chat", json={"message": text, "conversation_id": conversation}
    )
    return response


def test_chat_answers_instant_questions_without_the_model(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            return (await ask(system, client, "Wie spät ist es?")).json()

    data = scenario(tmp_path, body)
    assert data["skill_id"] == "time.now" and "19 Uhr 12" in data["text"]


def test_chat_weather_has_sources_and_follow_ups(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            first = (await ask(system, client, "Wie wird das Wetter morgen in Frankfurt?")).json()
            second = (await ask(system, client, "und übermorgen?")).json()
            return first, second

    first, second = scenario(tmp_path, body)
    assert "Frankfurt" in first["text"] and first["sources"][0]["name"].startswith("Open-Meteo")
    assert first["actions"] and "Frankfurt" in second["text"]


def test_chat_conversations_are_separate(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            await ask(system, client, "Wie wird das Wetter morgen in Frankfurt?", "a")
            return (await ask(system, client, "und übermorgen?", "b")).json()

    data = scenario(tmp_path, body)
    assert "Frankfurt" not in data["text"]


def test_other_questions_go_to_the_model(tmp_path):
    async def body(system):
        system.model.script = [text_chunks("Das ist ", "ein Test.")]
        async with system.client() as client:
            await system.login(client)
            return (await ask(system, client, "Erzähl mir etwas über Giraffen")).json()

    data = scenario(tmp_path, body, model=True)
    assert data["text"] == "Das ist ein Test." and data["skill_id"] is None


def test_the_model_can_call_tools_in_chat(tmp_path):
    async def body(system):
        system.model.script = [
            tool_chunks("get_sun_moon", '{"what": "sunset"}'),
            text_chunks("Die Sonne geht heute spät unter."),
        ]
        async with system.client() as client:
            await system.login(client)
            data = (await ask(system, client, "Erzähl mir etwas zur Dämmerung bitte")).json()
        rows = system.runtime.db.query(
            "SELECT tool, ok, channel FROM tool_calls WHERE tool = 'get_sun_moon'"
        )
        return data, rows

    data, rows = scenario(tmp_path, body, model=True)
    assert data["text"] == "Die Sonne geht heute spät unter."
    assert len(rows) == 1 and rows[0]["ok"] == 1


def test_without_a_model_chat_says_so_honestly(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            return (await ask(system, client, "Erzähl mir etwas über Giraffen")).json()

    assert "Sprachmodell nicht eingeschaltet" in scenario(tmp_path, body)["text"]


def test_an_unreachable_model_gives_503(tmp_path):
    async def body(system):
        system.model.script = [503]
        async with system.client() as client:
            await system.login(client)
            return await ask(system, client, "Erzähl mir etwas über Giraffen")

    assert scenario(tmp_path, body, model=True).status_code == 503


@pytest.mark.parametrize(
    "payload",
    [{"message": ""}, {"message": "x" * 4001}, {"message": "a", "conversation_id": "../x"}],
)
def test_chat_input_is_checked(tmp_path, payload):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            return (await client.post("/api/chat", json=payload)).status_code

    assert scenario(tmp_path, body) == 422


# -- reload --------------------------------------------------------------------------------------
def test_reload_applies_a_change_and_refuses_a_broken_file(tmp_path):
    async def body(system):
        path = system.tree / "config" / "moritz-agent.toml"
        async with system.client() as client:
            await system.login(client)
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "max_sentences = 3", "max_sentences = 2", 1
                ),
                encoding="utf-8",
            )
            good = (await client.post("/api/system/reload")).json()
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "max_sentences = 2", "max_sentences = 77", 1
                ),
                encoding="utf-8",
            )
            bad = (await client.post("/api/system/reload")).json()
            status = (await client.get("/api/system/status")).json()
        return good, bad, status, system.config.settings.agent.phone.max_sentences

    good, bad, status, sentences = scenario(tmp_path, body)
    assert good["ok"] and good["changed"] == ["settings.agent"]
    assert not bad["ok"] and bad["errors"] and sentences == 2
    assert status["components"]["config"]["state"] == "degraded"


# -- admin (updater) -------------------------------------------------------------------------------
def test_admin_endpoints_need_the_token_file_value(tmp_path):
    async def body(system):
        async with system.client() as client:
            return [
                (await client.get("/api/system/activity")).status_code,
                (
                    await client.get("/api/system/activity", headers={"X-Admin-Token": "falsch"})
                ).status_code,
                (
                    await client.get("/api/system/activity", headers=system.admin_headers())
                ).status_code,
            ]

    assert scenario(tmp_path, body) == [403, 403, 200]


def test_admin_is_loopback_only(tmp_path):
    async def body(system):
        async with system.client(ip="192.168.1.50") as client:
            return (
                await client.get("/api/system/activity", headers=system.admin_headers())
            ).status_code

    assert scenario(tmp_path, body) == 403


def test_activity_and_drain(tmp_path):
    async def body(system):
        async with system.client() as client:
            headers = system.admin_headers()
            idle = (await client.get("/api/system/activity", headers=headers)).json()
            await client.post("/api/system/drain", json={"drain": True}, headers=headers)
            drained = (await client.get("/api/system/activity", headers=headers)).json()
            on_disk = (system.tree / "data" / "run" / "drain").exists()
            await client.post("/api/system/drain", json={"drain": False}, headers=headers)
            return idle, drained, on_disk, (system.tree / "data" / "run" / "drain").exists()

    idle, drained, on_disk, after = scenario(tmp_path, body)
    assert idle["in_call"] is False and idle["draining"] is False
    assert drained["draining"] is True and on_disk and not after


# -- hardening -----------------------------------------------------------------------------------------
def test_a_foreign_origin_cannot_post(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            evil = await client.post(
                "/api/chat", json={"message": "hallo"}, headers={"Origin": "https://evil.example"}
            )
            own = await client.post(
                "/api/chat", json={"message": "hallo"}, headers={"Origin": "http://testserver"}
            )
            return evil.status_code, own.status_code

    assert scenario(tmp_path, body) == (403, 200)


def test_app_files_are_whitelisted_and_have_security_headers(tmp_path):
    async def body(system):
        async with system.client() as client:
            return {
                "index": await client.get("/"),
                "js": await client.get("/app/js/app.js"),
                "view": await client.get("/app/js/views/chat.js"),
                "css": await client.get("/app/app.css"),
                "logo": await client.get("/branding/m-agent-logo-64.png"),
                "scribbles": await client.get("/branding/scribbles/scribbles-black.svg"),
                "traversal": await client.get("/app/..%2f..%2fpasswords.txt"),
                "dotdot": await client.get("/app/../../passwords.txt"),
                "html": await client.get("/app/index.html"),
                "readme": await client.get("/app/../README.md"),
                "secret": await client.get("/branding/../../passwords.txt"),
                "other": await client.get("/branding/README.md"),
                "old": await client.get("/static/status.js"),
                "docs": await client.get("/docs"),
                "openapi": await client.get("/openapi.json"),
                "status": await client.get("/status", follow_redirects=False),
            }

    r = scenario(tmp_path, body)
    assert all(r[k].status_code == 200 for k in ("index", "js", "view", "css", "logo", "scribbles"))
    for key in (
        "traversal",
        "dotdot",
        "html",
        "readme",
        "secret",
        "other",
        "old",
        "docs",
        "openapi",
    ):
        assert r[key].status_code == 404, key
    assert r["js"].headers["content-type"].startswith("text/javascript")
    assert r["status"].status_code == 308 and r["status"].headers["location"] == "/#/status"
    csp = r["index"].headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp
    assert r["index"].headers["x-content-type-options"] == "nosniff"
    assert "m-agent" in r["index"].text and 'type="module"' in r["index"].text


def test_the_app_has_no_inline_code_and_no_foreign_addresses():
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parents[2] / "frontend/app"
    html = (app / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "style=" not in html and " on" + "click=" not in html
    for path in app.rglob("*"):
        if path.suffix not in {".html", ".css", ".js"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "SPDX-License-Identifier: LicenseRef-MSOL-1.1" in text, path
        # nothing from the internet: no CDN, no fonts, no trackers (ADR-040)
        foreign = [u for u in re.findall(r"https?://[^\s\"')]+", text) if "w3.org" not in u]
        assert not foreign, (path, foreign)
        if path.suffix == ".js":
            assert "innerHTML" not in text and "eval(" not in text, path


# -- internal API (phone worker → main process) ------------------------------------------------
async def post_turn(client, headers, call_id, text):
    events = []
    async with client.stream(
        "POST", "/internal/phone/turn", json={"call_id": call_id, "text": text}, headers=headers
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line:
                events.append(json.loads(line))
    return events


def test_internal_endpoints_need_the_start_token(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            body = {"call_id": "c1", "text": "Hallo"}
            return [
                (await client.post("/internal/phone/turn", json=body)).status_code,
                (
                    await client.post(
                        "/internal/phone/turn", json=body, headers={"X-Internal-Token": "x"}
                    )
                ).status_code,
                (
                    await client.post(
                        "/internal/phone/cancel",
                        json={"call_id": "c1"},
                        headers=system.admin_headers(),
                    )
                ).status_code,
                (await client.get("/api/system/status")).status_code,
            ]

    assert scenario(tmp_path, body) == [403, 403, 403, 404]


def test_a_turn_streams_the_reply_and_keeps_the_history(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            first = await post_turn(client, system.internal_headers(), "call-1", "Wie spät ist es?")
            second = await post_turn(
                client, system.internal_headers(), "call-1", "Erzähl mir etwas über Giraffen"
            )
            return first, second, system.model.requests

    system_model_script = [text_chunks("Giraffen sind groß.")]

    async def go():
        async with running_system(tmp_path, model=True) as system:
            system.model.script = list(system_model_script)
            return await body(system)

    first, second, requests = run(go())
    assert first == [
        {
            "type": "reply",
            "text": first[0]["text"],
            "prompt": None,
            "hangup": False,
            "skill_id": "time.now",
            "timer": None,
        }
    ]
    assert "19 Uhr 12" in first[0]["text"]
    assert second[0]["text"] == "Giraffen sind groß."
    contents = [m["content"] for m in requests[0]["messages"]]
    assert contents[-3:] == ["Wie spät ist es?", first[0]["text"], "Erzähl mir etwas über Giraffen"]


def test_a_slow_weather_lookup_announces_the_weather_prompt(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            return await post_turn(
                client,
                system.internal_headers(),
                "call-2",
                "Wie wird das Wetter morgen in Frankfurt?",
            )

    events = scenario(tmp_path, body, delay_s=0.4)
    assert events[0] == {"type": "thinking", "prompt": "thinking_weather"}
    assert events[-1]["type"] == "reply" and "Frankfurt" in events[-1]["text"]


def test_a_model_failure_is_reported_as_an_error_event(tmp_path):
    async def go():
        async with running_system(tmp_path, model=True) as system:
            system.model.script = [503]
            async with system.client(internal=True) as client:
                return await post_turn(
                    client, system.internal_headers(), "call-3", "Erzähl mir etwas über Giraffen"
                )

    events = run(go())
    assert events == [{"type": "error", "kind": "unavailable", "message": events[0]["message"]}]


def test_cancel_stops_the_generation(tmp_path):
    async def go():
        async with running_system(tmp_path, model=True) as system:
            system.model.gate = True
            async with system.client(internal=True) as client:
                headers = system.internal_headers()
                turn = asyncio.create_task(
                    post_turn(client, headers, "call-4", "Erzähl mir etwas über Giraffen")
                )
                await system.model.wait_for_running()
                cancelled = (
                    await client.post(
                        "/internal/phone/cancel", json={"call_id": "call-4"}, headers=headers
                    )
                ).json()
                events = await asyncio.wait_for(turn, 3)
                await asyncio.sleep(0.05)
                return cancelled, events, system.model.abort_calls

    cancelled, events, aborts = run(go())
    assert cancelled == {"cancelled": True} and len(aborts) == 1
    assert events == [{"type": "cancelled"}]


def test_call_events_are_stored(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            headers = system.internal_headers()
            await client.post(
                "/internal/phone/event",
                json={
                    "call_id": "call-5",
                    "event": "call_started",
                    "remote": "sip:192.168.1.176",
                    "codec": "G722",
                },
                headers=headers,
            )
            await post_turn(client, headers, "call-5", "Wie spät ist es?")
            await client.post(
                "/internal/phone/event",
                json={"call_id": "call-5", "event": "call_ended", "reason": "remote_hangup"},
                headers=headers,
            )
            rows = system.runtime.db.query(
                "SELECT codec, end_reason, turns FROM calls WHERE id = 'call-5'"
            )
            turns = system.runtime.db.query(
                "SELECT user_text, path FROM call_turns WHERE call_id = 'call-5'"
            )
            return [dict(r) for r in rows], [dict(r) for r in turns], system.runtime.active_calls

    rows, turns, active = scenario(tmp_path, body)
    assert rows == [{"codec": "G722", "end_reason": "remote_hangup", "turns": 1}]
    assert turns == [{"user_text": "Wie spät ist es?", "path": "skill"}] and active == 0


def test_the_greeting_hint_comes_from_the_skills(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            return (
                await client.post(
                    "/internal/phone/greeting_hint",
                    json={"call_id": "call-6"},
                    headers=system.internal_headers(),
                )
            ).json()

    assert scenario(tmp_path, body) == {"text": None}  # no serious warning in the fixtures


def test_internal_input_is_limited(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            return (
                await client.post(
                    "/internal/phone/turn",
                    json={"call_id": "c", "text": "x" * 3000},
                    headers=system.internal_headers(),
                )
            ).status_code

    assert scenario(tmp_path, body) == 422


# -- the authenticator on its own ------------------------------------------------------------------------
def test_authenticator_without_login_never_validates(tmp_path):
    async def body(system):
        auth = Authenticator(lambda: system.config.current)
        return auth.enabled, auth.valid("irgendwas"), auth.login("a", "b", "1.2.3.4").reason

    assert scenario(tmp_path, body, web_login=False) == (False, False, "not_configured")


def test_a_timer_request_reaches_the_phone_in_the_reply(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            headers = system.internal_headers()
            timer = await post_turn(client, headers, "c1", "Stell einen Timer auf zehn Minuten")
            plain = await post_turn(client, headers, "c1", "Wie spät ist es?")
            return timer[-1], plain[-1]

    timer, plain = scenario(tmp_path, body)
    assert timer["type"] == "reply" and timer["timer"][0] == 600
    assert plain["timer"] is None


def test_a_call_whose_end_never_arrives_does_not_stay_active(tmp_path):
    async def body(system):
        runtime = system.runtime
        runtime.call_started("lost-call", "sip:20", "G722")
        active_before = runtime.active_calls
        # the phone worker died mid-call: no call_ended ever comes
        runtime._calls["lost-call"].touched -= runtime.settings.phone.max_call_duration_s + 301
        rows = runtime.db.query("SELECT end_reason FROM calls WHERE id = 'lost-call'")
        return active_before, runtime.active_calls, rows

    before, after, _rows = scenario(tmp_path, body)
    assert (before, after) == (1, 0)

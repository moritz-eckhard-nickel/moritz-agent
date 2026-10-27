# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Model page (docs/plan/15 P2-08): status, settings written line by line, restart, measuring."""

from __future__ import annotations

import asyncio

from moritz_agent.api.routes_model import kv_gb
from moritz_agent.config.editing import EditError, set_secret, set_settings, toml_value

from .system_util import running_system


def scenario(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return asyncio.run(go())


def test_toml_values_and_line_by_line_edits_keep_comments(tmp_path):
    assert toml_value(True) == "true" and toml_value(3) == "3" and toml_value(0.5) == "0.5"
    assert toml_value('a "b"') == '"a \\"b\\""' and toml_value(["x", 1]) == '["x", 1]'
    path = tmp_path / "c.toml"
    path.write_text(
        '# Kopf\n[inference]\ncontext_size = 8192   # Kommentar\nkv_cache = "f16"\n', "utf-8"
    )
    old = set_settings(
        path, [("inference", "context_size", 51200), ("inference", "smart_cache", 2)]
    )
    text = path.read_text("utf-8")
    assert old.startswith("# Kopf") and text.startswith("# Kopf")
    assert "context_size = 51200   # Kommentar" in text and "smart_cache = 2" in text
    try:
        toml_value("zwei\nzeilen")
    except EditError:
        pass
    else:  # pragma: no cover
        raise AssertionError("newline accepted")


def test_secrets_replace_only_their_line(tmp_path):
    path = tmp_path / "passwords.txt"
    path.write_text("# geheim\n[sip]\npassword = alt\nuser = agent\n", "utf-8")
    path.chmod(0o600)
    set_secret(path, "sip", "password", "neu%Wert")
    assert path.read_text("utf-8") == "# geheim\n[sip]\npassword = neu%Wert\nuser = agent\n"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    for bad in (" vorne", "zwei\nzeilen"):
        try:
            set_secret(path, "sip", "password", bad)
        except EditError:
            continue
        raise AssertionError(bad)  # pragma: no cover


def test_the_model_page_shows_the_settings_and_the_estimate(tmp_path):
    async def body(system):
        async with system.client() as client:
            anonymous = (await client.get("/api/model")).status_code
            await system.login(client)
            return anonymous, (await client.get("/api/model")).json()

    anonymous, data = scenario(tmp_path, body)
    assert anonymous == 401
    assert data["settings"]["context_size"] == 51200 and data["settings"]["kv_cache"] == "q8_0"
    assert data["kv_estimate_gb"] == kv_gb(51200, "q8_0") == 2.5
    assert data["model"].endswith(".gguf") and data["managed"] is False and data["in_call"] is False


def test_changing_settings_writes_the_file_and_asks_for_a_restart(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            ok = (
                await client.put(
                    "/api/model/settings", json={"context_size": 32768, "moe_cpu_layers": 30}
                )
            ).json()
            bad = await client.put("/api/model/settings", json={"context_size": 100})
            text = (system.tree / "config" / "moritz-agent.toml").read_text("utf-8")
        return ok, bad.status_code, text, system.config.settings.inference

    ok, bad, text, inference = scenario(tmp_path, body)
    assert ok == {"ok": True, "restart_required": True}
    assert inference.context_size == 32768 and inference.moe_cpu_layers == 30
    assert "context_size = 32768" in text and "# ≥ 50k für lange Chats" in text  # comment stays
    assert bad == 422


def test_restart_and_measure_say_why_they_cannot(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            restart = await client.post("/api/model/restart")
            measure = await client.post("/api/model/measure")
        return restart, measure

    restart, measure = scenario(tmp_path, body)
    assert restart.status_code == 409 and restart.json()["detail"]["error"] == "not_managed"
    assert measure.status_code == 409 and measure.json()["detail"]["error"] == "model_unavailable"


def test_measuring_with_a_model(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            system.runtime.call_started("c-1")
            during = (await client.post("/api/model/measure")).json()
            system.runtime.call_ended("c-1")
            after = await client.post("/api/model/measure")
        return during, after, system.model.requests

    during, after, requests = scenario(tmp_path, body, model=True)
    assert during["detail"]["error"] == "in_call"  # the phone comes first
    assert after.status_code == 200, after.text
    data = after.json()
    assert data["total_ms"] >= 0 and "Weilburg" in requests[-1]["messages"][0]["content"]

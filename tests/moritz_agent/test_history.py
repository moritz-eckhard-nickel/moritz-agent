# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""History of the WebUI (docs/plan/15 P2-04): all channels, 15 days, pinned forever, search, export."""

from __future__ import annotations

import asyncio

from moritz_agent.api.routes_chat import ChatBody, web_turn
from moritz_agent.storage import Database
from moritz_agent.storage.history import HistoryStore, fts_query, make_title

from .fake_model import text_chunks, tool_chunks
from .system_util import running_system

DAY = 86400.0


def store(tmp_path, clock):
    db = Database(tmp_path / "db.sqlite3")
    db.ensure()
    return HistoryStore(db, clock=lambda: clock[0])


def scenario(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, **options) as system:
            return await body(system)

    return asyncio.run(go())


# -- the store ----------------------------------------------------------------------------------------
def test_web_and_calls_stay_one_conversation_discord_splits_after_half_an_hour(tmp_path):
    clock = [1_000_000.0]
    history = store(tmp_path, clock)
    web = history.record("web", "web:w-1", "Hallo", "Servus!")
    clock[0] += 2 * 3600
    assert history.record("web", "web:w-1", "Noch da?", "Klar.") == web
    first = history.record("discord", "dm:42", "Wetter?", "Sonnig.")
    clock[0] += 29 * 60
    assert history.record("discord", "dm:42", "Und morgen?", "Regen.") == first
    clock[0] += 31 * 60
    assert history.record("discord", "dm:42", "Witz bitte", "Nein.") != first
    items = history.list()
    assert [i["source"] for i in items] == ["discord", "discord", "web"]
    assert history.get(web)["messages"][-1] == {
        **history.get(web)["messages"][-1],
        "role": "assistant",
        "text": "Klar.",
    }


def test_titles_are_short_and_search_finds_words_titles_and_umlauts(tmp_path):
    clock = [1_000_000.0]
    history = store(tmp_path, clock)
    long = "Erzähl mir bitte ganz ausführlich alles was du über Giraffen in Afrika weißt und mehr"
    giraffes = history.record("web", "web:a", long, "Giraffen sind die höchsten Landtiere.")
    history.record("phone", "call-1", "Wie wird das Wetter?", "Morgen wird es wärmer.")
    assert make_title(long).endswith(" …") and len(make_title(long)) <= 62
    assert [i["id"] for i in history.list(query="giraff")] == [giraffes]
    assert len(history.list(query="warmer")) == 1  # "wärmer" without the umlaut
    assert history.list(query="Wetter")[0]["source"] == "phone"
    assert history.list(query='" OR 1=1 --') == [] and fts_query('a" NEAR(b') == '"a"* "near"* "b"*'
    assert history.list(query="100%") == []


def test_fifteen_days_after_the_last_message_unless_pinned(tmp_path):
    clock = [1_000_000.0]
    history = store(tmp_path, clock)
    old = history.record("web", "web:old", "Alt", "Ja.")
    kept = history.record("web", "web:kept", "Wichtig", "Gespeichert.")
    assert history.update(kept, pinned=True)
    clock[0] += 14 * DAY
    fresh = history.record("phone", "call-9", "Neu", "Ok.")
    clock[0] += 2 * DAY
    assert history.purge(15) == ["web:old"]
    ids = {i["id"] for i in history.list()}
    assert ids == {kept, fresh} and old not in ids
    assert history.list(query="Alt") == []  # the search index forgot it too


def test_rename_delete_export_and_pairs(tmp_path):
    clock = [1_000_000.0]
    history = store(tmp_path, clock)
    conversation = history.record("web", "web:x", "Was ist 2+2?", "**4**")
    history.record("web", "web:x", "Und 3+3?", "6")
    assert history.update(conversation, title="  Rechnen   mit Anton ")
    assert history.get(conversation)["title"] == "Rechnen mit Anton"
    text = history.markdown(conversation)
    assert text.startswith("# Rechnen mit Anton") and "**Du:**\n\nWas ist 2+2?" in text
    assert "**Anton:**\n\n**4**" in text
    assert history.pairs("web:x", 10) == [("Was ist 2+2?", "**4**"), ("Und 3+3?", "6")]
    assert history.pairs("web:x", 1) == [("Und 3+3?", "6")]
    assert history.delete(conversation) == "web:x" and history.get(conversation) is None
    assert not history.delete(conversation) and history.list(query="Rechnen") == []


# -- wired into the system ------------------------------------------------------------------------------
def test_web_chat_and_phone_calls_land_in_the_history_with_the_run_steps(tmp_path):
    async def body(system):
        system.model.script = [
            tool_chunks("get_current_time", '{"kind": "time"}'),
            text_chunks("Es ist 19 Uhr 12."),
        ]
        async with system.client() as client:
            await system.login(client)
            await client.post(
                "/api/chat/stream",
                json={"message": "Erzähl was über Giraffen", "conversation_id": "w-1"},
            )
            await system.runtime.turn("call-7", "Was ist 17 mal 23?")
            listing = (await client.get("/api/conversations")).json()
            web = next(i for i in listing["items"] if i["source"] == "web")
            detail = (await client.get(f"/api/conversations/{web['id']}")).json()
            phone = (await client.get("/api/conversations?source=phone")).json()["items"]
        return web, detail, phone

    web, detail, phone = scenario(tmp_path, body, model=True)
    assert web["chat_id"] == "w-1" and web["title"] == "Erzähl was über Giraffen"
    assert "external_id" not in web
    answer = detail["messages"][-1]
    assert answer["role"] == "assistant" and "19 Uhr 12" in answer["text"]
    assert [s["type"] for s in answer["steps"]] == ["tool_call", "tool_result"]
    assert answer["meta"]["tools"] == ["get_current_time"]
    assert (
        len(phone) == 1 and phone[0]["title"] == "Was ist 17 mal 23?" and "chat_id" not in phone[0]
    )


def test_rename_pin_export_and_delete_over_the_api(tmp_path):
    async def body(system):
        async with system.client() as client:
            await system.login(client)
            await client.post(
                "/api/chat", json={"message": "Was ist 17 mal 23?", "conversation_id": "w-2"}
            )
            item = (await client.get("/api/conversations")).json()["items"][0]
            url = f"/api/conversations/{item['id']}"
            renamed = (await client.patch(url, json={"title": "Mathe", "pinned": True})).json()
            pinned = (await client.get("/api/conversations?pinned=true")).json()["items"]
            export = await client.get(url + "/export.md")
            deleted = (await client.delete(url)).status_code
            gone = (await client.get(url)).status_code
            bad = (await client.get("/api/conversations/../../etc")).status_code
        return renamed, pinned, export, deleted, gone, bad

    renamed, pinned, export, deleted, gone, bad = scenario(tmp_path, body)
    assert renamed["title"] == "Mathe" and renamed["pinned"] is True and len(pinned) == 1
    assert export.headers["content-type"].startswith("text/markdown")
    assert "attachment" in export.headers["content-disposition"] and "# Mathe" in export.text
    assert "17 mal 23 ist 391." in export.text
    assert deleted == 200 and gone == 404 and bad == 404


def test_a_web_conversation_continues_with_its_memory_after_a_restart(tmp_path):
    async def body(system):
        chat = system.runtime.chat
        await chat.run(web_turn(ChatBody(message="Was ist 17 mal 23?", conversation_id="w-3")))
        chat.end("web:w-3")  # what a restart does to the short-term memory
        conversation = chat._conversation(web_turn(ChatBody(message="Und?", conversation_id="w-3")))
        return conversation.context.history

    assert scenario(tmp_path, body) == [("Was ist 17 mal 23?", "17 mal 23 ist 391.")]


def test_nothing_is_kept_when_transcripts_are_switched_off(tmp_path):
    async def body(system):
        system.config.current.settings.storage.store_transcripts = False
        await system.runtime.chat.run(
            web_turn(ChatBody(message="Was ist 2 mal 2?", conversation_id="w-4"))
        )
        return system.runtime.history.list()

    assert scenario(tmp_path, body) == []


def test_the_history_needs_the_login(tmp_path):
    async def body(system):
        async with system.client() as client:
            return [
                (await client.get("/api/conversations")).status_code,
                (await client.get("/api/conversations/h-0123456789abcdef")).status_code,
                (await client.delete("/api/conversations/h-0123456789abcdef")).status_code,
            ]

    assert scenario(tmp_path, body) == [401, 401, 401]

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Discord data, planner, chat service and the internal Discord API (P1-31, P1-38) – no network."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from moritz_agent.config.settings import Settings
from moritz_agent.core.chat import AccessDenied
from moritz_agent.core.principal import Principal, Role, discord_role
from moritz_agent.core.scheduler import Scheduler, in_range, quiet_end
from moritz_agent.core.surface import Surface
from moritz_agent.core.turn import Turn, TurnResult
from moritz_agent.skills.providers.brightsky import Warning
from moritz_agent.storage import Database, DiscordStore

from .fake_model import text_chunks
from .system_util import (
    ADMIN_PIN,
    BOT_TOKEN,
    OWNER_ID,
    STRANGER_ID,
    TRUSTED_ID,
    running_system,
)

BERLIN = ZoneInfo("Europe/Berlin")


def run(coro):
    return asyncio.run(coro)


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=BERLIN)


@pytest.fixture
def store(tmp_path) -> DiscordStore:
    return DiscordStore(Database(tmp_path / "d.sqlite3"))


# -- storage ---------------------------------------------------------------------------------------------------
def test_principals_are_created_and_updated(store):
    assert store.principal("1") is None
    first = store.save_principal(
        "1", "owner", home_postal_code="60311", home_name="Frankfurt am Main"
    )
    assert first["role"] == "owner" and first["home_postal_code"] == "60311"
    second = store.save_principal("1", "owner", quiet_hours="23:00-06:00")
    assert second["quiet_hours"] == "23:00-06:00" and second["home_postal_code"] == "60311"
    with pytest.raises(ValueError):
        store.save_principal("1", "owner", password="x")


def test_subscriptions_are_unique_per_person_and_kind(store):
    store.set_subscription("1", "warnings", {"level": 3})
    store.set_subscription("1", "warnings", {"level": 2})
    store.set_subscription("1", "briefing", {"time": "06:45"})
    store.set_subscription("2", "warnings", {})
    rows = store.subscriptions("warnings")
    assert [(r["user_id"], r["params"]) for r in rows] == [("1", {"level": 2}), ("2", {})]
    assert store.remove_subscription("1", "warnings") and not store.remove_subscription(
        "1", "warnings"
    )
    assert [r["kind"] for r in store.subscriptions(user_id="1")] == ["briefing"]


def test_reminders_come_due_in_order_and_are_marked(store):
    soon = store.add_reminder("1", "dm:1", at(18, 20), "Zahnarzt")
    later = store.add_reminder("1", "default", at(19, 8), "Müll")
    assert [r["id"] for r in store.due_reminders(at(18, 21))] == [soon]
    store.mark_reminder_delivered(soon, at(18, 21))
    assert store.due_reminders(at(18, 21)) == []
    assert [r["id"] for r in store.open_reminders("1")] == [later]
    assert store.cancel_reminder(later, "2") is False  # somebody else's
    assert store.cancel_reminder(later, "1") is True


def test_outbox_dedupes_waits_and_gives_up(store):
    now = at(18, 12)
    first = store.enqueue("reminder", "default", {"text": "a"}, dedupe_key="k1")
    assert store.enqueue("reminder", "default", {"text": "a"}, dedupe_key="k1") is None
    held = store.enqueue("system", "default", {"text": "b"}, not_before=now + timedelta(hours=2))
    assert [i["id"] for i in store.pending(now)] == [first]
    assert [i["id"] for i in store.pending(now + timedelta(hours=3))] == [first, held]
    store.ack(first, True, now)
    assert (
        store.enqueue("reminder", "default", {"text": "a"}, dedupe_key="k1") is not None
    )  # delivered: free again
    for _ in range(5):
        store.ack(held, False, now)
    assert held not in [i["id"] for i in store.pending(now + timedelta(hours=3))]
    assert store.purge_outbox(now + timedelta(days=30)) >= 2


def test_state_lookup_is_exact_not_a_pattern(store):
    store.set_state("warn:1:a_b", "3")
    store.set_state("warn:1:axb", "2")
    assert store.states("warn:1:a_") == {"warn:1:a_b": "3"}
    assert store.drop_state("warn:1:a_b") and store.states("warn:1:") == {"warn:1:axb": "2"}


def test_command_hash_is_remembered(store):
    assert store.registered_hash() is None
    store.save_registered_hash("abc")
    store.save_registered_hash("def")
    assert store.registered_hash() == "def"


# -- roles ------------------------------------------------------------------------------------------------------
def test_roles_follow_the_configured_ids():
    cfg = Settings().discord.model_copy(update={"owner_user_ids": ["1"], "trusted_user_ids": ["2"]})
    assert discord_role(cfg, "1") is Role.OWNER and discord_role(cfg, "2") is Role.TRUSTED
    assert discord_role(cfg, "3") is Role.UNKNOWN
    guest = cfg.model_copy(update={"guest_mode": "skills"})
    assert discord_role(guest, "3") is Role.GUEST
    assert Role.OWNER.at_least(Role.TRUSTED) and not Role.GUEST.at_least(Role.TRUSTED)


def test_principal_short_form_hides_the_id():
    person = Principal("discord:123456789012345678", Role.OWNER, "discord")
    assert person.short() == "…5678" and person.user_id == "123456789012345678"


# -- planner -------------------------------------------------------------------------------------------------------
def make_warning(level, uid="w1", event="Sturmböen", end_hours=30, now=None):
    now = now or at(18, 12)
    return Warning(
        event=event,
        level=level,
        severity={1: "minor", 2: "moderate", 3: "severe", 4: "extreme"}[level],
        start=now,
        end=now + timedelta(hours=end_hours),
        headline=f"Amtliche Warnung vor {event}",
        description="Sturmböen bis 85 km/h",
        instruction="Gegenstände sichern",
        uid=uid,
    )


class Rig:
    def __init__(self, store, now, warnings=(), answers=None):
        self.store = store
        self.moment = now
        self.warnings = list(warnings)
        self.answers = answers or {}
        self.asked: list[tuple[str, str]] = []
        self.cfg = Settings().discord
        self.scheduler = Scheduler(
            store, lambda: self.cfg, lambda: self.moment, ask=self.ask, alerts=self.alerts
        )

    async def ask(self, user, text):
        self.asked.append((user, text))
        answer = self.answers.get(text)
        return SimpleNamespace(result=answer) if answer is not None else None

    async def alerts(self, user):
        return list(self.warnings)

    def box(self, kind=None):
        items = self.store.pending(self.moment + timedelta(days=2), 100)
        return [i for i in items if kind is None or i["kind"] == kind]


def test_ranges_across_midnight():
    assert in_range(at(18, 23, 30), "22:00-07:00") and in_range(at(18, 3), "22:00-07:00")
    assert not in_range(at(18, 12), "22:00-07:00") and not in_range(at(18, 7), "22:00-07:00")
    assert quiet_end(at(18, 23), "22:00-07:00") == at(19, 7)
    assert quiet_end(at(18, 3), "22:00-07:00") == at(18, 7)


def test_a_due_reminder_goes_to_the_outbox_once(store):
    rig = Rig(store, at(18, 20))
    store.add_reminder("1", "dm:1", at(18, 20).astimezone(UTC) - timedelta(seconds=30), "Zahnarzt")
    store.add_reminder("1", "default", at(18, 22), "später")
    result = run(rig.scheduler.tick())
    assert result.reminders == 1
    (item,) = rig.box("reminder")
    assert item["target"] == "dm:1" and item["payload"]["text"] == "Zahnarzt"
    assert item["payload"]["title"] == "⏰ Erinnerung"
    assert run(rig.scheduler.tick()).reminders == 0


def test_a_reminder_from_before_a_restart_is_late_but_not_too_old(store):
    rig = Rig(store, at(18, 20))
    store.add_reminder("1", "default", at(18, 18), "zwei Stunden her")
    store.add_reminder("1", "default", at(17, 20), "einen Tag her")
    run(rig.scheduler.tick())
    (item,) = rig.box("reminder")
    assert (
        item["payload"]["title"] == "⏰ Erinnerung (verspätet)"
        and item["payload"]["text"] == "zwei Stunden her"
    )
    assert store.open_reminders() == []  # the old one is gone as well


def test_warnings_are_announced_once_per_change_and_ended(store):
    store.set_subscription("1", "warnings", {"level": 3})
    rig = Rig(store, at(18, 12), [make_warning(3)])
    assert run(rig.scheduler.tick()).warnings == 1
    (item,) = rig.box("warning")
    assert item["serious"] and item["target"] == "default" and item["payload"]["level"] == 3
    assert (
        "Sturmböen" in item["payload"]["title"]
        and item["payload"]["instruction"] == "Gegenstände sichern"
    )
    rig.moment = at(18, 12, 20)
    assert run(rig.scheduler.tick()).warnings == 0  # unchanged
    rig.moment = at(18, 12, 40)
    rig.warnings = [make_warning(4)]  # worse
    assert run(rig.scheduler.tick()).warnings == 1
    rig.moment = at(18, 13, 0)
    rig.warnings = []  # over
    assert run(rig.scheduler.tick()).warnings == 1
    assert [i["kind"] for i in rig.box()] == ["warning", "warning", "all_clear"]


def test_warnings_are_checked_every_ten_minutes_only(store):
    store.set_subscription("1", "warnings", {"level": 3})
    rig = Rig(store, at(18, 12), [make_warning(3)])
    run(rig.scheduler.tick())
    rig.moment = at(18, 12, 5)
    rig.warnings = [make_warning(3), make_warning(3, uid="w2")]
    assert run(rig.scheduler.tick()).warnings == 0
    rig.moment = at(18, 12, 11)
    assert run(rig.scheduler.tick()).warnings == 1


def test_below_the_chosen_level_nothing_is_sent(store):
    store.set_subscription("1", "warnings", {"level": 3})
    rig = Rig(store, at(18, 12), [make_warning(2)])
    assert run(rig.scheduler.tick()).warnings == 0


def test_quiet_hours_hold_back_small_warnings_but_not_serious_ones(store):
    store.set_subscription("1", "warnings", {"level": 2})
    rig = Rig(store, at(18, 23, 30), [make_warning(2, uid="small"), make_warning(3, uid="big")])
    assert run(rig.scheduler.tick()).warnings == 1
    assert (
        "Sturmböen" in rig.box("warning")[0]["payload"]["title"]
        and rig.box("warning")[0]["payload"]["level"] == 3
    )
    rig.moment = at(19, 7, 30)  # morning: the small one comes now
    assert run(rig.scheduler.tick()).warnings == 1
    assert sorted(i["payload"]["level"] for i in rig.box("warning")) == [2, 3]


def test_warnings_can_go_to_a_direct_message(store):
    store.set_subscription("1", "warnings", {"level": 3})
    rig = Rig(store, at(18, 12), [make_warning(3)])
    rig.cfg = rig.cfg.model_copy(
        update={"notify": rig.cfg.notify.model_copy(update={"target": "dm"})}
    )
    run(rig.scheduler.tick())
    assert rig.box("warning")[0]["target"] == "dm:1"


def briefing_answer(text="Heute ist Sonntag."):
    return SimpleNamespace(text=text)


def test_the_morning_briefing_comes_once_a_day_in_its_window(store):
    store.set_subscription("1", "briefing", {"time": "06:45"})
    rig = Rig(store, at(19, 6, 30), answers={"Morgenbriefing": briefing_answer()})
    assert run(rig.scheduler.tick()).briefings == 0  # too early
    rig.moment = at(19, 6, 50)
    assert run(rig.scheduler.tick()).briefings == 1
    rig.moment = at(19, 7, 5)
    assert run(rig.scheduler.tick()).briefings == 0  # already sent today
    rig.moment = at(20, 6, 46)
    assert run(rig.scheduler.tick()).briefings == 1
    assert [i["payload"]["text"] for i in rig.box("briefing")] == ["Heute ist Sonntag."] * 2


def test_a_briefing_is_not_sent_hours_late_nor_on_weekends_if_asked(store):
    store.set_subscription("1", "briefing", {"time": "06:45", "weekdays": True})
    rig = Rig(store, at(24, 11, 0), answers={"Morgenbriefing": briefing_answer()})
    assert run(rig.scheduler.tick()).briefings == 0  # Saturday 24th? no: 11:00 is far after 06:45
    rig.moment = at(24, 6, 50)  # Saturday
    assert run(rig.scheduler.tick()).briefings == 0
    rig.moment = at(26, 6, 50)  # Monday
    assert run(rig.scheduler.tick()).briefings == 1


def test_the_waste_hint_only_comes_when_something_is_collected(store):
    store.set_subscription("1", "waste", {})
    rig = Rig(
        store,
        at(18, 19, 5),
        answers={
            "Welche Tonne kommt morgen?": SimpleNamespace(
                text="Morgen wird nichts abgeholt.", data={"pickups": 0}
            )
        },
    )
    assert run(rig.scheduler.tick()).other == 0
    rig.moment = at(19, 19, 5)
    rig.answers["Welche Tonne kommt morgen?"] = SimpleNamespace(
        text="Morgen wird die Biotonne abgeholt.", data={"pickups": 1}
    )
    assert run(rig.scheduler.tick()).other == 1
    assert rig.box("waste")[0]["payload"]["text"] == "Morgen wird die Biotonne abgeholt."
    rig.moment = at(19, 19, 30)
    assert run(rig.scheduler.tick()).other == 0


def test_system_notes_are_throttled_and_wait_for_the_morning(store):
    store.set_subscription("1", "system", {})
    rig = Rig(store, at(18, 14))
    assert rig.scheduler.system_event("phone", "Das Telefon ist gestört.") == 1
    assert rig.scheduler.system_event("phone", "Das Telefon ist gestört.") == 0  # same hour
    rig.moment = at(18, 23, 10)
    assert rig.scheduler.system_event("inference", "Das Sprachmodell ist gestört.") == 1
    waiting = [i for i in store.pending(at(18, 23, 30), 10) if i["kind"] == "system"]
    assert len(waiting) == 1  # the night one is not due before 07:00
    assert len(store.pending(at(19, 7, 1), 10)) == 2


def test_call_notes_go_to_subscribers_only(store):
    store.set_subscription("1", "calls", {})
    rig = Rig(store, at(18, 14))
    assert rig.scheduler.call_event("Anruf beendet, 3 Min. 12 s") == 1
    assert rig.box("call")[0]["payload"]["text"].startswith("Anruf beendet")


def test_the_owner_gets_sensible_defaults_once(store):
    rig = Rig(store, at(18, 14))
    rig.scheduler.ensure_defaults("1")
    assert {s["kind"] for s in store.subscriptions(user_id="1")} == {"warnings", "system"}
    store.remove_subscription("1", "system")
    rig.scheduler.ensure_defaults("1")  # a deliberate "off" stays off
    assert {s["kind"] for s in store.subscriptions(user_id="1")} == {"warnings"}
    assert store.subscriptions("warnings")[0]["params"] == {"level": 3}


# -- chat service ------------------------------------------------------------------------------------------------
def turn(
    system,
    user,
    text,
    *,
    role=None,
    surface=Surface.CHAT,
    conversation="discord:dm:1",
    target="dm:1",
):
    role = role or {OWNER_ID: Role.OWNER, TRUSTED_ID: Role.TRUSTED}.get(user, Role.UNKNOWN)
    person = system.runtime.chat.principal(user, role, "Test")
    return Turn(text, person, surface, conversation, reply_target=target)


def chat(system, *args, **kwargs):
    return system.runtime.chat.run(turn(system, *args, **kwargs))


def test_the_owner_gets_an_instant_answer_and_a_card_for_data(tmp_path):
    async def body(system):
        clock = await chat(system, OWNER_ID, "Wie spät ist es?")
        weather = await chat(
            system,
            OWNER_ID,
            "Wie wird das Wetter morgen in Frankfurt?",
            conversation="discord:dm:2",
        )
        return clock, weather

    clock, weather = run_in(tmp_path, body)
    assert clock.skill_id == "time.now" and "19 Uhr 12" in clock.text and clock.card is None
    assert weather.card["title"] == "Wetter" and "Open-Meteo" in weather.card["footer"]
    assert weather.card["color"] == "info" and weather.sources[0]["name"].startswith("Open-Meteo")
    assert {a["label"] for a in weather.actions} == {"Übermorgen", "Wochenende"}


def run_in(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, discord=True, notes=True, **options) as system:
            return await body(system)

    return run(go())


def test_an_unknown_person_is_refused(tmp_path):
    async def body(system):
        with pytest.raises(AccessDenied):
            await chat(system, STRANGER_ID, "Wie spät ist es?")

    run_in(tmp_path, body)


def test_notes_belong_to_the_owner_alone(tmp_path):
    async def body(system):
        await chat(
            system, OWNER_ID, "Schreib Milch auf die Einkaufsliste", conversation="discord:dm:1"
        )
        own = await chat(
            system, OWNER_ID, "Was steht auf der Einkaufsliste?", conversation="discord:dm:1"
        )
        other = await chat(
            system,
            TRUSTED_ID,
            "Was steht auf der Einkaufsliste?",
            conversation="discord:dm:2",
            target="dm:2",
        )
        return own, other

    own, other = run_in(tmp_path, body)
    assert "Milch" in own.text and "keinen Zugriff" in other.text and other.serious


def test_a_personal_home_town_changes_the_weather(tmp_path):
    async def body(system):
        system.runtime.discord_store.save_principal(
            TRUSTED_ID, "trusted", home_postal_code="60311", home_name="Frankfurt am Main"
        )
        mine = await chat(
            system, TRUSTED_ID, "Wie ist das Wetter?", conversation="discord:dm:2", target="dm:2"
        )
        home = await chat(system, OWNER_ID, "Wie ist das Wetter?", conversation="discord:dm:1")
        return mine, home

    mine, home = run_in(tmp_path, body)
    assert "Frankfurt" in mine.text and "Weilburg" in home.text


def test_a_reminder_is_kept_and_listed(tmp_path):
    async def body(system):
        made = await chat(
            system, OWNER_ID, "Erinnere mich morgen um 8 an den Zahnarzt", target="dm:1001"
        )
        listed = await chat(system, OWNER_ID, "Welche Erinnerungen habe ich?", target="dm:1001")
        rows = system.runtime.discord_store.open_reminders(OWNER_ID)
        return made, listed, rows

    made, listed, rows = run_in(tmp_path, body)
    assert made.reminder["id"] == rows[0]["id"] and rows[0]["target"] == "dm:1001"
    assert rows[0]["text"] == "an den Zahnarzt" and "8 Uhr" in listed.text


def test_a_timer_in_chat_becomes_a_real_reminder(tmp_path):
    async def body(system):
        made = await chat(
            system, OWNER_ID, "Stell einen Timer auf 10 Minuten", target="channel:555"
        )
        return made, system.runtime.discord_store.open_reminders(OWNER_ID)

    made, rows = run_in(tmp_path, body)
    assert made.reminder is not None and rows[0]["target"] == "channel:555"
    due = datetime.fromisoformat(rows[0]["due_at"])
    assert (
        abs((due - datetime(2026, 10, 18, 17, 22, tzinfo=UTC)).total_seconds()) < 5
    )  # 19:12 CEST + 10 min


def test_an_open_question_is_answered_with_the_label_of_an_option(tmp_path):
    async def body(system):
        first = await chat(system, OWNER_ID, "Wetter in Neustadt")
        assert first.clarify is not None, first
        second = await chat(system, OWNER_ID, first.clarify["options"][0])
        return first, second

    first, second = run_in(tmp_path, body)
    assert len(first.clarify["options"]) >= 2 and second.skill_id.startswith("weather.")


def test_conversations_do_not_share_follow_ups(tmp_path):
    async def body(system):
        await chat(
            system,
            OWNER_ID,
            "Wie wird das Wetter morgen in Frankfurt?",
            conversation="discord:dm:1",
        )
        same = await chat(system, OWNER_ID, "und übermorgen?", conversation="discord:dm:1")
        other = await chat(system, OWNER_ID, "und übermorgen?", conversation="discord:ch:9")
        return same, other

    same, other = run_in(tmp_path, body)
    assert "Frankfurt" in same.text and other.skill_id is None


def test_spoken_answers_have_no_card_and_no_markdown(tmp_path):
    async def body(system):
        return await chat(
            system,
            OWNER_ID,
            "Wie wird das Wetter morgen in Frankfurt?",
            surface=Surface.SPOKEN,
            conversation="discord:vc:7",
        )

    result = run_in(tmp_path, body)
    assert result.card is None and "Frankfurt" in result.text


def test_model_answers_stream_and_keep_markdown(tmp_path):
    async def body(system):
        system.model.script = [text_chunks("Giraffen sind **sehr** groß.", " Sie leben in Afrika.")]
        events = [
            e
            async for e in system.runtime.chat.events(
                turn(system, OWNER_ID, "Erzähl mir etwas über Giraffen")
            )
        ]
        return events

    events = run_in(tmp_path, body, model=True)
    assert events[-1]["type"] == "result"
    result = events[-1]["result"]
    assert (
        result.markdown == "Giraffen sind **sehr** groß. Sie leben in Afrika."
        and result.skill_id is None
    )
    partials = [e for e in events if e["type"] == "partial"]
    assert all(p["text"].startswith("Giraffen") for p in partials)


def test_chat_turns_are_counted_by_channel_without_text_in_the_stats(tmp_path):
    async def body(system):
        await chat(system, OWNER_ID, "Wie spät ist es?")
        return [dict(r) for r in system.runtime.db.query("SELECT channel, path FROM call_turns")]

    assert run_in(tmp_path, body) == [{"channel": "discord", "path": "skill"}]


def test_turn_result_survives_json():
    original = TurnResult(
        text="a", card={"title": "t"}, actions=[{"label": "x", "say": "y"}], reminder={"id": 1}
    )
    again = TurnResult.from_json(json.loads(json.dumps(original.to_json())))
    assert again == original
    assert TurnResult.from_json({"text": "b", "unknown": 1}).text == "b"


# -- internal Discord API ----------------------------------------------------------------------------------------------
async def post_turn(system, client, user, text, **extra):
    body = {
        "conversation_id": "discord:dm:" + user,
        "text": text,
        "user_id": user,
        "reply_target": "dm:" + user,
        **extra,
    }
    events = []
    async with client.stream(
        "POST", "/internal/discord/turn", json=body, headers=system.internal_headers()
    ) as response:
        status = response.status_code
        async for line in response.aiter_lines():
            if line:
                events.append(json.loads(line))
    return status, events


def test_api_turn_returns_the_result_as_json(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            return await post_turn(system, client, OWNER_ID, "Wie spät ist es?")

    status, events = run_in(tmp_path, body)
    assert status == 200 and events[-1]["type"] == "result"
    assert (
        events[-1]["result"]["skill_id"] == "time.now"
        and "19 Uhr 12" in events[-1]["result"]["text"]
    )


def test_api_refuses_unknown_people_and_wrong_tokens(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            stranger = await post_turn(system, client, STRANGER_ID, "Hallo")
            no_token = await client.post(
                "/internal/discord/turn",
                json={"conversation_id": "x", "text": "a", "user_id": OWNER_ID},
            )
            bad_input = await client.post(
                "/internal/discord/turn",
                json={"conversation_id": "a b", "text": "a", "user_id": "abc"},
                headers=system.internal_headers(),
            )
            return stranger, no_token.status_code, bad_input.status_code

    stranger, no_token, bad_input = run_in(tmp_path, body)
    assert stranger[0] == 403 and no_token == 403 and bad_input == 422


def test_api_outbox_is_fetched_and_acknowledged(tmp_path):
    async def body(system):
        store = system.runtime.discord_store
        store.enqueue("reminder", "default", {"text": "Hallo"}, user_id=OWNER_ID)
        async with system.client(internal=True) as client:
            headers = system.internal_headers()
            items = (await client.get("/internal/discord/outbox", headers=headers)).json()["items"]
            await client.post(
                "/internal/discord/outbox/ack",
                json={"id": items[0]["id"], "delivered": True},
                headers=headers,
            )
            again = (await client.get("/internal/discord/outbox", headers=headers)).json()["items"]
            return items, again

    items, again = run_in(tmp_path, body)
    assert (
        items[0]["payload"] == {"text": "Hallo"} and items[0]["target"] == "default" and again == []
    )


def test_api_home_town_and_quiet_hours(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            headers = system.internal_headers()
            ok = await client.put(
                f"/internal/discord/principal/{TRUSTED_ID}",
                json={"home": "60311", "quiet_hours": "23:00-06:00"},
                headers=headers,
            )
            unknown = await client.put(
                f"/internal/discord/principal/{TRUSTED_ID}",
                json={"home": "Gibtsnichtstadt"},
                headers=headers,
            )
            stranger = await client.put(
                f"/internal/discord/principal/{STRANGER_ID}",
                json={"home": "60311"},
                headers=headers,
            )
            bad = await client.put(
                f"/internal/discord/principal/{TRUSTED_ID}",
                json={"quiet_hours": "spät"},
                headers=headers,
            )
            got = (
                await client.get(f"/internal/discord/principal/{TRUSTED_ID}", headers=headers)
            ).json()
            return ok, unknown, stranger, bad, got

    ok, unknown, stranger, bad, got = run_in(tmp_path, body)
    assert ok.json()["home"]["postal_code"] == "60311" and "Frankfurt" in ok.json()["home"]["name"]
    assert unknown.status_code == 404 and stranger.status_code == 403 and bad.status_code == 422
    assert got["role"] == "trusted" and got["quiet_hours"] == "23:00-06:00"


def test_api_subscriptions_respect_roles(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            headers = system.internal_headers()

            async def put(user, kind, **extra):
                return await client.put(
                    f"/internal/discord/subscriptions/{user}",
                    json={"kind": kind, **extra},
                    headers=headers,
                )

            return {
                "trusted_warn": (await put(TRUSTED_ID, "warnings", params={"level": 9})).json(),
                "trusted_system": (await put(TRUSTED_ID, "system")).status_code,
                "owner_system": (await put(OWNER_ID, "system")).status_code,
                "unknown_kind": (await put(OWNER_ID, "spam")).status_code,
                "bad_time": (await put(OWNER_ID, "briefing", params={"time": "25:99"})).status_code,
                "briefing": (
                    await put(OWNER_ID, "briefing", params={"time": "06:45", "weekdays": True})
                ).json(),
                "stranger": (await put(STRANGER_ID, "warnings")).status_code,
                "off": (await put(OWNER_ID, "briefing", enabled=False)).json(),
            }

    r = run_in(tmp_path, body)
    assert r["trusted_warn"]["params"] == {"level": 4} and r["trusted_system"] == 403
    assert r["owner_system"] == 200 and r["unknown_kind"] == 422 and r["bad_time"] == 422
    assert r["briefing"]["params"] == {"time": "06:45", "weekdays": True}
    assert r["stranger"] == 403 and r["off"]["removed"] is True


def test_api_admin_is_for_the_owner_only(tmp_path):
    async def body(system):
        restarted = []
        system.ctx.restart = lambda: restarted.append(True)
        async with system.client(internal=True) as client:
            headers = system.internal_headers()
            out = {}
            for user in (OWNER_ID, TRUSTED_ID):
                out[user] = [
                    (
                        await client.post(
                            f"/internal/discord/admin/reload?user_id={user}", headers=headers
                        )
                    ).status_code,
                    (
                        await client.post(
                            f"/internal/discord/admin/drain?user_id={user}",
                            json={"drain": True},
                            headers=headers,
                        )
                    ).status_code,
                    (
                        await client.get(
                            f"/internal/discord/admin/logs?user_id={user}", headers=headers
                        )
                    ).status_code,
                    (
                        await client.post(
                            f"/internal/discord/admin/restart?user_id={user}", headers=headers
                        )
                    ).status_code,
                ]
            await client.post(
                f"/internal/discord/admin/drain?user_id={OWNER_ID}",
                json={"drain": False},
                headers=headers,
            )
        return out, restarted

    out, restarted = run_in(tmp_path, body)
    assert out[OWNER_ID] == [200, 200, 200, 200] and out[TRUSTED_ID] == [403, 403, 403, 403]
    assert restarted == [True]


def test_api_restart_waits_for_a_call_to_end(tmp_path):
    async def body(system):
        system.ctx.restart = lambda: None
        system.runtime.call_started("c1", "sip:20", "G722")
        async with system.client(internal=True) as client:
            return (
                await client.post(
                    f"/internal/discord/admin/restart?user_id={OWNER_ID}",
                    headers=system.internal_headers(),
                )
            ).status_code

    assert run_in(tmp_path, body) == 409


def test_api_overview_shows_the_situation_but_no_credential(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            return (
                await client.get("/internal/discord/overview", headers=system.internal_headers())
            ).text

    text = run_in(tmp_path, body)
    data = json.loads(text)
    assert data["situation"]["call"] is False and "components" in data
    assert BOT_TOKEN not in text and ADMIN_PIN not in text


def test_api_logs_filter_by_category(tmp_path):
    async def body(system):
        log_file = system.runtime.settings.resolve(
            system.runtime.settings.logging.file, system.ctx.root
        )
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            "12:00 INFO  [Phone] Anruf\n12:01 INFO  [Discord] verbunden\n", encoding="utf-8"
        )
        async with system.client(internal=True) as client:
            return (
                await client.get(
                    f"/internal/discord/admin/logs?user_id={OWNER_ID}&category=discord",
                    headers=system.internal_headers(),
                )
            ).json()

    try:
        data = run_in(tmp_path, body)
    finally:
        pass
    assert data["lines"] == ["12:01 INFO  [Discord] verbunden"]


def test_api_feedback_is_counted(tmp_path):
    async def body(system):
        async with system.client(internal=True) as client:
            for rating in ("up", "up", "down"):
                await client.post(
                    "/internal/discord/feedback",
                    json={"skill_id": "weather.now", "rating": rating},
                    headers=system.internal_headers(),
                )
        store = system.runtime.discord_store
        return store.state("feedback:weather.now:up"), store.state("feedback:weather.now:down")

    assert run_in(tmp_path, body) == ("2", "1")


def test_a_call_note_reaches_subscribers_with_topics_only_if_allowed(tmp_path):
    async def body(system):
        store = system.runtime.discord_store
        store.set_subscription(OWNER_ID, "calls", {})
        system.runtime.call_started("c9", "sip:20", "G722")
        await system.runtime.turn("c9", "Wie spät ist es?")
        system.runtime.call_ended("c9", "caller_hangup")
        return [i["payload"]["text"] for i in store.pending(system.runtime.svc.now(), 10)]

    texts = run_in(tmp_path, body)
    assert len(texts) == 1 and texts[0].startswith("Anruf beendet") and "Themen" not in texts[0]


# -- phone → Discord (P1-39) --------------------------------------------------------------------------------------
def test_the_phone_can_send_the_last_answer_to_discord(tmp_path):
    async def body(system):
        runtime = system.runtime
        runtime.call_started("c1", "sip:20@192.168.1.176")
        await runtime.turn("c1", "Wie spät ist es?")
        reply = await runtime.turn("c1", "Schick mir das auf Discord")
        pending = system.runtime.discord_store.pending(runtime.svc.now(), 10)
        return reply, [(i["kind"], i["target"], i["payload"]["text"]) for i in pending]

    reply, pending = run_in(tmp_path, body)
    assert reply.text == "Okay, ich habe es dir auf Discord geschickt."
    assert pending == [("forward", f"dm:{OWNER_ID}", "Es ist 19 Uhr 12.")]


def test_a_known_extension_gets_it_on_its_own_discord_and_nothing_goes_out_without_discord(
    tmp_path,
):
    async def body(system):
        system.config.settings.discord.phone_extensions = {"20": TRUSTED_ID}
        runtime = system.runtime
        runtime.call_started("c1", "sip:20@192.168.1.176")
        await runtime.turn("c1", "Welcher Tag ist heute?")
        await runtime.turn("c1", "Schreib mir das auf Discord")
        runtime.call_started("c2", "sip:99@x")
        nothing = await runtime.turn("c2", "Schick mir das auf Discord")  # nothing said before
        targets = [i["target"] for i in runtime.discord_store.pending(runtime.svc.now(), 10)]
        return targets, nothing.text

    targets, nothing = run_in(tmp_path, body)
    assert targets == [f"dm:{TRUSTED_ID}"] and "noch nichts" in nothing


def test_without_discord_the_phone_says_so(tmp_path):
    async def go():
        async with running_system(tmp_path) as system:
            runtime = system.runtime
            runtime.call_started("c1", "sip:20@x")
            await runtime.turn("c1", "Wie spät ist es?")
            return (await runtime.turn("c1", "Schick mir das auf Discord")).text

    assert "nicht eingerichtet" in run(go())

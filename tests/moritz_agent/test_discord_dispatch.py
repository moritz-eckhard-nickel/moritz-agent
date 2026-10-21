# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Messages, commands and buttons through the real main process, answered into a recorder (P1-33…37)."""

from __future__ import annotations

import asyncio
import json

import pytest

from moritz_agent.discord import components
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.commands.handlers import (
    format_calls,
    parse_quiet,
    parse_subscription,
)
from moritz_agent.discord.dispatch import NEEDS_PIN

from .discord_util import FOREIGN_GUILD_ID, GUILD_ID, Recorder, bench
from .fake_model import text_chunks
from .skills_util import Session
from .system_util import (
    ADMIN_PIN,
    BOT_TOKEN,
    CHANNEL_ID,
    OWNER_ID,
    STRANGER_ID,
    TRUSTED_ID,
    running_system,
)


def run_in(tmp_path, body, **options):
    async def go():
        async with running_system(tmp_path, discord=True, notes=True, **options) as system:
            return await body(bench(system))

    return asyncio.run(go())


# -- messages -----------------------------------------------------------------------------------------------
def test_the_owner_asks_in_a_direct_message(tmp_path):
    async def body(b):
        return await b.say("Wie spät ist es?")

    sent = run_in(tmp_path, body)
    assert len(sent.sent) == 1 and "19 Uhr 12" in sent.text
    assert sent.typed == 1 and sent.sent[0].content.endswith(("⏰", "✨", "🐾"))


def test_a_stranger_is_ignored_and_a_notice_comes_once_a_day(tmp_path):
    async def body(b):
        silent = await b.say("Wie spät ist es?", STRANGER_ID)
        b.system.config.settings.discord.unknown_users = "notice"
        first = await b.say("Hallo?", STRANGER_ID)
        again = await b.say("Hallo?", STRANGER_ID)
        return silent, first, again

    silent, first, again = run_in(tmp_path, body)
    assert not silent.sent and not again.sent
    assert first.texts == ["Ich spreche nur mit freigegebenen Personen."]


def test_the_default_channel_answers_everything_other_channels_need_a_mention(tmp_path):
    async def body(b):
        home = await b.say("Wie spät ist es?", where="S")
        elsewhere = await b.say("Wie spät ist es?", where="S", channel="123")
        origin = b.origin(where="S", channel="123")
        mention = Recorder()
        await b.dispatcher.message(
            b.info("<@5000> Wie spät ist es?", origin, mentions_bot=True), origin, mention
        )
        named = await b.say("Nikita, wie spät ist es?", where="S", channel="123")
        return home, elsewhere, mention, named

    home, elsewhere, mention, named = run_in(tmp_path, body)
    assert "19 Uhr 12" in home.text and not elsewhere.sent
    assert "19 Uhr 12" in mention.text and "19 Uhr 12" in named.text


def test_a_foreign_server_is_not_answered_in_the_channel(tmp_path):
    async def body(b):
        return await b.say("Wie spät ist es?", where="U", channel="55", guild=FOREIGN_GUILD_ID)

    assert not run_in(tmp_path, body).sent


def test_weather_arrives_as_a_card_with_buttons_in_the_style(tmp_path):
    async def body(b):
        return await b.say("Wie wird das Wetter morgen in Frankfurt?")

    sent = run_in(tmp_path, body)
    message = sent.sent[0]
    assert message.embed and message.embed["title"] and message.embed["footer"]["text"]
    assert message.buttons and message.buttons[0].custom_id.startswith("a:1001:")
    assert "Open-Meteo" in message.embed["footer"]["text"]


def test_rate_limit_answers_once_and_then_stays_quiet(tmp_path):
    async def body(b):
        b.system.config.settings.discord.rate_limits.owner_per_minute = 2
        answers = [await b.say("Wie spät ist es?") for _ in range(2)]
        limited = await b.say("Wie spät ist es?")
        quiet = await b.say("Wie spät ist es?")
        b.clock.now += 61
        again = await b.say("Wie spät ist es?")
        return answers, limited, quiet, again

    answers, limited, quiet, again = run_in(tmp_path, body)
    assert all("19 Uhr 12" in a.text for a in answers) and "Nicht so schnell" in limited.text
    assert not quiet.sent and "19 Uhr 12" in again.text


def test_maintenance_mode_tells_why(tmp_path):
    async def body(b):
        b.draining[0] = True
        return await b.say("Wie spät ist es?")

    assert "aktualisiert" in run_in(tmp_path, body).text


def test_maintenance_mode_also_holds_back_menus_and_buttons(tmp_path):
    async def body(b):
        b.draining[0] = True
        menu = Recorder(ephemeral=True)
        await b.dispatcher.context_menu("Nikita fragen", "Wie spät ist es?", b.origin(), menu)
        button = Recorder()
        custom_id = components.encode_action(OWNER_ID, "Wie spät ist es?")
        await b.dispatcher.component(custom_id, [], b.origin(), button)
        pick = Recorder()
        await b.dispatcher.component(components.encode_pick(OWNER_ID), ["1:Eins"], b.origin(), pick)
        return menu, button, pick

    for sent in run_in(tmp_path, body):
        assert "aktualisiert" in sent.text and "19 Uhr" not in sent.text


def test_too_long_input_is_cut_and_said(tmp_path):
    async def body(b):
        b.system.config.settings.discord.max_message_chars = 100
        return await b.say("Wie spät ist es? " + "x" * 300)

    sent = run_in(tmp_path, body)
    assert "nur die ersten 100 Zeichen" in sent.texts[0]


def test_secrets_never_leave_in_an_answer(tmp_path):
    async def body(b):
        b.system.model.script = [text_chunks(f"Der Token ist {BOT_TOKEN} und die PIN {ADMIN_PIN}.")]
        return await b.say("Erzähl mir etwas über Giraffen")

    sent = run_in(tmp_path, body, model=True)
    assert BOT_TOKEN not in sent.text and ADMIN_PIN not in sent.text and "***" in sent.text


class ScriptedCore:
    """Feeds ``events`` to the dispatcher, then answers with ``result`` (the stream of the real core
    arrives in one piece through the test transport, so the timing is tested with this stand-in)."""

    def __init__(self, bench, events, result, step=0.0):
        self.bench, self.events, self.result, self.step = bench, events, result, step

    async def turn(self, on_event, **body):
        for event in self.events:
            self.bench.clock.now += self.step
            await on_event(event)
        return self.result


def test_model_answers_are_streamed_then_replaced_by_the_final_text(tmp_path):
    from moritz_agent.core.turn import TurnResult

    async def body(b):
        final = TurnResult(markdown="Giraffen sind **sehr** groß. Sie leben in Afrika.")
        events = [
            {"type": "partial", "text": "Giraffen"},  # no sentence yet: nothing is sent
            {"type": "partial", "text": "Giraffen sind **sehr** groß."},  # first sentence: sent
            {"type": "partial", "text": "Giraffen sind **sehr** groß. Sie leben"},  # too soon
            {"type": "partial", "text": "Giraffen sind **sehr** groß. Sie leben in Afrika."},
        ]
        b.dispatcher.core = ScriptedCore(b, events, final, step=0.7)
        return await b.say("Erzähl mir etwas über Giraffen")

    sent = run_in(tmp_path, body)
    assert len(sent.sent) == 1
    assert sent.texts[0].startswith("Giraffen sind **sehr** groß. Sie leben in Afrika.")
    assert "▌" not in sent.texts[0]
    assert len(sent.edits) == 2  # one while streaming (1.2 s passed), one with the final text


def test_a_long_streamed_answer_is_split_when_it_is_done(tmp_path):
    from moritz_agent.core.turn import TurnResult

    async def body(b):
        long = ("Ein Absatz mit Text. " * 40 + "\n\n") * 4
        events = [{"type": "partial", "text": "Ein Absatz mit Text."}]
        b.dispatcher.core = ScriptedCore(b, events, TurnResult(markdown=long))
        return await b.say("Erzähl mir etwas")

    sent = run_in(tmp_path, body)
    assert 1 < len(sent.sent) <= 3 or sent.sent[0].file is not None
    assert all(len(m.content) <= 2000 for m in sent.sent)


def test_a_failing_stream_edits_the_half_answer_into_an_error(tmp_path):
    from moritz_agent.discord.core import CoreUnavailable

    class Breaking:
        async def turn(self, on_event, **body):
            await on_event({"type": "partial", "text": "Giraffen sind groß."})
            raise CoreUnavailable("connection lost")

    async def body(b):
        b.dispatcher.core = Breaking()
        return await b.say("Erzähl mir etwas über Giraffen")

    sent = run_in(tmp_path, body)
    assert len(sent.sent) == 1 and "Uff" in sent.texts[0]


def test_core_down_gives_a_friendly_error(tmp_path):
    async def body(b):
        b.dispatcher.core = type(b.core)("http://127.0.0.1:1", "x")
        return await b.say("Wie spät ist es?")

    sent = run_in(tmp_path, body)
    assert "Uff" in sent.text and "Token" not in sent.text


# -- buttons and menus -----------------------------------------------------------------------------------------
def test_a_follow_up_button_asks_in_the_same_conversation(tmp_path):
    async def body(b):
        first = await b.say("Wie wird das Wetter morgen in Frankfurt?")
        button = first.sent[0].buttons[0]
        origin = b.origin()
        pressed = Recorder()
        await b.dispatcher.component(button.custom_id, [], origin, pressed)
        return pressed

    pressed = run_in(tmp_path, body)
    assert pressed.began == 1 and pressed.sent and "Frankfurt" in json.dumps(pressed.sent[0].embed)


def test_only_the_asker_or_the_owner_may_press(tmp_path):
    async def body(b):
        mine = components.encode_action(TRUSTED_ID, "Wie spät ist es?")
        other = Recorder()
        await b.dispatcher.component(mine, [], b.origin(OWNER_ID, where="S"), Recorder())
        await b.dispatcher.component(
            components.encode_action(OWNER_ID, "Wie spät ist es?"),
            [],
            b.origin(TRUSTED_ID),
            other,
        )
        stranger = Recorder()
        await b.dispatcher.component(mine, [], b.origin(STRANGER_ID), stranger)
        return other, stranger

    other, stranger = run_in(tmp_path, body)
    assert "nicht deine Frage" in other.text
    assert "darf ich leider nicht" in stranger.text


def test_a_question_back_is_answered_with_the_menu(tmp_path):
    async def body(b):
        first = await b.say("Wie wird das Wetter morgen in Neustadt?")
        message = first.sent[0]
        assert message.select is not None
        choice = f"1:{message.select.options[0]}"
        second = Recorder()
        await b.dispatcher.component(message.select.custom_id, [choice], b.origin(), second)
        return message, second

    message, second = run_in(tmp_path, body)
    assert len(message.select.options) >= 2
    assert second.sent and "Neustadt" in second.text + json.dumps(second.sent[0].embed or {})


# -- reminders ------------------------------------------------------------------------------------------------------
def test_a_reminder_goes_to_the_place_it_was_asked_in(tmp_path):
    async def body(b):
        dm = await b.say("Erinnere mich morgen um 8 Uhr an den Zahnarzt")
        home = await b.say("Erinnere mich morgen um 9 Uhr an den Zahnarzt", where="S")
        rows = b.system.runtime.discord_store.open_reminders(OWNER_ID)
        return dm, home, [r["target"] for r in rows]

    dm, home, targets = run_in(tmp_path, body)
    assert dm.reactions == ["✅"] and home.reactions == ["✅"]
    assert targets == ["dm:1001", "default"]


# -- commands ---------------------------------------------------------------------------------------------------------
def test_a_slash_command_becomes_the_sentence_the_router_knows(tmp_path):
    async def body(b):
        return await b.command("wetter", {"ort": "Frankfurt", "wann": "morgen"}, where="S")

    sent = run_in(tmp_path, body)
    assert sent.began == 1 and sent.sent[0].embed and "Frankfurt" in json.dumps(sent.sent[0].embed)


def test_commands_follow_the_role_and_place_matrix(tmp_path):
    async def body(b):
        guest = await b.command("frag", {"text": "Wie spät ist es?"}, user=STRANGER_ID)
        notes_in_server = await b.command("notiz", {"aktion": "zeigen"}, where="S")
        trusted_admin = await b.command("status", group="admin", user=TRUSTED_ID)
        owner_admin_in_server = await b.command("status", group="admin", where="S")
        return guest, notes_in_server, trusted_admin, owner_admin_in_server

    for sent in run_in(tmp_path, body):
        assert "leider nicht" in sent.text, sent.text


def test_commands_in_a_foreign_server_answer_privately(tmp_path):
    async def body(b):
        spec = commands.find("frag")
        origin = b.origin(where="U", channel="55")
        sender = Recorder(ephemeral=True)
        await b.dispatcher.command(spec, {"text": "Wie spät ist es?"}, origin, sender)
        return sender, b.system.runtime.chat

    sender, _ = run_in(tmp_path, body)
    assert sender.sent[0].ephemeral and "19 Uhr 12" in sender.text


def test_every_say_command_is_answered_by_the_skill_it_stands_for():
    """The sentences of /wetter, /pollen … reach the router of the phone and the chat alike."""
    expected = {
        ("wetter", ("ort", "Wiesbaden"), ("wann", "morgen")): "weather.day",
        (
            "wetter",
            ("detail", "regen"),
        ): "weather.rain",
        (
            "wetter",
            ("detail", "wind"),
        ): "weather.wind",
        (
            "wetter",
            ("detail", "temperatur"),
        ): "weather.temperature",
        (
            "wetter",
            ("detail", "frost"),
        ): "weather.frost",
        ("warnungen",): "warn.weather",
        ("pollen", ("wann", "morgen")): "pollen.forecast",
        ("luft",): "air.quality",
        ("sonne",): "sun.rise_set",
        ("mond",): "moon.phase",
        ("zeit", ("ort", "Tokio")): "time.world",
        ("zeit",): "time.now",
        ("datum", ("ausdruck", "in 3 Wochen")): "date.offset",
        ("datum", ("ausdruck", "24.12.")): "date.weekday_of",
        ("feiertage",): "holiday.next",
        ("feiertage", ("jahr", 2027)): "holiday.list",
        ("ferien",): "school.next",
        ("rechne", ("ausdruck", "17 mal 23")): "calc.arith",
        ("umrechnen", ("ausdruck", "5 Meilen in Kilometer")): "convert.units",
        ("kurs", ("betrag", "50"), ("waehrung", "Dollar")): "money.fx",
        ("sprit",): "money.fuel",
        ("pegel",): "water.level",
        ("muell",): "waste.next",
        ("fussball",): "football.last",
        ("nachrichten",): "news.headlines",
        ("buchstabiere", ("wort", "Weilburg")): "spell.word",
        ("wuerfel", ("anzahl", 2), ("seiten", 6)): "random.dice",
        ("wuerfel",): "random.dice",
        ("muenze",): "random.coin",
        ("zufall", ("von", 1), ("bis", 100)): "random.number",
        ("timer", ("dauer", "10 Minuten")): "timer.start",
        ("erinnere", ("wann", "morgen um 8 Uhr"), ("was", "den Zahnarzt")): "remind.add",
        ("notiz", ("aktion", "hinzu"), ("text", "Milch kaufen")): "notes.add",
        ("notiz",): "notes.read",
        ("einkauf", ("aktion", "hinzu"), ("text", "Milch")): "notes.add",
        ("einkauf",): "notes.read",
        ("briefing",): "briefing",
    }
    for key, skill in expected.items():
        spec = commands.find(key[0])
        assert spec is not None and spec.say is not None, key
        values = dict(key[1:])
        text = commands.sentence(spec, values)
        assert Session().skill(text) == skill, (key, text)


def test_all_strings_of_the_table_fit_discords_limits():
    def walk(spec: commands.Spec) -> None:
        assert 1 <= len(spec.name) <= 32 and spec.name == spec.name.lower(), spec.name
        assert 1 <= len(spec.description) <= 100, spec.name
        assert len(spec.options) <= 25
        for opt in spec.options:
            assert opt.name.isascii() and opt.name == opt.name.lower() and len(opt.name) <= 32
            assert 1 <= len(opt.description) <= 100, (spec.name, opt.name)
            assert len(opt.choices) <= 25
            for label, value in opt.choices:
                assert 1 <= len(label) <= 100 and 1 <= len(value) <= 100
        for sub in spec.subcommands:
            walk(sub)

    for spec in commands.SPECS:
        walk(spec)
    names = [s.name for s in commands.SPECS]
    assert len(names) == len(set(names)) <= 100


def test_inactive_functions_register_no_command(tmp_path):
    from moritz_agent.config.settings import Settings

    settings = Settings()
    settings.skills.notes.enabled = False
    settings.skills.waste.enabled = False
    names = {s.name for s in commands.active_specs(commands.Features.from_settings(settings))}
    assert {"frag", "wetter", "hilfe", "abo", "admin"} <= names
    assert not names & {"notiz", "einkauf", "muell", "joinvc", "leavevc", "sprit", "fussball"}
    settings.skills.notes.enabled = True
    voice = commands.Features.from_settings(settings, voice=True)
    names = {s.name for s in commands.active_specs(voice)}
    assert {"notiz", "joinvc", "leavevc"} <= names
    settings.skills.enabled = False
    assert "wetter" not in {
        s.name for s in commands.active_specs(commands.Features.from_settings(settings))
    }


def test_the_registration_fingerprint_changes_with_the_table():
    one = commands.digest([{"name": "a", "description": "x"}])
    assert one == commands.digest([{"description": "x", "name": "a"}])
    assert one != commands.digest([{"name": "a", "description": "y"}])


# -- /abo, /einstellungen, /erinnerungen, /anrufe, /hilfe -------------------------------------------------------------
def test_parse_subscription():
    assert parse_subscription("warnungen", "an") == (True, {"level": 3})
    assert parse_subscription("warnungen", "2") == (True, {"level": 2})
    assert parse_subscription("warnungen", "extrem") == (True, {"level": 4})
    assert parse_subscription("warnungen", "aus") == (False, {})
    assert isinstance(parse_subscription("warnungen", "vielleicht"), str)
    assert parse_subscription("briefing", "07:15 wochentags") == (
        True,
        {"time": "07:15", "weekdays": True},
    )
    assert parse_subscription("briefing", "an") == (True, {"time": "06:45", "weekdays": False})
    assert isinstance(parse_subscription("briefing", "25:00"), str)
    assert parse_subscription("muell", "an") == (True, {})
    assert isinstance(parse_subscription("muell", "hm"), str)


def test_parse_quiet():
    assert parse_quiet("22:00-07:00") == "22:00-07:00"
    assert parse_quiet("23.30 – 6:15") == "23:30-06:15"
    assert parse_quiet("aus") == "00:00-00:00" and parse_quiet("") == ""
    assert parse_quiet("abends") is None


def test_subscriptions_are_kept_for_the_planner(tmp_path):
    async def body(b):
        warnings = await b.command("abo", {"was": "warnungen", "einstellung": "2"})
        briefing = await b.command("abo", {"was": "briefing", "einstellung": "07:00 wochentags"})
        bad = await b.command("abo", {"was": "muell", "einstellung": "hm"})
        trusted_calls = await b.command(
            "abo", {"was": "anrufe", "einstellung": "an"}, user=TRUSTED_ID
        )
        subs = {
            (s["user_id"], s["kind"]): s["params"]
            for s in b.system.runtime.discord_store.subscriptions()
        }
        return warnings, briefing, bad, trusted_calls, subs

    warnings, briefing, bad, trusted_calls, subs = run_in(tmp_path, body)
    assert "Stufe 2" in warnings.text and "07:00" in briefing.text and "an“ oder „aus" in bad.text
    assert "nicht erlauben" in trusted_calls.text
    assert subs[(OWNER_ID, "warnings")] == {"level": 2}
    assert subs[(OWNER_ID, "briefing")] == {"time": "07:00", "weekdays": True}
    assert warnings.sent[0].ephemeral


def test_settings_change_the_home_town_for_the_next_question(tmp_path):
    async def body(b):
        before = await b.say("Wie wird das Wetter morgen?")
        saved = await b.command("einstellungen", {"heimatort": "60311", "ruhezeit": "23:00-06:00"})
        after = await b.say("Wie wird das Wetter morgen?")
        unknown = await b.command("einstellungen", {"heimatort": "Gibtsnichtstadt"})
        bad_quiet = await b.command("einstellungen", {"ruhezeit": "abends"})
        reset = await b.command("einstellungen", {"heimatort": ""})
        return before, saved, after, unknown, bad_quiet, reset

    before, saved, after, unknown, bad_quiet, reset = run_in(tmp_path, body)
    assert "Weilburg" in json.dumps(before.sent[0].embed)
    assert "Frankfurt" in json.dumps(saved.sent[0].embed) and "23:00-06:00" in json.dumps(
        saved.sent[0].embed
    )
    assert "Frankfurt" in json.dumps(after.sent[0].embed)
    assert "kenne ich leider nicht" in unknown.text and "Ruhezeit" in bad_quiet.text
    assert "wie zu Hause" in json.dumps(reset.sent[0].embed)


def test_reminders_can_be_listed_and_deleted(tmp_path):
    async def body(b):
        await b.say("Erinnere mich morgen um 8 Uhr an den Zahnarzt")
        listed = await b.command("erinnerungen")
        number = b.system.runtime.discord_store.open_reminders(OWNER_ID)[0]["id"]
        gone = await b.command("erinnerungen", {"loeschen": number})
        none = await b.command("erinnerungen")
        missing = await b.command("erinnerungen", {"loeschen": 999})
        return listed, gone, none, missing

    listed, gone, none, missing = run_in(tmp_path, body)
    assert "Zahnarzt" in listed.text and "08:00" in listed.text
    assert "Gelöscht" in gone.text and "keine offenen" in none.text and "nicht" in missing.text


def test_a_long_list_of_reminders_fits_into_one_message(tmp_path):
    from datetime import UTC, datetime, timedelta

    from moritz_agent.discord.render import MESSAGE_LIMIT

    async def body(b):
        store = b.system.runtime.discord_store
        due = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
        for n in range(25):
            store.add_reminder(OWNER_ID, "default", due + timedelta(hours=n), f"{n}\n" + "x" * 480)
        return await b.command("erinnerungen")

    listed = run_in(tmp_path, body)
    (message,) = listed.sent
    lines = message.content.splitlines()
    assert len(message.content) <= MESSAGE_LIMIT
    assert all(len(line) < 120 for line in lines) and any("…" in line for line in lines)
    assert "weitere" in message.content and "/erinnerungen loeschen" in message.content


def test_calls_are_listed_without_content(tmp_path):
    overview = {
        "phone": {"registration": "registered", "in_call": False},
        "calls": [
            {
                "started_at": "2026-10-18T17:03:00+00:00",
                "ended_at": "2026-10-18T17:06:10+00:00",
                "remote_uri": "sip:20@192.168.1.176",
                "end_reason": "remote hangup",
            }
        ],
    }
    text = format_calls(overview, "Europe/Berlin")
    assert "18.10. 19:03" in text and "3 min" in text and "Nebenstelle 20" in text
    assert "frei" in text and format_calls({"phone": {"in_call": True}}, "UTC").startswith(
        "📞 Gerade"
    )


def test_help_lists_only_what_the_person_may_and_what_works(tmp_path):
    async def body(b):
        owner = await b.command("hilfe")
        trusted = await b.command("hilfe", user=TRUSTED_ID)
        privacy = await b.command("hilfe", {"thema": "datenschutz"})
        admin = await b.command("hilfe", {"thema": "admin"}, user=TRUSTED_ID)
        return owner, trusted, privacy, admin

    owner, trusted, privacy, admin = run_in(tmp_path, body)
    assert "/wetter" in owner.text and "/notiz" in owner.text and "/hilfe" in owner.text
    assert "/notiz" not in trusted.text and "/anrufe" not in trusted.text
    assert "😇" in privacy.text and "nur für den Owner" in admin.text


# -- admin ----------------------------------------------------------------------------------------------------------------
def test_admin_status_version_and_logs(tmp_path):
    async def body(b):
        status = await b.command("status", group="admin")
        version = await b.command("version", group="admin")
        logs = await b.command("logs", {"zeilen": 20}, group="admin")
        return status, version, logs

    status, version, logs = run_in(tmp_path, body)
    card = status.sent[0].embed
    names = [f["name"] for f in card["fields"]]
    assert any("Discord" in n for n in names) and any("Sprachmodell" in n for n in names)
    assert "Version" in card["description"] and status.sent[0].ephemeral
    assert "moritz-agent" in version.text
    assert logs.sent  # either lines as a file or the hint that there are none


def test_dangerous_admin_commands_wait_for_a_button(tmp_path):
    async def body(b):
        asked = await b.command("neu-laden", group="admin")
        yes = asked.sent[0].buttons[0].custom_id
        no = asked.sent[0].buttons[1].custom_id
        done = Recorder()
        outcome = await b.dispatcher.component(yes, [], b.origin(), done)
        again = Recorder()
        await b.dispatcher.component(yes, [], b.origin(), again)  # single use
        declined = await b.command("wartung", {"modus": "an"}, group="admin")
        await b.dispatcher.component(
            declined.sent[0].buttons[1].custom_id, [], b.origin(), Recorder()
        )
        still_off = b.system.ctx.draining()
        accepted = await b.command("wartung", {"modus": "an"}, group="admin")
        await b.dispatcher.component(
            accepted.sent[0].buttons[0].custom_id, [], b.origin(), Recorder()
        )
        return asked, outcome, done, again, still_off, b.system.ctx.draining(), no

    asked, outcome, done, again, still_off, draining, _ = run_in(tmp_path, body)
    assert "neu laden" in asked.text and outcome is None and "Neu geladen" in done.text
    assert "abgelaufen" in again.text and not still_off and draining


def test_restart_needs_the_pin_and_locks_after_three_wrong_ones(tmp_path):
    async def body(b):
        restarted: list[bool] = []
        b.system.ctx.restart = lambda: restarted.append(True)
        asked = await b.command("neustart", group="admin")
        button = asked.sent[0].buttons[0].custom_id
        nonce = components.decode(button).nonce
        outcome = await b.dispatcher.component(button, [], b.origin(), Recorder())
        wrong = [Recorder() for _ in range(3)]
        for sender in wrong:
            await b.dispatcher.pin_submitted(nonce, "0000", b.origin(), sender)
        locked = Recorder()
        await b.dispatcher.pin_submitted(nonce, ADMIN_PIN, b.origin(), locked)
        return asked, outcome, wrong, locked, restarted

    asked, outcome, wrong, locked, restarted = run_in(tmp_path, body)
    assert "PIN" in asked.text and outcome == NEEDS_PIN
    assert all("stimmt nicht" in s.text for s in wrong[:3])
    assert "Zu viele" in locked.text and not restarted


def test_restart_with_the_right_pin_and_without_a_call(tmp_path):
    async def body(b):
        restarted: list[bool] = []
        b.system.ctx.restart = lambda: restarted.append(True)
        asked = await b.command("neustart", group="admin")
        nonce = components.decode(asked.sent[0].buttons[0].custom_id).nonce
        done = Recorder()
        await b.dispatcher.pin_submitted(nonce, ADMIN_PIN, b.origin(), done)
        return done, restarted

    done, restarted = run_in(tmp_path, body)
    assert "bis gleich" in done.text and restarted == [True]


def test_restart_is_refused_during_a_call(tmp_path):
    async def body(b):
        b.system.ctx.phone_status = lambda: {"in_call": True}
        b.system.ctx.restart = lambda: None
        asked = await b.command("neustart", group="admin")
        nonce = components.decode(asked.sent[0].buttons[0].custom_id).nonce
        done = Recorder()
        await b.dispatcher.pin_submitted(nonce, ADMIN_PIN, b.origin(), done)
        return done

    assert "Anruf" in run_in(tmp_path, body).text


def test_feedback_reactions_count_per_skill(tmp_path):
    async def body(b):
        assert await b.dispatcher.feedback(OWNER_ID, "👍", "weather.day")
        assert await b.dispatcher.feedback(OWNER_ID, "👎", "weather.day")
        assert not await b.dispatcher.feedback(OWNER_ID, "🎉")
        assert not await b.dispatcher.feedback(STRANGER_ID, "👍")
        store = b.system.runtime.discord_store
        return store.state("feedback:weather.day:up"), store.state("feedback:weather.day:down")

    assert run_in(tmp_path, body) == ("1", "1")


# -- places and the command fingerprint over the internal API ---------------------------------------------------------
def test_places_complete_names_and_postcodes(tmp_path):
    async def body(b):
        return await b.core.places("Weilb"), await b.core.places("603"), await b.core.places("")

    names, postcodes, nothing = run_in(tmp_path, body)
    assert names and names[0]["name"].startswith("Weilburg") and names[0]["postal_code"] == "35781"
    assert postcodes and all(p["postal_code"].startswith("603") for p in postcodes)
    assert nothing == []


def test_the_registered_fingerprint_is_kept_in_the_database(tmp_path):
    async def body(b):
        before = await b.core.commands_hash()
        await b.core.set_commands_hash("abc12345")
        return before, await b.core.commands_hash()

    assert run_in(tmp_path, body) == (None, "abc12345")


def test_home_channel_constants_are_consistent():
    assert CHANNEL_ID and GUILD_ID and pytest  # the benches use them; guard against typos

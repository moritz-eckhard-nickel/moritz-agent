# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Discord worker logic without Discord: access, style, activities, rendering, buttons (P1-33…35, P1-43)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from moritz_agent.config.settings import Discord, Settings
from moritz_agent.core.principal import Role
from moritz_agent.core.turn import TurnResult
from moritz_agent.discord import activities, components, render, sessions
from moritz_agent.discord.access import (
    NOTICE_STRANGER,
    AccessPolicy,
    CommandRule,
    MessageInfo,
    RateLimiter,
    Reaction,
    strip_address,
)
from moritz_agent.discord.style import SMILEY, Styler, StyleState, no_emoji

ROOT = Path(__file__).resolve().parents[2]
BERLIN = ZoneInfo("Europe/Berlin")
BOT = "9000"
OWNER, TRUSTED, STRANGER = "1001", "1002", "1999"
HOME_GUILD, HOME_CHANNEL, OTHER_GUILD = "700", "800", "701"


def discord_cfg(**changes) -> Discord:
    base = Settings().discord.model_copy(
        update={"owner_user_ids": [OWNER], "trusted_user_ids": [TRUSTED], **changes}
    )
    return base


def policy(**changes) -> AccessPolicy:
    return AccessPolicy(
        discord_cfg(**changes),
        default_channel_id=HOME_CHANNEL,
        default_guild_id=HOME_GUILD,
        bot_id=BOT,
    )


def message(author=OWNER, content="Hallo", **kw) -> MessageInfo:
    defaults = {"channel_id": HOME_CHANNEL, "guild_id": HOME_GUILD, "author_is_bot": False}
    return MessageInfo(author_id=author, content=content, **{**defaults, **kw})


# -- addressing -----------------------------------------------------------------------------------------
def test_mentions_and_the_name_are_removed_from_the_question():
    assert strip_address(f"<@{BOT}> wie spät ist es", BOT) == ("wie spät ist es", True, False)
    assert strip_address(f"<@!{BOT}>  Wetter?", BOT)[0] == "Wetter?"
    assert strip_address("Anton, wie spät ist es", BOT) == ("wie spät ist es", False, True)
    assert strip_address("hey anton: Wetter", BOT)[0] == "Wetter"
    assert strip_address("Anton ist toll", BOT) == ("Anton ist toll", False, False)
    assert strip_address("<@123> hallo", BOT) == ("<@123> hallo", False, False)


# -- the access matrix ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("author", "where", "expected"),
    [
        # in the default channel Anton answers everything of the owner and of trusted people
        (OWNER, {}, Reaction.ANSWER),
        (TRUSTED, {}, Reaction.ANSWER),
        (STRANGER, {}, Reaction.IGNORE),
        # another channel of the home server: only when addressed
        (OWNER, {"channel_id": "801"}, Reaction.IGNORE),
        (OWNER, {"channel_id": "801", "mentions_bot": True}, Reaction.ANSWER),
        (OWNER, {"channel_id": "801", "replies_to_bot": True}, Reaction.ANSWER),
        (OWNER, {"channel_id": "801", "in_bot_thread": True}, Reaction.ANSWER),
        (OWNER, {"channel_id": "801", "content": "Anton, hallo"}, Reaction.ANSWER),
        # a direct message
        (OWNER, {"guild_id": None}, Reaction.ANSWER),
        (TRUSTED, {"guild_id": None}, Reaction.ANSWER),
        (STRANGER, {"guild_id": None}, Reaction.IGNORE),
        # a server that is not ours: nothing, even for the owner
        (OWNER, {"guild_id": OTHER_GUILD, "mentions_bot": True}, Reaction.IGNORE),
        # bots, including ourselves
        (BOT, {}, Reaction.IGNORE),
        (OWNER, {"author_is_bot": True}, Reaction.IGNORE),
    ],
)
def test_who_gets_an_answer(author, where, expected):
    assert policy().message(message(author, **where)).reaction is expected


def test_allowed_extra_servers_and_chat_channels():
    both = policy(allowed_guild_ids=[OTHER_GUILD], chat_channel_ids=["802"])
    assert (
        both.message(message(guild_id=OTHER_GUILD, channel_id="900", mentions_bot=True)).reaction
        is Reaction.ANSWER
    )
    assert both.message(message(guild_id=OTHER_GUILD, channel_id="900")).reaction is Reaction.IGNORE
    assert both.message(message(channel_id="802")).reaction is Reaction.ANSWER


def test_the_question_is_cleaned_and_the_role_is_reported():
    decision = policy().message(message(TRUSTED, f"<@{BOT}> Wetter in Gießen?", mentions_bot=True))
    assert decision.reaction is Reaction.ANSWER and decision.text == "Wetter in Gießen?"
    assert decision.role is Role.TRUSTED


def test_the_name_trigger_can_be_switched_off():
    off = policy(name_trigger=False)
    assert (
        off.message(message(channel_id="801", content="Anton, hallo")).reaction is Reaction.IGNORE
    )


def test_guests_only_with_guest_mode_and_only_when_addressed():
    closed = policy()
    assert closed.message(message(STRANGER, mentions_bot=True)).reaction is Reaction.IGNORE
    open_ = policy(guest_mode="skills")
    assert open_.message(message(STRANGER)).reaction is Reaction.IGNORE  # not addressed
    assert open_.message(message(STRANGER, mentions_bot=True)).reaction is Reaction.ANSWER
    assert open_.message(message(STRANGER, guild_id=None)).reaction is Reaction.IGNORE  # no DMs
    assert open_.message(message(STRANGER, mentions_bot=True)).role is Role.GUEST


def test_unknown_people_can_be_told_once_a_day():
    quiet = policy()
    assert quiet.message(message(STRANGER, guild_id=None)).reaction is Reaction.IGNORE
    polite = policy(unknown_users="notice")
    first = polite.message(message(STRANGER, guild_id=None), today="2026-10-18")
    again = polite.message(message(STRANGER, guild_id=None), today="2026-10-18")
    next_day = polite.message(message(STRANGER, guild_id=None), today="2026-10-19")
    assert first.reaction is Reaction.NOTICE and again.reaction is Reaction.IGNORE
    assert next_day.reaction is Reaction.NOTICE


def test_a_stranger_on_our_server_is_reported_once():
    p = policy()
    stranger = message(STRANGER)
    assert p.stranger_hint(stranger) == NOTICE_STRANGER
    assert p.stranger_hint(stranger) is None
    assert p.stranger_hint(message(OWNER)) is None
    assert p.stranger_hint(message(STRANGER, guild_id=OTHER_GUILD)) is None
    assert p.stranger_hint(message("77", author_is_bot=True)) is None


@pytest.mark.parametrize(
    ("user", "rule", "context", "allowed"),
    [
        (OWNER, CommandRule("OV", "S DM U"), "U", True),
        (TRUSTED, CommandRule("OV", "S DM U"), "S", True),
        (TRUSTED, CommandRule("O", "DM"), "DM", False),
        (OWNER, CommandRule("O", "DM"), "S", False),
        (STRANGER, CommandRule("OVG", "S DM U"), "S", False),
    ],
)
def test_command_rules(user, rule, context, allowed):
    assert policy().command_allowed(user, rule, context) is allowed


def test_a_guest_may_use_the_guest_commands():
    p = policy(guest_mode="skills")
    assert p.command_allowed(STRANGER, CommandRule("OVG", "S"), "S") is True
    assert p.command_allowed(STRANGER, CommandRule("OV", "S"), "S") is False


def test_rate_limits_per_role_and_minute():
    now = [0.0]
    limiter = RateLimiter(lambda: discord_cfg(), lambda: now[0])
    assert all(limiter.allow("t", Role.TRUSTED) for _ in range(10))
    assert not limiter.allow("t", Role.TRUSTED)
    assert limiter.allow("o", Role.OWNER)  # another person
    now[0] = 61
    assert limiter.allow("t", Role.TRUSTED)
    assert limiter.limit(Role.GUEST) == 3 and limiter.limit(Role.OWNER) == 30


# -- sessions --------------------------------------------------------------------------------------------
def test_conversation_names_and_reply_targets():
    assert sessions.dm(5) == "discord:dm:5" and sessions.channel(6) == "discord:ch:6"
    assert sessions.thread(7) == "discord:th:7" and sessions.voice(8) == "discord:vc:8"
    assert sessions.reply_target("dm", user_id=5) == "dm:5"
    assert sessions.reply_target("guild", channel_id=6, default_id="9") == "channel:6"
    assert sessions.reply_target("guild", channel_id=9, default_id="9") == "default"


# -- style -------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def styler() -> Styler:
    return Styler.from_root(ROOT, "cute")


def test_facts_come_first_and_sugar_comes_after(styler):
    text = styler.decorate("Morgen wird es regnen.", skill_id="weather.day", serious=False, seed=1)
    assert text == "Morgen wird es regnen. :("


def test_serious_answers_get_no_decoration(styler):
    plain = "Unwetterwarnung für Weilburg: Sturmböen."
    assert styler.decorate(plain, skill_id="warn.weather", serious=True, seed=5) == plain
    assert styler.decorate("Sturm.", skill_id="warn.weather", serious=True, seed=5) == "Sturm."


def test_the_normal_style_changes_nothing(styler):
    normal = Styler(styler.data, "normal")
    assert (
        normal.decorate("Es ist 19 Uhr 12.", skill_id="time.now", serious=False, seed=5)
        == "Es ist 19 Uhr 12."
    )
    assert normal.error("unavailable") == (
        "Uff, an die Daten komm ich gerade nicht ran Versuch’s gleich nochmal."
    )
    assert normal.phrase("joined_voice", channel="Quatschecke") == "Bin unterwegs in Quatschecke"


def test_text_with_a_smiley_already_gets_no_second_one(styler):
    assert styler.decorate("Schön :)", skill_id="weather.now", serious=False, seed=5) == "Schön :)"


def test_no_emoji_ever_and_one_smiley_at_most(styler):
    """Moritz, 21.10.2026: no emoji – :) :( :3 and the like, or nothing."""
    state = StyleState()
    for seed in range(1, 60):
        out = styler.decorate(
            "Antwort ☀️ fertig.", skill_id="weather.now", serious=False, seed=seed, state=state
        )
        assert no_emoji(out) == out and out.startswith("Antwort fertig.")
        assert len(SMILEY.findall(out)) == 1


def test_no_emoji_takes_them_out_cleanly():
    assert no_emoji("⏰ Erinnerung") == "Erinnerung"
    assert no_emoji("Schön 🌤️ und warm 🐾.") == "Schön und warm."
    assert no_emoji("Zeile 1 ✨\n🔊 Zeile 2") == "Zeile 1\nZeile 2"
    assert no_emoji("19:30 Uhr, 3 > 2 → ok") == "19:30 Uhr, 3 > 2 → ok"
    assert no_emoji("Toll 🐾 :) und „🎤 Text“") == "Toll :) und „Text“"


def test_the_style_and_activity_data_have_no_emoji():
    for name in ("stil.de.toml", "aktivitaeten.de.toml"):
        text = (ROOT / "assets/data/discord" / name).read_text(encoding="utf-8")
        assert no_emoji(text) == text, name


def test_decoration_is_deterministic_per_message(styler):
    args = {"skill_id": "money.fx", "serious": False, "seed": 42}
    assert styler.decorate("100 Dollar sind 91 Euro.", **args) == styler.decorate(
        "100 Dollar sind 91 Euro.", **args
    )


def test_the_phrase_lists_are_complete(styler):
    assert styler.phrase("joined_voice", channel="Quatschecke") == "Bin unterwegs in Quatschecke :)"
    assert styler.phrase("startup", 1)
    for key in (
        "unavailable",
        "model_down",
        "starting",
        "generic",
        "rate_limited",
        "maintenance",
        "forbidden",
        "too_long",
    ):
        assert styler.data["errors"][key]


# -- activities --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def activity_data():
    return activities.load(ROOT)


def picker(activity_data, seed=1, **cfg) -> activities.ActivityPicker:
    return activities.ActivityPicker(
        activity_data, Settings().discord.activities.model_copy(update=cfg), seed=seed
    )


def noon(day=20, month=10) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=BERLIN)


def test_the_activity_file_is_valid_and_harmless(activity_data):
    assert activities.validate(activity_data) == []
    forbidden = ("hackt", "festplatte kaputt", "virus", "gelöscht", "trojaner")
    texts = [e["text"].lower() for e in activity_data["base"]]
    assert not [t for t in texts if any(w in t for w in forbidden)]
    assert len(activity_data["base"]) >= 25 and len({e["kind"] for e in activity_data["base"]}) == 5


def test_a_bad_activity_file_is_reported():
    problems = activities.validate(
        {"base": [{"kind": "dancing", "text": "x" * 200}], "situation": {}}
    )
    assert len(problems) >= 3


def test_no_repeat_within_the_last_ten(activity_data):
    p = picker(activity_data)
    now, seen = noon(), []
    for _ in range(40):
        seen.append(p.pick({}, now).text)
        now += timedelta(minutes=10)
    assert all(len(set(seen[i : i + 10])) == 10 for i in range(len(seen) - 9))


def test_the_rotation_lies_between_seven_and_fifteen_minutes(activity_data):
    p = picker(activity_data)
    now = noon()
    for _ in range(30):
        p.pick({}, now)
        wait = (p.next_change - now).total_seconds() / 60
        assert 7 <= wait <= 15
        now = p.next_change
    assert not p.due({}, now - timedelta(minutes=1)) or True


def test_due_follows_the_clock_and_the_situation(activity_data):
    p = picker(activity_data)
    now = noon()
    assert p.due({}, now)  # nothing chosen yet
    p.pick({}, now)
    assert not p.due({}, now + timedelta(minutes=3))
    assert p.due({}, p.next_change + timedelta(seconds=1))
    assert p.due({"call": True}, now + timedelta(seconds=30))  # a call begins: at once
    p.pick({"call": True}, now + timedelta(seconds=30))
    assert p.current.text.startswith("Telefoniert") and not p.due(
        {"call": True}, now + timedelta(minutes=1)
    )
    assert p.due({}, now + timedelta(minutes=1))  # the call is over: back to normal


def test_situations_take_precedence_in_the_right_order(activity_data):
    p = picker(activity_data)
    night = datetime(2026, 10, 20, 2, 0, tzinfo=BERLIN)
    assert p.pick({}, night).text.startswith(("Träumt", "Zählt"))
    assert p.pick({"call": True}, night).text.startswith("Telefoniert")  # call beats night
    warning = p.pick({"call": True, "warning_level": 3}, night)
    assert warning.serious and warning.text.startswith(
        "Achtet auf das Unwetter"
    )  # a warning beats everything
    assert p.pick({"weather": "rain"}, noon()).status == "Spielt im Regen"
    assert p.pick({"services_down": True}, noon()).text.startswith("Sucht das Internet")
    assert p.pick({"startup": True}, noon()).text.startswith("Wacht gerade auf")
    assert p.pick({"maintenance": True, "call": True}, noon()).text.startswith(
        "Wird gerade frisch gemacht"
    )
    assert p.pick({"voice": True}, noon()).text.startswith("Quatscht mit Moritz")


def test_special_days(activity_data):
    p = picker(activity_data, seed=3)
    christmas = {p.pick({}, noon(24, 12)).text for _ in range(12)}
    assert "Packt Geschenke ein" in christmas
    halloween = {p.pick({}, noon(31, 10)).text for _ in range(12)}
    assert "Spukt in deinen Kabeln" in halloween
    easter_sunday = datetime(2026, 4, 5, 12, tzinfo=BERLIN)
    assert "Versteckt Eier im Dateisystem" in {p.pick({}, easter_sunday).text for _ in range(12)}
    carnival = datetime(2026, 2, 14, 12, tzinfo=BERLIN)
    assert "Helau aus dem Serverraum" in {p.pick({}, carnival).text for _ in range(12)}


def test_activities_can_be_switched_off(activity_data):
    p = picker(activity_data, enabled=False)
    assert not p.due({}, noon())
    quiet = picker(activity_data, situational=False)
    assert not quiet.pick({"call": True}, noon()).text.startswith("Telefoniert")


def test_own_sayings_join_the_rotation(tmp_path, activity_data):
    local = tmp_path / "local.toml"
    local.write_text('[[base]]\nkind = "custom"\ntext = "🥨 Brezeln zählen"\n', encoding="utf-8")
    data = activities.load(ROOT, local)
    assert any(e["text"] == "🥨 Brezeln zählen" for e in data["base"])
    assert len(data["base"]) == len(activity_data["base"]) + 1


# -- components --------------------------------------------------------------------------------------------------
def test_custom_ids_round_trip_and_stay_short():
    cid = components.encode_action("1001", "und morgen")
    assert cid == "a:1001:und morgen"
    decoded = components.decode(cid)
    assert (decoded.kind, decoded.user_id, decoded.payload) == ("a", "1001", "und morgen")
    assert len(components.encode_action("1001", "x" * 500)) == 100
    assert components.decode(components.encode_pick("1001")).kind == "c"
    confirm = components.decode(components.encode_confirm("restart", "ab12cd34", "yes"))
    assert (confirm.payload, confirm.nonce, confirm.answer) == ("restart", "ab12cd34", "yes")


@pytest.mark.parametrize("bad", ["", "zzz", "a:abc:und", "a:1001:", "c:abc", "x:only:two", "q:1:2"])
def test_foreign_custom_ids_are_not_understood(bad):
    assert components.decode(bad) is None


def test_only_the_asker_and_the_owner_may_press():
    assert components.may_press("1", "1", ["9"]) and components.may_press("9", "1", ["9"])
    assert not components.may_press("2", "1", ["9"])


def test_confirmations_expire_and_work_once():
    now = [0.0]
    confirm = components.Confirmations(lambda: now[0])
    nonce = confirm.ask("restart", "1")
    assert confirm.take(nonce, "2") is None  # somebody else
    assert confirm.take(nonce, "1").action == "restart"
    assert confirm.take(nonce, "1") is None  # used up
    late = confirm.ask("reload", "1")
    now[0] = 61
    assert confirm.take(late, "1") is None


def test_pin_entry_is_blocked_after_three_wrong_tries():
    now = [0.0]
    confirm = components.Confirmations(lambda: now[0])
    for _ in range(3):
        assert not confirm.pin_blocked("1")
        confirm.pin_failed("1")
    assert confirm.pin_blocked("1") and not confirm.pin_blocked("2")
    now[0] = 601
    assert not confirm.pin_blocked("1")


# -- rendering ---------------------------------------------------------------------------------------------------
def rendered(result, styler, **kw):
    defaults = {
        "user_id": "1001",
        "styler": styler,
        "state": StyleState(),
        "seed": 3,
        "secrets": [],
    }
    return render.render_result(result, **{**defaults, **kw})


def test_a_short_answer_is_one_message_with_buttons(styler):
    result = TurnResult(
        text="Es ist 19 Uhr 12.",
        markdown="Es ist 19 Uhr 12.",
        skill_id="time.now",
        actions=[
            {"label": "Morgen", "say": "und morgen"},
            {"label": "Wochenende", "say": "und am Wochenende"},
        ],
    )
    (message,) = rendered(result, styler)
    assert message.content.startswith("Es ist 19 Uhr 12.") and message.embed is None
    assert [b.custom_id for b in message.buttons] == [
        "a:1001:und morgen",
        "a:1001:und am Wochenende",
    ]


def test_cards_become_embeds_with_color_and_footer(styler):
    card = {
        "title": "Wetter",
        "description": "Morgen wechselhaft bei 8 bis 13 Grad.",
        "fields": [
            {"name": "Mehr Details", "value": "Regenrisiko bis 80 Prozent", "inline": False}
        ],
        "color": "info",
        "footer": "Open-Meteo.com (CC BY 4.0)",
    }
    result = TurnResult(
        text="x",
        markdown="x",
        skill_id="weather.day",
        card=card,
        sources=[{"name": "Open-Meteo.com", "url": "https://open-meteo.com/"}],
    )
    (message,) = rendered(result, styler)
    assert message.embed["title"] == "Wetter" and message.embed["color"] == render.COLORS["info"]
    assert message.embed["footer"]["text"] == "Open-Meteo.com (CC BY 4.0)"
    assert message.embed["description"].startswith("Morgen wechselhaft bei 8 bis 13 Grad.")
    link = message.buttons[-1]
    assert link.style == "link" and link.url == "https://open-meteo.com/"


def test_embed_limits_hold():
    card = {
        "title": "T" * 400,
        "description": "d" * 9000,
        "fields": [{"name": "n" * 400, "value": "v" * 2000, "inline": True} for _ in range(40)],
        "footer": "f" * 5000,
    }
    embed = render.build_embed(card)
    assert len(embed["title"]) <= 256 and len(embed["description"]) <= 4096
    assert len(embed["fields"]) <= 25 and all(
        len(f["value"]) <= 1024 for f in embed.get("fields", [])
    )
    total = len(embed["title"]) + len(embed["description"]) + len(embed["footer"]["text"])
    total += sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
    assert total <= 6000


def test_long_text_is_split_at_paragraphs():
    text = "\n\n".join(f"Absatz {i}: " + "wort " * 80 for i in range(12))
    pieces = render.split_text(text, 2000)
    assert all(len(p) <= 2000 for p in pieces) and len(pieces) >= 3
    assert "".join(pieces).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(
        " ", ""
    )
    assert all(p.rstrip().endswith("wort") for p in pieces[:-1])


def test_code_blocks_stay_closed_in_every_piece():
    block = "```python\n" + "\n".join(f"print({i})" for i in range(400)) + "\n```"
    pieces = render.split_text("Hier der Code:\n\n" + block, 2000)
    assert len(pieces) >= 2
    for piece in pieces:
        assert piece.count("```") % 2 == 0, piece[:80]
        assert len(piece) <= 2000


def test_very_long_answers_go_into_a_file(styler):
    text = "\n\n".join("Absatz " + "wort " * 200 for _ in range(30))
    result = TurnResult(text=text, markdown=text)
    (message,) = rendered(result, styler)
    assert message.file[0] == "antwort.md" and message.file[1].decode() == text
    assert len(message.content) < 2000 and "gekürzt" in message.content


def test_a_question_back_becomes_a_menu(styler):
    result = TurnResult(
        clarify={
            "question": "Welches Neustadt meinst du?",
            "options": ["Neustadt (Hessen)", "Neustadt an der Weinstraße"],
        }
    )
    (message,) = rendered(result, styler)
    assert (
        message.content == "Welches Neustadt meinst du?"
        and message.select.options[0] == "Neustadt (Hessen)"
    )
    assert message.select.custom_id == "c:1001"


def test_secrets_never_leave(styler):
    token = "test-only-bot-token-0123456789abcdef"
    result = TurnResult(
        text=f"Der Schlüssel ist {token}.",
        markdown=f"Der Schlüssel ist {token}.",
        card={
            "title": "Auskunft",
            "description": f"Siehe {token}",
            "fields": [{"name": "x", "value": token}],
        },
        skill_id="geo.home",
    )
    out = rendered(result, styler, secrets=[token, "kurz"])
    dump = repr([m.content for m in out] + [m.embed for m in out])
    assert token not in dump and "***" in dump


def test_model_answers_get_their_sources_as_links(styler):
    result = TurnResult(
        text="Laut tagesschau.de gibt es Neuigkeiten.",
        markdown="Laut tagesschau.de gibt es Neuigkeiten.",
        sources=[{"name": "tagesschau.de", "url": "https://www.tagesschau.de/a"}],
    )
    (message,) = rendered(result, styler)
    assert "Quellen: [tagesschau.de](https://www.tagesschau.de/a)" in message.content
    assert message.buttons[0].style == "link"


def test_ephemeral_flag_is_carried(styler):
    (message,) = rendered(TurnResult(text="Hallo", markdown="Hallo"), styler, ephemeral=True)
    assert message.ephemeral


def test_serious_answers_stay_plain(styler):
    result = TurnResult(
        text="Ich komme gerade nicht an die Wetterdaten.",
        markdown="Ich komme gerade nicht an die Wetterdaten.",
        skill_id="weather.now",
        serious=True,
    )
    (message,) = rendered(result, styler)
    assert message.content == "Ich komme gerade nicht an die Wetterdaten."


# -- notifications from the outbox ----------------------------------------------------------------------------
def test_warning_notifications_carry_level_colors_and_instructions():
    item = {
        "kind": "warning",
        "user_id": "1001",
        "payload": {
            "title": "Achtung: Amtliche Warnung vor Sturmböen",
            "text": "Sturmböen bis 85 km/h",
            "level": 3,
            "instruction": "Gegenstände sichern",
            "until": "2026-10-18T22:00",
            "source": "DWD",
        },
    }
    message = render.render_notification(item, secrets=[], mention=render.mention_for(item))
    assert message.content == "<@1001>" and message.embed["color"] == render.COLORS["alert"]
    assert message.embed["fields"][0] == {
        "name": "Was tun?",
        "value": "Gegenstände sichern",
        "inline": False,
    }
    assert message.embed["footer"]["text"] == "DWD"
    extreme = render.render_notification(
        {**item, "payload": {**item["payload"], "level": 4}}, secrets=[]
    )
    assert extreme.embed["color"] == render.COLORS["violet"]


def test_reminders_and_briefings_are_cards():
    item = {
        "kind": "reminder",
        "user_id": "1001",
        "payload": {"title": "Erinnerung", "text": "an den Zahnarzt", "mention": "1001"},
    }
    message = render.render_notification(
        item, secrets=["geheim12345"], mention=render.mention_for(item)
    )
    assert (
        message.embed["title"] == "Erinnerung" and message.embed["description"] == "an den Zahnarzt"
    )
    assert render.mention_for({"payload": {}, "user_id": None}) is None
    assert render.mention_for({"payload": {"mention": "abc"}, "user_id": "5"}) is None


def test_random_import_is_deterministic():
    assert random.Random(5).random() == random.Random(5).random()


def test_a_saying_with_a_control_character_is_refused_and_a_broken_file_stops_nothing(tmp_path):
    import asyncio

    from moritz_agent.discord.presence import LOCAL_FILE, ActivityManager

    async def nothing(*args):
        return {}

    manager = ActivityManager(
        ROOT, tmp_path, lambda: Settings().discord, lambda: "Europe/Berlin", nothing, nothing
    )
    for bad in ("Spielt\x7fVerstecken", "Spielt\x85Fangen", "Tab\tweg"):
        assert "Steuerzeichen" in (manager.suggest("playing", bad) or "")
    assert manager.suggest("playing", 'Backslash \\ und "Zitat"') is None
    assert manager.picker() is not None  # what was written is valid TOML
    local = tmp_path / LOCAL_FILE
    local.write_text('[[base]]\nkind = "playing"\ntext = "kaputt\x7f"\n', encoding="utf-8")
    manager.reload()
    assert manager.picker().pick({}, noon()).text  # the shipped list keeps the rotation going
    assert asyncio.run(manager.change()) is not None
    assert "kaputt" in (manager.suggest("playing", "noch einer") or "")  # no overwrite, a hint
    assert "kaputt" in local.read_text(encoding="utf-8")


def test_the_owner_of_the_bot_application_is_always_owner():
    from moritz_agent.config.settings import Discord
    from moritz_agent.core.principal import Role, discord_role, owner_ids, remember_app_owners

    cfg = Discord(owner_user_ids=[])
    try:
        assert discord_role(cfg, "424242424242") is Role.UNKNOWN
        remember_app_owners(["424242424242"])
        assert discord_role(cfg, "424242424242") is Role.OWNER
        assert owner_ids(Discord(owner_user_ids=["1111"])) == ["1111", "424242424242"]
    finally:
        remember_app_owners([])


def test_activities_carry_their_verb_because_discord_only_shows_the_text():
    from moritz_agent.discord.activities import Activity, load

    assert Activity("playing", "im Regen").status == "Spielt im Regen"
    assert Activity("listening", "Ebbelwoi-Lofi").status == "Hört Ebbelwoi-Lofi"
    assert Activity("watching", ", ob der Toast schon fertig ist").status.startswith("Schaut, ob")
    assert (
        Activity("custom", "🧦 Sucht die zweite Socke").status == "Sucht die zweite Socke"
    )  # no emoji
    from moritz_agent.config.settings import REPO_ROOT

    for entry in load(REPO_ROOT)["base"]:
        status = Activity(entry["kind"], entry["text"]).status
        assert len(status) <= 128 and "  " not in status, status

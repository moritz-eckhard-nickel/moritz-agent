# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The discord.py side without Discord: conversions, command tree, senders, worker steps (P1-33, P1-43).

discord.py objects are real where they are plain data (embeds, views, the command tree) and mocks
with the right class where they would need a connection (messages, channels, interactions).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import httpx

from moritz_agent.core.principal import Role
from moritz_agent.core.scheduler import Scheduler  # noqa: F401  (the planner fills the outbox)
from moritz_agent.discord import components, setup
from moritz_agent.discord.client import (
    AntonClient,
    InteractionSender,
    MessageSender,
    kwargs_for,
    only_asker,
    view_for,
)
from moritz_agent.discord.commands import register
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.dispatch import NEEDS_PIN
from moritz_agent.discord.render import Button, OutMessage, Select
from moritz_agent.discord.status import read_status, write_status
from moritz_agent.discord.worker import DiscordWorker, WorkerOptions

from .discord_util import GUILD_ID
from .system_util import (
    ADMIN_PIN,
    BOT_TOKEN,
    CHANNEL_ID,
    OWNER_ID,
    ROOT,
    STRANGER_ID,
    running_system,
)


# -- OutMessage → discord.py -----------------------------------------------------------------------------------
def test_buttons_menus_and_embeds_become_discord_components():
    out = OutMessage(
        content="Hallo",
        embed={
            "title": "Wetter",
            "description": "sonnig",
            "color": 0x3498DB,
            "fields": [],
            "footer": {"text": "Open-Meteo"},
        },
        buttons=[
            Button("Morgen", components.encode_action("1001", "und morgen?")),
            Button("Quelle", style="link", url="https://open-meteo.com"),
            Button("Ja", components.encode_confirm("reload", "ab12", "ok"), "danger"),
        ],
    )
    view = view_for(out)
    assert view is not None and view.timeout is None
    labels = [item.label for item in view.children]
    assert labels == ["Morgen", "Quelle", "Ja"]
    assert view.children[1].url == "https://open-meteo.com" and view.children[1].custom_id is None
    assert view.children[2].style is discord.ButtonStyle.danger
    kwargs = kwargs_for(out)
    assert kwargs["content"] == "Hallo" and kwargs["embed"].title == "Wetter"
    assert (kwargs["embed"].footer.text == "Open-Meteo" and kwargs["view"] is view) or kwargs[
        "view"
    ]


def test_a_menu_carries_the_position_and_the_name_of_each_choice():
    out = OutMessage(
        content="Welches?",
        select=Select(
            "Welches meinst du?",
            components.encode_pick("1001"),
            ["Neustadt in Hessen", "Neustadt an der Weinstraße"],
        ),
    )
    menu = view_for(out).children[0]
    assert [(o.label, o.value) for o in menu.options] == [
        ("Neustadt in Hessen", "1:Neustadt in Hessen"),
        ("Neustadt an der Weinstraße", "2:Neustadt an der Weinstraße"),
    ]
    assert menu.custom_id == "c:1001"


def test_editing_clears_what_is_gone_and_a_file_travels_along():
    plain = kwargs_for(OutMessage(content="nur Text"), edit=True)
    assert plain["embed"] is None and plain["view"] is None and plain["content"] == "nur Text"
    sending = kwargs_for(OutMessage(content="x", file=("antwort.md", b"# Antwort")))
    assert sending["file"].filename == "antwort.md" and "embed" not in sending
    editing = kwargs_for(OutMessage(content="x", file=("antwort.md", b"# Antwort")), edit=True)
    assert editing["attachments"][0].filename == "antwort.md"
    assert kwargs_for(OutMessage()).get("content") is None or "content" not in kwargs_for(
        OutMessage()
    )


def test_mentions_are_limited_to_the_asker():
    mentions = only_asker(discord.Object(7))
    assert not mentions.everyone and not mentions.roles and [u.id for u in mentions.users] == [7]
    assert only_asker(None).users is False


# -- the command tree ----------------------------------------------------------------------------------------
def build_tree(**changes):
    from moritz_agent.config.settings import Settings

    settings = Settings()
    settings.skills.notes.enabled = changes.get("notes", True)
    features = commands.Features.from_settings(
        settings, voice=changes.get("voice", True), speech=True
    )
    client = discord.Client(intents=discord.Intents.none())
    tree = discord.app_commands.CommandTree(client)

    async def bridge(interaction, spec, values):
        return None

    async def menu(interaction, name, message):
        return None

    async def suggest(interaction, current):
        return []

    return register.build(tree, features, bridge, menu, suggest), tree


def test_the_whole_table_becomes_valid_discord_commands():
    payloads, _ = build_tree()
    names = {p["name"]: p for p in payloads}
    assert {
        "frag",
        "wetter",
        "abo",
        "hilfe",
        "admin",
        "joinvc",
        "Anton fragen",
        "Vorlesen",
    } <= set(names)
    assert len(payloads) <= 100
    wetter = {o["name"]: o for o in names["wetter"]["options"]}
    assert wetter["ort"]["autocomplete"] is True and len(wetter["wann"]["choices"]) == 4
    assert [o["name"] for o in names["admin"]["options"]] == [
        "status",
        "version",
        "logs",
        "neu-laden",
        "wartung",
        "neustart",
    ]
    # required options come first, choices keep their values, ranges are carried over
    abo = names["abo"]["options"]
    assert [o["name"] for o in abo] == ["was", "einstellung"] and all(o["required"] for o in abo)
    zahlen = {o["name"]: o for o in names["wuerfel"]["options"]}
    assert zahlen["anzahl"]["min_value"] == 1 and zahlen["seiten"]["max_value"] == 1000
    assert names["joinvc"]["options"][0]["channel_types"] == [2]


def test_contexts_follow_the_matrix_of_the_plan():
    payloads, _ = build_tree()
    names = {p["name"]: p for p in payloads}
    # contexts: 0 = server, 1 = direct message with the bot, 2 = other chats (user app)
    assert names["wetter"]["contexts"] == [0, 1, 2] and names["wetter"]["integration_types"] == [
        0,
        1,
    ]
    assert names["admin"]["contexts"] == [1] and names["admin"]["integration_types"] == [0]
    assert names["joinvc"]["contexts"] == [0] and names["notiz"]["contexts"] == [
        0,
        1,
        2,
    ]  # a user app also shows up in servers


def test_inactive_functions_are_not_registered_and_the_fingerprint_follows():
    full, _ = build_tree()
    less, _ = build_tree(notes=False, voice=False)
    gone = {p["name"] for p in full} - {p["name"] for p in less}
    assert gone == {"notiz", "einkauf", "joinvc", "leavevc"}
    again, _ = build_tree()
    assert commands.digest(full) == commands.digest(again) != commands.digest(less)


# -- the senders ---------------------------------------------------------------------------------------------------
def fake_message(*, guild: bool = True, author: int = 1001, channel_id: int = 55, **extra):
    message = MagicMock(spec=discord.Message)
    message.id = 424242
    message.author = MagicMock(spec=discord.User)
    message.author.id = author
    message.author.bot = False
    message.author.display_name = "Moritz"
    message.guild = SimpleNamespace(id=int(GUILD_ID)) if guild else None
    message.channel = MagicMock(spec=discord.TextChannel if guild else discord.DMChannel)
    message.channel.id = channel_id
    message.channel.send = AsyncMock(return_value=SimpleNamespace(id=777))
    message.reply = AsyncMock(return_value=SimpleNamespace(id=778))
    message.add_reaction = AsyncMock()
    message.mentions = []
    message.reference = None
    message.content = "Hallo"
    message.attachments = []
    message.flags = discord.MessageFlags._from_value(0)
    for key, value in extra.items():
        setattr(message, key, value)
    return message


def test_a_message_sender_replies_in_servers_and_writes_plainly_in_direct_chats():
    async def go():
        server = fake_message()
        sender = MessageSender(server)
        await sender.send(OutMessage(content="Eins"))
        await sender.send(OutMessage(content="Zwei"))
        direct = fake_message(guild=False)
        await MessageSender(direct).send(OutMessage(content="Hi"))
        await sender.react("✅")
        return server, sender, direct

    server, sender, direct = asyncio.run(go())
    server.reply.assert_awaited_once()
    assert server.reply.await_args.kwargs["mention_author"] is False
    assert server.channel.send.await_count == 1  # the second message is a plain one in the channel
    assert server.reply.await_args.kwargs["allowed_mentions"].users[0].id == 1001
    direct.channel.send.assert_awaited_once()
    server.add_reaction.assert_awaited_with("✅")
    assert sender.ids == [778, 777]


def test_an_interaction_sender_defers_once_and_answers_privately_when_asked():
    async def go():
        interaction = MagicMock(spec=discord.Interaction)
        interaction.type = discord.InteractionType.application_command
        interaction.user = SimpleNamespace(id=1001)
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(side_effect=[False, True, True])
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock(return_value=SimpleNamespace(id=9))
        sender = InteractionSender(interaction, True)
        await sender.begin()
        await sender.send(OutMessage(content="geheim"))
        async with sender.typing():
            pass
        return interaction, sender

    interaction, sender = asyncio.run(go())
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["ephemeral"] is True and kwargs["wait"] is True and kwargs["content"] == "geheim"
    assert sender.ids == [9]


# -- the client: who asks from where ------------------------------------------------------------------------------------
class Wired:
    """A worker around the real main process with a client that has never connected."""

    def __init__(self, system, tmp_path):
        self.worker = DiscordWorker(
            WorkerOptions(
                config=system.tree / "config" / "moritz-agent.toml",
                passwords=system.tree / "passwords.txt",
                state_root=system.tree,
            ),
            ROOT,
            core=None,
        )


def wired(tmp_path, body):
    async def go():
        async with running_system(tmp_path, discord=True, notes=True) as system:
            worker = DiscordWorker(
                WorkerOptions(
                    config=system.tree / "config" / "moritz-agent.toml",
                    passwords=system.tree / "passwords.txt",
                    state_root=system.tree,
                ),
                ROOT,
                core=None,
            )
            from moritz_agent.discord.core import CoreApi

            worker.config.load()
            worker.core = CoreApi(
                "http://testserver",
                system.ctx.internal_token,
                transport=httpx.ASGITransport(app=system.internal_app, client=("127.0.0.1", 1)),
            )
            worker._build()
            worker.policy.bot_id = "5000"
            worker.policy.default_guild_id = GUILD_ID
            client = AntonClient(worker)
            client._connection.user = SimpleNamespace(id=5000, name="Anton")
            worker.client = client
            return await body(system, worker, client)

    return asyncio.run(go())


def test_the_origin_distinguishes_our_server_direct_chats_and_foreign_places(tmp_path):
    async def body(system, worker, client):
        mine = client.origin_of(fake_message())
        direct = client.origin_of(fake_message(guild=False))
        foreign_message = fake_message()
        foreign_message.guild = SimpleNamespace(id=9999)
        foreign = client.origin_of(foreign_message)
        thread = fake_message()
        thread.channel = MagicMock(spec=discord.Thread)
        thread.channel.id = 66
        in_thread = client.origin_of(thread)
        return mine, direct, foreign, in_thread

    mine, direct, foreign, in_thread = wired(tmp_path, body)
    assert (mine.where, mine.place, mine.conversation) == ("S", "guild", "discord:ch:55")
    assert (direct.where, direct.place, direct.conversation) == ("DM", "dm", "discord:dm:1001")
    assert (
        foreign.where == "U" and foreign.foreign and foreign.reply_target(CHANNEL_ID) == "dm:1001"
    )
    assert in_thread.place == "thread" and in_thread.conversation == "discord:th:66"
    assert mine.message_id == 424242 and mine.name == "Moritz"


def interaction_origin(channel: dict | None, context: int | None):
    """The origin of a real ``discord.Interaction`` built from a gateway payload."""
    from moritz_agent.config.settings import Settings
    from moritz_agent.discord.access import AccessPolicy

    async def go():
        cfg = Settings().discord.model_copy(update={"owner_user_ids": [OWNER_ID]})
        policy = AccessPolicy(cfg, default_channel_id=CHANNEL_ID, default_guild_id=GUILD_ID)
        policy.bot_id = "5000"
        client = AntonClient(SimpleNamespace(policy=policy, voice_messages=None))
        bot = {"id": "5000", "username": "Anton", "discriminator": "0", "avatar": None}
        client._connection.user = discord.ClientUser(state=client._connection, data=bot)
        user = {"id": OWNER_ID, "username": "moritz", "discriminator": "0", "avatar": None}
        data = {
            "id": "1",
            "type": 2,
            "token": "t",
            "version": 1,
            "application_id": "5000",
            "attachment_size_limit": 8_000_000,
            "channel_id": "900",
            "data": {"id": "2", "name": "admin", "type": 1},
        }
        if channel is not None:
            data["channel"] = channel
        if context is not None:
            data["context"] = context
        data["user"] = user
        origin = client.origin_of(discord.Interaction(data=data, state=client._connection))
        spec = commands.find("status", "admin")
        assert spec is not None
        return origin, policy.command_allowed(OWNER_ID, spec.rule, origin.where)

    return asyncio.run(go())


def test_an_interaction_in_the_bot_dm_is_a_direct_chat_and_allows_admin():
    owner = {"id": OWNER_ID, "username": "moritz", "discriminator": "0", "avatar": None}
    friend = {"id": "4242", "username": "freund", "discriminator": "0", "avatar": None}
    for channel in ({"id": "900", "type": 1, "recipients": [owner]}, {"id": "900", "type": 1}):
        origin, admin = interaction_origin(channel, context=1)
        assert origin.where == "DM" and not origin.foreign and admin
        assert origin.conversation == f"discord:dm:{OWNER_ID}"
    # through the user installation in somebody else's DM or a group: a foreign place
    origin, admin = interaction_origin({"id": "901", "type": 1, "recipients": [friend]}, context=2)
    assert origin.where == "U" and origin.foreign and not admin
    origin, _ = interaction_origin({"id": "902", "type": 3, "recipients": [friend]}, context=2)
    assert origin.where == "U"
    # older payloads without a context: the recipients decide
    origin, _ = interaction_origin({"id": "900", "type": 1, "recipients": [owner]}, context=None)
    assert origin.where == "DM"
    origin, _ = interaction_origin({"id": "901", "type": 1, "recipients": [friend]}, context=None)
    assert origin.where == "U"


def test_the_message_info_knows_mentions_replies_and_own_threads(tmp_path):
    async def body(system, worker, client):
        plain = client.info_of(fake_message())
        mention = client.info_of(fake_message(mentions=[SimpleNamespace(id=5000)]))
        original = MagicMock(spec=discord.Message)
        original.author = SimpleNamespace(id=5000)
        reply = client.info_of(fake_message(reference=SimpleNamespace(resolved=original)))
        thread = fake_message()
        thread.channel = MagicMock(spec=discord.Thread)
        thread.channel.id = 66
        thread.channel.owner_id = 5000
        own_thread = client.info_of(thread)
        return plain, mention, reply, own_thread

    plain, mention, reply, own_thread = wired(tmp_path, body)
    assert not (plain.mentions_bot or plain.replies_to_bot or plain.in_bot_thread)
    assert mention.mentions_bot and reply.replies_to_bot and own_thread.in_bot_thread
    assert plain.guild_id == GUILD_ID and plain.channel_id == "55" and plain.author_id == "1001"


def test_a_message_is_answered_end_to_end_through_the_client(tmp_path):
    async def body(system, worker, client):
        home = home_channel()
        worker.default_channel = home
        message = fake_message(content="Wie spät ist es?", channel_id=int(CHANNEL_ID))
        await client._on_message(message)
        stranger = fake_message(
            author=int(STRANGER_ID), content="Wie spät ist es?", channel_id=int(CHANNEL_ID)
        )
        await client._on_message(stranger)
        await client._on_message(stranger)
        return message, stranger, home

    message, stranger, home = wired(tmp_path, body)
    message.channel.send.assert_not_awaited()  # it is a reply in the server
    sent = message.reply.await_args.kwargs
    assert "19 Uhr 12" in sent["content"]
    stranger.reply.assert_not_awaited()  # no answer for strangers …
    assert home.send.await_count == 1  # … but the home channel hears about them once
    assert "jemand Neues" in home.send.await_args.kwargs["content"]


def test_a_pin_button_opens_the_dialog_as_the_first_answer(tmp_path):
    async def body(system, worker, client):
        asked = MagicMock()
        asked.type = discord.InteractionType.component
        from .discord_util import Recorder

        recorder = Recorder()
        spec = commands.find("neustart", "admin")
        origin = client.origin_of(fake_message(guild=False))
        await worker.dispatcher.command(spec, {}, origin, recorder)
        custom_id = recorder.sent[0].buttons[0].custom_id

        interaction = MagicMock(spec=discord.Interaction)
        interaction.type = discord.InteractionType.component
        interaction.data = {"custom_id": custom_id}
        interaction.user = SimpleNamespace(id=int(OWNER_ID), display_name="Moritz")
        interaction.guild_id = None
        interaction.channel = None
        interaction.channel_id = 7
        interaction.id = 5
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.send_modal = AsyncMock()
        interaction.response.defer = AsyncMock()
        await client.on_interaction(interaction)
        return interaction, NEEDS_PIN

    interaction, _ = wired(tmp_path, body)
    interaction.response.send_modal.assert_awaited_once()
    interaction.response.defer.assert_not_awaited()
    assert interaction.response.send_modal.await_args.args[0].title == "Bitte bestätigen"


def test_foreign_buttons_and_other_apps_interactions_are_left_alone(tmp_path):
    async def body(system, worker, client):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.type = discord.InteractionType.component
        interaction.data = {"custom_id": "not-ours"}
        interaction.response = MagicMock()
        interaction.response.defer = AsyncMock()
        await client.on_interaction(interaction)
        return interaction

    assert not wired(tmp_path, body).response.defer.await_count


def test_reactions_count_as_feedback_only_on_answers_anton_gave(tmp_path):
    async def body(system, worker, client):
        await client._on_message(
            fake_message(content="Wie spät ist es?", channel_id=int(CHANNEL_ID))
        )
        message_id = next(iter(worker.dispatcher.skill_of), None)
        payload = SimpleNamespace(user_id=1001, message_id=message_id or 0, emoji="👍")
        await client.on_raw_reaction_add(payload)
        await client.on_raw_reaction_add(
            SimpleNamespace(user_id=1001, message_id=12345, emoji="👍")
        )
        await client.on_raw_reaction_add(
            SimpleNamespace(user_id=5000, message_id=message_id, emoji="👍")
        )
        store = system.runtime.discord_store
        return message_id, store.state("feedback:time.now:up")

    message_id, counted = wired(tmp_path, body)
    assert message_id == 778 and counted == "1"


def test_place_suggestions_come_from_the_gazetteer_and_not_for_strangers(tmp_path):
    async def body(system, worker, client):
        known = SimpleNamespace(user=SimpleNamespace(id=1001))
        stranger = SimpleNamespace(user=SimpleNamespace(id=int(STRANGER_ID)))
        return (
            await client.suggest_places(known, "Weilb"),
            await client.suggest_places(known, "W"),
            await client.suggest_places(stranger, "Weilb"),
        )

    found, short, nobody = wired(tmp_path, body)
    assert found and found[0].name.startswith("Weilburg") and "35781" in found[0].name
    assert short == [] and nobody == []


# -- the worker --------------------------------------------------------------------------------------------------------------
def stub_client(channel, guilds=(), ready=True):
    user = AsyncMock()
    client = MagicMock()
    client.user = SimpleNamespace(id=5000, name="Anton")
    client.application_id = 7000
    client.guilds = list(guilds)
    client.is_ready = MagicMock(return_value=ready)
    client.latency = 0.041
    client.get_channel = MagicMock(return_value=channel)
    client.fetch_channel = AsyncMock(return_value=channel)
    client.fetch_user = AsyncMock(return_value=user)
    client.close = AsyncMock()
    client.show = AsyncMock()
    client.build_commands = MagicMock(return_value=[{"name": "frag"}])
    client.tree = SimpleNamespace(sync=AsyncMock())
    client.user_stub = user
    return client


def home_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.guild = SimpleNamespace(id=int(GUILD_ID))
    channel.send = AsyncMock()
    return channel


def test_ready_finds_the_home_channel_greets_once_and_leaves_foreign_servers(tmp_path):
    async def body(system, worker, client):
        channel = home_channel()
        foreign = MagicMock(spec=discord.Guild)
        foreign.id, foreign.name, foreign.leave = 9999, "Fremd", AsyncMock()
        mine = MagicMock(spec=discord.Guild)
        mine.id, mine.leave = int(GUILD_ID), AsyncMock()
        stub = stub_client(channel, [mine, foreign])
        worker.policy.default_guild_id = ""
        await worker.ready(stub)
        await worker.ready(stub)
        return worker, channel, foreign, mine

    worker, channel, foreign, mine = wired(tmp_path, body)
    assert worker.state == "ready" and worker.policy.default_guild_id == GUILD_ID
    foreign.leave.assert_awaited()
    mine.leave.assert_not_awaited()
    texts = [call.kwargs.get("content", "") for call in channel.send.await_args_list]
    assert sum("wach" in t or "da bin ich" in t or "startklar" in t for t in texts) == 1
    assert any("fremden Server" in t and "Fremd" in t for t in texts)


def test_the_startup_message_can_be_switched_off_and_waits_for_maintenance(tmp_path):
    async def body(system, worker, client):
        channel = home_channel()
        worker.config.settings.discord.startup_message = False
        await worker.ready(stub_client(channel))
        return channel

    channel = wired(tmp_path, body)
    channel.send.assert_not_awaited()


def test_without_a_home_channel_notes_go_to_the_owner_as_a_direct_message(tmp_path):
    async def body(system, worker, client):
        stub = stub_client(None)
        stub.get_channel.return_value = None
        stub.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x"))
        await worker.ready(stub)
        return worker, stub

    worker, stub = wired(tmp_path, body)
    assert worker.default_channel is None and worker.status_payload()["default_channel"] == "fehlt"
    stub.fetch_user.assert_awaited_with(int(OWNER_ID))
    stub.user_stub.send.assert_awaited()


def test_commands_are_registered_only_when_they_changed(tmp_path):
    async def body(system, worker, client):
        stub = stub_client(home_channel())
        first = await worker.sync_commands(stub)
        second = await worker.sync_commands(stub)
        stub.build_commands.return_value = [{"name": "frag"}, {"name": "wetter"}]
        third = await worker.sync_commands(stub)
        forced = await worker.sync_commands(stub, force=True)
        stub.tree.sync.side_effect = discord.HTTPException(
            MagicMock(status=429, reason="x"), "slow"
        )
        stub.build_commands.return_value = [{"name": "other"}]
        failed = await worker.sync_commands(stub)
        return first, second, third, forced, failed, stub.tree.sync.await_count

    assert wired(tmp_path, body) == (True, False, True, True, False, 4)


def test_the_outbox_is_delivered_with_a_mention_of_the_person_only(tmp_path):
    async def body(system, worker, client):
        channel = home_channel()
        stub = stub_client(channel)
        worker.client = stub
        worker.default_channel = channel
        store = system.runtime.discord_store
        store.enqueue(
            "reminder",
            "default",
            {"title": "⏰ Erinnerung", "text": "Zahnarzt", "mention": OWNER_ID},
            user_id=OWNER_ID,
        )
        store.enqueue(
            "reminder",
            f"dm:{OWNER_ID}",
            {"title": "⏰ Erinnerung", "text": "Privat"},
            user_id=OWNER_ID,
        )
        store.enqueue(
            "warning",
            "default",
            {"title": "⚠️ Unwetter", "text": "Sturm", "level": 3, "source": "DWD"},
            user_id=OWNER_ID,
            serious=True,
        )
        sent = await worker.pump_once()
        again = await worker.pump_once()
        return sent, again, channel, stub

    sent, again, channel, stub = wired(tmp_path, body)
    assert sent == 3 and again == 0
    first = channel.send.await_args_list[0].kwargs
    assert first["content"] == f"<@{OWNER_ID}>" and first["embed"].description == "Zahnarzt"
    assert first["allowed_mentions"].everyone is False and first["allowed_mentions"].users[
        0
    ].id == int(OWNER_ID)
    assert channel.send.await_args_list[1].kwargs["embed"].title == "Unwetter"  # emoji filtered
    assert stub.user_stub.send.await_args.kwargs["embed"].description == "Privat"


def test_a_message_that_cannot_be_delivered_is_tried_again_later(tmp_path):
    async def body(system, worker, client):
        channel = home_channel()
        channel.send.side_effect = discord.Forbidden(MagicMock(status=403, reason="x"), "no")
        worker.client, worker.default_channel = stub_client(channel), channel
        store = system.runtime.discord_store
        store.enqueue(
            "system", "default", {"title": "🔧 Hinweis", "text": "Telefon weg"}, user_id=OWNER_ID
        )
        failed = await worker.pump_once()
        channel.send.side_effect = None
        at_once = await worker.pump_once()  # not again within seconds: it waits a little
        system.runtime.svc.clock.advance(seconds=30)
        later = await worker.pump_once()
        return failed, at_once, later

    assert wired(tmp_path, body) == (0, 0, 1)


def test_a_closed_dm_goes_to_the_home_channel_with_a_mention(tmp_path):
    async def body(system, worker, client):
        channel = home_channel()
        stub = stub_client(channel)
        stub.user_stub.send.side_effect = discord.Forbidden(
            MagicMock(status=403, reason="x"), "Cannot send messages to this user"
        )
        worker.client, worker.default_channel = stub, channel
        system.runtime.discord_store.enqueue(
            "reminder",
            f"dm:{OWNER_ID}",
            {"title": "⏰ Erinnerung", "text": "Privat"},
            user_id=OWNER_ID,
        )
        return await worker.pump_once(), channel

    sent, channel = wired(tmp_path, body)
    assert sent == 1
    kwargs = channel.send.await_args.kwargs
    assert kwargs["content"] == f"<@{OWNER_ID}>" and kwargs["embed"].description == "Privat"
    assert kwargs["allowed_mentions"].everyone is False


def test_a_network_error_neither_kills_the_outbox_pump_nor_loses_the_message(tmp_path, monkeypatch):
    import aiohttp

    from moritz_agent.discord import worker as worker_module

    async def body(system, worker, client):
        channel = home_channel()
        channel.send.side_effect = aiohttp.ClientOSError(110, "Connection timed out")
        worker.client, worker.default_channel = stub_client(channel), channel
        store = system.runtime.discord_store
        store.enqueue("system", "default", {"title": "🔧 Hinweis", "text": "x"}, user_id=OWNER_ID)
        assert await worker.pump_once() == 0  # a failure, not an exception
        (row,) = store.db.query("SELECT attempts FROM outbox")
        assert row["attempts"] == 1
        # and even an unexpected error inside the loop does not end it
        calls = 0

        async def flaky():
            nonlocal calls
            calls += 1
            raise ConnectionResetError("gone")

        monkeypatch.setattr(worker, "pump_once", flaky)
        monkeypatch.setattr(worker_module, "OUTBOX_EVERY_S", 0.001)
        task = asyncio.ensure_future(worker._outbox_pump())
        await asyncio.sleep(0.05)
        alive = not task.done()
        task.cancel()
        return alive, calls

    alive, calls = wired(tmp_path, body)
    assert alive and calls > 3


def test_notes_into_the_home_channel_never_ping_anybody(tmp_path):
    async def body(system, worker, client):
        channel = home_channel()
        worker.default_channel = channel
        foreign = MagicMock(spec=discord.Guild)
        foreign.id, foreign.name, foreign.leave = 9999, "@everyone", AsyncMock()
        await worker.guild_joined(stub_client(channel), foreign)
        return channel

    channel = wired(tmp_path, body)
    mentions = channel.send.await_args.kwargs["allowed_mentions"]
    assert mentions.everyone is False and mentions.roles is False and mentions.users is False
    client_default = AntonClient(SimpleNamespace(voice_messages=None)).allowed_mentions
    assert client_default.everyone is False and client_default.roles is False


def test_the_status_file_has_no_token_and_no_content(tmp_path):
    async def body(system, worker, client):
        worker.client = stub_client(home_channel())
        worker.state = "ready"
        worker.default_channel = home_channel()
        write_status(system.tree, worker.status_payload())
        return read_status(system.tree), (
            system.tree / "data" / "run" / "discord-status.json"
        ).read_text()

    status, raw = wired(tmp_path, body)
    assert status["state"] == "ready" and status["latency_ms"] == 41 and status["guilds"] == 0
    assert BOT_TOKEN not in raw and ADMIN_PIN not in raw and "Moritz" not in raw


def test_a_stale_or_stopped_status_means_no_worker(tmp_path):
    write_status(tmp_path, {"state": "stopped"})
    assert read_status(tmp_path) is None
    path = tmp_path / "data" / "run" / "discord-status.json"
    path.write_text(json.dumps({"state": "ready", "updated": 1.0}))
    assert read_status(tmp_path) is None


def test_a_reload_with_a_new_token_reconnects_and_applies_the_new_rules(tmp_path):
    async def body(system, worker, client):
        stub = stub_client(home_channel())
        worker.client = stub
        before_styler = worker.dispatcher.styler.style
        text = (system.tree / "passwords.txt").read_text()
        (system.tree / "passwords.txt").write_text(text.replace(BOT_TOKEN, BOT_TOKEN + "-new"))
        toml = system.tree / "config" / "moritz-agent.toml"
        toml.write_text(toml.read_text().replace('style = "cute"', 'style = "normal"'))
        await worker.reload()
        return before_styler, worker.dispatcher.styler.style, stub

    before, after, stub = wired(tmp_path, body)
    assert (before, after) == ("cute", "normal")
    stub.close.assert_awaited()


def test_a_broken_file_on_reload_keeps_the_old_rules(tmp_path):
    async def body(system, worker, client):
        stub = stub_client(home_channel())
        worker.client = stub
        (system.tree / "passwords.txt").write_text("[discord]\nbot_token = a b\n")
        await worker.reload()
        return stub, worker.config.passwords.discord.bot_token.reveal()

    stub, token = wired(tmp_path, body)
    stub.close.assert_not_awaited()
    assert token == BOT_TOKEN


def test_roles_come_from_the_lists_in_the_configuration(tmp_path):
    async def body(system, worker, client):
        return [worker.policy.role(i) for i in (OWNER_ID, "1002", STRANGER_ID)]

    assert wired(tmp_path, body) == [Role.OWNER, Role.TRUSTED, Role.UNKNOWN]


# -- setup (REST, no gateway) ---------------------------------------------------------------------------------------------------
def rest(handler):
    return httpx.MockTransport(handler)


def test_the_permission_number_is_the_one_of_the_plan_and_has_no_admin_right():
    assert setup.permissions_value() == 70678018640960
    permissions = discord.Permissions(setup.permissions_value())
    assert (
        not permissions.administrator
        and not permissions.manage_guild
        and not permissions.mention_everyone
    )
    assert (
        permissions.send_voice_messages
        and permissions.connect
        and permissions.create_public_threads
    )


def test_invite_links_for_server_and_user_installation():
    server, user = setup.invite_links(7000)
    assert "client_id=7000" in server and "permissions=70678018640960" in server
    assert "scope=bot+applications.commands" in server
    assert "integration_type=1" in user and "scope=applications.commands" in user


def good_api(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == f"Bot {BOT_TOKEN}"
    path = request.url.path
    if path.endswith("/users/@me"):
        return httpx.Response(200, json={"id": "7000", "username": "Anton"})
    if path.endswith("/applications/@me"):
        return httpx.Response(
            200,
            json={"id": "7000", "bot_public": False, "flags": 1 << 19, "owner": {"id": OWNER_ID}},
        )
    if path.endswith("/users/@me/guilds"):
        return httpx.Response(200, json=[{"id": GUILD_ID, "name": "Zuhause"}])
    if path.endswith(f"/channels/{CHANNEL_ID}"):
        return httpx.Response(
            200, json={"id": CHANNEL_ID, "type": 0, "name": "anton", "guild_id": GUILD_ID}
        )
    return httpx.Response(404)


def test_the_check_reports_in_plain_words_and_never_the_token():
    report = asyncio.run(setup.check(BOT_TOKEN, CHANNEL_ID, [OWNER_ID], transport=rest(good_api)))
    assert report.ok and report.owner_ids == [OWNER_ID] and report.application_id == "7000"
    text = "\n".join(c.text for c in report.checks)
    assert "Anton" in text and "Public Bot“ ist aus" in text and "#anton" in text
    assert BOT_TOKEN not in text


def test_the_check_warns_about_public_bots_and_stops_on_a_bad_token():
    def public(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/applications/@me"):
            return httpx.Response(200, json={"id": "7000", "bot_public": True, "flags": 0})
        return good_api(request)

    report = asyncio.run(setup.check(BOT_TOKEN, CHANNEL_ID, [], transport=rest(public)))
    levels = {c.level for c in report.checks}
    text = "\n".join(c.text for c in report.checks)
    assert (
        not report.ok and "Public Bot“ ist an" in text and "Message Content Intent ist aus" in text
    )
    assert "error" in levels and "warn" in levels

    refused = asyncio.run(setup.check(BOT_TOKEN, transport=rest(lambda r: httpx.Response(401))))
    assert [c.text for c in refused.checks] == ["Der Bot-Token wurde abgelehnt"]


def test_the_check_finds_a_channel_on_a_server_anton_is_not_on():
    def elsewhere(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/channels/{CHANNEL_ID}"):
            return httpx.Response(
                200, json={"id": CHANNEL_ID, "type": 0, "name": "x", "guild_id": "1"}
            )
        return good_api(request)

    report = asyncio.run(setup.check(BOT_TOKEN, CHANNEL_ID, [OWNER_ID], transport=rest(elsewhere)))
    assert not report.ok and any("nicht ist" in c.text for c in report.checks)


def test_team_applications_name_all_members_as_owner_candidates():
    team = {
        "team": {
            "members": [
                {"user": {"id": "1"}, "membership_state": 2},
                {"user": {"id": "2"}, "membership_state": 1},  # invited, not yet a member
                {"user": {"id": "3"}, "membership_state": 2},
            ]
        }
    }
    assert setup.owner_ids_of(team) == ["1", "3"]
    assert setup.owner_ids_of({"owner": {"id": 9}}) == ["9"] and setup.owner_ids_of({}) == []


def test_say_and_channel_list_use_the_rest_api_without_pinging_anybody():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "1"})
        return httpx.Response(
            200,
            json=[
                {"id": "5", "type": 2, "name": "Sprache", "position": 0},
                {"id": "4", "type": 0, "name": "anton", "position": 1},
                {"id": "3", "type": 0, "name": "allgemein", "position": 0},
            ],
        )

    async def go():
        async with setup.DiscordRest(BOT_TOKEN, transport=rest(handler)) as client:
            await client.say(CHANNEL_ID, "Guude! @everyone")
            return await client.text_channels(GUILD_ID)

    channels = asyncio.run(go())
    assert seen["body"]["allowed_mentions"] == {"parse": []}
    assert [c["name"] for c in channels] == ["allgemein", "anton"]


def test_errors_of_the_api_never_contain_the_token():
    async def go():
        async with setup.DiscordRest(
            BOT_TOKEN, transport=rest(lambda r: httpx.Response(500))
        ) as client:
            try:
                await client.me()
            except setup.DiscordApiError as exc:
                return str(exc), exc.status

    text, status = asyncio.run(go())
    assert BOT_TOKEN not in text and status == 500


def test_the_command_line_has_all_commands():
    from moritz_agent.discord.__main__ import build_parser

    parser = build_parser()
    for argv in (
        ["run"],
        ["check"],
        ["invite"],
        ["channels"],
        ["sync-commands"],
        ["say", "hi"],
        ["profile"],
    ):
        assert parser.parse_args(argv).func


def test_sync_commands_registers_what_the_worker_would_and_remembers_it(tmp_path, monkeypatch):
    from discord import app_commands

    from moritz_agent.discord import core as core_module
    from moritz_agent.discord import worker as worker_module
    from moritz_agent.discord.speech import SpeechService
    from moritz_agent.storage import Database, DiscordStore

    from .system_util import make_tree

    tree = make_tree(tmp_path, discord=True)
    Database(tmp_path / "db.sqlite3").ensure()  # an installation that has run before
    monkeypatch.delenv(core_module.ENV_URL, raising=False)
    monkeypatch.setattr(SpeechService, "stt_available", lambda self: True)
    monkeypatch.setattr(AntonClient, "login", AsyncMock())
    monkeypatch.setattr(AntonClient, "close", AsyncMock())
    synced = AsyncMock(return_value=[])
    monkeypatch.setattr(app_commands.CommandTree, "sync", synced)
    built: list[list[dict]] = []
    original = AntonClient.build_commands

    def build(self, features):
        built.append(original(self, features))
        return built[-1]

    monkeypatch.setattr(AntonClient, "build_commands", build)
    options = WorkerOptions(
        config=tree / "config" / "moritz-agent.toml", passwords=tree / "passwords.txt"
    )
    assert asyncio.run(worker_module.sync_once(options, ROOT)) == 0
    synced.assert_awaited_once()
    names = {payload["name"] for payload in built[0]}
    assert {"joinvc", "leavevc", "Vorlesen"} <= names  # the voice parts are not forgotten
    stored = DiscordStore(Database(tmp_path / "db.sqlite3")).registered_hash()
    assert stored == commands.digest(built[0])  # the worker will not register a smaller set again


def test_reconnecting_the_latency_is_infinite_and_the_status_still_works(tmp_path):
    """Seen live (21.10.2026): ``round(inf * 1000)`` killed the heartbeat and the worker got restarted."""

    async def body(system, worker, client):
        worker.client = stub_client(home_channel())
        worker.state = "ready"
        worker.client.latency = float("inf")
        first = worker.status_payload()
        worker.client.latency = float("nan")
        return first, worker.status_payload()

    first, second = wired(tmp_path, body)
    assert first["latency_ms"] is None and second["latency_ms"] is None


def test_logging_in_for_sync_commands_needs_no_main_process(tmp_path):
    """Seen on Sophie-1: ``discord sync-commands`` crashed in setup_hook (no core to ask)."""
    from moritz_agent.discord.worker import DiscordWorker, WorkerOptions

    from .system_util import make_tree

    tree = make_tree(tmp_path, discord=True)
    worker = DiscordWorker(
        WorkerOptions(
            config=tree / "config" / "moritz-agent.toml", passwords=tree / "passwords.txt"
        )
    )
    client = MagicMock()
    asyncio.run(worker.setup(client))  # no AttributeError
    client.build_commands.assert_not_called()  # sync_once registers by itself

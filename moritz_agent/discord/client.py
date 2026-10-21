# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The only place that talks discord.py for text: events in, ``Sender``s out (docs/plan/14 §4.2).

Everything that decides something lives in ``dispatch.py``/``access.py``; this module translates
discord.py objects into plain data (``MessageInfo``, ``Origin``) and plain answers (``OutMessage``)
into messages, embeds, buttons and files. Mentions are limited to the asker (never @everyone).
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol

import discord
from discord import app_commands

from moritz_agent.core.principal import Role
from moritz_agent.discord import components
from moritz_agent.discord.access import MessageInfo
from moritz_agent.discord.activities import Activity
from moritz_agent.discord.commands import register
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.dispatch import NEEDS_PIN, Dispatcher, ephemeral_for
from moritz_agent.discord.render import OutMessage
from moritz_agent.discord.sender import Origin, Sender
from moritz_agent.logging_setup import get_logger

if TYPE_CHECKING:
    from moritz_agent.discord.worker import DiscordWorker

log = get_logger("discord")

BUTTON_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}
PIN_PREFIX = "p:"
REACTIONS = {"👍", "👎"}


class VoiceMessageHandler(Protocol):
    async def handle(self, message: discord.Message, origin: Origin, sender: Sender) -> bool: ...


# -- OutMessage → discord.py -----------------------------------------------------------------------------
def view_for(out: OutMessage) -> discord.ui.View | None:
    """Buttons and the menu of an answer. The presses are handled in ``on_interaction`` (the ids are
    stateless), so the items need no callbacks and keep working after a restart."""
    if not out.buttons and out.select is None:
        return None
    view = discord.ui.View(timeout=None)
    for button in out.buttons:
        if button.style == "link":
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link, label=button.label, url=button.url
                )
            )
        else:
            view.add_item(
                discord.ui.Button(
                    style=BUTTON_STYLES.get(button.style, discord.ButtonStyle.secondary),
                    label=button.label,
                    custom_id=button.custom_id,
                )
            )
    if out.select is not None:
        view.add_item(
            discord.ui.Select(
                custom_id=out.select.custom_id,
                placeholder=out.select.placeholder,
                options=[
                    discord.SelectOption(label=name[:100], value=f"{index}:{name}"[:100])
                    for index, name in enumerate(out.select.options, 1)
                ],
            )
        )
    return view


def kwargs_for(out: OutMessage, *, edit: bool = False) -> dict[str, Any]:
    """Arguments for ``send``/``edit``; empty things are left out (or cleared when editing)."""
    kwargs: dict[str, Any] = {"content": out.content or (None if edit else discord.utils.MISSING)}
    embed = discord.Embed.from_dict(out.embed) if out.embed else None
    if edit:
        kwargs["embed"] = embed
        kwargs["view"] = view_for(out)
    else:
        if embed is not None:
            kwargs["embed"] = embed
        view = view_for(out)
        if view is not None:
            kwargs["view"] = view
    if out.file is not None:
        file = discord.File(io.BytesIO(out.file[1]), filename=out.file[0])
        kwargs["attachments" if edit else "file"] = [file] if edit else file
    return {k: v for k, v in kwargs.items() if v is not discord.utils.MISSING}


def only_asker(user: discord.abc.Snowflake | None) -> discord.AllowedMentions:
    """Never @everyone, @here or roles – at most the person who asked."""
    return discord.AllowedMentions(
        everyone=False, roles=False, replied_user=False, users=[user] if user else False
    )


# -- the senders ---------------------------------------------------------------------------------------------
class MessageSender:
    """Answers in the channel of a message; replies to it in servers, plain text in direct chats."""

    ephemeral = False

    def __init__(self, message: discord.Message) -> None:
        self.message = message
        self.ids: list[int] = []
        self._first = True

    async def begin(self) -> None:
        return None

    async def send(self, out: OutMessage) -> discord.Message:
        kwargs = kwargs_for(out)
        kwargs["allowed_mentions"] = only_asker(self.message.author)
        if self._first and self.message.guild is not None:
            sent = await self.message.reply(mention_author=False, **kwargs)
        else:
            sent = await self.message.channel.send(**kwargs)
        self._first = False
        self.ids.append(sent.id)
        return sent

    async def edit(self, handle: object, out: OutMessage) -> None:
        assert isinstance(handle, discord.Message)
        await handle.edit(**kwargs_for(out, edit=True))

    def typing(self) -> contextlib.AbstractAsyncContextManager[None]:
        return self.message.channel.typing()  # type: ignore[return-value]

    async def react(self, emoji: str) -> None:
        with contextlib.suppress(discord.HTTPException):
            await self.message.add_reaction(emoji)


class InteractionSender:
    """Answers an interaction: deferred at once, then follow-ups (visible only to the caller if asked)."""

    def __init__(self, interaction: discord.Interaction, ephemeral: bool) -> None:
        self.interaction = interaction
        self.ephemeral = ephemeral
        self.ids: list[int] = []

    async def begin(self) -> None:
        response = self.interaction.response
        if response.is_done():
            return
        if self.interaction.type is discord.InteractionType.application_command:
            await response.defer(ephemeral=self.ephemeral, thinking=True)
        else:
            await response.defer(ephemeral=self.ephemeral)

    async def send(self, out: OutMessage) -> discord.WebhookMessage:
        await self.begin()
        kwargs = kwargs_for(out)
        sent = await self.interaction.followup.send(
            ephemeral=self.ephemeral or out.ephemeral,
            allowed_mentions=only_asker(self.interaction.user),
            wait=True,
            **kwargs,
        )
        self.ids.append(sent.id)
        return sent

    async def edit(self, handle: object, out: OutMessage) -> None:
        assert isinstance(handle, discord.WebhookMessage)
        await handle.edit(**kwargs_for(out, edit=True))

    @contextlib.asynccontextmanager
    async def typing(self) -> AsyncIterator[None]:
        yield  # the deferred "Nikita denkt nach …" is the indicator

    async def react(self, emoji: str) -> None:
        return None


class PinModal(discord.ui.Modal):
    """The PIN of a dangerous admin command, typed into a form only the owner sees."""

    pin: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="PIN", min_length=1, max_length=64, style=discord.TextStyle.short
    )

    def __init__(self, client: NikitaClient, nonce: str) -> None:
        super().__init__(title="Bitte bestätigen", timeout=120)
        self.client = client
        self.nonce = nonce

    async def on_submit(self, interaction: discord.Interaction) -> None:
        origin = self.client.origin_of(interaction)
        sender = InteractionSender(interaction, True)
        await self.client.dispatcher.pin_submitted(self.nonce, str(self.pin.value), origin, sender)


# -- the client -------------------------------------------------------------------------------------------------
class NikitaClient(discord.Client):
    def __init__(self, worker: DiscordWorker) -> None:
        intents = discord.Intents.default()
        intents.message_content = (
            True  # Developer Portal: Message Content Intent (docs/plan/14 §14.1)
        )
        intents.voice_states = True
        intents.members = False
        intents.presences = False
        super().__init__(
            intents=intents, max_messages=None, member_cache_flags=discord.MemberCacheFlags.none()
        )
        self.worker = worker
        self.tree = app_commands.CommandTree(self)
        self.tree.on_error = self._on_command_error  # type: ignore[assignment]
        self.voice_messages: VoiceMessageHandler | None = worker.voice_messages

    # -- helpers -------------------------------------------------------------------------------------------
    @property
    def dispatcher(self) -> Dispatcher:
        return self.worker.dispatcher

    def origin_of(self, source: discord.Interaction | discord.Message) -> Origin:
        """Who asks from where, in the terms of the access rules."""
        policy = self.worker.policy
        if isinstance(source, discord.Interaction):
            user, guild_id, channel, ident = (
                source.user,
                source.guild_id,
                source.channel,
                source.id,
            )
            channel_id = source.channel_id or 0
        else:
            user, channel, ident = source.author, source.channel, source.id
            guild_id = source.guild.id if source.guild else None
            channel_id = source.channel.id
        in_thread = isinstance(channel, discord.Thread)
        if guild_id is None:
            private_with_bot = (
                isinstance(channel, discord.DMChannel)
                and channel.recipient is not None
                and self.user is not None
                and channel.recipient.id == self.user.id
            ) or channel is None
            where = "DM" if private_with_bot or isinstance(source, discord.Message) else "U"
        else:
            where = "S" if policy.guild_allowed(str(guild_id)) else "U"
        return Origin(
            user_id=str(user.id),
            name=getattr(user, "display_name", "") or "",
            where=where,
            guild_id=str(guild_id) if guild_id else None,
            channel_id=str(channel_id),
            in_thread=in_thread,
            message_id=ident,
        )

    def info_of(self, message: discord.Message) -> MessageInfo:
        bot_id = self.user.id if self.user else 0
        reference = message.reference.resolved if message.reference else None
        replies_to_bot = isinstance(reference, discord.Message) and reference.author.id == bot_id
        thread = message.channel if isinstance(message.channel, discord.Thread) else None
        return MessageInfo(
            author_id=str(message.author.id),
            author_is_bot=message.author.bot,
            channel_id=str(message.channel.id),
            content=message.content or "",
            guild_id=str(message.guild.id) if message.guild else None,
            mentions_bot=any(m.id == bot_id for m in message.mentions),
            replies_to_bot=replies_to_bot,
            in_bot_thread=thread is not None and thread.owner_id == bot_id,
            is_voice_message=bool(
                message.flags.voice if hasattr(message.flags, "voice") else False
            ),
        )

    # -- lifecycle -----------------------------------------------------------------------------------------------
    async def setup_hook(self) -> None:
        await self.worker.setup(self)

    async def on_ready(self) -> None:
        await self.worker.ready(self)

    async def on_resumed(self) -> None:
        log.info("Discord: Verbindung wieder da")

    async def on_disconnect(self) -> None:
        log.info("Discord: Verbindung verloren, ich verbinde mich neu")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.worker.guild_joined(self, guild)

    # -- messages -------------------------------------------------------------------------------------------------
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or (self.user and message.author.id == self.user.id):
            return
        try:
            await self._on_message(message)
        except Exception:
            log.exception("Discord: Nachricht konnte nicht verarbeitet werden")

    async def _on_message(self, message: discord.Message) -> None:
        info = self.info_of(message)
        origin = self.origin_of(message)
        hint = self.worker.policy.stranger_hint(info)
        if hint:
            await self.worker.say_in_default_channel(self, hint)
        sender = MessageSender(message)
        if (
            self.voice_messages is not None
            and message.attachments
            and self.worker.policy.role(origin.user_id) is not Role.UNKNOWN
            and await self.voice_messages.handle(message, origin, sender)
        ):
            return
        result = await self.dispatcher.message(info, origin, sender)
        voice = self.worker.voice
        if result is not None and voice is not None and message.channel.id == voice.channel_id:
            await voice.speak_answer(message.channel.id, result.text or result.markdown)

    # -- voice channel ---------------------------------------------------------------------------------------------
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        voice = self.worker.voice
        if voice is None:
            return
        try:
            await voice.on_voice_state(member, before, after)
        except Exception:
            log.exception("Discord: Sprachkanal-Ereignis konnte nicht verarbeitet werden")

    # -- reactions -------------------------------------------------------------------------------------------------
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if (self.user and payload.user_id == self.user.id) or str(payload.emoji) not in REACTIONS:
            return
        skill = self.dispatcher.skill_of.get(payload.message_id)
        if skill is not None:
            await self.dispatcher.feedback(str(payload.user_id), str(payload.emoji), skill)

    # -- interactions (buttons, menus; commands go through the tree) -------------------------------------------------------
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        data = interaction.data or {}
        custom_id = str(data.get("custom_id", ""))
        if components.decode(custom_id) is None:
            return
        origin = self.origin_of(interaction)
        cfg = self.worker.settings().discord
        sender = InteractionSender(interaction, ephemeral_for(None, origin, cfg))
        try:
            outcome = await self.dispatcher.component(
                custom_id, [str(v) for v in data.get("values", [])], origin, sender
            )
            if outcome == NEEDS_PIN and not interaction.response.is_done():
                decoded = components.decode(custom_id)
                assert decoded is not None
                await interaction.response.send_modal(PinModal(self, decoded.nonce))
        except Exception:
            log.exception("Discord: Knopf konnte nicht verarbeitet werden")

    # -- slash commands and menus ----------------------------------------------------------------------------------------
    async def run_command(
        self, interaction: discord.Interaction, spec: commands.Spec, values: dict[str, Any]
    ) -> None:
        origin = self.origin_of(interaction)
        cfg = self.worker.settings().discord
        sender = InteractionSender(interaction, ephemeral_for(spec, origin, cfg))
        await self.dispatcher.command(spec, values, origin, sender)

    async def run_menu(
        self, interaction: discord.Interaction, name: str, message: discord.Message
    ) -> None:
        origin = self.origin_of(interaction)
        cfg = self.worker.settings().discord
        sender = InteractionSender(
            interaction, ephemeral_for(None, origin, cfg) or name == "Vorlesen"
        )
        if name == "Vorlesen" and self.worker.voice_messages is not None:
            await self.worker.voice_messages.read_aloud(message, origin, sender)
            return
        await self.dispatcher.context_menu(name, message.content or "", origin, sender)

    async def suggest_places(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if self.worker.policy.role(str(interaction.user.id)) is Role.UNKNOWN or len(current) < 2:
            return []
        try:
            places = await self.worker.core.places(current)
        except Exception:
            return []
        return [
            app_commands.Choice(
                name=(p["name"] + (f" ({p['postal_code']})" if p["postal_code"] else ""))[:100],
                value=p["name"][:100],
            )
            for p in places[:25]
        ]

    async def _on_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.error("Discord: Befehl fehlgeschlagen (%s)", type(error).__name__)
        text = self.dispatcher.say("generic").content
        with contextlib.suppress(discord.HTTPException):
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)

    # -- commands: register when changed ---------------------------------------------------------------------------------------
    def build_commands(self, features: commands.Features) -> list[dict[str, Any]]:
        return register.build(
            self.tree, features, self.run_command, self.run_menu, self.suggest_places
        )

    # -- presence ----------------------------------------------------------------------------------------------------------
    async def show(self, activity: Activity | None) -> None:
        if activity is None:
            await self.change_presence(status=discord.Status.online, activity=None)
            return
        kinds = {
            "playing": lambda t: discord.Game(name=t),
            "listening": lambda t: discord.Activity(type=discord.ActivityType.listening, name=t),
            "watching": lambda t: discord.Activity(type=discord.ActivityType.watching, name=t),
            "competing": lambda t: discord.Activity(type=discord.ActivityType.competing, name=t),
            "custom": lambda t: discord.CustomActivity(name=t),
        }
        await self.change_presence(
            status=discord.Status.online, activity=kinds[activity.kind](activity.text)
        )

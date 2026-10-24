# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The Discord worker process: connection, status, outbox, activities, maintenance (docs/plan/14 §4.2).

A separate process like the phone worker – a crash or a library error here never takes the phone
down. It talks to the main process over the internal API only and runs with a lower CPU priority
(set by the supervisor) so that the phone's speech recognition always computes first.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord

from moritz_agent import __version__
from moritz_agent.config.reload import ConfigError, ConfigManager
from moritz_agent.config.settings import REPO_ROOT, Discord, Settings
from moritz_agent.core.principal import owner_ids, remember_app_owners
from moritz_agent.discord.access import AccessPolicy, RateLimiter
from moritz_agent.discord.admin import AdminCommands
from moritz_agent.discord.client import AntonClient
from moritz_agent.discord.commands import spec as commands
from moritz_agent.discord.commands.handlers import LocalCommands
from moritz_agent.discord.core import CoreApi, CoreForbidden, CoreUnavailable
from moritz_agent.discord.dispatch import Dispatcher
from moritz_agent.discord.presence import ActivityManager
from moritz_agent.discord.render import OutMessage, mention_for, render_notification
from moritz_agent.discord.setup import invite_links
from moritz_agent.discord.speech import SpeechService
from moritz_agent.discord.status import UNSTABLE_MARK, write_status
from moritz_agent.discord.style import Styler
from moritz_agent.discord.voice.session import VoiceManager
from moritz_agent.discord.voice_messages import VoiceMessages
from moritz_agent.logging_setup import adopt, get_logger, setup_logging
from moritz_agent.phone.control import DRAIN_FILE, run_dir

log = get_logger("discord")

OUTBOX_EVERY_S = 2.0
HEARTBEAT_EVERY_S = 1.0
PRESENCE_EVERY_S = 10.0
STARTUP_STATE_S = 60.0
# lost gateway connections within FLAP_WINDOW_S that make the worker give up the DAVE fork (P1-32)
FLAPS = 4
FLAP_WINDOW_S = 600.0
EXIT_UNSTABLE = 4
RECONNECT_BACKOFF = (2.0, 60.0)


@dataclass
class WorkerOptions:
    config: Path | None = None
    passwords: Path | None = None
    state_root: Path | None = None  # where data/run lives (default: the installation)
    standalone: bool = False  # start the main process inside (./test-1.sh discord run)
    force_sync: bool = False  # register the commands even if nothing changed
    no_startup_message: bool = False


class DiscordWorker:
    def __init__(
        self,
        options: WorkerOptions,
        root: Path = REPO_ROOT,
        core: CoreApi | None = None,
    ) -> None:
        self.options = options
        self.root = root
        self.state_root = options.state_root or root
        self.config = ConfigManager(options.config, options.passwords, root)
        self.core: CoreApi = core  # type: ignore[assignment]
        self.client: AntonClient | None = None
        self.policy: AccessPolicy
        self.dispatcher: Dispatcher
        self.activity: ActivityManager
        self.voice: VoiceManager | None = None
        self.speech_service: SpeechService | None = None
        self.voice_messages: VoiceMessages | None = None  # voice messages and "Vorlesen"
        self.stop_event = asyncio.Event()
        self.default_channel: discord.abc.Messageable | None = None
        self.state = "starting"
        self.last_error = ""
        self.started_sent = False
        self.exit_code = 0
        self._lost: list[float] = []  # monotonic times of lost gateway connections
        self._standalone: Any = None
        self._connect_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._reload_event = asyncio.Event()

    # -- settings -----------------------------------------------------------------------------------------
    def settings(self) -> Settings:
        return self.config.settings

    @property
    def cfg(self) -> Discord:
        return self.config.settings.discord

    @property
    def drain_path(self) -> Path:
        return run_dir(self.state_root) / DRAIN_FILE

    def secrets(self) -> list[str]:
        return self.config.passwords.secret_values()

    def features(self) -> commands.Features:
        return commands.Features.from_settings(
            self.settings(), voice=self.voice is not None, speech=self.voice_messages is not None
        )

    # -- build ------------------------------------------------------------------------------------------------
    def _build(self) -> None:
        creds = self.config.passwords.discord
        self.policy = AccessPolicy(self.cfg, default_channel_id=creds.channel_id)
        limiter = RateLimiter(lambda: self.cfg)
        styler = Styler.from_root(self.root, self.cfg.style)
        self.dispatcher = Dispatcher(
            self.core,
            self.settings,
            self.policy,
            limiter,
            styler,
            secrets=self.secrets,
            draining=self.drain_path.exists,
        )
        self.activity = ActivityManager(
            self.root,
            self.state_root,
            lambda: self.cfg,
            lambda: self.settings().general.timezone,
            self._set_presence,
            self.core.situation,
        )
        admin = AdminCommands(
            self.core,
            self.dispatcher.confirmations,
            secrets=self.secrets,
            admin_pin=lambda: self.config.passwords.discord.admin_pin.reveal(),
            local_status=self.local_status,
            data_root=self.state_root,
        )
        self.dispatcher.local = LocalCommands(
            self.core,
            self.settings,
            self.policy,
            styler,
            admin,
            self.features,
            activity=self.activity,
            voice=self.voice,
        )

    async def _set_presence(self, activity: Any) -> None:
        if self.client is not None and self.client.is_ready():
            with contextlib.suppress(discord.HTTPException, ConnectionError):
                await self.client.show(activity)

    def local_status(self) -> dict[str, Any]:
        client = self.client
        latency = client.latency if client and client.is_ready() else None
        if latency is not None and not math.isfinite(latency):
            latency = None  # discord.py reports inf (or nan) while the gateway reconnects
        return {
            "latency_ms": round(latency * 1000) if latency is not None else None,
            "guilds": len(client.guilds) if client else 0,
            "voice": bool(self.voice and getattr(self.voice, "active", False)),
        }

    # -- run -------------------------------------------------------------------------------------------------------
    async def run(self) -> int:
        try:
            self.config.load()
        except ConfigError as exc:
            for issue in exc.report.errors:
                log.error("Konfiguration: %s: %s", issue.where, issue.message)
            return 2
        settings = self.settings()
        setup_logging(
            settings.logging.level,
            settings.resolve(settings.logging.file, self.root),
            self.secrets(),
            settings.logging.max_bytes,
            settings.logging.backup_count,
        )
        adopt("discord", "INFO")  # discord.py's own reasons for reconnects end up in our log
        if not self.config.passwords.discord.enabled:
            log.error("Discord ist nicht eingerichtet: in passwords.txt fehlt [discord] bot_token")
            return 3
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)
        loop.add_signal_handler(signal.SIGHUP, lambda: self._spawn(self.reload()))
        if self.core is None:
            self.core = await self._open_core()
        self._build()
        self._attach_voice()
        log.info("Discord-Worker %s startet", __version__)
        self._spawn(self._connect_forever())
        self._spawn(self._heartbeat())
        self._spawn(self._outbox_pump())
        self._spawn(self._presence_loop())
        self._spawn(self._housekeeping())
        try:
            await self.stop_event.wait()
        finally:
            await self.shutdown()
        return self.exit_code

    # -- connection trouble ------------------------------------------------------------------------------------------
    def connection_lost(self) -> None:
        """The gateway dropped. With the DAVE fork, losing it again and again (seen on Sophie-1,
        24.10.2026) switches the fork off: the supervisor restarts the worker with the pinned
        discord.py, text and speaking keep working, only listening in voice channels stops."""
        now = time.monotonic()
        self._lost = [t for t in self._lost if now - t < FLAP_WINDOW_S] + [now]
        log.info(
            "Discord: Verbindung verloren (%d× in 10 min), ich verbinde mich neu", len(self._lost)
        )
        env = voice_environment()
        if env is None or len(self._lost) < FLAPS:
            return
        log.error(
            "Discord: %d Verbindungsabbrüche in 10 min mit dem DAVE-Fork – schalte ihn ab und starte mit "
            "dem stabilen discord.py neu (Zuhören im Sprachkanal aus; wieder an: ./test-3.sh setup)",
            len(self._lost),
        )
        with contextlib.suppress(OSError):
            (env / UNSTABLE_MARK).write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))
        self.exit_code = EXIT_UNSTABLE
        self.stop_event.set()

    def _attach_voice(self) -> None:
        """Voice messages and the voice channel are optional parts; where Whisper or Piper are not
        installed the commands are simply not registered (docs/plan/14 §9.5)."""
        self.speech_service = self._speech_service()
        messages, channel = self._voice_parts(self.speech_service)
        if self.cfg.voice_messages.enabled:
            if messages:
                self.voice_messages = VoiceMessages(
                    self.dispatcher,
                    self.speech_service,  # type: ignore[arg-type]
                    lambda message: self.client.info_of(message),  # type: ignore[union-attr]
                )
            else:
                log.info("Discord: Spracherkennung nicht installiert – keine Sprachnachrichten")
        if self.cfg.voice.enabled and self.speech_service is not None:
            if channel:
                self.voice = VoiceManager(self)
            else:
                log.info("Discord: keine Sprachmodelle – kein Sprachkanal")
        if self.dispatcher.local is not None:
            self.dispatcher.local.voice = self.voice

    def _speech_service(self) -> SpeechService | None:
        if self.cfg.voice_messages.enabled or self.cfg.voice.enabled:
            return SpeechService(self.settings, self.root)
        return None

    def _voice_parts(self, speech: SpeechService | None) -> tuple[bool, bool]:
        """Which optional parts can run: (voice messages, voice channel)."""
        if speech is None:
            return False, False
        stt = speech.stt_available()
        messages = self.cfg.voice_messages.enabled and stt
        channel = self.cfg.voice.enabled and (stt or speech.tts_available())
        return messages, channel

    def standalone_features(self) -> commands.Features:
        """The features the running worker would register – without building it (``sync-commands``)."""
        messages, channel = self._voice_parts(self._speech_service())
        return commands.Features.from_settings(self.settings(), voice=channel, speech=messages)

    async def _open_core(self) -> CoreApi:
        core = CoreApi.from_environment()
        if core is not None:
            return core
        if not self.options.standalone:
            raise SystemExit("Keine Verbindung zum Hauptprozess (MORITZ_INTERNAL_URL fehlt)")
        from moritz_agent.supervisor import Supervisor

        sup = Supervisor(
            self.root,
            state_root=self.state_root,
            settings_file=self.options.config,
            passwords_file=self.options.passwords,
            serve_web=False,
            start_phone=False,
            start_discord=False,
            manage_processes=False,
        )
        await sup.start()
        self._standalone = sup
        assert sup.ctx is not None
        log.info(
            "Eigenständiger Betrieb: Hauptprozess läuft im Worker (ohne Telefon und Sprachmodell)"
        )
        return CoreApi(f"http://127.0.0.1:{sup.internal_port}", sup.ctx.internal_token)

    def _spawn(self, coroutine: Any) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def shutdown(self) -> None:
        self.state = "stopped"
        if self.voice is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.voice.shutdown(), 8.0)
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.client is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.client.close(), 5.0)
        write_status(self.state_root, {"state": "stopped", "version": __version__})
        if self.core is not None:
            with contextlib.suppress(Exception):
                await self.core.aclose()
        if self._standalone is not None:
            await self._standalone.shutdown()
        log.info("Discord-Worker beendet")

    # -- connection ---------------------------------------------------------------------------------------------------
    async def _connect_forever(self) -> None:
        """Connect; if it breaks down, again with a growing pause. A wrong token waits for a reload."""
        delay = RECONNECT_BACKOFF[0]
        while not self.stop_event.is_set():
            token = self.config.passwords.discord.bot_token
            self.client = AntonClient(self)
            self.state = "connecting"
            started = time.monotonic()
            try:
                await self.client.start(token.reveal(), reconnect=True)
            except discord.LoginFailure:
                self.state, self.last_error = "failed", "Der Bot-Token wurde abgelehnt"
                log.error(
                    "Discord: Der Bot-Token wurde abgelehnt – neuen Token in passwords.txt eintragen"
                )
                await self._wait_for_reload()
                continue
            except discord.PrivilegedIntentsRequired:
                self.state = "failed"
                self.last_error = "Message Content Intent fehlt im Developer Portal"
                log.error("Discord: %s", self.last_error)
                await self._wait_for_reload()
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
                log.warning("Discord: Verbindung beendet (%s)", type(exc).__name__)
            finally:
                with contextlib.suppress(Exception):
                    await self.client.close()
            if self.stop_event.is_set():
                break
            delay = (
                RECONNECT_BACKOFF[0]
                if time.monotonic() - started > 60
                else min(delay * 2, RECONNECT_BACKOFF[1])
            )
            self.state = "connecting"
            await asyncio.sleep(delay)

    async def _wait_for_reload(self) -> None:
        self._reload_event = asyncio.Event()
        await self._reload_event.wait()

    async def reload(self) -> None:
        """SIGHUP: new settings and passwords; a new token means connecting again."""
        before = self.config.passwords.discord
        result = self.config.reload()
        if not result.ok:
            log.error("Neue Konfiguration abgelehnt, die alte bleibt aktiv")
            return
        self.policy.configure(self.cfg, self.config.passwords.discord.channel_id)
        self.activity.reload()
        self.dispatcher.styler.style = self.cfg.style
        after = self.config.passwords.discord
        if after.bot_token != before.bot_token:
            log.info("Discord: neuer Token, ich verbinde mich neu")
            if self.client is not None and not (
                self.voice and getattr(self.voice, "active", False)
            ):
                with contextlib.suppress(Exception):
                    await self.client.close()
        self._reload_event.set()
        if self.client is not None and self.client.is_ready():
            await self.sync_commands(self.client)

    # -- hooks of the client --------------------------------------------------------------------------------------------------
    async def setup(self, client: AntonClient) -> None:
        if self.core is None:  # ``sync-commands`` (sync_once) registers by itself, without a core
            return
        await self.sync_commands(client)

    async def sync_commands(self, client: AntonClient, *, force: bool = False) -> bool:
        """Register the commands with Discord – only if they differ from the last registration."""
        payloads = client.build_commands(self.features())
        digest = commands.digest(payloads)
        known: str | None = None
        with contextlib.suppress(CoreUnavailable, CoreForbidden):
            known = await self.core.commands_hash()
        if digest == known and not (force or self.options.force_sync):
            log.info("Discord: %d Befehle unverändert", len(payloads))
            return False
        try:
            await client.tree.sync()
        except discord.HTTPException as exc:
            log.error("Discord: Befehle konnten nicht registriert werden (%s)", exc.status)
            return False
        with contextlib.suppress(CoreUnavailable, CoreForbidden):
            await self.core.set_commands_hash(digest)
        log.info("Discord: %d Befehle registriert", len(payloads))
        return True

    async def ready(self, client: AntonClient) -> None:
        assert client.user is not None
        self.policy.bot_id = str(client.user.id)
        await self._learn_app_owners(client)
        self.state = "ready"
        self.last_error = ""
        log.info("Discord: verbunden als %s auf %d Server(n)", client.user.name, len(client.guilds))
        await self._find_default_channel(client)
        for guild in list(client.guilds):
            await self.guild_joined(client, guild)
        for text in invite_links(client.application_id or client.user.id):
            log.info("Einladung: %s", text)
        self.activity.flags["startup"] = True
        self._spawn(self._end_startup_state())
        if not self.started_sent:
            self.started_sent = True
            await self._startup_message(client)

    async def _end_startup_state(self) -> None:
        await asyncio.sleep(STARTUP_STATE_S)
        self.activity.flags["startup"] = False

    async def _find_default_channel(self, client: AntonClient) -> None:
        channel_id = self.config.passwords.discord.channel_id
        self.default_channel = None
        if not channel_id:
            log.warning("Discord: Standardkanal fehlt (channel_id in passwords.txt)")
            return
        try:
            channel = client.get_channel(int(channel_id)) or await client.fetch_channel(
                int(channel_id)
            )
        except (discord.NotFound, discord.Forbidden):
            log.warning("Discord: Standardkanal nicht erreichbar (ID prüfen, Rechte prüfen)")
            return
        if isinstance(channel, discord.abc.Messageable) and getattr(channel, "guild", None):
            self.default_channel = channel
            self.policy.default_guild_id = str(channel.guild.id)  # type: ignore[union-attr]

    async def _startup_message(self, client: AntonClient) -> None:
        if (
            not self.cfg.startup_message
            or self.options.no_startup_message
            or self.drain_path.exists()
        ):
            return
        text = self.dispatcher.styler.phrase("startup", seed=int(time.time()) // 60)
        if not self.dispatcher.styler.cute:
            text = "Ich bin wieder da."
        await self.say_in_default_channel(client, text)

    async def _learn_app_owners(self, client: AntonClient) -> None:
        """Whoever owns the bot application (or its team) is an owner, configured or not."""
        try:
            info = await client.application_info()
        except Exception as exc:  # never stops the start: the configured owners still count
            log.warning("Discord: Besitzer der Anwendung unbekannt (%s)", type(exc).__name__)
            return
        team = getattr(info, "team", None)
        if team is not None:
            ids = [str(m.id) for m in getattr(team, "members", [])]
        else:
            ids = [str(info.owner.id)] if getattr(info, "owner", None) is not None else []
        remember_app_owners(ids)
        if ids:
            log.info(
                "Discord: Besitzer der Anwendung ist Owner (…%s)", ", …".join(i[-4:] for i in ids)
            )
        with contextlib.suppress(CoreUnavailable, CoreForbidden):
            await self.core.set_app_owners(ids)

    async def say_in_default_channel(self, client: AntonClient, text: str) -> bool:
        """Into the home channel; without one as a direct message to the owner."""
        kwargs = _plain(OutMessage(content=text))
        # nobody is pinged – the text may carry a server name like "@everyone"
        kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        try:
            if self.default_channel is not None:
                await self.default_channel.send(**kwargs)
                return True
            owner = next(iter(owner_ids(self.cfg)), None)
            if owner:
                await (await client.fetch_user(int(owner))).send(**kwargs)
                return True
        except discord.HTTPException as exc:
            log.warning("Discord: Nachricht an den Standardkanal fehlgeschlagen (%s)", exc.status)
        except (OSError, TimeoutError) as exc:
            log.warning(
                "Discord: Nachricht an den Standardkanal fehlgeschlagen (%s)", type(exc).__name__
            )
        return False

    async def guild_joined(self, client: AntonClient, guild: discord.Guild) -> None:
        """Anton lives on one private server; she leaves every other one at once (§5.2)."""
        if self.policy.guild_allowed(str(guild.id)) or not self.policy.default_guild_id:
            return
        log.warning("Discord: fremder Server %s – ich verlasse ihn", guild.id)
        with contextlib.suppress(discord.HTTPException):
            await guild.leave()
        await self.say_in_default_channel(
            client,
            f"Jemand hat mich auf einen fremden Server geholt ({guild.name}) – ich bin sofort wieder gegangen.",
        )

    # -- loops ----------------------------------------------------------------------------------------------------------------
    def status_payload(self) -> dict[str, Any]:
        """What ``discord-status.json`` says – no token, no content, no names."""
        local = self.local_status()
        client = self.client
        ready = bool(client and client.is_ready())
        return {
            "state": "ready" if ready and self.state == "ready" else self.state,
            "version": __version__,
            "draining": self.drain_path.exists(),
            "latency_ms": local["latency_ms"],
            "guilds": local["guilds"],
            "voice": local["voice"],
            "default_channel": "ok" if self.default_channel else "fehlt",
            "bot_id": self.policy.bot_id or None,
            "error": self.last_error or None,
        }

    async def _heartbeat(self) -> None:
        while True:
            try:
                write_status(self.state_root, self.status_payload())
            # a dead heartbeat looks like a hung worker and the supervisor would restart it
            except Exception:
                log.exception("Discord: Status konnte nicht geschrieben werden")
            await asyncio.sleep(HEARTBEAT_EVERY_S)

    async def _housekeeping(self) -> None:
        """Once a minute: let go of the speech models when nobody needs them."""
        while True:
            await asyncio.sleep(60)
            if self.speech_service is not None:
                self.speech_service.unload_if_idle(self.cfg.voice.unload_after_minutes)

    async def _presence_loop(self) -> None:
        while True:
            await asyncio.sleep(PRESENCE_EVERY_S)
            if self.client is not None and self.client.is_ready():
                self.activity.flags["maintenance"] = self.drain_path.exists()
                self.activity.flags["voice"] = bool(
                    self.voice and getattr(self.voice, "active", False)
                )
                with contextlib.suppress(Exception):
                    await self.activity.tick()

    async def _outbox_pump(self) -> None:
        """Messages the main process wants to send: reminders, warnings, briefing, notes (§11)."""
        while True:
            await asyncio.sleep(OUTBOX_EVERY_S)
            try:
                await self.pump_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a network hiccup must not end the pump for good
                log.warning("Discord: Ausgang fehlgeschlagen (%s)", type(exc).__name__)

    async def pump_once(self) -> int:
        client = self.client
        if client is None or not client.is_ready():
            return 0
        try:
            items = await self.core.outbox()
        except (CoreUnavailable, CoreForbidden):
            return 0
        sent = 0
        for item in items:
            delivered = await self._deliver(client, item)
            sent += int(delivered)
            with contextlib.suppress(CoreUnavailable, CoreForbidden):
                await self.core.ack(item["id"], delivered)
        return sent

    async def _deliver(self, client: AntonClient, item: dict[str, Any]) -> bool:
        target = item["target"]
        try:
            destination = await self._destination(client, target, item.get("user_id"))
            if destination is None:
                return False
            try:
                await self._send_item(destination, item, dm=target.startswith("dm:"))
            except discord.Forbidden:
                # direct messages closed (or blocked): the home channel, with a mention
                if not target.startswith("dm:") or self.default_channel is None:
                    raise
                log.info(
                    "Discord: %s-Nachricht per DM verweigert, in den Standardkanal", item["kind"]
                )
                await self._send_item(self.default_channel, item, dm=False)
            return True
        except discord.HTTPException as exc:
            log.warning("Discord: %s-Nachricht nicht zugestellt (%s)", item["kind"], exc.status)
            return False
        except (OSError, TimeoutError) as exc:  # aiohttp's connection errors are OSErrors
            log.warning(
                "Discord: %s-Nachricht nicht zugestellt (%s)", item["kind"], type(exc).__name__
            )
            return False

    async def _send_item(
        self, destination: discord.abc.Messageable, item: dict[str, Any], *, dm: bool
    ) -> None:
        mention = None if dm else mention_for(item)
        out = render_notification(item, secrets=self.secrets(), mention=mention)
        kwargs = _plain(out)
        user_id = item.get("user_id") or ""
        kwargs["allowed_mentions"] = discord.AllowedMentions(
            everyone=False,
            roles=False,
            replied_user=False,
            users=[discord.Object(int(user_id))] if str(user_id).isdigit() else False,
        )
        await destination.send(**kwargs)

    async def _destination(
        self, client: AntonClient, target: str, user_id: Any
    ) -> discord.abc.Messageable | None:
        if target.startswith("dm:"):
            return await client.fetch_user(int(target[3:]))
        if target.startswith("channel:"):
            channel = client.get_channel(int(target[8:])) or await client.fetch_channel(
                int(target[8:])
            )
            if isinstance(channel, discord.abc.Messageable):
                return channel
        if self.default_channel is not None:
            return self.default_channel
        if user_id and str(user_id).isdigit():
            return await client.fetch_user(int(user_id))
        return None


def _plain(out: OutMessage) -> dict[str, Any]:
    from moritz_agent.discord.client import kwargs_for

    return kwargs_for(out)


def run(options: WorkerOptions) -> int:
    return asyncio.run(DiscordWorker(options).run())


async def sync_once(options: WorkerOptions, root: Path = REPO_ROOT) -> int:
    """``sync-commands``: log in (no gateway), register the commands, leave.

    It registers what the worker would (voice commands and "Vorlesen" included) and stores the
    fingerprint, so the running worker registers again at its next start if its own one differs."""
    worker = DiscordWorker(options, root)
    try:
        worker.config.load()
    except ConfigError as exc:
        for issue in exc.report.errors:
            print(f"Konfiguration: {issue.where}: {issue.message}")
        return 2
    token = worker.config.passwords.discord.bot_token
    if not token:
        print("In passwords.txt fehlt [discord] bot_token.")
        return 2
    client = AntonClient(worker)
    try:
        await client.login(token.reveal())
        payloads = client.build_commands(worker.standalone_features())
        await client.tree.sync()
    except discord.LoginFailure:
        print("Der Bot-Token wurde abgelehnt.")
        return 1
    except discord.HTTPException as exc:
        print(f"Discord hat die Befehle abgelehnt ({exc.status}).")
        return 1
    finally:
        await client.close()
    print(f"{len(payloads)} Befehle registriert.")
    await _remember_digest(worker, commands.digest(payloads))
    return 0


async def _remember_digest(worker: DiscordWorker, digest: str) -> bool:
    """Store the fingerprint of what was just registered (main process, or else the database)."""
    core = CoreApi.from_environment()
    if core is not None:
        try:
            await core.set_commands_hash(digest)
            return True
        except (CoreUnavailable, CoreForbidden):
            pass
        finally:
            with contextlib.suppress(Exception):
                await core.aclose()
    settings = worker.settings()
    path = settings.resolve(settings.storage.database, worker.state_root)
    if not path.is_file():
        return False  # no database yet: the worker registers at its first start anyway
    from moritz_agent.storage import Database, DiscordStore, StorageError

    db = Database(path)
    try:
        DiscordStore(db).save_registered_hash(digest)
        return True
    except (StorageError, sqlite3.Error, OSError) as exc:
        print(f"Hinweis: Stand der Befehle nicht gespeichert ({type(exc).__name__}).")
        return False
    finally:
        db.close()


def nice_self() -> None:
    """A lower CPU priority than the phone (docs/plan/14 §4.2); the supervisor also sets it."""
    with contextlib.suppress(OSError):
        os.nice(5)


def voice_environment() -> Path | None:
    """The DAVE fork environment this worker runs in (runtime/discord-venv), else ``None``."""
    env = Path(sys.prefix)
    return env if (env / ".moritz-voice").is_file() else None

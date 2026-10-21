# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""``/joinvc``: Nikita in the voice channel, a conversation like a phone call (docs/plan/14 §9).

One session at a time. The conversation itself is the phone's ``CallSession`` (same state machine,
same announcements, same voice) with a Discord ``CallMedia``; this module is the part around it:

* [Wartet]  Nikita sits quietly in the channel until an allowed person is there
* [Im Gespräch]  a ``CallSession`` runs: greeting, listen, answer, listen … (barge-in allowed)
* [Ruht]  after silence Nikita stays, listens only for "Nikita …" and then asks "Ja?"

Listening needs the receiving extension (``receive.py``); without it the session runs in the mode
"nur sprechen": text written into the voice channel is answered aloud.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import discord

from moritz_agent.core.principal import Role
from moritz_agent.discord.sender import Origin
from moritz_agent.discord.voice import receive
from moritz_agent.discord.voice.pipeline import BargeInDetector, is_wake_word
from moritz_agent.discord.voice.playback import DiscordMedia
from moritz_agent.discord.voice.responder import VoiceResponder
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.vad import UtteranceEnd
from moritz_agent.phone.dialogue import CallSession, SessionDeps

if TYPE_CHECKING:
    from moritz_agent.discord.worker import DiscordWorker

log = get_logger("discord")
START_DELAY_S = 1.0  # after somebody arrives: the audio stands, then the greeting (no ringing)
CHECK_EVERY_S = 5.0
CONNECT_TIMEOUT_S = 20.0
REST_MAX_PENDING = 1
HEARD_WINDOW_S = 35.0  # who spoke within this time counts for the next answer (> one utterance)
VOICE_ROLES = frozenset({Role.OWNER, Role.TRUSTED})  # only they are heard (§9.2)


class VoiceMode(StrEnum):
    WAITING = "waiting"
    TALKING = "talking"
    RESTING = "resting"


class RestListener:
    """In rest mode only the name wakes Nikita: utterances are recognised and checked for "Nikita"."""

    def __init__(
        self,
        segmenter: Any,
        transcribe: Callable[[bytes], Awaitable[str]],
        on_wake: Callable[[], None],
    ) -> None:
        self.segmenter = segmenter
        self.transcribe = transcribe
        self.on_wake = on_wake
        self._busy = 0
        self._tasks: set[asyncio.Task[None]] = set()

    def feed(self, pcm: bytes) -> None:
        for event in self.segmenter.feed(pcm):
            if isinstance(event, UtteranceEnd) and self._busy < REST_MAX_PENDING:
                self._busy += 1
                task = asyncio.ensure_future(self._check(event.pcm))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _check(self, pcm: bytes) -> None:
        try:
            text = await self.transcribe(pcm)
            if is_wake_word(text):
                self.on_wake()
        except Exception:
            log.debug("Weckwort-Prüfung fehlgeschlagen", exc_info=True)
        finally:
            self._busy -= 1

    def cancel(self) -> None:
        for task in list(self._tasks):
            task.cancel()


class VoiceSession:
    def __init__(
        self,
        manager: VoiceManager,
        channel: Any,
        voice_client: Any,
        caller_id: str,
        receiving: bool,
    ) -> None:
        self.manager = manager
        self.channel = channel
        self.vc = voice_client
        self.speaker_id = caller_id
        self.receiving = receiving
        self.mode = VoiceMode.WAITING
        self.media = DiscordMedia(voice_client, on_hangup=lambda reason: None)
        self.call: CallSession | None = None
        self.responder: VoiceResponder | None = None
        self.detector: BargeInDetector | None = None
        self.rest: RestListener | None = None
        self._deps: SessionDeps | None = None
        self._call_task: asyncio.Task[str] | None = None
        self._start_task: asyncio.Task[None] | None = None
        self._watch: asyncio.Task[None] | None = None
        self._empty_since: float | None = time.monotonic()
        self._greeted = False
        self._conversations = 0
        self._closing = False
        self._heard: dict[
            int, tuple[float, float]
        ] = {}  # user → (first, last) audio since the last answer
        self._loop = asyncio.get_running_loop()

    # -- people --------------------------------------------------------------------------------------
    def humans(self) -> list[int]:
        """The allowed people in the channel (owner, trusted) – nobody else is heard (§9.2)."""
        policy = self.manager.policy
        bot_id = self.manager.bot_id
        return [
            user_id
            for user_id in getattr(self.channel, "voice_states", {})
            if user_id != bot_id and policy.role(str(user_id)) in VOICE_ROLES
        ]

    def allowed(self, user_id: int) -> bool:
        return self.manager.policy.role(str(user_id)) in VOICE_ROLES

    def speaker(self) -> tuple[str, str]:
        """Whose question the next answer is (called once per utterance by the responder).

        Audio of everybody is mixed into one conversation, so the answer runs as the person with
        the *fewest* rights among those heard since the last answer (on equal rights: whoever
        started) – a trusted person's question never runs with the owner's rights."""
        now = time.monotonic()
        heard = [
            (uid, first)
            for uid, (first, last) in self._heard.items()
            if now - last <= HEARD_WINDOW_S
        ]
        self._heard.clear()
        if heard:
            policy = self.manager.policy
            chosen = min(heard, key=lambda item: (policy.role(str(item[0])).rank, item[1]))[0]
            self.speaker_id = str(chosen)
        member = getattr(self.channel, "voice_states", {}).get(int(self.speaker_id))
        name = getattr(getattr(member, "member", None), "display_name", "") or ""
        return self.speaker_id, name

    # -- start -------------------------------------------------------------------------------------------
    async def start(self) -> None:
        speech = self.manager.speech
        speech.active += 1
        try:
            stt, vad, tts, announcements = await speech.prepare_voice()
        except Exception:
            speech.active -= 1
            raise
        phone = self.manager.settings().phone
        cfg = self.manager.cfg
        phone = phone.model_copy(update={"max_call_duration_s": cfg.voice.max_session_minutes * 60})
        self.responder = VoiceResponder(self.manager.core, self.channel.id, self.speaker)
        self._deps = SessionDeps(
            phone=phone,
            stt=stt,
            vad=vad,
            tts=tts,
            announcements=announcements,
            responder=self.responder,  # type: ignore[arg-type]
            timezone=self.manager.settings().general.timezone,
        )
        vad_settings = phone.vad
        make = lambda: vad.new_segmenter(  # noqa: E731 - one per consumer
            threshold=vad_settings.threshold,
            min_silence_ms=vad_settings.min_silence_ms,
            speech_pad_ms=vad_settings.speech_pad_ms,
            min_speech_ms=vad_settings.min_speech_ms,
            max_utterance_s=vad_settings.max_utterance_s,
        )
        self.detector = BargeInDetector(make()) if cfg.voice.barge_in else None
        self.rest = RestListener(make(), self._transcribe_text, self._wake)
        if self.receiving:
            listener = receive.Listener(self.allowed, self._deliver)
            try:
                self.vc.listen(receive.make_sink(listener))
            except Exception:
                log.warning(
                    "Discord: Zuhören im Sprachkanal nicht möglich – nur sprechen", exc_info=True
                )
                self.receiving = False
        self._watch = asyncio.ensure_future(self._watcher())
        self.update()

    async def _transcribe_text(self, pcm: bytes) -> str:
        return (await self.manager.speech.transcribe(pcm)).text

    # -- audio in (the receiving extension's thread) -----------------------------------------------------------
    def _deliver(self, user_id: int, pcm: bytes) -> None:
        self._loop.call_soon_threadsafe(self.on_audio, user_id, pcm)

    def on_audio(self, user_id: int, pcm: bytes) -> None:
        """Mono 16 kHz audio of an allowed person, on the event loop thread."""
        if not self.allowed(user_id):
            return  # (the listener filters already; a changed role counts at once)
        now = time.monotonic()
        first, _ = self._heard.get(user_id, (now, now))
        self._heard[user_id] = (first, now)
        if self.mode is VoiceMode.TALKING and self.call is not None:
            speaking = self.media.pending_ms() > 0 or bool(self.vc.is_playing())
            heard = self.detector.feed(pcm, speaking) if self.detector else None
            self.call.rx_audio(pcm)
            if heard:
                log.info("Discord: unterbrochen")
                self.call.barge_in(heard)
        elif self.mode is VoiceMode.RESTING and self.rest is not None:
            self.rest.feed(pcm)

    # -- state ---------------------------------------------------------------------------------------------------
    def update(self) -> None:
        """Somebody came or went: decide what Nikita does (docs/plan/14 §9.1)."""
        if self._closing:
            return
        humans = self.humans()
        now = time.monotonic()
        if humans:
            self._empty_since = None
            if humans and not self.speaker_id.isdigit():
                self.speaker_id = str(humans[0])
        elif self._empty_since is None:
            self._empty_since = now
        if self.mode is VoiceMode.WAITING and humans:
            if self.receiving:
                self._schedule_start("greeting")
            elif not self._greeted:
                self._greeted = True
                self._spawn(self.announce("greeting"))
        elif not humans:
            self._greeted = False
            if self.mode is VoiceMode.TALKING and self.call is not None:
                self.call.remote_hangup("caller_hangup")
            elif self.mode is VoiceMode.RESTING:
                self.mode = VoiceMode.WAITING

    def _schedule_start(self, first_prompt: str) -> None:
        if self._start_task is not None and not self._start_task.done():
            return
        self._start_task = asyncio.ensure_future(self._start_after_delay(first_prompt))

    async def _start_after_delay(self, first_prompt: str) -> None:
        await asyncio.sleep(START_DELAY_S if first_prompt == "greeting" else 0)
        if self._closing or self.mode is VoiceMode.TALKING or not self.humans():
            return
        self.begin(first_prompt)

    def _wake(self) -> None:
        """ "Nikita …" in rest mode."""
        if self.mode is VoiceMode.RESTING and not self._closing:
            self.begin("yes")

    def begin(self, first_prompt: str = "greeting") -> None:
        """Start a conversation: the phone's ``CallSession`` on this voice channel."""
        assert self._deps is not None
        cfg = self.manager.cfg
        self._conversations += 1
        quiet = "going_quiet" if cfg.voice.on_silence == "rest" else "goodbye"
        self.call = CallSession(
            f"discord-vc-{self.channel.id}-{self._conversations}",
            self.media,
            self._deps,
            remote=f"discord:{self.channel.id}",
            first_prompt=first_prompt,
            silence_goodbye=quiet,
        )
        self.mode = VoiceMode.TALKING
        self._call_task = asyncio.ensure_future(self.call.run())
        self._call_task.add_done_callback(self._call_done)
        log.info("Discord: Gespräch im Sprachkanal beginnt")

    def _call_done(self, task: asyncio.Task[str]) -> None:
        self.call = None
        try:
            reason = task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Discord: Gespräch im Sprachkanal abgebrochen")
            reason = "error"
        self._spawn(self._after_call(reason))

    async def _after_call(self, reason: str) -> None:
        if self._closing:
            return
        cfg = self.manager.cfg
        log.info("Discord: Gespräch beendet (%s)", reason)
        if self.responder is not None:
            await self.responder.end()
        if reason == "goodbye":
            if cfg.voice.after_goodbye == "leave":
                await self.manager.close(self, "Gespräch beendet")
            else:
                self.mode = VoiceMode.RESTING
        elif reason == "silence_timeout":
            if cfg.voice.on_silence == "leave":
                await self.manager.close(self, "Stille")
            else:
                self.mode = VoiceMode.RESTING
        elif reason in {"max_duration", "media_timeout", "maintenance"}:
            await self.manager.close(self, reason, announce=True)
        elif reason in {"unintelligible", "errors", "error", "out_of_service"}:
            self.mode = VoiceMode.RESTING
        else:  # the person left the channel
            self.mode = VoiceMode.WAITING
            self.update()

    # -- talking without a conversation --------------------------------------------------------------------------
    async def announce(self, prompt_id: str) -> None:
        """Play an announcement ("greeting") directly."""
        if self._deps is None:
            return
        data = self._deps.announcements.get(prompt_id)
        if data:
            self.media.play(data)

    async def say(self, text: str) -> None:
        """Say a text aloud (the answer to a message written into the voice channel)."""
        if self._deps is None or not text.strip():
            return
        pcm = await self.manager.speech.synthesize(text)
        self.media.play(pcm)

    # -- housekeeping ---------------------------------------------------------------------------------------------
    async def _watcher(self) -> None:
        cfg = self.manager.cfg
        while not self._closing:
            await asyncio.sleep(CHECK_EVERY_S)
            if not self.vc.is_connected():
                await self.manager.close(self, "Verbindung verloren", announce=True)
                return
            if self.manager.draining() and self.media.pending_ms() == 0:
                await self.manager.close(self, "Wartung", announce=True)
                return
            if (
                self._empty_since is not None
                and time.monotonic() - self._empty_since > cfg.voice.idle_leave_minutes * 60
            ):
                await self.manager.close(self, "niemand mehr da", announce=True)
                return

    def _spawn(self, coroutine: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coroutine)
        self.manager.tasks.add(task)
        task.add_done_callback(self.manager.tasks.discard)

    async def stop(self) -> None:
        self._closing = True
        for task in (self._start_task, self._watch):
            if task is not None and task is not asyncio.current_task():
                task.cancel()  # (the watcher itself may be the one closing the session)
        if self.rest is not None:
            self.rest.cancel()
        if self.call is not None:
            self.call.remote_hangup("leave")
        if self._call_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._call_task, 5.0)
        self.media.clear_playback()
        if self.responder is not None:
            await self.responder.end()
        with contextlib.suppress(Exception):
            await self.vc.disconnect(force=True)
        self.manager.speech.active = max(0, self.manager.speech.active - 1)


class VoiceManager:
    """Owns the one voice session; the commands ``/joinvc`` and ``/leavevc`` and the client's
    voice-state events go through here."""

    def __init__(self, worker: DiscordWorker) -> None:
        self.worker = worker
        self.session: VoiceSession | None = None
        self.tasks: set[asyncio.Task[None]] = set()
        self._joining = False

    # -- shortcuts -------------------------------------------------------------------------------------------------
    @property
    def policy(self):
        return self.worker.policy

    @property
    def core(self):
        return self.worker.core

    @property
    def speech(self):
        assert self.worker.speech_service is not None
        return self.worker.speech_service

    @property
    def cfg(self):
        return self.worker.cfg

    def settings(self):
        return self.worker.settings()

    @property
    def bot_id(self) -> int:
        return int(self.worker.policy.bot_id or 0)

    def draining(self) -> bool:
        return self.worker.drain_path.exists()

    @property
    def active(self) -> bool:
        return self.session is not None

    @property
    def channel_id(self) -> int | None:
        return self.session.channel.id if self.session else None

    def _style(self, text: str) -> str:
        return (
            text
            if self.worker.dispatcher.styler.cute
            else text.replace(" ✨", "").replace(" 👋", "")
        )

    # -- /joinvc -------------------------------------------------------------------------------------------------------
    def _channel_of(self, user_id: str) -> Any | None:
        """The voice channel a person is in (from the voice states the gateway sent)."""
        client = self.worker.client
        if client is None:
            return None
        for guild in client.guilds:
            for channel in [*guild.voice_channels, *getattr(guild, "stage_channels", [])]:
                if int(user_id) in getattr(channel, "voice_states", {}):
                    return channel
        return None

    def _resolve(self, user_id: str, channel_id: str | None) -> Any | None:
        client = self.worker.client
        if client is None:
            return None
        wanted = channel_id or ""
        if wanted:
            return client.get_channel(int(wanted))
        found = self._channel_of(user_id)
        if found is not None:
            return found
        default = self.cfg.voice.default_channel_id
        return client.get_channel(int(default)) if default else None

    async def join(self, origin: Origin, channel_id: str | None) -> str:
        styler = self.worker.dispatcher.styler
        if self.draining():
            return styler.error("maintenance")
        if self._joining:
            return "Ich bin gerade dabei …"
        channel = self._resolve(origin.user_id, channel_id)
        if channel is None or not isinstance(channel, discord.VoiceChannel | discord.StageChannel):
            return "Ich weiß nicht, in welchen Sprachkanal ich soll 🤔 Geh in einen hinein oder sag mir einen."
        if not self.policy.guild_allowed(str(channel.guild.id)):
            return styler.error("forbidden")
        if isinstance(channel, discord.StageChannel) and not self.cfg.voice.stage_fallback:
            return "Bühnenkanäle sind bei mir ausgeschaltet."
        if self.session is not None:
            if self.session.channel.id == channel.id:
                return self._style("Ich bin schon da ✨")
            return f"Ich bin schon in 🔊 {self.session.channel.name}. Erst `/leavevc`."
        me = channel.guild.me
        if me is not None:
            permissions = channel.permissions_for(me)
            if not (permissions.connect and permissions.speak):
                return "In dem Kanal darf ich nicht sprechen oder nicht hinein (Rechte „Verbinden“ und „Sprechen“)."
        self._joining = True
        try:
            return await self._connect(origin, channel)
        except (TimeoutError, discord.ClientException, discord.HTTPException) as exc:
            log.warning("Discord: Sprachkanal nicht erreichbar (%s)", type(exc).__name__)
            return styler.error("unavailable")
        finally:
            self._joining = False

    async def _connect(self, origin: Origin, channel: Any) -> str:
        speech = self.speech
        if not (speech.stt_available() or speech.tts_available()):
            return "Meine Stimme und mein Gehör sind gerade nicht installiert 🙈"
        receiving = receive.available()
        vc = await channel.connect(
            cls=receive.client_class(), timeout=CONNECT_TIMEOUT_S, reconnect=True, self_deaf=False
        )
        session = VoiceSession(self, channel, vc, origin.user_id, receiving)
        try:
            await session.start()
        except Exception:
            log.exception("Discord: Sprachsitzung konnte nicht starten")
            with contextlib.suppress(Exception):
                await vc.disconnect(force=True)
            return self.worker.dispatcher.styler.error("generic")
        self.session = session
        self.policy.extra_chat_channels = {str(channel.id)}  # the chat of the voice channel
        log.info("Discord: im Sprachkanal (%s)", "hört zu" if session.receiving else "nur sprechen")
        text = self._style(
            self.worker.dispatcher.styler.phrase("joined_voice", channel=channel.name)
        )
        if not session.receiving:
            text += "\nIch kann hier nur sprechen, nicht zuhören – schreib mir in den Chat dieses Sprachkanals, dann antworte ich laut."
        return text

    async def leave(self, origin: Origin) -> str:
        session = self.session
        if session is None:
            return "Ich bin gerade in keinem Sprachkanal."
        name = session.channel.name
        await self.close(session, "leavevc")
        return self._style(self.worker.dispatcher.styler.phrase("left_voice", channel=name))

    async def close(self, session: VoiceSession, why: str, *, announce: bool = False) -> None:
        if self.session is not session:
            return
        self.session = None
        self.policy.extra_chat_channels = set()
        name = session.channel.name
        await session.stop()
        log.info("Discord: Sprachkanal verlassen (%s)", why)
        if announce and self.worker.client is not None:
            await self.worker.say_in_default_channel(
                self.worker.client, self._style(f"Ich bin raus aus 🔊 {name} ({why}) 👋")
            )

    async def shutdown(self) -> None:
        if self.session is not None:
            await self.close(self.session, "Ende")
        for task in list(self.tasks):
            task.cancel()

    # -- events of the client ----------------------------------------------------------------------------------------------
    async def on_voice_state(self, member: Any, before: Any, after: Any) -> None:
        session = self.session
        if member.id == self.bot_id:
            if session is not None and after.channel is None:
                await self.close(session, "rausgeworfen", announce=True)
            return
        if session is not None:
            if session.channel in (before.channel, after.channel):
                session.update()
            return
        if (
            self.cfg.voice.auto_join
            and after.channel is not None
            and before.channel is None
            and self.policy.role(str(member.id)) is Role.OWNER
            and not self.draining()
        ):
            origin = Origin(user_id=str(member.id), where="S", guild_id=str(after.channel.guild.id))
            await self.join(origin, str(after.channel.id))

    async def speak_answer(self, channel_id: int, text: str) -> None:
        """Mode "nur sprechen": the answer to a message in the voice channel's chat, aloud."""
        session = self.session
        if session is not None and session.channel.id == channel_id and not session.receiving:
            with contextlib.suppress(Exception):
                await session.say(text)

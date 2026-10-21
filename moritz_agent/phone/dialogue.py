# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""One phone call: the asyncio orchestrator around the pure state machine (PHONE-20 … PHONE-36).

``CallSession`` connects the call media (RTP audio in and out, provided by the SIP layer) with
voice activity detection, speech recognition, the responder and the voice. It performs the
actions of :class:`CallStateMachine` and feeds the results back as events.

Half duplex (PHONE-29): while Anton speaks – and for a short guard time afterwards – incoming
audio is discarded, so the voice is never "heard" and transcribed. Hanging up from either side
cancels recognition, the answer in progress, the synthesis and the playback (PHONE-28).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

from moritz_agent.config.settings import Phone
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.announcements import AnnouncementStore
from moritz_agent.phone.audio.pcm import beep, chunk_frames
from moritz_agent.phone.audio.stt import SpeechToText
from moritz_agent.phone.audio.tts import TtsError, TtsService
from moritz_agent.phone.audio.vad import SileroVad, UtteranceEnd
from moritz_agent.phone.media import CallMedia
from moritz_agent.phone.responder import Responder, ResponderUnavailable, TurnContext
from moritz_agent.phone.state_machine import (
    Action,
    ArmTimer,
    BargeIn,
    CallAnswered,
    CallStateMachine,
    CancelReply,
    CancelTimer,
    Cleanup,
    Event,
    HangUp,
    MachineConfig,
    PlaybackDone,
    PlayPrompt,
    PlayText,
    RemoteHangup,
    ReplyFailed,
    ReplyReady,
    RequestReply,
    StartListening,
    State,
    StopPlayback,
    TimerAlarm,
    TimerFired,
    Transcribe,
    TranscriptReady,
    UtteranceEnded,
)

log = get_logger("phone")
SILENCE_RETRY_S = 1.5  # the silence timer fired while the caller is mid-sentence: look again soon


@dataclass
class SessionDeps:
    phone: Phone
    stt: SpeechToText | None  # None = speech recognition is not available (out of service)
    vad: SileroVad
    tts: TtsService
    announcements: AnnouncementStore
    responder: Responder
    timezone: str = "Europe/Berlin"


def machine_config(phone: Phone, silence_goodbye: str = "goodbye") -> MachineConfig:
    return MachineConfig(
        silence_goodbye=silence_goodbye,
        silence_prompt_s=phone.silence_prompt_s,
        silence_hangup_s=phone.silence_hangup_s,
        thinking_prompt_after_s=phone.thinking_prompt_after_s,
        turn_deadline_s=phone.turn_deadline_s,
        max_reprompts=phone.max_reprompts,
        max_unclear_hangup=phone.max_unclear_hangup,
        max_call_duration_s=phone.max_call_duration_s,
    )


class CallSession:
    def __init__(
        self,
        call_id: str,
        media: CallMedia,
        deps: SessionDeps,
        remote: str = "",
        *,
        first_prompt: str = "greeting",
        silence_goodbye: str = "goodbye",
    ) -> None:
        self.call_id = call_id
        self.first_prompt = first_prompt  # "greeting"; a Discord session woken from rest says "yes"
        self.remote = remote
        self.media = media
        self.deps = deps
        self.machine = CallStateMachine(machine_config(deps.phone, silence_goodbye))
        self._loop = asyncio.get_running_loop()  # sessions are created on the event loop thread
        self._events: asyncio.Queue[Event] = asyncio.Queue()
        self._rx: asyncio.Queue[bytes] = asyncio.Queue()
        self._items: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._tasks: set[asyncio.Task] = set()
        self._reply_task: asyncio.Task | None = None
        self._done_task: asyncio.Task | None = None
        self._segmenter = deps.vad.new_segmenter(
            threshold=deps.phone.vad.threshold,
            min_silence_ms=deps.phone.vad.min_silence_ms,
            speech_pad_ms=deps.phone.vad.speech_pad_ms,
            min_speech_ms=deps.phone.vad.min_speech_ms,
            max_utterance_s=deps.phone.vad.max_utterance_s,
        )
        self._context = TurnContext(
            call_id, deps.phone.assistant_name, deps.timezone, started_at=time.monotonic()
        )
        self._listening = False
        self._busy = False  # an item is being synthesized/played
        self._utterance = b""
        self._alarm_count = 0
        self._prebuffer = b""  # the first words of an interruption, replayed into the VAD
        self._player_task: asyncio.Task | None = None
        self._last_rx = self._loop.time()
        self._turn_clock: dict[str, float] = {}

    # -- thread-safe entry points (called from the SIP/media threads) --------------------
    def rx_audio(self, pcm: bytes) -> None:
        self._loop.call_soon_threadsafe(self._rx.put_nowait, pcm)

    def remote_hangup(self, reason: str = "caller_hangup") -> None:
        self._loop.call_soon_threadsafe(self._events.put_nowait, RemoteHangup(reason))

    def barge_in(self, heard: bytes = b"") -> None:
        """Somebody talks over Anton (Discord voice, docs/plan/14 §9.3): stop talking and listen.
        ``heard`` is what was said so far (PCM16 16 kHz); it is replayed so no word is lost."""
        self._loop.call_soon_threadsafe(self._interrupt, heard)

    def _interrupt(self, heard: bytes) -> None:
        self._prebuffer = heard
        self._events.put_nowait(BargeIn())

    # -- main loop ---------------------------------------------------------------------
    @property
    def state(self) -> State:
        return self.machine.state

    async def run(self) -> str:
        """Run the call until it ends; returns the end reason."""
        started = self._loop.time()
        log.info("Anruf %s von %s angenommen", self.call_id, self.remote or "?")
        if self.deps.stt is None:
            return await self._out_of_service()
        self._notify("call_started", self.remote)
        self._player_task = self._spawn(self._player_loop())
        for coroutine in (self._rx_loop(), self._watchdog()):
            self._spawn(coroutine)
        self._events.put_nowait(CallAnswered(self.first_prompt))
        try:
            while self.machine.state is not State.ENDED:
                event = await self._events.get()
                if isinstance(event, PlaybackDone) and not self._player_idle():
                    continue  # stale: something new was queued meanwhile
                actions = self.machine.handle(event)
                log.debug(
                    "%s → %s %s",
                    type(event).__name__,
                    self.machine.state.value,
                    [type(a).__name__ for a in actions],
                )
                for action in actions:
                    await self._perform(action)
        finally:
            await self._shutdown()
        reason = self.machine.end_reason or "unknown"
        self._notify("call_ended", reason)
        log.info(
            "Anruf %s beendet (%s) nach %.0f s, %d Runden",
            self.call_id,
            reason,
            self._loop.time() - started,
            self.machine.turns,
        )
        return reason

    async def _out_of_service(self) -> str:
        """Speech recognition is not available: say so honestly and hang up (ADR-011, PHONE-34)."""
        log.error("Anruf %s: Spracherkennung nicht verfügbar – Störungsansage", self.call_id)
        self._spawn(self._player_loop())
        self._queue_playback("prompt", "error_generic")
        try:
            while True:
                event = await self._events.get()
                if isinstance(event, RemoteHangup):
                    return event.reason
                if isinstance(event, PlaybackDone) and self._player_idle():
                    self.media.hangup("out_of_service")
                    return "out_of_service"
        finally:
            await self._shutdown()

    def _notify(self, hook: str, value: str) -> None:
        """Tell the responder that a call began or ended (only the remote one wants to know)."""
        method = getattr(self.deps.responder, hook, None)
        if method is not None:
            with contextlib.suppress(Exception):
                method(self.call_id, value)

    async def _queue_greeting_hint(self) -> None:
        """ "Übrigens: Für Weilburg gilt …" right after the greeting (cache only, never delays it)."""
        hint_source = getattr(self.deps.responder, "greeting_hint", None)
        if hint_source is None:
            return
        try:
            hint = await asyncio.wait_for(hint_source(self._context), timeout=0.5)
        except (TimeoutError, Exception):
            return
        if hint:
            log.info("Warnhinweis nach der Begrüßung")
            self._queue_playback("text", hint)

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.ensure_future(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _perform(self, action: Action) -> None:
        match action:
            case PlayPrompt(prompt):
                if prompt == "thinking":  # skills may ask for a more specific one
                    skills = self._context.extras.get("skills")
                    prompt = getattr(skills, "thinking_prompt", None) or prompt
                if prompt == "timer_done":
                    self._queue_playback("beep", "")  # a short signal, then the words
                self._queue_playback("prompt", prompt)
                if prompt == "greeting":
                    await self._queue_greeting_hint()
            case PlayText(text):
                self._queue_playback("text", text)
            case StartListening():
                self._segmenter.reset()
                self._drain_rx()
                self._listening = True
                if self._prebuffer:  # an interruption: its first words are not lost
                    for frame in chunk_frames(self._prebuffer):
                        self._rx.put_nowait(frame)
                    self._prebuffer = b""
            case StopPlayback():
                await self._stop_playback()
            case Transcribe():
                self._listening = False
                self._spawn(self._transcribe(self._utterance))
            case RequestReply(text):
                self._turn_clock["reply_request"] = self._loop.time()
                self._reply_task = self._spawn(self._reply(text))
            case CancelReply():
                if self._reply_task:
                    self._reply_task.cancel()
                    self.deps.tts.cancel()
            case ArmTimer(name, seconds):
                self._arm(name, seconds)
            case CancelTimer(name):
                handle = self._timers.pop(name, None)
                if handle:
                    handle.cancel()
            case HangUp(reason):
                self.media.hangup(reason)
            case Cleanup():
                pass  # _shutdown() runs when the loop ends

    async def _stop_playback(self) -> None:
        """Drop everything queued or being synthesized and play nothing more (barge-in)."""
        self.deps.tts.cancel()
        while not self._items.empty():
            self._items.get_nowait()
        task = self._player_task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.media.clear_playback()
        self._busy = False
        self._player_task = self._spawn(self._player_loop())

    # -- timers ------------------------------------------------------------------------
    def _arm(self, name: str, seconds: float) -> None:
        previous = self._timers.pop(name, None)
        if previous:
            previous.cancel()
        self._timers[name] = self._loop.call_later(seconds, self._timer_fired, name)

    def _timer_fired(self, name: str) -> None:
        self._timers.pop(name, None)
        if name == "silence" and self._segmenter.in_speech:
            self._arm(name, SILENCE_RETRY_S)  # the caller is talking right now
            return
        self._events.put_nowait(TimerFired(name))

    # -- caller audio ------------------------------------------------------------------
    def _drain_rx(self) -> None:
        while not self._rx.empty():
            self._rx.get_nowait()

    async def _rx_loop(self) -> None:
        while True:
            frame = await self._rx.get()
            self._last_rx = self._loop.time()
            if not self._listening:
                continue  # half duplex: nobody is listening while we speak or think
            for event in self._segmenter.feed(frame):
                if isinstance(event, UtteranceEnd):
                    self._listening = False
                    self._utterance = event.pcm
                    self._turn_clock = {"vad_end": self._loop.time()}
                    log.debug("Äußerung: %d ms (%s)", event.duration_ms, event.reason)
                    self._events.put_nowait(UtteranceEnded())
                    self._drain_rx()
                    break

    async def _watchdog(self) -> None:
        """End calls whose audio has died. Uses the RTP packet counter if the media layer has one
        (the audio port keeps ticking with silence even when the network is gone), else the
        arrival of frames."""
        limit = self.deps.phone.media_dead_timeout_s
        last_packets: int | None = None
        last_change = self._loop.time()
        while True:
            await asyncio.sleep(min(1.0, limit / 4))
            now = self._loop.time()
            packets = self.media.rx_packets()
            if packets is None:
                silent_for = now - self._last_rx
            else:
                if packets != last_packets:
                    last_packets, last_change = packets, now
                silent_for = now - last_change
            if silent_for > limit:
                log.warning("Anruf %s: kein Audio mehr seit %.0f s", self.call_id, limit)
                self._events.put_nowait(RemoteHangup("media_timeout"))
                return

    # -- recognition and answer --------------------------------------------------------
    async def _transcribe(self, pcm: bytes) -> None:
        started = self._loop.time()
        try:
            transcript = await asyncio.to_thread(self.deps.stt.transcribe, pcm)
        except Exception:
            log.exception("Spracherkennung fehlgeschlagen")
            self._events.put_nowait(TranscriptReady(None))
            return
        stt_cfg = self.deps.phone.stt
        usable = transcript.usable(stt_cfg.no_speech_threshold, stt_cfg.min_avg_logprob)
        self._turn_clock["stt_s"] = self._loop.time() - started
        self._events.put_nowait(TranscriptReady(transcript.text if usable else None))

    async def _reply(self, text: str) -> None:
        try:
            reply = await self.deps.responder.respond(text, self._context)
        except ResponderUnavailable as exc:
            log.warning("Antwort nicht möglich: %s", exc)
            self._events.put_nowait(ReplyFailed("unavailable"))
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Antwort fehlgeschlagen")
            self._events.put_nowait(ReplyFailed("error"))
            return
        self._turn_clock["reply_s"] = self._loop.time() - self._turn_clock.get(
            "reply_request", self._loop.time()
        )
        self._arm_kitchen_timer(reply)
        spoken = reply.text or ""
        self._context.turn += 1
        self._context.last_reply = reply.text or self._context.last_reply
        self._context.history.append((text, spoken or (reply.prompt or "")))
        self._events.put_nowait(
            ReplyReady(text=reply.text, prompt=reply.prompt, hangup=reply.hangup)
        )

    def _arm_kitchen_timer(self, reply) -> None:
        """ "Stell einen Timer auf 10 Minuten": when the time is up Anton says so (SKILL "Eieruhr")."""
        timer = getattr(getattr(reply, "result", None), "start_timer", None) or (
            reply.meta or {}
        ).get("timer")
        if not timer:
            return
        seconds, label = float(timer[0]), str(timer[1])
        self._alarm_count += 1
        name = f"alarm:{self._alarm_count}"
        self._timers[name] = self._loop.call_later(seconds, self._alarm_fired, name, label)

    def _alarm_fired(self, name: str, label: str) -> None:
        self._timers.pop(name, None)
        self._events.put_nowait(TimerAlarm(label))

    # -- playback ----------------------------------------------------------------------
    def _queue_playback(self, kind: str, value: str) -> None:
        self._listening = False
        self._items.put_nowait((kind, value))

    async def _player_loop(self) -> None:
        while True:
            kind, value = await self._items.get()
            self._busy = True
            try:
                if kind == "beep":
                    self._push(beep())
                elif kind == "prompt":
                    await self._play_prompt(value)
                else:
                    await self._speak(value)
            except TtsError as exc:
                log.error("Sprachausgabe fehlgeschlagen: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Wiedergabe fehlgeschlagen")
            finally:
                self._busy = False
            self._schedule_done_check()

    async def _play_prompt(self, prompt_id: str) -> None:
        data = self.deps.announcements.get(prompt_id)
        if data:
            self._push(data)
            return
        prompt = self.deps.announcements.catalog.get(prompt_id)
        if prompt is None:
            log.error("Unbekannte Ansage '%s'", prompt_id)
            return
        log.warning("Ansage '%s' nicht vorbereitet – spreche live", prompt_id)
        await self._speak(prompt.text)

    async def _speak(self, text: str) -> None:
        # "Sprich langsamer" / "Lauter bitte" change speed and volume for the rest of the call
        skills = self._context.extras.get("skills")
        speed = getattr(skills, "tempo", 1.0)
        gain_db = getattr(skills, "loudness_db", 0.0)
        async for chunk in self.deps.tts.stream(text, speed=speed, gain_db=gain_db):
            self._push(chunk)

    def _push(self, data: bytes) -> None:
        if "first_audio" not in self._turn_clock and "vad_end" in self._turn_clock:
            self._turn_clock["first_audio"] = self._loop.time()
            self._log_turn()
        self.media.play(data)

    def _log_turn(self) -> None:
        clock = self._turn_clock
        total = clock["first_audio"] - clock["vad_end"]
        log.info(
            "Runde %d: Sprachende → erster Ton %.2f s (STT %.2f s, Antwort %.2f s)",
            self.machine.turns,
            total,
            clock.get("stt_s", 0.0),
            clock.get("reply_s", 0.0),
        )

    def _player_idle(self) -> bool:
        return self._items.empty() and not self._busy and self.media.pending_ms() == 0

    def _schedule_done_check(self) -> None:
        if self._done_task is None or self._done_task.done():
            self._done_task = self._spawn(self._await_done())

    async def _await_done(self) -> None:
        guard = self.deps.phone.playback_tail_guard_ms / 1000
        while True:
            while self.media.pending_ms() > 0:
                await asyncio.sleep(0.02)
            await asyncio.sleep(guard)  # the last samples are still on their way to the phone
            if self._player_idle():
                break
        self._events.put_nowait(PlaybackDone())

    # -- teardown ----------------------------------------------------------------------
    async def _shutdown(self) -> None:
        for handle in self._timers.values():
            handle.cancel()
        self._timers.clear()
        self.deps.tts.cancel()
        self.media.clear_playback()
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*pending, return_exceptions=True)
        self._listening = False

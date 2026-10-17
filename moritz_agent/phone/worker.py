# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The phone worker: wires SIP, voice activity detection, speech recognition and voice together.

Start order (ADR-011, PHONE-34):
 1. load settings and passwords.txt,
 2. build the speech components (VAD, Whisper, voices – CosyVoice starts loading in the background),
 3. make sure all required announcements exist (rendered with the best voice that is ready now),
 4. only then start SIP and register – the phone never answers without being able to speak.
Announcements spoken by a fallback voice are re-rendered with the main voice (Hessisch Nikita)
in the background as soon as it is ready, one at a time and never during a call.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from moritz_agent.config.secrets import Passwords, PasswordsFileError, load_passwords
from moritz_agent.config.settings import REPO_ROOT, Settings, SettingsError, load_settings
from moritz_agent.logging_setup import get_logger, setup_logging
from moritz_agent.phone import dialogue
from moritz_agent.phone.audio.announcements import AnnouncementStore, load_catalog
from moritz_agent.phone.audio.factory import build_stt, build_tts, build_vad
from moritz_agent.phone.audio.stt import SpeechToText, Transcript
from moritz_agent.phone.audio.tts import TtsService
from moritz_agent.phone.audio.vad import SileroVad
from moritz_agent.phone.dialogue import CallSession, SessionDeps
from moritz_agent.phone.responder import Responder, TestResponder
from moritz_agent.phone.sip import SipCallMedia, SipPhone

log = get_logger("phone")
PROMPT_CATALOG = "assets/audio/prompts.de.toml"


class ScriptedStt:
    """Test hook (--stt fake:"a|b"): answers with fixed texts instead of recognizing speech."""

    def __init__(self, script: str) -> None:
        self.texts = [t.strip() for t in script.split("|")] or [""]
        self.calls = 0

    def transcribe(self, pcm: bytes) -> Transcript:
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        log.info("(Testmodus) Erkannter Text: %r", text)
        return Transcript(text=text, avg_logprob=-0.1, no_speech_prob=0.0, audio_s=len(pcm) / 32000)


@dataclass
class WorkerOptions:
    config: Path | None = None
    passwords: Path | None = None
    stt: str = "whisper"  # "whisper" or 'fake:"text|text"'
    register: bool = True
    allow: list[str] | None = None  # overrides phone.allowed_source_ips
    tts_engines: list[str] | None = None  # overrides engine order, e.g. ["espeak"]
    no_cosyvoice: bool = False
    force_start: bool = False  # register even if announcements are missing (never in production)
    sip_port: int | None = None  # overrides phone.local_sip_port (tests next to another SIP client)


class PhoneWorker:
    def __init__(
        self, options: WorkerOptions, root: Path = REPO_ROOT, responder: Responder | None = None
    ) -> None:
        self.options = options
        self.root = root
        self.responder: Responder = responder or TestResponder()
        self.settings: Settings = load_settings(options.config, root)
        self.passwords: Passwords = load_passwords(
            options.passwords or root / self.settings.general.passwords_file
        )
        if options.allow is not None:
            self.settings.phone.allowed_source_ips = options.allow
        if options.sip_port is not None:
            self.settings.phone.local_sip_port = options.sip_port
        self.vad: SileroVad | None = None
        self.stt: SpeechToText | None = None
        self.tts: TtsService | None = None
        self.announcements: AnnouncementStore | None = None
        self.sip: SipPhone | None = None
        self._stop: asyncio.Event | None = None

    # -- build -------------------------------------------------------------------------
    def _apply_engine_overrides(self) -> None:
        tts = self.settings.phone.tts
        if self.options.tts_engines:
            order = self.options.tts_engines
            tts.engine, tts.fallback_engines = order[0], order[1:]  # type: ignore[assignment]
        if self.options.no_cosyvoice:
            tts.fallback_engines = [e for e in tts.fallback_engines if e != "cosyvoice"]  # type: ignore[assignment]
            if tts.engine == "cosyvoice":
                remaining = tts.fallback_engines or ["espeak"]
                tts.engine, tts.fallback_engines = remaining[0], remaining[1:]  # type: ignore[assignment]

    def _build_components(self) -> None:
        self._apply_engine_overrides()
        self.vad = build_vad(self.settings, self.root)
        if self.options.stt.startswith("fake:"):
            self.stt = ScriptedStt(self.options.stt[5:])
        else:
            try:
                self.stt = build_stt(self.settings, self.root)
            except (
                Exception
            ) as exc:  # missing model, broken install: answer calls with a fault message
                log.error("Spracherkennung nicht verfügbar: %s", exc)
                self.stt = None
        self.tts = build_tts(self.settings, self.root)
        catalog = load_catalog(
            self.root / PROMPT_CATALOG,
            {
                "greeting_text": self.settings.phone.greeting_text,
                "assistant_name": self.settings.phone.assistant_name,
            },
        )
        self.announcements = AnnouncementStore(self.tts, catalog)

    def _session_factory(self, media: SipCallMedia, remote: str) -> CallSession:
        assert self.vad and self.tts and self.announcements
        deps = SessionDeps(
            phone=self.settings.phone,
            stt=self.stt,
            vad=self.vad,
            tts=self.tts,
            announcements=self.announcements,
            responder=self.responder,
            timezone=self.settings.general.timezone,
        )
        return dialogue.CallSession(media.call_id, media, deps, remote)

    # -- run ---------------------------------------------------------------------------
    async def run(self) -> int:
        loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._stop.set)
        loop.add_signal_handler(signal.SIGHUP, self._reload)

        started = time.monotonic()
        await asyncio.to_thread(self._build_components)
        assert self.tts and self.announcements
        log.info("Sprachkomponenten bereit nach %.1f s", time.monotonic() - started)

        if not await self._prepare_announcements():
            await self._shutdown()
            return 2

        self.sip = SipPhone(
            self.passwords.sip,
            self.settings.phone,
            loop,
            self._session_factory,
            pjsip_log_level=self.settings.logging.pjsip_log_level,
            register=self.options.register,
        )
        try:
            self.sip.start()
        except Exception as exc:
            log.error("SIP konnte nicht gestartet werden: %s", exc)
            await self._shutdown()
            return 3
        if self.options.register:
            log.info("Warte auf die Registrierung bei %s …", self.passwords.sip.registrar)
        else:
            log.info(
                "Direktmodus: nimmt Anrufe direkt an Port %d an (keine Registrierung)",
                self.settings.phone.local_sip_port,
            )
        log.info("Nikita ist bereit (Strg+C beendet).")

        upgrade = asyncio.ensure_future(self._upgrade_loop())
        heartbeat = asyncio.ensure_future(self._heartbeat())
        try:
            await self._stop.wait()
        finally:
            for task in (upgrade, heartbeat):
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.gather(upgrade, heartbeat, return_exceptions=True)
            await self._shutdown()
        return 0

    async def _prepare_announcements(self) -> bool:
        assert self.announcements and self.tts and self._stop
        warned = 0.0
        while True:
            missing = await asyncio.to_thread(self.announcements.ensure)
            if not missing:
                status = self.announcements.status()
                provisional = len(status["provisional"])
                log.info(
                    "Ansagen bereit (%d, davon %d vorläufig mit Ersatzstimme)",
                    status["loaded"],
                    provisional,
                )
                return True
            if self.options.force_start:
                log.error("Ansagen fehlen (%s) – Start trotzdem erzwungen", ", ".join(missing))
                return True
            if time.monotonic() - warned > 15:
                warned = time.monotonic()
                log.warning(
                    "Warte auf eine Stimme für die Ansagen (%s) – %s",
                    ", ".join(missing),
                    self.tts.describe(),
                )
            try:
                await asyncio.wait_for(self._stop.wait(), 3.0)
                return False
            except TimeoutError:
                continue

    async def _upgrade_loop(self) -> None:
        assert self.announcements
        while True:
            await asyncio.sleep(5)
            idle = lambda: self.sip is not None and not self.sip.busy  # noqa: E731
            while await asyncio.to_thread(self.announcements.upgrade_once, idle):
                await asyncio.sleep(0.5)

    async def _heartbeat(self) -> None:
        last = ""
        while True:
            await asyncio.sleep(30)
            if self.sip is None:
                continue
            state = self.sip.status()
            line = f"{state['registration']}, Anruf: {'ja' if state['in_call'] else 'nein'}"
            if line != last:
                log.info("Status: %s", line)
                last = line

    def _reload(self) -> None:
        """SIGHUP: re-read settings and passwords.txt; SIP changes apply once no call is active."""
        try:
            settings = load_settings(self.options.config, self.root)
            passwords = load_passwords(
                self.options.passwords or self.root / settings.general.passwords_file
            )
        except (SettingsError, PasswordsFileError) as exc:
            log.error("Neue Konfiguration abgelehnt, die alte bleibt aktiv: %s", exc)
            return
        if self.options.allow is not None:
            settings.phone.allowed_source_ips = self.options.allow
        if self.options.sip_port is not None:
            settings.phone.local_sip_port = self.options.sip_port
        self.settings, self.passwords = settings, passwords
        setup_logging(
            settings.logging.level, self.root / settings.logging.file, passwords.secret_values()
        )
        if self.sip is not None:
            self.sip.reload(passwords.sip, settings.phone)
        log.info("Konfiguration neu geladen")

    async def _shutdown(self) -> None:
        if self.sip is not None:
            await asyncio.to_thread(self.sip.stop)
        if self.tts is not None:
            self.tts.close()
        log.info("Beendet.")

    def status(self) -> dict:
        return {
            "sip": self.sip.status() if self.sip else None,
            "tts": self.tts.describe() if self.tts else None,
            "announcements": self.announcements.status() if self.announcements else None,
            "stt": "bereit" if self.stt else "nicht verfügbar",
        }

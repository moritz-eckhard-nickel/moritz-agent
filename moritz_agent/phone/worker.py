# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The phone worker: wires SIP, voice activity detection, speech recognition and voice together.

Start order (ADR-011, PHONE-34):
 1. load settings and passwords.txt,
 2. build the speech components (VAD, Whisper, voice – Piper "Hessisch", espeak-ng as fallback),
 3. make sure all required announcements exist (cached or rendered now),
 4. only then start SIP and register – the phone never answers without being able to speak.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from moritz_agent import __version__
from moritz_agent.config.secrets import Passwords, PasswordsFileError, load_passwords
from moritz_agent.config.settings import REPO_ROOT, Settings, SettingsError, load_settings
from moritz_agent.logging_setup import get_logger, setup_logging
from moritz_agent.phone import dialogue, remote
from moritz_agent.phone.audio.announcements import AnnouncementStore, load_catalog
from moritz_agent.phone.audio.factory import build_stt, build_tts, build_vad
from moritz_agent.phone.audio.stt import SpeechToText, Transcript
from moritz_agent.phone.audio.tts import TtsService
from moritz_agent.phone.audio.vad import SileroVad
from moritz_agent.phone.callback import CallbackSession
from moritz_agent.phone.control import PhoneControl
from moritz_agent.phone.dialogue import CallSession, SessionDeps
from moritz_agent.phone.responder import Responder, TestResponder
from moritz_agent.phone.sip import SipCallMedia, SipPhone
from moritz_agent.skills.providers import Providers
from moritz_agent.skills.responder import SkillResponder
from moritz_agent.skills.services import build_services

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
    force_start: bool = False  # register even if announcements are missing (never in production)
    sip_port: int | None = None  # overrides phone.local_sip_port (tests next to another SIP client)


class PhoneWorker:
    def __init__(
        self, options: WorkerOptions, root: Path = REPO_ROOT, responder: Responder | None = None
    ) -> None:
        self.options = options
        self.root = root
        self.settings: Settings = load_settings(options.config, root)
        self.passwords: Passwords = load_passwords(
            options.passwords or root / self.settings.general.passwords_file
        )
        if options.allow is not None:
            self.settings.phone.allowed_source_ips = options.allow
        if options.sip_port is not None:
            self.settings.phone.local_sip_port = options.sip_port
        # Started by the supervisor: every utterance goes to the main process (instant answers,
        # search, language model). Started alone (./test-1.sh): instant answers first (time,
        # calendar, weather, …), then the test answer.
        self.responder: Responder = (
            responder
            or remote.from_environment()
            or SkillResponder(
                build_services(self.settings, root, providers=Providers), fallback=TestResponder()
            )
        )
        if isinstance(self.responder, SkillResponder):
            self.responder.svc.secrets = dict(self.passwords.optional_services)
        self.vad: SileroVad | None = None
        self.stt: SpeechToText | None = None
        self.tts: TtsService | None = None
        self.announcements: AnnouncementStore | None = None
        self.sip: SipPhone | None = None
        self.control = PhoneControl(root, __version__)
        self._stop: asyncio.Event | None = None

    # -- build -------------------------------------------------------------------------
    def _apply_engine_overrides(self) -> None:
        tts = self.settings.phone.tts
        if self.options.tts_engines:
            order = self.options.tts_engines
            tts.engine, tts.fallback_engines = order[0], order[1:]  # type: ignore[assignment]

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
            draining=self.control.draining,
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
        log.info("Anton ist bereit (Strg+C beendet).")
        self._start_skills()

        heartbeat = asyncio.ensure_future(self._heartbeat())
        try:
            await self._stop.wait()
        finally:
            heartbeat.cancel()
            with contextlib.suppress(Exception):
                await asyncio.gather(heartbeat, return_exceptions=True)
            await self._shutdown()
        return 0

    async def _prepare_announcements(self) -> bool:
        assert self.announcements and self.tts
        missing = await asyncio.to_thread(self.announcements.ensure)
        if not missing:
            status = self.announcements.status()
            log.info("Ansagen bereit (%d, Stimme: %s)", status["loaded"], status["voice"])
            return True
        log.error(
            "Ansagen fehlen (%s) – %s. Modelle laden: ./test-1.sh models fetch bzw. moritz-install.sh",
            ", ".join(missing),
            self.tts.describe(),
        )
        if self.options.force_start:
            log.error("Start trotzdem erzwungen (--force)")
            return True
        return False

    async def _heartbeat(self) -> None:
        """Once a second: publish the status file; every 2 s: a call to make? every 30 s: log."""
        last, ticks, draining = "", 0, False
        while True:
            await asyncio.sleep(1)
            if self.sip is None:
                continue
            if ticks % 2 == 0:
                await self._maybe_call_back()
            state = self.sip.status()
            state["skills"] = self._skills_status()
            await asyncio.to_thread(self.control.write_status, state)
            if self.control.draining() != draining:
                draining = not draining
                log.info(
                    "Wartungsmodus %s", "an: neue Anrufe werden abgewiesen" if draining else "aus"
                )
            ticks += 1
            if ticks % 30:
                continue
            line = f"{state['registration']}, Anruf: {'ja' if state['in_call'] else 'nein'}"
            if line != last:
                log.info("Status: %s", line)
                last = line

    async def _maybe_call_back(self) -> None:
        """Anton calls back ("Sag mir am Telefon …" on Discord): fetch the order from the main
        process and dial – only when registered, idle and not in maintenance."""
        if not isinstance(self.responder, remote.RemoteResponder) or self.sip is None:
            return
        if self.sip.busy or self.control.draining() or self.sip.registration.state != "registered":
            return
        order = await self.responder.next_callback()
        if not order or self.tts is None:
            return
        loop = asyncio.get_running_loop()
        responder, tts = self.responder, self.tts
        callback_id = int(order["id"])
        text = str(order.get("text") or "")
        speak_after = float(order.get("speak_after_s", 1.0))
        guard = self.settings.phone.playback_tail_guard_ms

        def factory(media: SipCallMedia, remote_uri: str) -> CallbackSession:
            return CallbackSession(media, tts, text, speak_after_s=speak_after, tail_guard_ms=guard)

        def on_result(outcome: str) -> None:  # on the SIP thread
            loop.call_soon_threadsafe(responder.callback_done, callback_id, outcome)

        self.sip.dial(
            str(order.get("extension") or self.settings.phone.callback.extension),
            float(order.get("ring_s", 12.0)),
            factory,
            on_result,
        )

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
        if isinstance(self.responder, SkillResponder):
            self.responder.svc.settings = settings
            self.responder.svc.secrets = dict(passwords.optional_services)
            if isinstance(self.responder.svc.providers, Providers):
                self.responder.svc.providers.refresh_config()
                self._start_skills()
        setup_logging(
            settings.logging.level, self.root / settings.logging.file, passwords.secret_values()
        )
        if self.sip is not None:
            self.sip.reload(passwords.sip, settings.phone)
        log.info("Konfiguration neu geladen")

    def _start_skills(self) -> None:
        """Keep the home weather and warnings warm in the background (docs/plan/13 §3.5)."""
        if not isinstance(self.responder, SkillResponder):
            return
        providers = self.responder.svc.providers
        if isinstance(providers, Providers) and self.settings.skills.online:
            providers.start_prefetch()

    def _skills_status(self) -> dict:
        """What the status file says about the instant answers: home place and data services."""
        if not isinstance(self.responder, SkillResponder):
            return {}
        from moritz_agent.skills.slots.where import home_place

        svc = self.responder.svc
        home = home_place(svc)
        providers = svc.providers
        return {
            "home": {
                "name": home.name,
                "postal_code": home.postal_codes[0] if home.postal_codes else "",
                "latitude": round(home.lat, 2),
                "longitude": round(home.lon, 2),
            },
            "online": self.settings.skills.online,
            "services": providers.snapshot() if isinstance(providers, Providers) else {},
        }

    async def _shutdown(self) -> None:
        if isinstance(self.responder, remote.RemoteResponder):
            await self.responder.aclose()
        if isinstance(self.responder, SkillResponder) and isinstance(
            self.responder.svc.providers, Providers
        ):
            await self.responder.svc.providers.aclose()
        if self.sip is not None:
            await asyncio.to_thread(self.sip.stop)
            await asyncio.to_thread(self.control.write_stopped)
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

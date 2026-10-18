# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""SIP side of the phone: registration, incoming calls and RTP audio via PJSUA2 (ADR-005).

Threading: PJSIP is driven by one dedicated thread that creates the endpoint and polls
``libHandleEvents`` (``mainThreadOnly``); every PJSUA2 call happens on that thread, other threads
hand work over with :meth:`SipPhone.submit`. The conference bridge clocks the audio port from its
own media thread; those callbacks only copy bytes in and out of buffers – no PJSIP calls, no
blocking. The asyncio side (dialogue.py) lives on the event-loop thread.

Behaviour (PHONE-01 … PHONE-10, PHONE-40):
* registers as the SIP account from passwords.txt, retries with exponential back-off,
* only accepts INVITEs from the configured source addresses (403 otherwise),
* answers immediately, a second call while one is active gets 486 Busy Here,
* negotiates G.722 > PCMA > PCMU, 16 kHz conference bridge, no sound device,
* never places outgoing calls,
* applies a changed SIP configuration by re-registering as soon as no call is active.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import ipaddress
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from moritz_agent import __version__
from moritz_agent.config.secrets import SipCredentials
from moritz_agent.config.settings import Phone
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio import pcm as pcmtools
from moritz_agent.phone.dialogue import CallSession

log = get_logger("sip")
pj = None  # pjsua2, imported lazily so that the rest of the package works without it


class SipError(RuntimeError):
    """SIP stack could not be started or configured."""


def _load_pjsua2():
    global pj
    if pj is None:
        try:
            import pjsua2
        except ImportError as exc:
            raise SipError(
                "pjsua2 fehlt – bauen mit scripts/build-pjsip.sh (./test-1.sh setup bzw. moritz-install.sh erledigen das)"
            ) from exc
        pj = pjsua2
    return pj


@dataclass
class RegistrationState:
    state: str = "unregistered"  # unregistered | registering | registered | failed | disabled
    code: int = 0
    reason: str = ""
    since: float = field(default_factory=time.time)
    retry_in_s: float = 0.0


def parse_source_ip(address: str) -> str:
    """'192.168.1.176:5060' / '[::1]:5060' → host part."""
    if address.startswith("["):
        return address[1 : address.index("]")]
    return address.rsplit(":", 1)[0] if address.count(":") == 1 else address


def ip_allowed(ip: str, allowed: list[str]) -> bool:
    """True if ``ip`` matches an entry of ``allowed`` (single address or CIDR). Empty list = nobody."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowed:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def backoff_delay(attempt: int, minimum: float, maximum: float) -> float:
    """Exponential back-off: min, 2·min, 4·min … capped at max."""
    return float(min(maximum, minimum * (2 ** max(0, attempt))))


class AudioPort:
    """Playback queue and receive hook for one call (audio-port callbacks run on a media thread)."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self.on_rx: Callable[[bytes], None] | None = None

    def enqueue(self, data: bytes) -> None:
        with self._lock:
            self._buffer += data

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def pending_ms(self) -> int:
        with self._lock:
            return len(self._buffer) // 2 * 1000 // pcmtools.SAMPLE_RATE

    def take(self, size: int) -> bytes:
        """Next ``size`` bytes to send, padded with silence (steady RTP flow)."""
        with self._lock:
            chunk = bytes(self._buffer[:size])
            del self._buffer[:size]
        return chunk + bytes(size - len(chunk)) if len(chunk) < size else chunk


class SipCallMedia:
    """``CallMedia`` implementation for one SIP call (used by the dialogue session)."""

    def __init__(self, phone: SipPhone, call, call_id: str) -> None:
        self.phone = phone
        self.call = call
        self.call_id = call_id
        self.audio = AudioPort()
        self.session: CallSession | None = None
        self.we_hung_up = False
        self.port = None  # PJSUA2 audio port and remote media, set by SipPhone._start_media
        self.remote_audio = None
        self._rx_packets: int | None = None

    # CallMedia protocol
    def play(self, data: bytes) -> None:
        self.audio.enqueue(data)

    def clear_playback(self) -> None:
        self.audio.clear()

    def pending_ms(self) -> int:
        return self.audio.pending_ms()

    def hangup(self, reason: str) -> None:
        self.we_hung_up = True
        log.info("Anruf %s: lege auf (%s)", self.call_id, reason)
        self.phone.submit(lambda: self.phone._hangup(self.call))

    def rx_packets(self) -> int | None:
        return self._rx_packets


class SipPhone:
    def __init__(
        self,
        creds: SipCredentials,
        phone: Phone,
        loop: asyncio.AbstractEventLoop,
        session_factory: Callable[[SipCallMedia, str], CallSession],
        pjsip_log_level: int = 3,
        register: bool = True,
        draining: Callable[[], bool] | None = None,
    ) -> None:
        self.creds = creds
        self.phone = phone
        self.loop = loop
        self.session_factory = session_factory
        self.pjsip_log_level = pjsip_log_level
        self.register = register
        self.draining = draining or (lambda: False)
        self.registration = RegistrationState("unregistered" if register else "disabled")
        self.last_error = ""
        self.calls_total = 0

        self._commands: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._timers: list[tuple[float, Callable[[], None]]] = []
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._ep = None
        self._account = None
        self._log_writer = None
        self._active = None  # the call that is being served
        self._active_media: SipCallMedia | None = None
        self._zombies: list[tuple[float, object]] = []
        self._pending_config: tuple[SipCredentials, Phone] | None = None
        self._retry_attempt = 0
        self._last_stats = 0.0

    # -- public API (any thread) -------------------------------------------------------
    def start(self, timeout: float = 20.0) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._thread_main, name="pjsip", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise SipError("PJSIP-Start dauerte zu lange")
        if self._error is not None:
            raise SipError(f"PJSIP-Start fehlgeschlagen: {self._error}") from self._error

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def submit(self, command: Callable[[], None]) -> None:
        """Run ``command`` on the PJSIP thread."""
        self._commands.put(command)

    @property
    def busy(self) -> bool:
        return self._active is not None

    def reload(self, creds: SipCredentials, phone: Phone) -> None:
        """Apply new SIP settings; re-registers once no call is active (PHONE-08)."""
        self._pending_config = (creds, phone)
        self.submit(self._apply_pending)

    def wait_registered(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.registration.state == "registered":
                return True
            time.sleep(0.1)
        return self.registration.state == "registered"

    def status(self) -> dict:
        reg = self.registration
        return {
            "registration": reg.state,
            "code": reg.code,
            "reason": reg.reason,
            "since": reg.since,
            "retry_in_s": round(reg.retry_in_s, 1),
            "in_call": self.busy,
            "calls_total": self.calls_total,
            "last_error": self.last_error,
        }

    # -- PJSIP thread ------------------------------------------------------------------
    def _thread_main(self) -> None:
        try:
            self._init_stack()
        except Exception as exc:  # reported to start()
            self._error = exc
            self._ready.set()
            self._destroy()
            return
        self._ready.set()
        try:
            while not self._stop.is_set():
                self._ep.libHandleEvents(20)
                self._run_commands()
                self._run_timers()
                self._poll_stats()
        finally:
            self._shutdown_stack()

    def _init_stack(self) -> None:
        pjsua = _load_pjsua2()
        creds, cfg = self.creds, self.phone
        if creds.transport == "tls":
            raise SipError("transport = tls wird noch nicht unterstützt (udp oder tcp verwenden)")

        outer = self

        class LogWriter(pjsua.LogWriter):
            def write(self, entry):
                log.debug("pjsip: %s", entry.msg.rstrip())

        self._log_writer = LogWriter()
        self._ep = pjsua.Endpoint()
        self._ep.libCreate()
        ep_cfg = pjsua.EpConfig()
        ep_cfg.uaConfig.threadCnt = 0
        ep_cfg.uaConfig.mainThreadOnly = True
        ep_cfg.uaConfig.userAgent = f"moritz-agent/{__version__}"
        ep_cfg.uaConfig.maxCalls = 4
        ep_cfg.logConfig.level = self.pjsip_log_level
        ep_cfg.logConfig.consoleLevel = 0
        ep_cfg.logConfig.msgLogging = 0  # SIP messages contain credentials (LOG-02)
        ep_cfg.logConfig.writer = self._log_writer
        ep_cfg.medConfig.clockRate = pcmtools.SAMPLE_RATE
        ep_cfg.medConfig.sndClockRate = pcmtools.SAMPLE_RATE
        ep_cfg.medConfig.channelCount = 1
        ep_cfg.medConfig.ecTailLen = 0  # no echo canceller: no sound card, half duplex dialogue
        ep_cfg.medConfig.noVad = True  # keep RTP flowing, silence is data too
        self._ep.libInit(ep_cfg)

        transport = pjsua.TransportConfig()
        transport.port = cfg.local_sip_port
        kind = pjsua.PJSIP_TRANSPORT_TCP if creds.transport == "tcp" else pjsua.PJSIP_TRANSPORT_UDP
        self._ep.transportCreate(kind, transport)
        self._ep.libStart()
        self._ep.audDevManager().setNullDev()
        self._set_codec_priorities()

        class Account(pjsua.Account):
            def onRegState(self, prm):
                outer._on_reg_state(self, prm)

            def onIncomingCall(self, prm):
                outer._on_incoming(self, prm)

        self._account_class = Account
        self._create_account()
        log.info(
            "SIP bereit: Port %d/%s, Codecs %s",
            cfg.local_sip_port,
            creds.transport,
            ", ".join(cfg.codecs),
        )

    def _set_codec_priorities(self) -> None:
        wanted = [c.lower() for c in self.phone.codecs]
        for info in self._ep.codecEnum2():
            codec_id = info.codecId.lower()
            priority = 0
            for rank, name in enumerate(wanted):
                if codec_id == name or codec_id.startswith(name + "/"):
                    priority = 255 - rank
                    break
            self._ep.codecSetPriority(info.codecId, priority)

    def _create_account(self) -> None:
        pjsua, creds, cfg = pj, self.creds, self.phone
        acc_cfg = pjsua.AccountConfig()
        display = creds.display_name.replace('"', "")
        host = creds.registrar
        acc_cfg.idUri = (
            f'"{display}" <sip:{creds.username}@{host}>'
            if display
            else f"sip:{creds.username}@{host}"
        )
        suffix = ";transport=tcp" if creds.transport == "tcp" else ""
        if self.register:
            acc_cfg.regConfig.registrarUri = f"sip:{host}:{creds.port}{suffix}"
            acc_cfg.regConfig.registerOnAdd = True
            acc_cfg.regConfig.timeoutSec = 300
            acc_cfg.regConfig.retryIntervalSec = 0  # we back off ourselves
            acc_cfg.sipConfig.authCreds.append(
                pjsua.AuthCredInfo("digest", "*", creds.auth_username, 0, creds.password.reveal())
            )
        else:
            acc_cfg.regConfig.registerOnAdd = False
        acc_cfg.natConfig.sipStunUse = pjsua.PJSUA_STUN_USE_DISABLED
        acc_cfg.natConfig.mediaStunUse = pjsua.PJSUA_STUN_USE_DISABLED
        acc_cfg.natConfig.iceEnabled = False
        acc_cfg.mediaConfig.transportConfig.port = cfg.rtp_port_start
        acc_cfg.mediaConfig.transportConfig.portRange = cfg.rtp_port_count
        self._account = self._account_class()
        self._account.create(acc_cfg)
        self._retry_attempt = 0
        if self.register:
            self.registration = RegistrationState("registering")

    def _run_commands(self) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                command()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.exception("SIP-Kommando fehlgeschlagen")

    def _schedule(self, delay: float, fn: Callable[[], None]) -> None:
        self._timers.append((time.monotonic() + delay, fn))

    def _run_timers(self) -> None:
        now = time.monotonic()
        due = [t for t in self._timers if t[0] <= now]
        self._timers = [t for t in self._timers if t[0] > now]
        for _, fn in due:
            try:
                fn()
            except Exception:
                log.exception("SIP-Timer fehlgeschlagen")
        self._zombies = [
            (t, obj) for t, obj in self._zombies if now - t < 5.0
        ]  # drop old call objects

    def _poll_stats(self) -> None:
        """Once a second: count received RTP packets of the active call (media liveness)."""
        now = time.monotonic()
        if now - self._last_stats < 1.0 or self._active is None or self._active_media is None:
            return
        self._last_stats = now
        try:
            stat = self._active.getStreamStat(0)
            self._active_media._rx_packets = int(stat.rtcp.rxStat.pkt)
        except Exception:
            self._active_media._rx_packets = None

    # -- registration ------------------------------------------------------------------
    def _on_reg_state(self, account, prm) -> None:
        info = account.getInfo()
        code, reason = int(prm.code), str(prm.reason)
        if info.regIsActive and 200 <= code < 300:
            self.registration = RegistrationState("registered", code, reason)
            self._retry_attempt = 0
            log.info("Registriert als %s bei %s", self.creds.username, self.creds.registrar)
        elif code >= 300 or (code == 0 and prm.status != 0):
            delay = backoff_delay(
                self._retry_attempt,
                self.phone.register_retry_min_s,
                self.phone.register_retry_max_s,
            )
            self._retry_attempt += 1
            self.registration = RegistrationState("failed", code, reason, retry_in_s=delay)
            log.warning(
                "Registrierung fehlgeschlagen (%s %s) – neuer Versuch in %.0f s",
                code,
                reason,
                delay,
            )
            self._schedule(delay, lambda: self._retry_registration())
        elif not info.regIsActive and 200 <= code < 300:
            self.registration = RegistrationState("unregistered", code, reason)
        else:
            self.registration = RegistrationState("registering", code, reason)

    def _retry_registration(self) -> None:
        if self._account is not None and self.register and self.registration.state == "failed":
            log.info("Registrierung erneut versuchen")
            self.registration = RegistrationState("registering")
            self._account.setRegistration(True)

    def _apply_pending(self) -> None:
        if self._pending_config is None:
            return
        if self._active is not None:
            log.info("Neue SIP-Einstellungen warten auf das Gesprächsende")
            return
        self.creds, self.phone = self._pending_config
        self._pending_config = None
        log.info("Übernehme neue SIP-Einstellungen – melde neu an")
        old = self._account
        self._account = None
        if old is not None:
            try:
                old.shutdown()
            except Exception:
                log.debug("Konto-Shutdown fehlgeschlagen", exc_info=True)
        self._set_codec_priorities()
        self._create_account()

    # -- calls -------------------------------------------------------------------------
    def _make_call_class(self):
        pjsua, outer = pj, self

        class Call(pjsua.Call):
            def onCallState(self, prm):
                outer._on_call_state(self)

            def onCallMediaState(self, prm):
                outer._on_media_state(self)

        return Call

    def _on_incoming(self, account, prm) -> None:
        pjsua = pj
        if not hasattr(self, "_call_class"):
            self._call_class = self._make_call_class()
        call = self._call_class(account, prm.callId)
        source = parse_source_ip(prm.rdata.srcAddress)
        op = pjsua.CallOpParam(True)
        if not ip_allowed(source, self.phone.allowed_source_ips):
            log.warning("INVITE von nicht erlaubter Adresse %s abgewiesen", source)
            op.statusCode = pjsua.PJSIP_SC_FORBIDDEN
            call.hangup(op)
            self._zombies.append((time.monotonic(), call))
            return
        if self.draining():
            log.info("Anruf von %s abgewiesen: Wartung (Update) läuft", source)
            op.statusCode = pjsua.PJSIP_SC_BUSY_HERE
            call.hangup(op)
            self._zombies.append((time.monotonic(), call))
            return
        if self._active is not None:
            log.info("Zweiter Anruf von %s: besetzt", source)
            op.statusCode = pjsua.PJSIP_SC_BUSY_HERE
            call.hangup(op)
            self._zombies.append((time.monotonic(), call))
            return
        self._active = call
        self._active_media = None
        self.calls_total += 1
        op.statusCode = pjsua.PJSIP_SC_OK
        call.answer(op)

    def _on_media_state(self, call) -> None:
        pjsua = pj
        if call is not self._active or self._active_media is not None:
            return
        info = call.getInfo()
        for index, media in enumerate(info.media):
            if (
                media.type == pjsua.PJMEDIA_TYPE_AUDIO
                and media.status == pjsua.PJSUA_CALL_MEDIA_ACTIVE
            ):
                self._start_media(call, index, info)
                return

    def _make_port_class(self):
        """The audio port class is created once; instances reference their call media via ``media``.

        (A class defined per call would form a reference cycle with the call objects, which then
        would be destroyed by the garbage collector on an arbitrary thread – PJSIP objects must be
        released on the SIP thread, so everything here is freed by reference counting.)
        """
        pjsua = pj

        class Port(pjsua.AudioMediaPort):
            media: SipCallMedia | None = None

            def onFrameRequested(self, frame):
                media = self.media
                data = (
                    media.audio.take(frame.size or pcmtools.FRAME_BYTES)
                    if media
                    else bytes(frame.size or 0)
                )
                frame.type = pjsua.PJMEDIA_FRAME_TYPE_AUDIO
                frame.buf = pjsua.ByteVector(list(data))
                frame.size = len(data)

            def onFrameReceived(self, frame):
                media = self.media
                session = media.session if media else None
                if session is not None and frame.size:
                    session.rx_audio(bytes(frame.buf))

        return Port

    def _start_media(self, call, index: int, info) -> None:
        pjsua = pj
        call_id = uuid.uuid4().hex[:8]
        media = SipCallMedia(self, call, call_id)
        if not hasattr(self, "_port_class"):
            self._port_class = self._make_port_class()
        fmt = pjsua.MediaFormatAudio()
        fmt.init(pjsua.PJMEDIA_FORMAT_PCM, pcmtools.SAMPLE_RATE, 1, pcmtools.FRAME_MS * 1000, 16)
        port = self._port_class()
        port.media = media
        port.createPort("nikita", fmt)
        remote_audio = call.getAudioMedia(index)
        remote_audio.startTransmit(port)
        port.startTransmit(remote_audio)
        media.port = port  # keep alive
        media.remote_audio = remote_audio
        self._active_media = media
        remote = str(info.remoteUri)
        log.info("Anruf %s: Medien aktiv (%s), Codec-Aushandlung abgeschlossen", call_id, remote)
        asyncio.run_coroutine_threadsafe(self._run_session(media, remote), self.loop)

    async def _run_session(self, media: SipCallMedia, remote: str) -> None:
        try:
            session = self.session_factory(media, remote)
            media.session = session
            reason = await session.run()
            log.debug("Sitzung %s beendet: %s", media.call_id, reason)
        except Exception:
            log.exception("Anrufsitzung abgestürzt")
            media.hangup("internal_error")
        finally:
            media.session = None
            self.submit(lambda: self._finish_call(media.call))

    def _on_call_state(self, call) -> None:
        info = call.getInfo()
        if info.state != pj.PJSIP_INV_STATE_DISCONNECTED:
            return
        media = self._active_media if call is self._active else None
        log.info("Anruf beendet (SIP %s %s)", info.lastStatusCode, info.lastReason)
        if media is not None and media.session is not None and not media.we_hung_up:
            with contextlib.suppress(RuntimeError):  # event loop already closed
                media.session.remote_hangup("caller_hangup")
        if call is self._active:
            self._finish_call(call)

    def _finish_call(self, call) -> None:
        if call is not self._active:
            return
        media = self._active_media
        self._active = None
        self._active_media = None
        if media is not None:
            media.audio.clear()
            port, remote_audio = getattr(media, "port", None), getattr(media, "remote_audio", None)
            if port is not None and remote_audio is not None:
                for source, target in ((port, remote_audio), (remote_audio, port)):
                    try:
                        source.stopTransmit(target)
                    except Exception as exc:  # the media may already be gone with the call
                        log.debug("stopTransmit nicht nötig: %s", exc)
            if port is not None:
                port.media = (
                    None  # break the cycle: freed by refcount once dropped from the zombie list
                )
            media.port = media.remote_audio = None
            self._zombies.append((time.monotonic(), port))
            self._zombies.append((time.monotonic(), remote_audio))
        self._zombies.append((time.monotonic(), call))
        if self._pending_config is not None:
            self._apply_pending()

    def _hangup(self, call) -> None:
        if call is not self._active:
            return
        try:
            call.hangup(pj.CallOpParam(True))
        except Exception:
            log.debug("hangup fehlgeschlagen (Anruf schon beendet?)", exc_info=True)

    # -- teardown ----------------------------------------------------------------------
    def _shutdown_stack(self) -> None:
        try:
            if self._active is not None:
                self._hangup(self._active)
            if self._account is not None and self.register:
                try:
                    self._account.setRegistration(False)
                    deadline = time.monotonic() + 1.0
                    while time.monotonic() < deadline:  # let the un-REGISTER go out
                        self._ep.libHandleEvents(50)
                except Exception:
                    log.debug("Abmelden fehlgeschlagen", exc_info=True)
            for _ in range(10):
                self._ep.libHandleEvents(20)
        finally:
            self._destroy()

    def _destroy(self) -> None:
        self._zombies.clear()
        self._account = None
        self._active = None
        self._active_media = None
        gc.collect()  # release leftover call/media objects now, on this thread, before the stack goes away
        if self._ep is not None:
            try:
                self._ep.libDestroy()
            except Exception:
                log.debug("libDestroy fehlgeschlagen", exc_info=True)
            self._ep = None

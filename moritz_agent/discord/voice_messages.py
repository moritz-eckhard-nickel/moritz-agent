# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Voice messages and "Vorlesen" (docs/plan/14 §10).

A voice message (or audio file up to five minutes) from an allowed person is downloaded into memory
from Discord's own CDN only, decoded, recognised by Whisper, and answered like a typed question –
the transcript is shown small above the answer so recognition mistakes are visible. Replies can come
as audio too (Ogg/Opus). Nothing is stored; no attachment is ever run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import urlparse

import discord
import httpx

from moritz_agent.config.settings import Discord
from moritz_agent.discord.access import MessageInfo, Reaction
from moritz_agent.discord.dispatch import Dispatcher
from moritz_agent.discord.render import OutMessage, redact
from moritz_agent.discord.sender import Origin, Sender
from moritz_agent.discord.speech import AudioError, SpeechService, decode_to_pcm16k, encode_ogg_opus
from moritz_agent.logging_setup import get_logger

log = get_logger("discord")
CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
MAX_BYTES = 25 * 1024 * 1024
READ_ALOUD_MAX_CHARS = 1500


def is_audio(attachment: discord.Attachment) -> bool:
    kind = (attachment.content_type or "").split(";")[0].strip().lower()
    return kind.startswith("audio/") or attachment.filename.lower().endswith(
        (".ogg", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".aac", ".flac")
    )


def from_cdn(url: str) -> bool:
    parts = urlparse(url)
    return parts.scheme == "https" and parts.hostname in CDN_HOSTS


class VoiceMessages:
    def __init__(
        self,
        dispatcher: Dispatcher,
        speech: SpeechService,
        info_of: Callable[[discord.Message], MessageInfo],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.speech = speech
        self.info_of = info_of
        self._transport = transport

    @property
    def cfg(self) -> Discord:
        return self.dispatcher.cfg

    # -- download ---------------------------------------------------------------------------------------
    async def fetch(self, url: str) -> bytes:
        """The bytes of an attachment – only from Discord's CDN, at most 25 MB."""
        if not from_cdn(url):
            raise AudioError("Dateien von anderen Adressen lade ich nicht.")
        data = bytearray()
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(20.0, connect=5.0),
                    transport=self._transport,
                    follow_redirects=False,
                ) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code != 200:
                    raise AudioError("Die Datei konnte ich nicht herunterladen.")
                async for chunk in response.aiter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise AudioError("Die Datei ist größer als 25 MB.")
        except httpx.HTTPError as exc:
            raise AudioError("Die Datei konnte ich nicht herunterladen.") from exc
        return bytes(data)

    # -- incoming ------------------------------------------------------------------------------------------
    async def handle(self, message: discord.Message, origin: Origin, sender: Sender) -> bool:
        """``True`` if the message carried audio for Anton and has been dealt with."""
        cfg = self.cfg
        audio = next((a for a in message.attachments if is_audio(a)), None)
        if audio is None or not cfg.voice_messages.enabled:
            return False
        decision = self.dispatcher.policy.message(
            self.info_of(message), today=self.dispatcher.today()
        )
        if decision.reaction is not Reaction.ANSWER:
            return False  # not meant for Anton (other channel, not addressed, stranger)
        limiter = self.dispatcher.limiter
        if not limiter.allow(origin.user_id, decision.role):
            await sender.send(self.dispatcher.say("rate_limited"))
            return True
        styler = self.dispatcher.styler
        styler.style = cfg.style
        max_seconds = float(cfg.voice_messages.max_seconds)
        if audio.duration and audio.duration > max_seconds:  # type: ignore[attr-defined]
            await sender.send(
                OutMessage(
                    content=f"Das ist länger als {int(max_seconds // 60)} Minuten – so lang höre ich nicht zu."
                )
            )
            return True
        if not self.speech.stt_available():
            await sender.send(OutMessage(content="Meine Spracherkennung ist gerade nicht bereit."))
            return True
        async with sender.typing():
            try:
                data = await self.fetch(audio.url)
                pcm = await asyncio.to_thread(decode_to_pcm16k, data, max_seconds)
                transcript = await self.speech.transcribe(pcm)
            except AudioError as exc:
                await sender.send(OutMessage(content=str(exc)))
                return True
            except Exception:
                log.exception("Discord: Sprachnachricht konnte nicht erkannt werden")
                await sender.send(self.dispatcher.say("generic"))
                return True
        if not transcript.usable():
            await sender.send(
                OutMessage(
                    content=redact(styler.error("not_understood"), self.dispatcher.secrets())
                )
            )
            return True
        text = transcript.text.strip()
        await sender.send(OutMessage(content=f"*{redact(text, self.dispatcher.secrets())}*"))
        result = await self.dispatcher.ask(text, origin, sender)
        if result is not None and await self._wants_voice(origin.user_id, True):
            await self._reply_with_voice(result.text or result.markdown, sender)
        return True

    async def _wants_voice(self, user_id: str, was_voice: bool) -> bool:
        mode = self.cfg.voice_messages.reply_with_voice
        try:
            saved = (await self.dispatcher.core.principal(user_id)).get("voice_reply")
        except Exception:
            saved = None
        mode = saved or mode
        return mode == "always" or (mode == "mirror" and was_voice)

    async def _reply_with_voice(self, text: str, sender: Sender, name: str = "antwort.ogg") -> None:
        if not text.strip() or not self.speech.tts_available():
            return
        try:
            pcm = await self.speech.synthesize(text[:READ_ALOUD_MAX_CHARS])
            data = await asyncio.to_thread(encode_ogg_opus, pcm)
        except Exception:
            log.warning("Discord: Sprachantwort konnte nicht erzeugt werden", exc_info=True)
            return
        # Sent as an audio file: whether a bot may send native voice messages is part of the
        # spike (P1-32); an audio file always works.
        await sender.send(OutMessage(file=(name, data)))

    # -- "Vorlesen" (context menu) ----------------------------------------------------------------------------
    async def read_aloud(self, message: discord.Message, origin: Origin, sender: Sender) -> None:
        await sender.begin()
        text = redact((message.content or "").strip(), self.dispatcher.secrets())
        if not text:
            await sender.send(
                OutMessage(content="In der Nachricht steht kein Text zum Vorlesen.", ephemeral=True)
            )
            return
        if not self.speech.tts_available():
            await sender.send(
                OutMessage(content="Meine Stimme ist gerade nicht bereit.", ephemeral=True)
            )
            return
        await self._reply_with_voice(text, sender, "vorlesen.ogg")

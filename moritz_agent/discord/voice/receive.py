# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Listening in the voice channel (docs/plan/14 §9.2, §9.5, ADR-036).

discord.py itself only *sends* audio. Receiving needs an extension (``discord-ext-voice-recv``) that
also decrypts Discord's end-to-end encryption (DAVE). The PyPI release cannot (June 2025); the fork
``zacker150/discord-ext-voice-recv`` with its discord.py fork can (spike P1-32, 24.10.2026). It
lives in its own environment ``runtime/discord-venv`` (scripts/setup-discord-voice.sh), because it
replaces the pinned discord.py. This module works with whatever is installed: if the extension is
missing, ``available()`` is false and the voice channel runs in the mode "nur sprechen" (Anton
answers text and voice messages with his voice, docs/plan/14 §9.5, result B).
"""

from __future__ import annotations

import asyncio
import importlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from moritz_agent.discord.voice.pipeline import Downmix
from moritz_agent.logging_setup import get_logger

log = get_logger("discord")


def extension() -> Any | None:
    """The ``discord.ext.voice_recv`` module, or ``None`` if it is not installed."""
    try:
        return importlib.import_module("discord.ext.voice_recv")
    except Exception:
        return None


def available() -> bool:
    return extension() is not None


class Listener:
    """Collects the audio of the allowed people, converted to what the conversation needs.

    ``allowed(user_id)`` decides *before* any decoding work whether a speaker is heard (docs/plan/14
    §9.2: others are dropped); ``deliver(user_id, pcm16k)`` gets mono 16 kHz audio, from the thread of
    the receiving extension.
    """

    def __init__(
        self,
        allowed: Callable[[int], bool],
        deliver: Callable[[int, bytes], None],
        only_person: Callable[[], int | None] = lambda: None,
    ) -> None:
        self.allowed = allowed
        self.deliver = deliver
        self.only_person = only_person  # the one allowed person in the channel, if there is one
        self._downmix: dict[int, Downmix] = {}
        self.dropped = 0
        self.stats = ReceiveStats()

    def on_audio(self, user_id: int | None, pcm48_stereo: bytes) -> None:
        self.stats.packets += 1
        if user_id is None:
            # Seen on Sophie-1 (24.10.2026): the fork knows the speaker only once the member is
            # cached – until then the audio has no user. With one allowed person in the channel it
            # can only be them.
            user_id = self.only_person()
            if user_id is None:
                self.stats.no_user += 1
                self.dropped += 1
                return
            self.stats.assigned += 1
        if not self.allowed(user_id):
            self.stats.not_allowed += 1
            self.dropped += 1
            return
        self.stats.heard(pcm48_stereo)
        mixer = self._downmix.get(user_id)
        if mixer is None:
            mixer = self._downmix[user_id] = Downmix()
        pcm = mixer.feed(pcm48_stereo)
        if pcm:
            self.deliver(user_id, pcm)

    def forget(self, user_id: int) -> None:
        self._downmix.pop(user_id, None)


@dataclass
class ReceiveStats:
    """What arrived from the voice channel – logged every few seconds while listening."""

    packets: int = 0
    no_user: int = 0  # audio nobody could be assigned to
    assigned: int = 0  # audio without user, given to the only allowed person
    not_allowed: int = 0
    delivered: int = 0
    peak: int = 0  # loudest sample since the last report (0 = only silence arrived)

    def heard(self, pcm: bytes) -> None:
        self.delivered += 1
        usable = len(pcm) - len(pcm) % 2
        if usable:
            loudest = int(np.abs(np.frombuffer(pcm[:usable], dtype="<i2").astype(np.int32)).max())
            self.peak = max(self.peak, loudest)

    def line(self) -> str:
        level = f"{20 * math.log10(self.peak / 32768):.0f} dBFS" if self.peak else "still"
        return (
            f"{self.packets} Pakete, {self.delivered} gehört (Pegel {level}), {self.assigned} zugeordnet, "
            f"{self.no_user} ohne Sprecher, {self.not_allowed} nicht erlaubt"
        )


def make_sink(listener: Listener) -> Any:
    """An ``AudioSink`` of the extension that feeds ``listener`` (decoded PCM, no Opus)."""
    module = extension()
    if module is None:
        raise RuntimeError("discord-ext-voice-recv ist nicht installiert")

    class AntonSink(module.AudioSink):  # type: ignore[name-defined]
        def wants_opus(self) -> bool:
            return False

        def write(self, user: Any, data: Any) -> None:
            pcm = getattr(data, "pcm", None)
            if not pcm:
                return
            user_id = getattr(user, "id", None)
            if user_id is None:  # the member is not cached: ask the voice client by SSRC
                ssrc = getattr(getattr(data, "packet", None), "ssrc", None)
                mapping = getattr(getattr(self, "voice_client", None), "_ssrc_to_id", None) or {}
                user_id = mapping.get(ssrc) if ssrc is not None else None
            listener.on_audio(user_id, bytes(pcm))

        def cleanup(self) -> None:
            return None

    return AntonSink()


async def dave_ready(vc: Any, timeout_s: float = 10.0) -> bool:
    """Wait until the end-to-end encrypted group is ready (the DAVE fork's ``dave_ready``).

    Clients without the attribute (no DAVE fork) count as ready."""
    if not hasattr(vc, "dave_ready"):
        return True
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not getattr(vc, "dave_ready", True):
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.1)
    return True


def diagnostics(vc: Any) -> str:
    """The fork's own receive counters that matter (DAVE decryption, unknown speakers)."""
    try:
        data = vc.get_recv_diagnostics()
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    keys = (
        "rtp_packets",
        "rtp_unknown_ssrc_dropped",
        "dave_inner_decrypt_ok",
        "dave_inner_decrypt_failed",
        "dave_plaintext_rejected",
        "dave_inner_defer_drop_expired",
    )
    found = {k: v for k, v in data.items() if k in keys or (k.startswith("dave_") and "fail" in k)}
    return ", ".join(f"{k}={v}" for k, v in sorted(found.items()))


def client_class() -> Any:
    """The voice client class to connect with: the extension's if present, else discord.py's."""
    module = extension()
    if module is not None:
        return module.VoiceRecvClient
    import discord

    return discord.VoiceClient

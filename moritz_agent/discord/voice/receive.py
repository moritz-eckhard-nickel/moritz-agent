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
from collections.abc import Callable
from typing import Any

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
        self, allowed: Callable[[int], bool], deliver: Callable[[int, bytes], None]
    ) -> None:
        self.allowed = allowed
        self.deliver = deliver
        self._downmix: dict[int, Downmix] = {}
        self.dropped = 0

    def on_audio(self, user_id: int | None, pcm48_stereo: bytes) -> None:
        if user_id is None or not self.allowed(user_id):
            self.dropped += 1
            return
        mixer = self._downmix.get(user_id)
        if mixer is None:
            mixer = self._downmix[user_id] = Downmix()
        pcm = mixer.feed(pcm48_stereo)
        if pcm:
            self.deliver(user_id, pcm)

    def forget(self, user_id: int) -> None:
        self._downmix.pop(user_id, None)


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
            if pcm:
                listener.on_audio(getattr(user, "id", None), bytes(pcm))

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


def client_class() -> Any:
    """The voice client class to connect with: the extension's if present, else discord.py's."""
    module = extension()
    if module is not None:
        return module.VoiceRecvClient
    import discord

    return discord.VoiceClient

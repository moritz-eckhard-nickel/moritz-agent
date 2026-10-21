# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Nikita's voice into the voice channel: ``CallMedia`` for Discord (docs/plan/14 §9.1, §9.3).

``CallSession`` hands over mono 16 kHz audio sentence by sentence (``play``); here it becomes 20 ms
frames of 48 kHz stereo that discord.py's player thread takes one by one (``PcmSource``), encodes to
Opus and sends (encrypted, DAVE). The player is started when there is something to say and ends
after half a second of nothing, so Nikita does not sit there as "speaking" all the time.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import discord

from moritz_agent.discord.voice.pipeline import (
    FRAME_BYTES,
    FRAME_MS,
    SILENCE_FRAME,
    frames_of,
    to_48k_stereo,
)

IDLE_FRAMES = (
    25  # 500 ms without audio: the player ends (and is started again by the next sentence)
)


class PcmSource(discord.AudioSource):
    """What discord.py's player thread reads every 20 ms."""

    def __init__(self, media: DiscordMedia) -> None:
        self.media = media

    def read(self) -> bytes:
        return self.media.next_frame()

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        return None


class DiscordMedia:
    """The ``CallMedia`` of a voice channel connection."""

    def __init__(
        self,
        voice_client: Any,
        on_hangup: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.voice_client = voice_client
        self.on_hangup = on_hangup
        self._clock = clock
        self._frames: deque[bytes] = deque()
        self._lock = threading.Lock()
        self._idle = 0
        self._last_tick = clock()
        self._ticks = 0

    # -- CallMedia (called on the event loop thread) --------------------------------------------------
    def play(self, pcm: bytes) -> None:
        frames = frames_of(to_48k_stereo(pcm))
        with self._lock:
            self._frames.extend(frames)
        self.ensure_playing()

    def clear_playback(self) -> None:
        with self._lock:
            self._frames.clear()
        if self.voice_client.is_playing():
            self.voice_client.stop()

    def pending_ms(self) -> int:
        with self._lock:
            return len(self._frames) * FRAME_MS

    def hangup(self, reason: str) -> None:
        if self.on_hangup is not None:
            self.on_hangup(reason)

    def rx_packets(self) -> int | None:
        """Grows while the connection lives (Discord sends nothing while nobody talks, so a counter
        of received packets would look dead); frozen after a disconnect."""
        if self.voice_client.is_connected():
            now = self._clock()
            self._ticks += int((now - self._last_tick) * 50)
            self._last_tick = now
        else:
            self._last_tick = self._clock()
        return self._ticks

    # -- the player thread -------------------------------------------------------------------------
    def next_frame(self) -> bytes:
        with self._lock:
            if self._frames:
                self._idle = 0
                return self._frames.popleft()
            self._idle += 1
            return SILENCE_FRAME if self._idle < IDLE_FRAMES else b""

    def ensure_playing(self) -> None:
        if self.voice_client.is_connected() and not self.voice_client.is_playing():
            self._idle = 0
            self.voice_client.play(PcmSource(self), after=self._player_ended)

    def _player_ended(self, error: Exception | None) -> None:
        """The player stopped: if more arrived in the meantime, start it again."""
        if self.pending_ms():
            loop = getattr(self.voice_client, "loop", None)
            if loop is not None:
                loop.call_soon_threadsafe(self.ensure_playing)


assert len(SILENCE_FRAME) == FRAME_BYTES

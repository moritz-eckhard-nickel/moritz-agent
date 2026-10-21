# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The media side of a conversation, the same for a phone call and a Discord voice channel (P1-36).

``CallSession`` (``dialogue.py``) talks to whatever carries the audio only through this interface:
the SIP layer implements it for a call, ``discord/voice/playback.py`` for a voice channel. Incoming
audio is handed to ``CallSession.rx_audio`` (mono PCM16 16 kHz, any frame size), the end of the
conversation from the other side to ``CallSession.remote_hangup``.
"""

from __future__ import annotations

from typing import Protocol


class CallMedia(Protocol):
    """The audio side of one conversation (implemented by the SIP layer and the Discord voice layer;
    faked in tests). Thread-safe."""

    def play(self, pcm: bytes) -> None:
        """Queue mono PCM16 16 kHz for playback to the other side."""

    def clear_playback(self) -> None:
        """Drop everything not yet played."""

    def pending_ms(self) -> int:
        """Milliseconds of queued audio that has not been played yet."""

    def hangup(self, reason: str) -> None:
        """End the conversation (BYE / leave the voice channel)."""

    def rx_packets(self) -> int | None:
        """A counter that keeps growing while audio can still arrive, or None if the media layer
        cannot tell. A counter that stands still means the connection is dead."""


MediaChannel = CallMedia  # the name used in the plan (docs/plan/14 §9.1)

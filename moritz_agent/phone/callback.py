# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Anton called and somebody picked up: one second of quiet, the message, a goodbye, hang up.

Moritz, 21.10.2026: "wenn einer rangeht, spricht er nach 1 Sekunde … und tut sich danach wieder
verabschieden und auflegen und nicht zuhören". So this session never listens – incoming audio is
dropped, nothing is transcribed – it only speaks. If the other side hangs up first, it stops.
"""

from __future__ import annotations

import asyncio

from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.audio.tts import TtsError, TtsService
from moritz_agent.phone.media import CallMedia

log = get_logger("phone")
GOODBYE = "Das war's von mir. Tschüss, Moritz!"


class CallbackSession:
    """Same surface as :class:`~moritz_agent.phone.dialogue.CallSession` for the SIP layer."""

    def __init__(
        self,
        media: CallMedia,
        tts: TtsService,
        text: str,
        *,
        speak_after_s: float = 1.0,
        tail_guard_ms: int = 300,
    ) -> None:
        self.media = media
        self.tts = tts
        self.text = text.strip()
        self.speak_after_s = speak_after_s
        self.tail_guard_s = tail_guard_ms / 1000
        self._loop = asyncio.get_running_loop()
        self._gone = asyncio.Event()

    # -- called from the SIP/media threads -------------------------------------------------------
    def rx_audio(self, pcm: bytes) -> None:
        """Not listening: what the other side says is dropped."""

    def remote_hangup(self, reason: str = "caller_hangup") -> None:
        self._loop.call_soon_threadsafe(self._gone.set)

    # -- the call ----------------------------------------------------------------------------------------
    async def run(self) -> str:
        if await self._wait_or_gone(self.speak_after_s):
            return "caller_hangup"
        message = f"{self.text} {GOODBYE}".strip()
        try:
            async for chunk in self.tts.stream(message):
                if self._gone.is_set():
                    self.tts.cancel()
                    return "caller_hangup"
                self.media.play(chunk)
        except TtsError as exc:
            log.error("Rückruf: Sprachausgabe fehlgeschlagen: %s", exc)
            self.media.hangup("tts_failed")
            return "tts_failed"
        while self.media.pending_ms() > 0 and not self._gone.is_set():
            await asyncio.sleep(0.02)
        if self._gone.is_set():
            return "caller_hangup"
        await self._wait_or_gone(self.tail_guard_s)  # the last samples are still on their way
        self.media.hangup("callback_done")
        return "done"

    async def _wait_or_gone(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._gone.wait(), seconds)
        except TimeoutError:
            return False
        return True

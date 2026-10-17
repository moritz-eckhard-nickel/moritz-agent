# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Pure call state machine (docs/plan/02-architektur.md §5.2, PHONE-20 … PHONE-36).

Events go in, actions come out – no audio, no SIP, no threads – so every path of a call can be
tested exhaustively. The asyncio orchestrator (dialogue.py) performs the actions and feeds the
resulting events back.

Flow:  RINGING → GREETING → LISTENING → TRANSCRIBING → THINKING → SPEAKING → LISTENING …
Silence, unintelligible speech, slow answers and failures each have their own spoken
announcement; a hang-up from the other side ends the call from any state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    RINGING = "ringing"
    GREETING = "greeting"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ENDING = "ending"  # last words are playing, then we hang up
    ENDED = "ended"


# --- events -------------------------------------------------------------------------------
@dataclass(frozen=True)
class CallAnswered:
    """The call is connected and media is flowing."""


@dataclass(frozen=True)
class PlaybackDone:
    """Everything queued for playback has been played (including the tail guard)."""


@dataclass(frozen=True)
class UtteranceEnded:
    """The VAD found the end of an utterance."""


@dataclass(frozen=True)
class TranscriptReady:
    text: str | None  # None = nothing usable was understood


@dataclass(frozen=True)
class ReplyReady:
    text: str | None = None  # spoken with the live voice
    prompt: str | None = None  # or: id of a pre-recorded announcement
    hangup: bool = False  # hang up after speaking (goodbye)


@dataclass(frozen=True)
class ReplyFailed:
    reason: str  # "unavailable" | "error"


@dataclass(frozen=True)
class TimerFired:
    name: str  # "silence" | "thinking" | "deadline" | "max_duration"


@dataclass(frozen=True)
class RemoteHangup:
    reason: str = "caller_hangup"


Event = (
    CallAnswered
    | PlaybackDone
    | UtteranceEnded
    | TranscriptReady
    | ReplyReady
    | ReplyFailed
    | TimerFired
    | RemoteHangup
)


# --- actions ------------------------------------------------------------------------------
@dataclass(frozen=True)
class PlayPrompt:
    prompt: str


@dataclass(frozen=True)
class PlayText:
    text: str


@dataclass(frozen=True)
class StartListening:
    """Reset the VAD and start accepting caller audio."""


@dataclass(frozen=True)
class Transcribe:
    """Run speech recognition on the utterance that just ended."""


@dataclass(frozen=True)
class RequestReply:
    text: str


@dataclass(frozen=True)
class CancelReply:
    pass


@dataclass(frozen=True)
class ArmTimer:
    name: str
    seconds: float


@dataclass(frozen=True)
class CancelTimer:
    name: str


@dataclass(frozen=True)
class HangUp:
    reason: str


@dataclass(frozen=True)
class Cleanup:
    """Cancel every pending task, stop playback and synthesis, release the call's resources."""


Action = (
    PlayPrompt
    | PlayText
    | StartListening
    | Transcribe
    | RequestReply
    | CancelReply
    | ArmTimer
    | CancelTimer
    | HangUp
    | Cleanup
)


@dataclass(frozen=True)
class MachineConfig:
    silence_prompt_s: float = 10.0
    silence_hangup_s: float = 10.0
    thinking_prompt_after_s: float = 2.5
    turn_deadline_s: float = 15.0
    max_reprompts: int = 2
    max_unclear_hangup: int = 4
    max_call_duration_s: float = 1800.0
    max_failures: int = 3


class CallStateMachine:
    def __init__(self, config: MachineConfig | None = None) -> None:
        self.cfg = config or MachineConfig()
        self.state = State.RINGING
        self.end_reason: str | None = None
        self.turns = 0
        self._silence_prompted = False
        self._thinking_prompted = False
        self._unclear = 0
        self._failures = 0
        self._hangup_reason = "goodbye"

    # -- helpers -----------------------------------------------------------------------
    def _listen(self) -> list[Action]:
        self.state = State.LISTENING
        seconds = self.cfg.silence_hangup_s if self._silence_prompted else self.cfg.silence_prompt_s
        return [StartListening(), ArmTimer("silence", seconds)]

    def _speak(self, play: Action, after: str = "listen", reason: str = "goodbye") -> list[Action]:
        """Play something; afterwards listen again (SPEAKING) or hang up (ENDING)."""
        self.state = State.ENDING if after == "hangup" else State.SPEAKING
        self._hangup_reason = reason
        return [play]

    def _goodbye(self, reason: str, prompt: str = "goodbye") -> list[Action]:
        actions: list[Action] = [
            CancelTimer("silence"),
            CancelTimer("thinking"),
            CancelTimer("deadline"),
        ]
        if self.state is State.THINKING:
            actions.append(CancelReply())
        return actions + self._speak(PlayPrompt(prompt), after="hangup", reason=reason)

    def _end(self, reason: str) -> list[Action]:
        self.state = State.ENDED
        self.end_reason = reason
        return [Cleanup()]

    # -- transitions -------------------------------------------------------------------
    def handle(self, event: Event) -> list[Action]:
        """Process one event; returns the actions to perform (empty if the event does not apply)."""
        if self.state is State.ENDED:
            return []
        if isinstance(event, RemoteHangup):
            return self._end(event.reason)

        if isinstance(event, TimerFired) and event.name == "max_duration":
            if self.state in (State.ENDING, State.RINGING):
                return []
            return self._goodbye("max_duration")

        match self.state:
            case State.RINGING:
                return self._ringing(event)
            case State.GREETING:
                return self._greeting(event)
            case State.LISTENING:
                return self._listening(event)
            case State.TRANSCRIBING:
                return self._transcribing(event)
            case State.THINKING:
                return self._thinking(event)
            case State.SPEAKING:
                return self._speaking(event)
            case State.ENDING:
                return self._ending(event)
        return []

    def _ringing(self, event: Event) -> list[Action]:
        if isinstance(event, CallAnswered):
            self.state = State.GREETING
            return [ArmTimer("max_duration", self.cfg.max_call_duration_s), PlayPrompt("greeting")]
        return []

    def _greeting(self, event: Event) -> list[Action]:
        if isinstance(event, PlaybackDone):
            return self._listen()
        return []

    def _listening(self, event: Event) -> list[Action]:
        if isinstance(event, UtteranceEnded):
            self.state = State.TRANSCRIBING
            self._silence_prompted = False
            return [CancelTimer("silence"), Transcribe()]
        if isinstance(event, TimerFired) and event.name == "silence":
            if not self._silence_prompted:
                self._silence_prompted = True
                return self._speak(PlayPrompt("still_there"))
            return self._goodbye("silence_timeout")
        return []

    def _transcribing(self, event: Event) -> list[Action]:
        if not isinstance(event, TranscriptReady):
            return []
        if event.text is None:
            self._unclear += 1
            if self._unclear >= self.cfg.max_unclear_hangup:
                return self._goodbye("unintelligible")
            prompt = (
                "not_understood"
                if self._unclear <= self.cfg.max_reprompts
                else "not_understood_again"
            )
            return self._speak(PlayPrompt(prompt))
        self._unclear = 0
        self.turns += 1
        self.state = State.THINKING
        self._thinking_prompted = False
        return [
            RequestReply(event.text),
            ArmTimer("thinking", self.cfg.thinking_prompt_after_s),
            ArmTimer("deadline", self.cfg.turn_deadline_s),
        ]

    def _thinking(self, event: Event) -> list[Action]:
        if isinstance(event, TimerFired):
            if event.name == "thinking" and not self._thinking_prompted:
                self._thinking_prompted = True
                return [PlayPrompt("thinking")]  # queued; the state stays THINKING
            if event.name == "deadline":
                return self._failed("timeout", cancel=True)
            return []
        if isinstance(event, ReplyReady):
            self._failures = 0
            actions: list[Action] = [CancelTimer("thinking"), CancelTimer("deadline")]
            play: Action = PlayPrompt(event.prompt) if event.prompt else PlayText(event.text or "")
            return actions + self._speak(
                play, after="hangup" if event.hangup else "listen", reason="goodbye"
            )
        if isinstance(event, ReplyFailed):
            return self._failed("error")
        return []

    def _failed(self, kind: str, cancel: bool = False) -> list[Action]:
        self._failures += 1
        actions: list[Action] = [CancelTimer("thinking"), CancelTimer("deadline")]
        if cancel:
            actions.append(CancelReply())
        prompt = "timeout" if kind == "timeout" else "error_generic"
        if self._failures >= self.cfg.max_failures:
            return actions + self._speak(
                PlayPrompt("error_generic"), after="hangup", reason="errors"
            )
        return actions + self._speak(PlayPrompt(prompt))

    def _speaking(self, event: Event) -> list[Action]:
        if isinstance(event, PlaybackDone):
            return self._listen()
        return []

    def _ending(self, event: Event) -> list[Action]:
        if isinstance(event, PlaybackDone):
            self.state = State.ENDED
            self.end_reason = self._hangup_reason
            return [HangUp(self._hangup_reason), Cleanup()]
        return []

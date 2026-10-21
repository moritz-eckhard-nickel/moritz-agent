# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

from moritz_agent.phone.state_machine import (
    ArmTimer,
    CallAnswered,
    CallStateMachine,
    CancelReply,
    CancelTimer,
    Cleanup,
    HangUp,
    MachineConfig,
    PlaybackDone,
    PlayPrompt,
    PlayText,
    RemoteHangup,
    ReplyFailed,
    ReplyReady,
    RequestReply,
    StartListening,
    State,
    TimerFired,
    Transcribe,
    TranscriptReady,
    UtteranceEnded,
)


def listening_machine(**overrides) -> CallStateMachine:
    machine = CallStateMachine(MachineConfig(**overrides))
    assert machine.handle(CallAnswered()) == [
        ArmTimer("max_duration", machine.cfg.max_call_duration_s),
        PlayPrompt("greeting"),
    ]
    assert machine.state is State.GREETING
    actions = machine.handle(PlaybackDone())
    assert actions == [StartListening(), ArmTimer("silence", machine.cfg.silence_prompt_s)]
    assert machine.state is State.LISTENING
    return machine


def to_thinking(machine: CallStateMachine, text: str = "Wie viel Uhr haben wir?") -> None:
    assert machine.handle(UtteranceEnded()) == [CancelTimer("silence"), Transcribe()]
    actions = machine.handle(TranscriptReady(text))
    assert actions[0] == RequestReply(text)
    assert machine.state is State.THINKING


def kinds(actions) -> list[type]:
    return [type(a) for a in actions]


def test_normal_turn_and_next_question():
    m = listening_machine()
    to_thinking(m)
    actions = m.handle(ReplyReady(text="Es ist neunzehn Uhr zwölf."))
    assert actions == [
        CancelTimer("thinking"),
        CancelTimer("deadline"),
        PlayText("Es ist neunzehn Uhr zwölf."),
    ]
    assert m.state is State.SPEAKING
    assert m.handle(PlaybackDone())[0] == StartListening()
    assert m.state is State.LISTENING
    to_thinking(m, "Und wie ist das Datum?")
    assert m.turns == 2


def test_three_turns_in_one_call():
    m = listening_machine()
    for i in range(3):
        to_thinking(m, f"Frage {i}")
        m.handle(ReplyReady(text="Antwort"))
        m.handle(PlaybackDone())
    assert m.turns == 3 and m.state is State.LISTENING


def test_prerecorded_reply_and_goodbye_hangs_up_after_playing():
    m = listening_machine()
    to_thinking(m, "Tschüss")
    actions = m.handle(ReplyReady(prompt="goodbye", hangup=True))
    assert PlayPrompt("goodbye") in actions and m.state is State.ENDING
    assert m.handle(UtteranceEnded()) == []  # caller noise while we say goodbye
    done = m.handle(PlaybackDone())
    assert done == [HangUp("goodbye"), Cleanup()]
    assert m.state is State.ENDED and m.end_reason == "goodbye"


def test_silence_asks_once_then_hangs_up():
    m = listening_machine()
    assert m.handle(TimerFired("silence")) == [PlayPrompt("still_there")]
    assert m.state is State.SPEAKING
    actions = m.handle(PlaybackDone())
    assert actions == [StartListening(), ArmTimer("silence", m.cfg.silence_hangup_s)]
    goodbye = m.handle(TimerFired("silence"))
    assert PlayPrompt("goodbye") in goodbye and m.state is State.ENDING
    assert m.handle(PlaybackDone()) == [HangUp("silence_timeout"), Cleanup()]


def test_speech_after_silence_prompt_resets_the_silence_logic():
    m = listening_machine()
    m.handle(TimerFired("silence"))
    m.handle(PlaybackDone())
    to_thinking(m)
    m.handle(ReplyReady(text="Antwort"))
    actions = m.handle(PlaybackDone())
    assert actions[1] == ArmTimer(
        "silence", m.cfg.silence_prompt_s
    )  # back to the short first timeout


def test_unintelligible_speech_escalates_then_hangs_up():
    m = listening_machine(max_reprompts=2, max_unclear_hangup=4)
    prompts = []
    for _ in range(3):
        m.handle(UtteranceEnded())
        actions = m.handle(TranscriptReady(None))
        prompts.append(actions[0])
        assert m.state is State.SPEAKING
        m.handle(PlaybackDone())
    assert prompts == [
        PlayPrompt("not_understood"),
        PlayPrompt("not_understood"),
        PlayPrompt("not_understood_again"),
    ]
    m.handle(UtteranceEnded())
    actions = m.handle(TranscriptReady(None))
    assert PlayPrompt("goodbye") in actions and m.state is State.ENDING
    assert m.handle(PlaybackDone())[0] == HangUp("unintelligible")


def test_understood_speech_resets_the_unclear_counter():
    m = listening_machine(max_unclear_hangup=2)
    m.handle(UtteranceEnded())
    m.handle(TranscriptReady(None))
    m.handle(PlaybackDone())
    to_thinking(m)
    m.handle(ReplyReady(text="ok"))
    m.handle(PlaybackDone())
    m.handle(UtteranceEnded())
    m.handle(TranscriptReady(None))  # first unclear again, not the second
    assert m.state is State.SPEAKING


def test_slow_answer_plays_thinking_prompt_once_then_answer():
    m = listening_machine()
    to_thinking(m)
    assert m.handle(TimerFired("thinking")) == [PlayPrompt("thinking")]
    assert m.state is State.THINKING
    assert m.handle(TimerFired("thinking")) == []  # only once per turn
    assert m.handle(PlaybackDone()) == []  # the thinking prompt finished: keep waiting
    actions = m.handle(ReplyReady(text="Gefunden."))
    assert PlayText("Gefunden.") in actions and m.state is State.SPEAKING


def test_deadline_cancels_the_reply_and_apologizes():
    m = listening_machine()
    to_thinking(m)
    actions = m.handle(TimerFired("deadline"))
    assert CancelReply() in actions and PlayPrompt("timeout") in actions
    assert m.handle(PlaybackDone())[0] == StartListening()


def test_reply_failure_speaks_error_and_keeps_the_call():
    m = listening_machine()
    to_thinking(m)
    actions = m.handle(ReplyFailed("unavailable"))
    assert PlayPrompt("error_generic") in actions and m.state is State.SPEAKING
    assert m.handle(PlaybackDone())[0] == StartListening()


def test_repeated_failures_end_the_call():
    m = listening_machine(max_failures=2)
    to_thinking(m)
    m.handle(ReplyFailed("error"))
    m.handle(PlaybackDone())
    to_thinking(m)
    actions = m.handle(ReplyFailed("error"))
    assert m.state is State.ENDING and PlayPrompt("error_generic") in actions
    assert m.handle(PlaybackDone())[0] == HangUp("errors")


def test_remote_hangup_cleans_up_from_every_state():
    def reach(state: State) -> CallStateMachine:
        m = CallStateMachine()
        if state is State.RINGING:
            return m
        m = listening_machine()
        if state is State.LISTENING:
            return m
        if state is State.TRANSCRIBING:
            m.handle(UtteranceEnded())
            return m
        to_thinking(m)
        if state is State.THINKING:
            return m
        m.handle(ReplyReady(text="x", hangup=state is State.ENDING))
        return m

    for state in (
        State.RINGING,
        State.LISTENING,
        State.TRANSCRIBING,
        State.THINKING,
        State.SPEAKING,
        State.ENDING,
    ):
        m = reach(state)
        assert m.state is state, state
        assert m.handle(RemoteHangup()) == [Cleanup()]
        assert m.state is State.ENDED and m.end_reason == "caller_hangup"
        assert m.handle(PlaybackDone()) == []  # nothing happens after the end


def test_max_duration_says_goodbye():
    m = listening_machine()
    actions = m.handle(TimerFired("max_duration"))
    assert PlayPrompt("goodbye") in actions and m.state is State.ENDING
    assert m.handle(PlaybackDone())[0] == HangUp("max_duration")


def test_max_duration_during_thinking_cancels_the_reply():
    m = listening_machine()
    to_thinking(m)
    assert CancelReply() in m.handle(TimerFired("max_duration"))


def test_events_that_do_not_apply_are_ignored():
    m = listening_machine()
    assert m.handle(TranscriptReady("zu früh")) == []
    assert m.handle(ReplyReady(text="zu früh")) == []
    assert m.handle(TimerFired("thinking")) == []
    assert m.state is State.LISTENING
    greeting = CallStateMachine()
    assert greeting.handle(UtteranceEnded()) == []


# -- Discord voice: first prompt, going quiet, being talked over (docs/plan/14 §9) ------------------------------
def test_the_first_prompt_can_be_something_else_than_the_greeting():
    from moritz_agent.phone.state_machine import CallAnswered, CallStateMachine, PlayPrompt

    machine = CallStateMachine()
    actions = machine.handle(CallAnswered("yes"))
    assert PlayPrompt("yes") in actions
    assert PlayPrompt("greeting") in CallStateMachine().handle(CallAnswered())


def test_silence_ends_with_the_configured_last_words():
    from moritz_agent.phone.state_machine import (
        CallAnswered,
        CallStateMachine,
        MachineConfig,
        PlaybackDone,
        PlayPrompt,
        TimerFired,
    )

    machine = CallStateMachine(MachineConfig(silence_goodbye="going_quiet"))
    machine.handle(CallAnswered())
    machine.handle(PlaybackDone())
    machine.handle(TimerFired("silence"))  # "Bist du noch da?"
    machine.handle(PlaybackDone())
    actions = machine.handle(TimerFired("silence"))
    assert PlayPrompt("going_quiet") in actions


def test_talking_over_anton_stops_the_playback_and_listens():
    from moritz_agent.phone.state_machine import (
        ArmTimer,
        BargeIn,
        CallAnswered,
        CallStateMachine,
        PlaybackDone,
        StartListening,
        State,
        StopPlayback,
    )

    machine = CallStateMachine()
    machine.handle(CallAnswered())
    assert machine.state is State.GREETING
    assert machine.handle(BargeIn()) == []  # the greeting is not interrupted
    machine.handle(PlaybackDone())
    machine.state = State.SPEAKING
    actions = machine.handle(BargeIn())
    assert actions[0] == StopPlayback() and StartListening() in actions
    assert any(isinstance(a, ArmTimer) and a.name == "silence" for a in actions)
    assert machine.state is State.LISTENING
    assert machine.handle(BargeIn()) == []  # already listening


# -- the kitchen timer (SKILL "Eieruhr") ------------------------------------------------------------------------------
def test_a_timer_that_runs_out_while_listening_is_announced_at_once():
    from moritz_agent.phone.state_machine import (
        CallAnswered,
        CallStateMachine,
        PlaybackDone,
        PlayPrompt,
        State,
        TimerAlarm,
    )

    machine = CallStateMachine()
    machine.handle(CallAnswered())
    machine.handle(PlaybackDone())
    assert machine.state is State.LISTENING
    actions = machine.handle(TimerAlarm("Eier"))
    assert PlayPrompt("timer_done") in actions and machine.state is State.SPEAKING
    again = machine.handle(PlaybackDone())  # afterwards the conversation goes on
    assert machine.state is State.LISTENING and any(
        type(a).__name__ == "StartListening" for a in again
    )


def test_a_timer_that_runs_out_while_busy_waits_for_its_turn():
    from moritz_agent.phone.state_machine import (
        CallAnswered,
        CallStateMachine,
        PlaybackDone,
        PlayPrompt,
        State,
        TimerAlarm,
    )

    machine = CallStateMachine()
    machine.handle(CallAnswered())
    assert machine.handle(TimerAlarm()) == []  # during the greeting: later
    actions = machine.handle(PlaybackDone())
    assert actions == [PlayPrompt("timer_done")] and machine.state is State.SPEAKING
    machine.handle(PlaybackDone())
    assert machine.state is State.LISTENING
    machine.state = State.ENDING
    assert machine.handle(TimerAlarm()) == []  # the call is over: nobody to tell

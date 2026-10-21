# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import pytest

from moritz_agent.agent.fastpath import answer, classify


@pytest.mark.parametrize(
    ("utterance", "intent"),
    [
        ("Wie viel Uhr ist es?", "time"),
        ("Wie spät ist es gerade?", "time"),
        ("Welcher Tag ist heute?", "weekday"),
        ("Welches Datum haben wir heute", "date"),
        ("Welcher Wochentag ist heute?", "weekday"),
        ("Welche Kalenderwoche ist gerade?", "calendar_week"),
        ("Welcher Tag ist morgen?", "tomorrow"),
        ("Welcher Tag war gestern?", "yesterday"),
        ("Wer bist du?", "identity"),
        ("Was kannst du?", "help"),
        ("Tschüss", "goodbye"),
        ("Auf Wiederhören", "goodbye"),
        ("Kannst du das wiederholen?", "repeat"),
    ],
)
def test_classification(utterance, intent):
    assert classify(utterance) == intent


@pytest.mark.parametrize(
    "utterance",
    [
        "",
        "Um wie viel Uhr fährt der Zug nach Frankfurt?",  # the clock is not what is asked for
        "Erzähl mir etwas über die Geschichte von Hessen und was dort im Mittelalter passiert ist",
        "Wie wird das Wetter morgen in Frankfurt?",
    ],
)
def test_not_a_fast_path(utterance):
    assert classify(utterance) is None


def test_time_comes_from_the_clock_not_from_a_model():
    result = answer("Wie viel Uhr ist es?")
    assert result is not None
    assert result.intent == "time"
    assert result.text and "Uhr" in result.text


def test_goodbye_hangs_up_with_prerecorded_announcement():
    result = answer("Tschüss")
    assert result is not None
    assert result.hangup is True
    assert result.prompt == "goodbye"


def test_identity_uses_the_configured_name():
    result = answer("Wer bist du?", assistant_name="Anton")
    assert result is not None and "Anton" in (result.text or "")


def test_repeat_returns_last_reply():
    result = answer("Kannst du das wiederholen?", last_reply="Es ist zwölf Uhr.")
    assert result is not None and result.text == "Es ist zwölf Uhr."

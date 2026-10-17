# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import re

import pytest

from moritz_agent.phone.audio.textnorm import cardinal, normalize_for_tts, ordinal, split_sentences


@pytest.mark.parametrize(
    ("number", "words"),
    [
        (0, "null"),
        (1, "eins"),
        (12, "zwölf"),
        (21, "einundzwanzig"),
        (100, "hundert"),
        (101, "hunderteins"),
        (1000, "tausend"),
        (1234, "tausendzweihundertvierunddreißig"),
        (2026, "zweitausendsechsundzwanzig"),
        (1_000_000, "eine Million"),
        (2_000_000, "zwei Millionen"),
    ],
)
def test_cardinals(number, words):
    assert cardinal(number) == words


@pytest.mark.parametrize(
    ("number", "words"),
    [(1, "erste"), (3, "dritte"), (7, "siebte"), (16, "sechzehnte"), (21, "einundzwanzigste")],
)
def test_ordinals(number, words):
    assert ordinal(number) == words


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("Es ist 19:12 Uhr.", "Es ist neunzehn Uhr zwölf."),
        (
            "Heute ist der 16.10.2026.",
            "Heute ist der sechzehnte Oktober zweitausendsechsundzwanzig.",
        ),
        ("Das kostet 4,50 €.", "Das kostet vier Euro fünfzig."),
        (
            "Es sind 12 °C und 5 km/h Wind.",
            "Es sind zwölf Grad Celsius und fünf Kilometer pro Stunde Wind.",
        ),
        ("Am 1. Mai", "Am ersten Mai"),
        ("z. B. 100 Menschen", "zum Beispiel hundert Menschen"),
        ("**Wichtig**: 21 Äpfel 😀", "Wichtig: einundzwanzig Äpfel"),
        ("Es gibt 1.234 Fälle.", "Es gibt tausendzweihundertvierunddreißig Fälle."),
        ("3 Mio. Einwohner", "drei Millionen Einwohner"),
    ],
)
def test_normalize_to_spoken_german(text, spoken):
    assert normalize_for_tts(text) == spoken


def test_no_digit_survives():
    text = (
        "Am 3.1.2027 um 07:05 Uhr: 2 Autos, 17,5 % von 1.000.000, Tel. 0151 1234567, Nr. 5, 40 km."
    )
    assert not re.search(r"\d", normalize_for_tts(text))


def test_split_sentences():
    assert split_sentences("Hallo Welt. Wie geht es dir? Gut!") == [
        "Hallo Welt.",
        "Wie geht es dir?",
        "Gut!",
    ]
    assert split_sentences("   ") == []

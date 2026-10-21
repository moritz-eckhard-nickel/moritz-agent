# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Preparing sentences: normalizing, dialect, number words, phonetics (docs/plan/13 §4.1, §9.1)."""

from __future__ import annotations

import pytest

from moritz_agent.skills.text import dialect
from moritz_agent.skills.text.normalize import prepare
from moritz_agent.skills.text.numbers import (
    clock_phrases,
    parse_cardinal,
    parse_ordinal,
    postcode_candidates,
    words_to_digits,
)
from moritz_agent.skills.text.phonetic import phonetic_code


@pytest.mark.parametrize(
    ("word", "value"),
    [
        ("null", 0), ("eins", 1), ("zwölf", 12), ("fünfunddreißig", 35), ("einundzwanzig", 21),
        ("hundert", 100), ("hundertfünf", 105), ("dreihundertvierzig", 340), ("tausend", 1000),
        ("zweitausendsechsundzwanzig", 2026), ("siebenhunderteinundachtzig", 781),
        ("fünfunddreißigtausendsiebenhunderteinundachtzig", 35781), ("neunundneunzig", 99),
        ("neunzehnhundertneunzig", 1990), ("neunzehnhundert", 1900),
        ("achtzehnhundertdreiundsiebzig", 1873),
    ],
)  # fmt: skip
def test_cardinals(word, value):
    assert parse_cardinal(word) == value


@pytest.mark.parametrize("word", ["ein", "eine", "einen", "hallo", "wetter", "", "elfhundert1"])
def test_articles_and_words_are_no_numbers(word):
    assert parse_cardinal(word) is None


@pytest.mark.parametrize(
    ("word", "value"),
    [("ersten", 1), ("dritten", 3), ("siebten", 7), ("achten", 8), ("dreizehnten", 13),
     ("zwanzigsten", 20), ("vierundzwanzigsten", 24), ("einunddreißigsten", 31)],
)  # fmt: skip
def test_ordinals(word, value):
    assert parse_ordinal(word) == value


def test_words_to_digits_keeps_articles():
    assert (
        words_to_digits("ich habe ein auto und zwei fahrräder")
        == "ich habe ein auto und 2 fahrräder"
    )


def test_ordinal_only_in_date_context():
    assert words_to_digits("am vierundzwanzigsten dezember") == "am 24. dezember"
    assert "zweite" in words_to_digits("das zweite buch")  # not a date → untouched


@pytest.mark.parametrize(
    ("spoken", "written"),
    [
        ("halb vier", "3:30"), ("viertel nach drei", "3:15"), ("viertel vor vier", "3:45"),
        ("viertel acht", "7:15"), ("dreiviertel acht", "7:45"), ("halb 12", "11:30"),
    ],
)  # fmt: skip
def test_clock_phrases(spoken, written):
    text = words_to_digits(spoken)
    assert clock_phrases(text) == written


def test_quarter_dialect_can_be_switched_off():
    assert clock_phrases("viertel 8", quarter_dialect=False) == "viertel 8"


@pytest.mark.parametrize(
    "spoken",
    [
        "3 5 7 8 1", "35 781", "35781", "drei fünf sieben acht eins", "fünfunddreißig sieben einundachtzig",
        "fünfunddreißigtausendsiebenhunderteinundachtzig", "35 7 81", "357 81",
    ],
)  # fmt: skip
def test_spoken_postal_codes(spoken):
    assert postcode_candidates(words_to_digits(spoken)) == ["35781"]


def test_no_postal_code_in_ordinary_numbers():
    assert postcode_candidates("17 mal 23") == []
    assert postcode_candidates("um 19 uhr 12") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Wie viel Uhr haben wir?", "wie viel uhr haben wir"),
        ("Anton, wie spät ist es?", "wie spät ist es"),
        ("Hey Anton wie spät ist es", "wie spät ist es"),
        ("Kannst du mir bitte mal sagen, wie spät es ist?", "wie spät es ist"),
        ("Sag mir bitte mal die Uhrzeit", "die uhrzeit"),
        ("Was ist 17 mal 23?", "was ist 17 mal 23"),
        ("Wie wird's morgen?", "wie wird es morgen"),
        ("Wie viele Tage noch bis zum 24.12.?", "wie viele tage noch bis zum 24.12."),
        ("Um halb vier", "um 3:30"),
        ("Weißt du, wie spät es ist", "wie spät es ist"),
        ("Wetter in sechs null drei eins eins", "wetter in 6 0 3 1 1"),
        ("19,90 Euro netto", "19,90 euro netto"),
    ],
)  # fmt: skip
def test_prepare(raw, expected):
    assert prepare(raw).text == expected


def test_prepare_remembers_that_anton_was_addressed():
    assert prepare("Anton, wie spät ist es?").addressed
    assert not prepare("Wie spät ist es?").addressed
    assert prepare("Anton").text == "anton"


def test_prepare_never_returns_empty_text():
    assert prepare("äh").text


# -- dialect: every dictionary entry has a test ---------------------------------------------
@pytest.mark.parametrize(("source", "target"), sorted(dialect.entries().items()))
def test_every_dialect_entry(source, target):
    result = dialect.to_standard(source)
    assert result == " ".join(target.split())


def test_dialect_has_enough_entries():
    assert len(dialect.entries()) >= 50  # SKILL-21


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Wie isses Wedder morsche?", "wie ist es wetter morgen"),
        ("Brauch isch en Schermche heit?", "brauche ich einen regenschirm heute"),
        ("Wie viel Uhr hammer?", "wie viel uhr haben wir"),
        ("Ei gude wie!", "guten tag"),
        ("Was hammer heit fürn Datum?", "was haben wir heute fürn datum"),
        ("Des is net schlimm, gell", "das ist nicht schlimm"),
    ],
)
def test_dialect_in_sentences(raw, expected):
    assert prepare(raw).text == expected


@pytest.mark.parametrize(
    ("a", "b"),
    [("Weilburg", "Weilborg"), ("Wetzlar", "Wetzler"), ("Limburg", "Limburk"), ("Gießen", "Giessen"), ("Meyer", "Maier")],
)  # fmt: skip
def test_phonetic_neighbours_share_a_code(a, b):
    assert phonetic_code(a) == phonetic_code(b)


def test_phonetic_codes_differ_for_different_names():
    assert phonetic_code("Weilburg") != phonetic_code("Wetzlar")
    assert phonetic_code("") == ""
    assert phonetic_code("Müller") == "657"


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("was ist zwei komma fünf mal vier", "was ist 2,5 mal 4"),
        ("null komma fünf plus eins komma fünfundzwanzig", "0,5 plus 1,25"),
        ("das komma steht falsch", "das komma steht falsch"),
    ],
)
def test_spoken_decimals(spoken, expected):
    assert words_to_digits(spoken) == expected

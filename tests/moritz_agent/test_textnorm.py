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


# -- weather, units, money, postcodes (docs/plan/13 §9.3, P1-29) -----------------------------------------------------
@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("−3 °C", "minus drei Grad Celsius"),  # U+2212
        ("-3 Grad", "minus drei Grad"),
        ("Heute −1 °C, morgen 4 °C.", "Heute minus ein Grad Celsius, morgen vier Grad Celsius."),
        ("12–15 °C", "zwölf bis fünfzehn Grad Celsius"),
        ("12 bis 15 Grad", "zwölf bis fünfzehn Grad"),
        ("von 8-10 Uhr", "von acht bis zehn Uhr"),
        ("12:30–13:00 Uhr", "zwölf Uhr dreißig bis dreizehn Uhr"),
        ("2,5 l/m²", "zweieinhalb Liter pro Quadratmeter"),
        ("1,5 l/m²", "eineinhalb Liter pro Quadratmeter"),
        ("2,5 mm", "zwei Komma fünf Millimeter"),
        ("0,5 mm/h", "null Komma fünf Millimeter pro Stunde"),
        ("1012 hPa", "tausendzwölf Hektopascal"),
        ("70 km/h", "siebzig Kilometer pro Stunde"),
        ("Bft 7", "Windstärke sieben"),
        ("10 m/s", "zehn Meter pro Sekunde"),
        ("18 µg/m³", "achtzehn Mikrogramm pro Kubikmeter"),
        ("4,2 ct/kWh", "vier Komma zwei Cent pro Kilowattstunde"),
        ("1,729 €", "ein Euro dreiundsiebzig"),
        ("1,719 €", "ein Euro zweiundsiebzig"),
        ("2,00 €", "zwei Euro"),
        ("1,5 €", "ein Euro fünfzig"),
        ("06:12 Uhr", "sechs Uhr zwölf"),
        ("1,42 m", "ein Meter zweiundvierzig"),
        ("0,96 m", "null Meter sechsundneunzig"),
        ("UV-Index 6", "U V Index sechs"),
        ("PLZ 35781", "Postleitzahl drei fünf sieben acht eins"),
        ("Postleitzahl 35781", "Postleitzahl drei fünf sieben acht eins"),
        ("Wetter in 35781 Weilburg", "Wetter in drei fünf sieben acht eins Weilburg"),
        (
            "Das sind 35781 Menschen.",
            "Das sind fünfunddreißigtausendsiebenhunderteinundachtzig Menschen.",
        ),
        ("DWD", "Deutscher Wetterdienst"),
        ("Wind aus NNW und SW", "Wind aus Nordnordwest und Südwest"),
        ("Daten von Open-Meteo", "Daten von Open Meteo"),
        ("2 m² und 3 m³", "zwei Quadratmeter und drei Kubikmeter"),
        ("3 kW", "drei Kilowatt"),
    ],
)
def test_weather_units_money_and_postcodes(text, spoken):
    assert normalize_for_tts(text) == spoken


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("1 Minute", "eine Minute"),
        ("in 1 Stunde", "in einer Stunde".replace("einer", "eine")),
        ("vor 1 Woche", "vor eine Woche"),  # the case ending is not our job
        ("1 Pfund", "ein Pfund"),
        ("1 Tag", "ein Tag"),
        ("1 Liter", "ein Liter"),
        ("um 1 Uhr", "um ein Uhr"),
        ("1 Million", "eine Million"),
        ("Platz 1", "Platz eins"),
        ("Es gibt 1 Name", "Es gibt ein Name"),
    ],
)
def test_one_takes_the_gender_of_what_follows(text, spoken):
    assert normalize_for_tts(text) == spoken


def test_nothing_digit_like_is_left_in_typical_answers():
    sentences = [
        "Morgen 4–9 °C, bis zu 2,5 l/m² Regen, Wind 25 km/h aus SW, Luftdruck 1008 hPa.",
        "Der Pegel der Lahn in Limburg beträgt 1,42 m.",
        "Super E10 kostet 1,729 € je Liter; Strom 4,2 ct/kWh.",
        "Pollenflug am 18.10.: Hasel 2, Erle 3. UV-Index 6. PM2.5 liegt bei 18 µg/m³.",
        "−3 °C um 06:45 Uhr in 35781 Weilburg.",
    ]
    for sentence in sentences:
        assert not re.search(r"\d", normalize_for_tts(sentence)), sentence


def test_the_pronunciation_list_is_valid_and_complete():
    import tomllib

    from moritz_agent.phone.audio.textnorm import PRONUNCIATION_FILE, _pronunciations

    data = tomllib.loads(PRONUNCIATION_FILE.read_text(encoding="utf-8"))
    assert data["woerter"] and data["ausdruecke"] and data["buchstaben"]["words"]
    assert all(isinstance(v, str) and v.strip() for v in data["woerter"].values())
    assert len(_pronunciations()) >= len(data["woerter"]) + len(data["ausdruecke"])
    assert normalize_for_tts(
        "Die KI sagt: PIN 4711"
    ) == "Die K I sagt: PIN vier tausend siebenhundertelf".replace(
        "PIN vier tausend siebenhundertelf", "P I N viertausendsiebenhundertelf"
    )
    assert normalize_for_tts("Super E10, E5 und CO2") == "Super E zehn, E fünf und C O zwei"


def test_a_missing_pronunciation_file_changes_nothing(tmp_path):
    from moritz_agent.phone.audio.textnorm import _pronunciations

    assert _pronunciations(tmp_path / "gibt-es-nicht.toml") == ()


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("10.000,00 €", "zehntausend Euro"),
        ("1.234,56 €", "tausendzweihundertvierunddreißig Euro sechsundfünfzig"),
        ("12.345,6 km", "zwölftausenddreihundertfünfundvierzig Komma sechs Kilometer"),
        ("1.234,5 kg", "tausendzweihundertvierunddreißigeinhalb Kilogramm"),
        ("0,5 Stunden", "null Komma fünf Stunden"),
        ("3,14159", "drei Komma eins vier eins fünf neun"),
        ("3/4 Liter", "drei Viertel Liter"),
        ("-5–-2 °C", "minus fünf bis minus zwei Grad Celsius"),
        ("Am 2024-10-21", "Am einundzwanzigsten Oktober zweitausendvierundzwanzig"),
        ("Am 1.10.2026", "Am ersten Oktober zweitausendsechsundzwanzig"),
    ],
)
def test_thousands_fractions_negative_ranges_and_iso_dates(text, spoken):
    assert normalize_for_tts(text) == spoken

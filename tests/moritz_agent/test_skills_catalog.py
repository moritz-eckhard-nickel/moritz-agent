# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Golden answers of the offline skills with a fixed clock (Sunday, 18 Oct 2026, 19:12)."""

from __future__ import annotations

from datetime import datetime

import pytest

from .skills_util import BERLIN, Session, ask

GOLDEN = [
    # P1-29: phrasings found missing by the 800 utterance corpus
    ("Wie viele Kilometer sind 10 Meilen?", "10 Meilen sind etwa 16,1 Kilometer."),
    (
        "Wie viel sind 100 Kilometer pro Stunde in Meilen pro Stunde?",
        "100 Kilometer pro Stunde sind etwa 62,1 Meilen pro Stunde.",
    ),
    ("Wie viel Grad Fahrenheit sind 20 Grad Celsius?", "20 Grad Celsius sind 68 Grad Fahrenheit."),
    ("Welcher Ort ist die 35781?", "35781 ist Weilburg im Landkreis Limburg-Weilburg, Hessen."),
    ("Wie viel ist 17,5 gerundet?", "Gerundet sind das 18."),
    ("Wie lange dauert es noch bis Neujahr?", "Noch 75 Tage bis Neujahr."),
    ("Wie lange ist Neujahr her?", "Seit Neujahr sind 290 Tage vergangen."),
    ("Wie viel Prozent vom Jahr sind schon vorbei?", "Etwa 80 Prozent – 291 von 365 Tagen."),
    ("Wie viel Uhr ist es?", "Es ist 19 Uhr 12."),
    ("Wie spät isses?", "Es ist 19 Uhr 12."),
    ("Wie viel Uhr hammer?", "Es ist 19 Uhr 12."),
    ("Datum und Uhrzeit?", "Heute ist Sonntag, der 18. Oktober 2026, und es ist 19 Uhr 12."),
    (
        "Wie spät ist es in New York?",
        "In New York ist es jetzt 13 Uhr 12, 6 Stunden früher als hier.",
    ),
    (
        "Uhrzeit in Tokio?",
        "In Tokio ist es jetzt 2 Uhr 12, 7 Stunden später als hier, das ist morgen.",
    ),
    ("Wie spät ist es in drei Stunden?", "In 3 Stunden ist es 22 Uhr 12."),
    ("Wie lange noch bis 22 Uhr?", "Noch 2 Stunden und 48 Minuten."),
    ("Wie lange ist es noch bis Mitternacht?", "Noch 4 Stunden und 48 Minuten."),
    (
        "Wann wird die Uhr umgestellt?",
        "Am Sonntag, 25. Oktober, um 3 Uhr wird die Uhr auf 2 Uhr zurückgestellt – eine Stunde länger schlafen.",
    ),
    (
        "Haben wir schon Winterzeit?",
        "Nein, noch gilt die Sommerzeit – bis Sonntag, 25. Oktober. Dann wird die Uhr eine Stunde zurückgestellt.",
    ),
    ("Welches Datum ist heute?", "Heute ist Sonntag, der 18. Oktober 2026."),
    ("Was hammer heit fürn Datum?", "Heute ist Sonntag, der 18. Oktober 2026."),
    ("Welcher Tag ist heute?", "Heute ist Sonntag."),
    ("Welcher Tag ist morgen?", "Morgen ist Montag, der 19. Oktober."),
    ("Welcher Tag war gestern?", "Gestern war Samstag, der 17. Oktober."),
    ("Was für ein Tag ist der 24. Dezember?", "Der 24. Dezember ist ein Donnerstag."),
    ("Welcher Wochentag war der 3. Oktober 1990?", "Der 3. Oktober 1990 war ein Mittwoch."),
    ("Welches Datum ist in drei Wochen?", "In 3 Wochen ist Sonntag, der 8. November."),
    ("Wie viele Tage noch bis Weihnachten?", "Noch 67 Tage bis Heiligabend."),
    ("Wie viele Tage bis zum Wochenende?", "Noch 6 Tage bis zum Wochenende."),
    ("Wie viele Tage bis zum ersten Advent?", "Noch 42 Tage bis zum ersten Advent."),
    ("Wie viele Wochen bis Weihnachten?", "Noch 9 Wochen und 4 Tage bis Heiligabend."),
    ("Wie viele Tage sind seit Neujahr vergangen?", "Seit Neujahr sind 290 Tage vergangen."),
    (
        "Wie viele Tage liegen zwischen dem 1. März und dem 15. April?",
        "Dazwischen liegen 45 Tage – das sind 6 Wochen und 3 Tage.",
    ),
    ("Welche KW haben wir?", "Wir haben Kalenderwoche 42."),
    (
        "Wann ist KW 50?",
        "Kalenderwoche 50 geht von Montag, 7. Dezember, bis Sonntag, 13. Dezember.",
    ),
    (
        "Der wievielte Tag des Jahres ist heute?",
        "Heute ist der 291. Tag des Jahres, es bleiben noch 74.",
    ),
    (
        "Wie viele Tage hat der Februar 2028?",
        "Der Februar 2028 hat 29 Tage – 2028 ist ein Schaltjahr.",
    ),
    ("Ist 2028 ein Schaltjahr?", "Ja, 2028 ist ein Schaltjahr."),
    ("Wie alt ist jemand, der am 12. Mai 1990 geboren ist?", "36 Jahre."),
    ("Wann ist Muttertag?", "Muttertag ist am Sonntag, 9. Mai 2027."),
    ("Wann ist der erste Advent?", "Der erste Advent ist am Sonntag, 29. November."),
    ("Wann ist Ostern 2027?", "Ostern ist am Sonntag, 28. März 2027."),
    ("Wann ist Vatertag?", "Vatertag ist Christi Himmelfahrt – am Donnerstag, 6. Mai 2027."),
    (
        "Wann ist der nächste Feiertag?",
        "Der nächste Feiertag in Hessen ist der erste Weihnachtstag, am Freitag, 25. Dezember.",
    ),
    ("Ist morgen ein Feiertag?", "Nein, morgen ist in Hessen kein Feiertag."),
    (
        "Ist der 1. Mai in Hessen ein Feiertag?",
        "Ja, der Tag der Arbeit ist in Hessen ein Feiertag.",
    ),
    ("Ist Fronleichnam in Bayern ein Feiertag?", "Ja, Fronleichnam ist in Bayern ein Feiertag."),
    (
        "Ist der 31. Oktober ein Feiertag?",
        "Nein, der 31. Oktober ist in Hessen kein Feiertag – aber in Brandenburg, Bremen, Hamburg und anderen.",
    ),
    (
        "Welche Feiertage gibt es im Dezember?",
        "Im Dezember in Hessen: der erste Weihnachtstag am 25. Dezember und der zweite Weihnachtstag am 26. Dezember.",
    ),
    (
        "Wann ist das nächste lange Wochenende?",
        "Das nächste lange Wochenende ist der erste Weihnachtstag, vom Freitag, 25. Dezember, bis Sonntag, 27. Dezember – 3 Tage frei.",
    ),
    ("Wie viele Arbeitstage hat der November?", "Der November hat 21 Arbeitstage in Hessen."),
    (
        "Wann sind die nächsten Ferien?",
        "Die Weihnachtsferien in Hessen gehen vom Mittwoch, 23. Dezember, bis Dienstag, 12. Januar 2027.",
    ),
    (
        "Sind gerade Ferien?",
        "Nein, gerade sind keine Ferien in Hessen. Die nächsten sind die Weihnachtsferien, ab 23. Dezember – in 66 Tagen.",
    ),
    ("Was ist 17 mal 23?", "17 mal 23 ist 391."),
    ("Was ist siebzehn mal dreiundzwanzig?", "17 mal 23 ist 391."),
    ("Wurzel aus 144", "Die Wurzel aus 144 ist 12."),
    ("2 hoch 10", "2 hoch 10 ist 1.024."),
    ("(3 plus 4) mal 5", "Klammer auf 3 plus 4 Klammer zu mal 5 ist 35."),
    ("10 durch 0", "Durch null kann man nicht teilen."),
    ("Was sind 19 Prozent von 249 Euro?", "19 Prozent von 249 Euro sind 47 Euro 31."),
    ("Wie viel Prozent sind 30 von 120?", "30 von 120 sind 25 Prozent."),
    (
        "Was sind 100 Euro netto brutto?",
        "100 Euro netto sind 119 Euro brutto bei 19 Prozent Mehrwertsteuer.",
    ),
    (
        "Wie viel Mehrwertsteuer ist in 59,90 Euro?",
        "In 59 Euro 90 stecken 9 Euro 56 Mehrwertsteuer bei 19 Prozent.",
    ),
    (
        "10 Prozent Trinkgeld auf 43 Euro?",
        "10 Prozent Trinkgeld auf 43 Euro sind 4 Euro 30, zusammen 47 Euro 30 – aufgerundet 48 Euro.",
    ),
    ("86 Euro durch 3 Personen", "Jeder zahlt 28 Euro 67."),
    ("Was ist ein Drittel von 90?", "Ein Drittel von 90 ist 30."),
    ("80 Euro minus 25 Prozent", "80 Euro minus 25 Prozent sind 60 Euro – du sparst 20 Euro."),
    ("Wie viel sind 5 Meilen in Kilometer?", "5 Meilen sind etwa 8,05 Kilometer."),
    ("100 Fahrenheit in Celsius", "100 Grad Fahrenheit sind etwa 37,8 Grad Celsius."),
    ("3 Esslöffel in Milliliter", "3 Esslöffel sind 45 Milliliter."),
    ("Wie viele Sekunden hat ein Tag?", "1 Tag ist 86.400 Sekunden."),
    ("Was ist 2026 in römischen Zahlen?", "2026 ist in römischen Zahlen M M X X V I."),
    (
        "Buchstabier Weilburg",
        "Weilburg: W wie Wuppertal, E wie Essen, I wie Ingelheim, L wie Leipzig, B wie Berlin, U wie Unna, R wie Rostock, G wie Goslar.",
    ),
    ("Zähl von 5 runter", "5, 4, 3, 2, 1, 0."),
    ("Was heißt Guude?", "Guude heißt einfach: Guten Tag."),
    (
        "Wer bist du?",
        "Ich bin Anton, Moritz’ Telefonassistent – ein Computerprogramm, kein Mensch.",
    ),
    (
        "Bist du eine KI?",
        "Ich bin Anton, ein Computerprogramm – kein Mensch, aber ich gebe mir Mühe.",
    ),
    ("Gute Nacht", "Gute Nacht, Moritz! Schlaf gut."),
    ("Hörst du mich?", "Ja, ich höre dich gut."),
    (
        "Speicherst du das?",
        "Ich nehme kein Audio auf. Den erkannten Text speichere ich 24 Stunden, dann wird er gelöscht.",
    ),
    ("Guten Morgen", "Guten Morgen! Heute ist Sonntag, der 18. Oktober 2026."),
]


@pytest.mark.parametrize(("question", "answer"), GOLDEN)
def test_golden_answers(question, answer):
    assert ask(question) == answer


def test_goodbye_is_the_prerecorded_announcement_and_hangs_up():
    session = Session()
    outcome = session.route("Tschüss")
    assert outcome.result is not None
    assert outcome.result.prompt == "goodbye" and outcome.result.hangup
    assert session.skill("Danke, das war's") == "talk.goodbye"  # not "thanks"


def test_time_comes_from_the_clock_at_the_moment_of_asking():
    session = Session()
    assert session.say("Wie spät ist es?") == "Es ist 19 Uhr 12."
    session.clock.advance(minutes=3)
    assert session.say("Wie spät ist es?") == "Es ist 19 Uhr 15."


def test_colloquial_clock_style():
    from moritz_agent.config.settings import load_settings

    settings = load_settings()
    settings.skills.time.spoken_style = "umgangssprachlich"
    session = Session(settings=settings)
    session.clock.advance(minutes=3)
    assert session.say("Wie spät ist es?") == "Es ist Viertel nach sieben."


def test_the_year_rolls_over():
    from datetime import datetime

    from .skills_util import BERLIN

    at = datetime(2026, 12, 31, 23, 59, tzinfo=BERLIN)
    assert ask("Welches Datum ist morgen?", at) == "Morgen ist Freitag, der 1. Januar."
    assert ask("Wie viele Tage bis Neujahr?", at) == "Das ist schon morgen, Freitag, der 1. Januar."
    assert ask("Welche KW haben wir?", at) == "Wir haben Kalenderwoche 53."


def test_leap_day():
    from datetime import datetime

    from .skills_util import BERLIN

    at = datetime(2028, 2, 28, 12, 0, tzinfo=BERLIN)
    assert ask("Welches Datum ist morgen?", at) == "Morgen ist Dienstag, der 29. Februar."


def test_help_lists_only_what_exists():
    session = Session()
    text = session.say("Was kannst du?")
    assert text and "Uhrzeit" in text and "Wetter" in text
    assert "rechnen" in text or "rechnen" in (session.say("Mehr Details") or "")


def test_details_follow_the_help():
    session = Session()
    session.say("Was kannst du?")
    detail = session.say("Mehr Details")
    assert detail and detail.startswith("Außerdem")
    assert session.say("Mehr Details") is None  # nothing left to add


def test_repeat_says_the_last_answer_again():
    session = Session()
    assert (
        session.say("Nochmal bitte") == "Ich habe noch nichts gesagt, das ich wiederholen könnte."
    )
    session.say("Wie viel Uhr ist es?")
    assert session.say("Kannst du das wiederholen?") == "Es ist 19 Uhr 12."


def test_speed_and_loudness_are_remembered_for_the_rest_of_the_call():
    session = Session()
    session.say("Sprich langsamer")
    assert 0.8 < session.ctx.tempo < 0.9
    for _ in range(6):
        session.say("Sprich langsamer")
    assert session.ctx.tempo == 0.7
    assert session.say("Sprich langsamer") == "Langsamer geht es nicht mehr."
    session.say("Lauter bitte")
    assert session.ctx.loudness_db == 3.0


def test_timer_is_registered_and_reported():
    session = Session()
    outcome = session.route("Stell einen Timer auf 3 Minuten")
    assert outcome.result.start_timer == (180.0, "3 Minuten")
    session.clock.advance(minutes=1)
    assert session.say("Wie lange noch?") == "Noch 2 Minuten."


def test_timer_is_limited_on_the_phone_but_not_in_chat():
    assert "höchstens 15 Minuten" in ask("Timer auf 2 Stunden")
    chat = Session(surface="chat")
    assert chat.route("Timer auf 2 Stunden").result.start_timer == (7200.0, "2 Stunden")


def test_dice_and_coin_are_reproducible_with_a_seed():
    assert Session(seed=5).say("Würfel mal") == Session(seed=5).say("Würfel mal")
    assert Session().say("Wirf eine Münze") in {"Kopf.", "Zahl."}


def test_jokes_do_not_repeat_within_a_call():
    session = Session()
    told = {session.say("Erzähl einen Witz") for _ in range(10)}
    assert len(told) == 10


@pytest.mark.parametrize("silly", ["Teile 5 durch 0", "10 hoch 1000", "Wurzel aus minus 4"])
def test_calculator_survives_nonsense(silly):
    answer = ask(silly)
    assert answer is None or answer


def test_calculator_never_runs_code():
    assert ask("__import__('os').system('echo hi')") is None
    assert ask("import os und rechne 2 plus 2") in (None, "2 plus 2 ist 4.")


# -- review findings: wrong answers that must not come back ----------------------------------------
WED_10 = datetime(2026, 10, 21, 10, 0, tzinfo=BERLIN)
WED_NOON = datetime(2026, 10, 21, 12, 0, tzinfo=BERLIN)
AUTUMN_SWITCH = datetime(2026, 10, 25, 1, 0, tzinfo=BERLIN)  # 01:00 summer time, change at 03:00
SPRING_SWITCH = datetime(2026, 3, 29, 1, 0, tzinfo=BERLIN)  # 01:00 winter time, change at 02:00

FOUND = [
    # date.today answers the day asked for, not today
    (WED_10, "Welches Datum ist nächsten Freitag?", "Freitag, der 23. Oktober"),
    (WED_10, "Welches Datum ist am Samstag?", "Samstag, der 24. Oktober"),
    (WED_10, "Welches Datum ist in einer Woche?", "Mittwoch, der 28. Oktober"),
    (WED_10, "Welches Datum ist Heiligabend?", "Heiligabend ist am Donnerstag, dem 24. Dezember"),
    (WED_10, "Welches Datum ist Ostern?", "Ostern ist am Sonntag, dem 28. März 2027"),
    (WED_10, "Der wievielte ist Muttertag?", "Sonntag, dem 9. Mai 2027"),
    (WED_10, "Welches Datum war letzten Samstag?", "Das war Samstag, der 17. Oktober"),
    (WED_10, "Welches Datum ist heute?", "Heute ist Mittwoch, der 21. Oktober 2026"),
    # spoken decimals
    (WED_10, "Was ist zwei Komma fünf mal vier?", "2,5 mal 4 ist 10."),
    (WED_10, "Was ist null komma fünf plus eins komma fünf?", "ist 2."),
    # negative temperatures
    (WED_10, "Was sind minus 40 Grad in Fahrenheit?", "Minus 40 Grad Celsius sind minus 40 Grad"),
    (WED_10, "Was sind -10 Grad Celsius in Fahrenheit?", "sind 14 Grad Fahrenheit"),
    # year-less dates share the year
    (WED_10, "Wie viele Tage sind zwischen 1. Oktober und 1. November?", "31 Tage"),
    # years
    (WED_10, "Welcher Wochentag war der 3.10.90?", "3. Oktober 1990 war ein Mittwoch"),
    (WED_10, "Wann war Ostern 1990?", "Ostern war am Sonntag, 15. April 1990"),
    (WED_10, "Welcher Wochentag ist Weihnachten 2027?", "24. Dezember 2027 ist ein Freitag"),
    (WED_10, "Welcher Wochentag war Ostern neunzehnhundertneunzig?", "15. April 1990"),
    # clock changes: elapsed time counts, not the wall clock
    (AUTUMN_SWITCH, "Wie spät ist es in 3 Stunden?", "ist es 3 Uhr."),
    (AUTUMN_SWITCH, "Wie lange noch bis 12 Uhr?", "Noch 12 Stunden."),
    (AUTUMN_SWITCH, "Wie lange noch bis 5 Uhr?", "Noch 5 Stunden."),
    (SPRING_SWITCH, "Wie spät ist es in 3 Stunden?", "ist es 5 Uhr."),
    (SPRING_SWITCH, "Wie spät ist es in 90 Minuten?", "ist es 3 Uhr 30."),
    (SPRING_SWITCH, "Wie lange noch bis 5 Uhr?", "Noch 3 Stunden."),
    (SPRING_SWITCH, "Haben wir gerade Sommerzeit?", "beginnt am Sonntag, 29. März."),
    (SPRING_SWITCH, "Wann beginnt die Sommerzeit?", "Am Sonntag, 29. März, um 2 Uhr"),
    (WED_10, "Wann beginnt die Sommerzeit?", "Am Sonntag, 28. März 2027, um 2 Uhr"),
    # dark or light
    (WED_NOON, "Ist es schon dunkel?", "Nein, es ist noch hell"),
    (WED_NOON, "Ist es noch hell?", "Ja, es ist noch hell"),
    (WED_NOON, "Wann ist es dunkel?", "Heute wird es gegen"),
    # VAT: add, tax on a net price, or extract
    (WED_10, "Was sind 100 Euro plus Mehrwertsteuer?", "sind 119 Euro"),
    (WED_10, "Was sind 100 Euro mit Mehrwertsteuer?", "sind 119 Euro"),
    (WED_10, "Was sind 100 Euro zuzüglich Mehrwertsteuer?", "sind 119 Euro"),
    (WED_10, "Was sind 19 Prozent Mehrwertsteuer von 100 Euro?", "100 Euro sind 19 Euro"),
    (WED_10, "Was sind 7 Prozent Mehrwertsteuer auf 50 Euro?", "50 Euro sind 3 Euro 50"),
    (WED_10, "Wie viel Mehrwertsteuer ist in 119 Euro?", "In 119 Euro stecken 19 Euro"),
    (WED_10, "100 Euro inklusive Mehrwertsteuer – wie viel Steuer?", "stecken 15 Euro 97"),
    (WED_10, "Was sind 100 Euro netto brutto?", "100 Euro netto sind 119 Euro brutto"),
    # Mariä Himmelfahrt is not Christi Himmelfahrt
    (WED_10, "Wann ist Mariä Himmelfahrt?", "Mariä Himmelfahrt ist am Sonntag, 15. August 2027"),
    (WED_10, "Ist Mariä Himmelfahrt ein Feiertag?", "in Hessen kein Feiertag – aber im Saarland"),
    # commercial rounding
    (WED_10, "Runde 2,5", "Gerundet sind das 3."),
    (WED_10, "Was sind 19 Prozent von 32,50 Euro?", "sind 6 Euro 18."),
    (WED_10, "Was sind 10 Prozent von 3 Euro 50?", "von 3 Euro 50 sind 0 Euro 35."),
    # long weekends grow over neighbouring holidays
    (WED_10, "Wann ist das nächste lange Wochenende?", "25. Dezember, bis Sonntag, 27. Dezember"),
    (
        datetime(2025, 12, 1, 10, 0, tzinfo=BERLIN),
        "Wann ist das nächste lange Wochenende?",
        "bis Sonntag, 28. Dezember – 4 Tage frei",
    ),
    (
        datetime(2028, 12, 1, 10, 0, tzinfo=BERLIN),
        "Wann ist das nächste lange Wochenende?",
        "vom Samstag, 23. Dezember, bis Dienstag, 26. Dezember – 4 Tage frei",
    ),
    # places with a spoken addition
    (WED_10, "Wie weit ist Frankfurt an der Oder?", "bis Frankfurt an der Oder etwa 485 Kilometer"),
    (WED_10, "Wie weit ist Frankfurt am Main?", "bis Frankfurt am Main etwa 51 Kilometer"),
    # calendar weeks
    (WED_10, "Welche Kalenderwoche ist nächste Woche?", "Nächste Woche ist Kalenderwoche 44."),
    (WED_10, "Welche Kalenderwoche ist letzte Woche?", "Letzte Woche war Kalenderwoche 42."),
    (WED_10, "Wann ist KW 1?", "Kalenderwoche 1 im Jahr 2027 geht von Montag, 4. Januar,"),
    (WED_10, "Wann ist KW 50?", "Kalenderwoche 50 geht von Montag, 7. Dezember,"),
    # Halloween is no holiday – the Reformationstag on the same day is
    (WED_10, "Ist Halloween ein Feiertag?", "Halloween selbst ist kein Feiertag"),
    (WED_10, "Ist Weihnachten ein Feiertag?", "Ja, der erste Weihnachtstag ist in Hessen"),
    (WED_10, "Ist Ostern 2027 ein Feiertag?", "Ja, Ostern ist in Hessen ein Feiertag."),
    (WED_10, "Ist Heilige Drei Könige ein Feiertag?", "aber in Baden-Württemberg, Bayern"),
    (WED_10, "Ist Buß- und Bettag ein Feiertag?", "aber in Sachsen."),
]


@pytest.mark.parametrize(("at", "question", "expected"), FOUND)
def test_review_findings(at, question, expected):
    answer = ask(question, at)
    assert answer is not None and expected in answer, answer


@pytest.mark.parametrize(
    "sentence",
    [
        "Ruf mich unter 0171-1234567 an",
        "Hat die Apotheke 24/7 offen?",
        "Ich wohne Hauptstraße 5-7",
        "Das Spiel endete 2-1",
        "Was war zwischen 1939-1945?",
    ],
)
def test_numbers_with_dash_or_slash_are_not_calculations(sentence):
    assert Session(WED_10).skill(sentence) != "calc.arith"


@pytest.mark.parametrize(
    ("sentence", "answer"),
    [
        ("Was ist 7-2?", "7 minus 2 ist 5."),
        ("5-3", "5 minus 3 ist 2."),
        ("Was ist 24/7?", "etwa 3,4286"),
    ],
)
def test_dash_and_slash_still_calculate_when_asked(sentence, answer):
    assert answer in ask(sentence, WED_10)


def test_sun_answers_keep_the_case_of_month_and_weekday():
    answer = ask("Wann geht die Sonne am 21. Juni auf?", WED_10)
    assert answer.startswith("Am Montag, dem 21. Juni 2027")

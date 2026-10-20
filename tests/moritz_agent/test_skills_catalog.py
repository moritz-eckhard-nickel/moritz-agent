# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Golden answers of the offline skills with a fixed clock (Sunday, 18 Oct 2026, 19:12)."""

from __future__ import annotations

import pytest

from .skills_util import Session, ask

GOLDEN = [
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
        "Ich bin Nikita, Moritz’ Telefonassistent – ein Computerprogramm, kein Mensch.",
    ),
    (
        "Bist du eine KI?",
        "Ich bin Nikita, ein Computerprogramm – kein Mensch, aber ich gebe mir Mühe.",
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
    text = ask("Was kannst du?")
    assert text and "Uhrzeit" in text and "rechnen" in text


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

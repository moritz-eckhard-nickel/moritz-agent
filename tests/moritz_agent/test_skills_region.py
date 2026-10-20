# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Money, river, waste, football, news and notes (docs/plan/13 §6.12, §6.13)."""

from __future__ import annotations

import time
from datetime import date, datetime

import httpx
import pytest

from moritz_agent.config.secrets import Secret
from moritz_agent.config.settings import load_settings
from moritz_agent.skills.providers import ecb, ics
from moritz_agent.skills.providers.http import HttpError
from moritz_agent.skills.store import NotesStore

from . import weather_fixtures as wf
from .skills_util import BERLIN, weather_session

ICS_URL = "https://awb.example.org/kalender.ics"


def settings_with(**sections):
    settings = load_settings()
    updates = {}
    for name, fields in sections.items():
        updates[name] = getattr(settings.skills, name).model_copy(update=fields)
    return settings.model_copy(update={"skills": settings.skills.model_copy(update=updates)})


def full_session(tmp_path, routes=None, at=None, **kwargs):
    settings = settings_with(
        waste={"enabled": True, "ics_url": ICS_URL},
        football={"enabled": True},
        news={"enabled": True},
        notes={"enabled": True},
        money={"fuel": True},
    )
    table = {"awb.example.org/kalender.ics": wf.waste_ics()}
    table.update(routes or {})
    extra = {"at": at} if at else {}
    session = weather_session(
        table, settings=settings, cache_dir=tmp_path / "cache", **extra, **kwargs
    )
    session.svc.secrets["tankerkoenig_api_key"] = Secret("00000000-0000-0000-0000-000000000000")
    session.svc.store = NotesStore(tmp_path / "notes.db")
    return session


# -- exchange rates ----------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "answer"),
    [
        (
            "Wie viel sind 100 Dollar in Euro?",
            "100 US-Dollar sind etwa 91 Euro 64 – EZB-Referenzkurs vom Freitag.",
        ),
        (
            "Wie steht der Franken?",
            "Ein Euro kostet 0,9321 Schweizer Franken – EZB-Referenzkurs vom Freitag.",
        ),
        (
            "Wie ist der Dollarkurs?",
            "Ein Euro kostet 1,0912 US-Dollar – EZB-Referenzkurs vom Freitag.",
        ),
        ("Euro in Pfund?", "1 Euro ist etwa 0,87 Pfund – EZB-Referenzkurs vom Freitag."),
        ("200 Yen in Euro", "200 Yen sind etwa 1 Euro 22 – EZB-Referenzkurs vom Freitag."),
        (
            "Wie viel sind 20 Euro in Pfund?",
            "20 Euro sind etwa 17,31 Pfund – EZB-Referenzkurs vom Freitag.",
        ),
        (
            "Was sind 100 Pfund in Schweizer Franken?",
            "100 Pfund sind etwa 108 Schweizer Franken – EZB-Referenzkurs vom Freitag.",
        ),
    ],
)
def test_exchange_rates(tmp_path, question, answer):
    assert full_session(tmp_path).say(question) == answer


def test_which_krone_is_asked_back(tmp_path):
    session = full_session(tmp_path)
    question = session.say("Wie viel sind 50 Kronen in Euro?")
    assert (
        question
        == "Welche Krone meinst du – die schwedische oder norwegische oder dänische oder tschechische?"
    )
    assert (
        session.say("die schwedische")
        == "50 Schwedische Kronen sind etwa 4 Euro 34 – EZB-Referenzkurs vom Freitag."
    )


def test_the_ecb_document_is_checked():
    rates = ecb.parse(wf.ecb_xml())
    assert rates.day == date(2026, 10, 16) and rates.convert(100, "USD", "EUR") == pytest.approx(
        91.64, abs=0.01
    )
    assert rates.convert(10, "EUR", "XXX") is None
    with pytest.raises(HttpError):
        ecb.parse('<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    with pytest.raises(HttpError):
        ecb.parse("<nothing/>")
    with pytest.raises(HttpError):
        ecb.parse("not xml at all")


def test_old_rates_are_still_used_when_the_service_is_down(tmp_path):
    session = full_session(tmp_path)
    session.say("Wie ist der Dollarkurs?")
    down = full_session(
        tmp_path,
        {"www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml": httpx.ConnectError("down")},
    )
    down.clock.advance(hours=8)
    assert down.say("Wie ist der Dollarkurs?").startswith("Ein Euro kostet 1,0912 US-Dollar")


# -- electricity and fuel --------------------------------------------------------------------------------------
def test_cheapest_electricity(tmp_path):
    at = datetime(2026, 10, 18, 9, 0, tzinfo=BERLIN)
    session = full_session(tmp_path, at=at)
    assert session.say("Wann ist Strom heute am billigsten?") == (
        "Am günstigsten heute zwischen 13 und 15 Uhr, an der Börse etwa 4 Cent pro Kilowattstunde "
        "ohne Steuern und Netzentgelte."
    )
    assert session.say("Was kostet Strom an der Börse?").startswith(
        "Gerade kostet Strom an der Börse etwa"
    )


def test_fuel_needs_the_key_and_says_so(tmp_path):
    session = full_session(tmp_path)
    assert session.say("Was kostet E10 gerade?") == (
        "Am günstigsten ist E10 gerade bei Aral in Weilburg für etwa 1 Euro 74, "
        "die zweitgünstigste verlangt 1 Euro 76."
    )
    session.svc.secrets.clear()
    session.svc.providers.cache.clear()
    assert session.say("Wo tanke ich am billigsten?") == (
        "Für Spritpreise fehlt mir der Tankerkönig-Schlüssel in der Datei passwords.txt."
    )


def test_the_fuel_key_never_shows_up_in_logs_or_errors(tmp_path, caplog):
    session = full_session(
        tmp_path, {"creativecommons.tankerkoenig.de/json/list.php": httpx.Response(500)}
    )
    caplog.set_level("DEBUG")
    text = session.say("Was kostet E10 gerade?")
    assert text is not None
    assert "00000000-0000" not in caplog.text and "00000000-0000" not in text
    assert "apikey" not in caplog.text


def test_the_fuel_service_refusing_the_key(tmp_path):
    session = full_session(
        tmp_path,
        {
            "creativecommons.tankerkoenig.de/json/list.php": {
                "ok": False,
                "message": "apikey 0000 ungültig",
            }
        },
    )
    text = session.say("Was kostet E10 gerade?")
    assert (
        text and "0000" not in text and text.startswith("Ich komme gerade nicht an die Spritpreise")
    )


# -- the river -----------------------------------------------------------------------------------------------------
def test_river_level_and_flood(tmp_path):
    session = full_session(tmp_path)
    assert session.say("Wie hoch steht die Lahn?") == (
        "Die Lahn am Pegel Leun steht bei 1 Meter 42, steigend, etwas über dem mittleren Wasserstand."
    )
    assert (
        session.say("Gibt es Hochwasser?")
        == "Nein, die Lahn am Pegel Leun steht mit 1 Meter 42 im üblichen Bereich."
    )
    high = full_session(
        tmp_path / "high",
        {
            "www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json": wf.pegel_answer(
                value=360.0, trend=1, state="high"
            ),
            "warnung.bund.de/api31/dashboard/065330000000.json": wf.nina_answer([wf.nina_flood()]),
        },
    )
    text = high.say("Gibt es Hochwasser?")
    assert text and text.startswith(
        "Ja, die Lahn am Pegel Leun ist mit 3 Meter 60 deutlich erhöht, steigend."
    )
    assert "Hochwasserinformation Lahn" in text and high.last.result.serious


def test_river_level_wording_for_low_water_and_the_nearest_gauge(tmp_path):
    low = full_session(
        tmp_path,
        {
            "www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json": wf.pegel_answer(
                value=50.0, trend=-1, mw=110.0
            )
        },
    )
    assert low.say("Wasserstand Lahn?") == (
        "Die Lahn am Pegel Leun steht bei 50 Zentimeter, fallend, unter dem mittleren Wasserstand."
    )
    settings = settings_with(water={"station": "Kalkofen"})
    chosen = weather_session(settings=settings)
    assert "Pegel Kalkofen" in chosen.say("Wie hoch steht die Lahn?")


# -- waste -------------------------------------------------------------------------------------------------------------
def test_waste_collection(tmp_path):
    session = full_session(tmp_path)
    assert session.say("Welche Tonne kommt morgen?") == "Morgen wird die Biotonne abgeholt."
    assert (
        session.say("Wann kommt die gelbe Tonne?")
        == "Die nächste gelbe Tonne wird abgeholt am Montag, 26. Oktober."
    )
    assert (
        session.say("Wann ist Sperrmüll?")
        == "Der nächste Sperrmüll wird abgeholt am Donnerstag, 5. November."
    )
    assert (
        session.say("Wann kommt die Papiertonne?")
        == "Die nächste Papiertonne wird abgeholt am Donnerstag, 22. Oktober."
    )
    assert session.say("Welche Tonne kommt übermorgen?") == "Übermorgen wird nichts abgeholt."
    week = session.say("Was wird diese Woche abgeholt?")
    assert week == "Abgeholt wird: morgen die Biotonne; am Donnerstag die Papiertonne."


def test_waste_without_a_calendar_or_switched_off():
    session = weather_session(settings=settings_with(waste={"enabled": True}))
    assert session.say("Welche Tonne kommt morgen?").startswith(
        "Einen Abfallkalender habe ich noch nicht."
    )
    off = weather_session()
    assert off.say("Welche Tonne kommt morgen?") == "Der Abfallkalender ist bei mir ausgeschaltet."


def test_waste_calendar_from_a_file(tmp_path):
    (tmp_path / "abfall.ics").write_text(wf.waste_ics(), encoding="utf-8")
    settings = settings_with(waste={"enabled": True, "ics_file": "abfall.ics"})
    session = weather_session(settings=settings)
    session.svc.root = tmp_path
    assert session.say("Welche Tonne kommt morgen?") == "Morgen wird die Biotonne abgeholt."


def test_ics_parser_expands_simple_rules_and_cleans_text():
    pickups = ics.parse(wf.waste_ics(), date(2026, 10, 18), date(2026, 12, 31))
    yellow = [p.day for p in pickups if p.summary == "Gelber Sack"]
    assert yellow == [
        date(2026, 10, 26),
        date(2026, 11, 9),
        date(2026, 11, 23),
    ]  # every 2 weeks, 3 times
    assert ics.kind_of("Sperrmüll, nach Anmeldung") == "Sperrmüll"
    assert ics.kind_of("Papiertonne (blau)") == "Papiertonne"
    assert ics.kind_of("Irgendwas") == "Irgendwas"
    folded = "BEGIN:VEVENT\r\nDTSTART:20261020T060000\r\nSUMMARY:Rest\r\n müll\r\nEND:VEVENT\r\n"
    assert ics.parse(folded, date(2026, 10, 1), date(2026, 10, 31))[0].summary == "Restmüll"
    assert (
        ics.parse(
            "BEGIN:VEVENT\nDTSTART:kaputt\nSUMMARY:x\nEND:VEVENT",
            date(2026, 1, 1),
            date(2027, 1, 1),
        )
        == []
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://awb.example.org/a.ics",
        "https://localhost/a.ics",
        "https://127.0.0.1/a.ics",
        "https://192.168.1.10/a.ics",
        "https://10.0.0.5/a.ics",
        "https://nas.local/a.ics",
        "https://[::1]/a.ics",
        "file:///etc/passwd",
    ],
)
def test_waste_links_must_be_public_https(url):
    with pytest.raises(HttpError):
        ics.check_url(url)
    assert ics.check_url("https://awb.example.org/a.ics") == "awb.example.org"


def test_a_private_calendar_link_is_refused_at_runtime(tmp_path):
    settings = settings_with(waste={"enabled": True, "ics_url": "https://192.168.1.10/a.ics"})
    session = weather_session(settings=settings)
    assert (
        session.say("Welche Tonne kommt morgen?")
        == "Der Abfallkalender ist nicht erlaubt oder nicht erreichbar."
    )


# -- football and news ------------------------------------------------------------------------------------------------------
def test_football(tmp_path):
    session = full_session(tmp_path)
    assert (
        session.say("Wie hat die Eintracht gespielt?")
        == "Eintracht Frankfurt hat gestern 2 zu 1 gegen VfL Wolfsburg gewonnen."
    )
    assert session.say("Wann spielt die Eintracht?") == (
        "Das nächste Spiel ist am Sonntag, 25. Oktober um 17 Uhr 30 auswärts gegen Borussia Dortmund."
    )
    assert session.say("Auf welchem Platz steht die Eintracht?") == (
        "Eintracht Frankfurt steht auf Platz 5 mit 12 Punkten nach 8 Spielen."
    )


def test_football_is_off_by_default():
    assert (
        weather_session().say("Wann spielt die Eintracht?")
        == "Fußballergebnisse sind bei mir ausgeschaltet."
    )


def test_headlines_are_titles_only_and_cleaned(tmp_path):
    session = full_session(tmp_path)
    text = session.say("Was gibt's Neues?")
    assert (
        text == "Laut tagesschau.de: Erste Meldung des Tages; Zweite Meldung mit; Dritte meldung."
    )
    assert "spam.example" not in text and "Werbung" not in text
    assert weather_session().say("Nachrichten?") == "Nachrichten sind bei mir ausgeschaltet."


# -- notes ---------------------------------------------------------------------------------------------------------------------
def test_shopping_list_and_notes(tmp_path):
    session = full_session(tmp_path)
    assert (
        session.say("Schreib Milch auf die Einkaufsliste.")
        == "Ich habe Milch auf die Einkaufsliste geschrieben."
    )
    assert (
        session.say("Setz Eier auf die Einkaufsliste")
        == "Ich habe Eier auf die Einkaufsliste geschrieben."
    )
    assert (
        session.say("Notiz: Reifen wechseln")
        == "Ich habe Reifen wechseln in deine Notizen geschrieben."
    )
    assert (
        session.say("Was steht auf der Einkaufsliste?")
        == "Auf der Einkaufsliste stehen Milch und Eier."
    )
    assert session.say("Lies meine Notizen vor") == "Deine Notiz ist Reifen wechseln."


def test_clearing_asks_first(tmp_path):
    session = full_session(tmp_path)
    session.say("Schreib Milch auf die Einkaufsliste")
    assert session.say("Lösch die Einkaufsliste.").startswith("Wirklich alles löschen?")
    assert session.say("nein") == "Alles klar, ich lasse es."
    assert session.say("Was steht auf der Einkaufsliste?") == "Auf der Einkaufsliste steht Milch."
    session.say("Lösch die Einkaufsliste.")
    assert session.say("ja") == "Okay, Einkaufsliste ist gelöscht, 1 Eintrag."
    assert session.say("Was steht auf der Einkaufsliste?") == "Auf der Einkaufsliste steht nichts."


def test_notes_are_off_by_default_and_the_store_forgets(tmp_path):
    assert (
        weather_session().say("Schreib Milch auf die Einkaufsliste")
        == "Notizen sind bei mir ausgeschaltet."
    )
    store = NotesStore(tmp_path / "n.db")
    store.add("notizen", "alt")
    store.add("notizen", "neu")
    import sqlite3

    with sqlite3.connect(tmp_path / "n.db") as conn:
        conn.execute("UPDATE notes SET created = ? WHERE text = 'alt'", (time.time() - 40 * 86400,))
    assert store.purge(30) == 1 and store.read("notizen") == ["neu"]
    assert store.clear("notizen") == 1 and store.read("notizen") == []


def test_nothing_is_written_by_questions(tmp_path):
    session = full_session(tmp_path)
    session.say("Wie spät ist es?")
    session.say("Wie ist das Wetter?")
    assert session.svc.store.read("notizen") == [] and session.svc.store.read("einkaufsliste") == []

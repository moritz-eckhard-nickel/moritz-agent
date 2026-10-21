# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Gazetteer and place expressions (docs/plan/13 §4.4, §5, ADR-031)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from moritz_agent.config.settings import REPO_ROOT, load_settings
from moritz_agent.skills.geo.distance import bearing_deg, compass_de, haversine_km, wind_from_de
from moritz_agent.skills.geo.gazetteer import Gazetteer, fold
from moritz_agent.skills.services import build_services
from moritz_agent.skills.slots.where import find_places, find_where, home_place
from moritz_agent.skills.text.normalize import prepare


@pytest.fixture(scope="module")
def gaz() -> Gazetteer:
    gazetteer = Gazetteer.load(REPO_ROOT)
    gazetteer.set_home("35781", "Weilburg")
    return gazetteer


@pytest.fixture(scope="module")
def svc():
    return build_services(load_settings(), REPO_ROOT)


def test_home_is_weilburg_35781(gaz):
    home = gaz.home
    assert home is not None
    assert (home.name, home.state, home.district) == ("Weilburg", "HE", "Limburg-Weilburg")
    assert "35781" in home.postal_codes
    assert 50.4 < home.lat < 50.6 and 8.1 < home.lon < 8.4


def test_configured_coordinates_override_the_table():
    gazetteer = Gazetteer.load(REPO_ROOT)
    home = gazetteer.set_home("35781", "Weilburg", 50.5, 8.3)
    assert (home.lat, home.lon) == (50.5, 8.3)


def test_unknown_home_falls_back_to_the_configured_values():
    gazetteer = Gazetteer.load(REPO_ROOT)
    home = gazetteer.set_home("99999", "Nirgendwo", 51.0, 9.0)
    assert (home.name, home.lat, home.lon) == ("Nirgendwo", 51.0, 9.0)


@pytest.mark.parametrize(
    ("plz", "name"),
    [
        ("35781", "Weilburg"),
        ("60311", "Frankfurt am Main"),
        ("60594", "Frankfurt am Main"),  # only in a range
        ("65549", "Limburg an der Lahn"),
        ("10115", "Berlin"),
        ("80999", "München"),
    ],
)
def test_postcodes(gaz, plz, name):
    place = gaz.by_postcode(plz)
    assert place is not None and place.name == name
    assert place.queried_postcode == plz


def test_unknown_postcode_has_a_near_miss(gaz):
    assert gaz.by_postcode("99999") is None
    assert gaz.by_postcode("abcde") is None
    assert [p.name for p in gaz.similar_postcodes("35791")][:1] == ["Weilburg"]


@pytest.mark.parametrize(
    ("spoken", "name", "how"),
    [
        ("Weilburg", "Weilburg", "exact"),
        ("weilburg", "Weilburg", "exact"),
        ("Limburg a d Lahn", "Limburg an der Lahn", "exact"),
        ("Limburg", "Limburg an der Lahn", "stripped"),
        ("Frankfurt", "Frankfurt am Main", "stripped"),
        ("Koeln", "Köln", None),
        ("Köln", "Köln", "exact"),
        ("Bad Homburg", "Bad Homburg vor der Höhe", "stripped"),
        ("Homburg", "Bad Homburg vor der Höhe", "stripped"),
        ("Kubach", "Kubach", "district"),
        ("Halle", "Halle (Saale)", "stripped"),
        ("Weilborg", "Weilburg", "fuzzy"),
        ("Weilbug", "Weilburg", "fuzzy"),
    ],
)
def test_names(gaz, spoken, name, how):
    found = gaz.find(spoken)
    assert found.best is not None, spoken
    assert found.best.place.name == name
    if how:
        assert found.best.how == how


def test_clear_winner_is_not_ambiguous(gaz):
    found = gaz.find("Frankfurt")
    assert not found.ambiguous
    assert found.hits[0].place.name == "Frankfurt am Main"


def test_neustadt_is_ambiguous(gaz):
    found = gaz.find("Neustadt")
    assert found.ambiguous
    names = {h.place.name for h in found.hits[:2]}
    assert names == {"Neustadt (Hessen)", "Neustadt an der Weinstraße"}


def test_a_district_belongs_to_its_town(gaz):
    place = gaz.by_postcode("35781")
    assert place is not None and place.name == "Weilburg"
    kubach = gaz.find("Kubach").best.place
    assert kubach.parent == "Weilburg"


def test_nonsense_finds_nothing(gaz):
    assert gaz.find("Xyzzyqq").best is None
    assert gaz.find("").best is None


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("Neustadt (Hessen)", "Neustadt in Hessen"),
        ("Halle (Saale)", "Halle an der Saale"),
        ("Selters (Taunus)", "Selters im Taunus"),
        ("Sylt (Westerland)", "Sylt"),
        ("Weilburg", "Weilburg"),
    ],
)
def test_spoken_names(gaz, raw, spoken):
    place = next(p for p in gaz.places if p.name == raw)
    assert place.spoken == spoken


def test_fold_unifies_spellings():
    assert fold("Köln") == fold("Koeln".replace("oe", "o")) == "koln"
    assert fold("St. Georgen") == fold("Sankt Georgen")
    assert fold("Bad  Homburg") == "bad homburg"


def test_postcode_ranges_cover_big_cities(gaz):
    codes = gaz.postcodes_of(gaz.find("Limburg an der Lahn").best.place)
    assert "65549" in codes and "65556" in codes


# -- distance ----------------------------------------------------------------------------------
def test_distance_weilburg_frankfurt(gaz):
    home = gaz.home
    frankfurt = gaz.find("Frankfurt am Main").best.place
    km = haversine_km(home.lat, home.lon, frankfurt.lat, frankfurt.lon)
    assert 45 < km < 60
    assert compass_de(bearing_deg(home.lat, home.lon, frankfurt.lat, frankfurt.lon)) == "Südosten"


@pytest.mark.parametrize(
    ("degrees", "word", "wind"),
    [
        (0, "Norden", "Nord"),
        (90, "Osten", "Ost"),
        (225, "Südwesten", "Südwest"),
        (350, "Norden", "Nord"),
    ],
)
def test_compass(degrees, word, wind):
    assert compass_de(degrees) == word
    assert wind_from_de(degrees) == wind


# -- place expressions ---------------------------------------------------------------------------------
def where(svc, sentence):
    return find_places(prepare(sentence).text, svc)


@pytest.mark.parametrize(
    ("sentence", "kind", "name", "how"),
    [
        ("wetter in berlin heute abend", "place", "Berlin", "exact"),
        ("wie ist das wetter in frankfurt morgen", "place", "Frankfurt am Main", "stripped"),
        ("wetter in 35781", "place", "Weilburg", "postcode"),
        ("wie wird das wetter in 6 0 3 1 1", "place", "Frankfurt am Main", "postcode"),
        ("wetter für sechs null drei eins eins", "place", "Frankfurt am Main", "postcode"),
        ("wie wird das wetter in weilborg", "place", "Weilburg", "fuzzy"),
        ("wetter in new york", "place", "New York", "exact"),
        ("limburg wetter", "place", "Limburg an der Lahn", "stripped"),
        ("wie ist das wetter bei uns in weilburg", "home", "Weilburg", "home"),
        ("wie ist das wetter hier", "home", "Weilburg", "home"),
        ("wetter zu hause", "home", "Weilburg", "home"),
        ("wie ist das wetter in der region", "region", "Weilburg", "home"),
        ("wie ist das wetter im landkreis", "region", "Weilburg", "home"),
    ],
)
def test_where(svc, sentence, kind, name, how):
    found = where(svc, sentence)
    assert found, sentence
    first = found[0]
    assert first.kind == kind
    assert first.place is not None and first.place.name == name
    assert first.how == how


@pytest.mark.parametrize(
    "sentence",
    [
        "wie ist das wetter",
        "wie wird das wetter morgen",
        "wie ist das wetter in der nacht",
        "wie wird das wetter in den nächsten tagen",
        "wie wird das wetter in 3 tagen",
        "regnet es bei regen",
        "wie wird das wetter in meinem urlaub",
        "wann hört der regen auf",
    ],
)
def test_no_place_in(svc, sentence):
    assert where(svc, sentence) == []
    assert find_where(prepare(sentence).text, svc).kind == "home"


def test_unknown_place_and_postcode(svc):
    unknown = where(svc, "wetter in atlantis")
    assert unknown[0].kind == "unknown" and unknown[0].spoken == "Atlantis"
    alps = where(svc, "wetter in den alpen")
    assert alps[0].kind == "unknown" and alps[0].spoken == "Alpen"
    bad = where(svc, "wetter in 35791")
    assert bad[0].kind == "bad_postcode"
    assert bad[0].suggestion is not None and bad[0].suggestion.name == "Weilburg"
    assert where(svc, "ich habe 12345 äpfel") == []  # five digits alone are no place


def test_ambiguous_place_offers_two_options(svc):
    found = where(svc, "wetter in neustadt")[0]
    assert found.kind == "ambiguous"
    assert {p.name for p in found.options} == {"Neustadt (Hessen)", "Neustadt an der Weinstraße"}


def test_two_places_in_spoken_order(svc):
    found = where(svc, "wie weit ist es von weilburg nach frankfurt")
    assert [w.place.name for w in found] == ["Weilburg", "Frankfurt am Main"]
    mixed = where(svc, "ist es in frankfurt wärmer als hier")
    assert [w.kind for w in mixed] == ["place", "home"]


def test_home_place_follows_the_settings():
    settings = load_settings()
    other = settings.model_copy(
        update={
            "skills": settings.skills.model_copy(
                update={
                    "home": settings.skills.home.model_copy(
                        update={"postal_code": "65549", "name": "Limburg an der Lahn"}
                    )
                }
            )
        }
    )
    service = build_services(other, REPO_ROOT)
    assert home_place(service).name == "Limburg an der Lahn"
    service.settings = settings  # a config reload changes the home without a restart
    assert home_place(service).name == "Weilburg"


def test_colloquial_names_and_countries_resolve_to_places(gaz):
    for said, place in (
        ("Malle", "Palma de Mallorca"),
        ("Mainhattan", "Frankfurt am Main"),
        ("Frankreich", "Paris"),
        ("Österreich", "Wien"),
        ("Neuseeland", "Auckland"),
    ):
        best = gaz.find(said).best
        assert best is not None and best.place.name == place, said
        assert best.how == "alias"
    assert gaz.find("Weilburg").best.how == "exact"  # an alias never replaces a real place


def test_the_weather_for_a_country_names_the_capital(svc):
    where = find_where(prepare("wie ist das wetter in frankreich").text, svc)
    assert where.kind == "place" and where.place.name == "Paris"
    assert where.spoken == "Paris"


def test_every_alias_points_at_a_place_that_exists(gaz):
    import tomllib

    tables = tomllib.loads((REPO_ROOT / "assets/data/geo/aliases.de.toml").read_text("utf-8"))
    names = {fold(p.name) for p in gaz.places}
    missing = [t for table in tables.values() for t in table.values() if fold(t) not in names]
    assert not missing


def test_data_files_are_consistent():
    seed = Path(REPO_ROOT / "assets/data/geo/seed-places.tsv").read_text(encoding="utf-8")
    rows = [line.split("\t") for line in seed.splitlines() if line and not line.startswith("#")]
    assert all(len(row) >= 7 for row in rows)
    assert all(47 <= float(row[4]) <= 55.1 and 5.8 <= float(row[5]) <= 15.1 for row in rows)
    names = [(row[0], row[3]) for row in rows]
    assert len(names) == len(set(names)), "duplicate place"


# -- full GeoNames data ------------------------------------------------------------------------------
def test_build_geodata_and_load_the_result(tmp_path, monkeypatch):
    """A tiny fake GeoNames download goes through the build script into the gazetteer."""
    import importlib.util
    import io
    import shutil
    import zipfile

    spec = importlib.util.spec_from_file_location(
        "build_geodata", REPO_ROOT / "scripts/build_geodata.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def zipped(text):
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as archive:
            archive.writestr("DE.txt", text)
        return blob.getvalue()

    postal = "\n".join(
        [
            "DE\t35781\tWeilburg\tHessen\tHE\tRegierungsbezirk Gießen\t06\tLandkreis Limburg-Weilburg\t06533\t50.4844\t8.2569\t4",
            "DE\t35792\tLöhnberg\tHessen\tHE\tRegierungsbezirk Gießen\t06\tLandkreis Limburg-Weilburg\t06533\t50.49\t8.3\t4",
            "DE\t99100\tKleinfahner\tThüringen\tTH\tx\t00\tLandkreis Gotha\t16067\t51.0\t10.9\t4",
        ]
    )
    cols = ["0"] * 19

    def place(name, lat, lon, feature, pop):
        row = list(cols)
        row[1], row[4], row[5], row[7], row[8], row[14] = (
            name,
            str(lat),
            str(lon),
            feature,
            "DE",
            str(pop),
        )
        return "\t".join(row)

    places = "\n".join(
        [
            place("Weilburg", 50.4844, 8.2569, "PPLA3", 13000),
            place("Waldhausen", 50.43, 8.27, "PPLX", 800),
            place("Kleinfahner", 51.0, 10.9, "PPL", 600),
            place("Irgendwas", 50.0, 8.0, "MT", 0),  # not a place
        ]
    )
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "DE.zip").write_bytes(zipped(postal))
    (tmp_path / "in" / "DE-places.zip").write_bytes(zipped(places))
    out = tmp_path / "root"
    shutil.copytree(REPO_ROOT / "assets/data/geo", out / "assets/data/geo")
    monkeypatch.setattr(module, "GEO", out / "assets/data/geo")
    assert module.main(["--from", str(tmp_path / "in")]) == 0
    sources = (out / "assets/data/geo/SOURCES.md").read_text(encoding="utf-8")
    assert "CC BY 4.0" in sources
    assert len(re.findall(r"`[0-9a-f]{64}`", sources)) == 2

    gazetteer = Gazetteer.load(out)
    assert gazetteer.by_postcode("99100").name == "Kleinfahner"  # only in the bulk data
    fahner = gazetteer.find("Kleinfahner").best.place
    assert fahner.state == "TH" and fahner.district == "Landkreis Gotha"
    assert gazetteer.find("Irgendwas").best is None
    weilburg = [p for p in gazetteer.places if p.name == "Weilburg"]
    assert len(weilburg) == 1, "the hand-kept entry wins over the bulk entry"
    assert gazetteer.find("Waldhausen").best.place.parent == "Weilburg"


# -- skills of the "places" group ------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("Wo ist 35781?", "35781 ist Weilburg im Landkreis Limburg-Weilburg, Hessen."),
        (
            "Welcher Ort hat die Postleitzahl 65549?",
            "65549 ist Limburg an der Lahn im Landkreis Limburg-Weilburg, Hessen.",
        ),
        ("Wo ist 35791?", "Die Postleitzahl 35791 kenne ich nicht. Meinst du 35781, Weilburg?"),
        (
            "Welche Postleitzahl hat Limburg?",
            "Limburg an der Lahn hat die Postleitzahlen 65549 bis 65556.",
        ),
        ("Welche Postleitzahl hat Weilburg?", "Weilburg hat die Postleitzahl 35781."),
        (
            "Welche Postleitzahl hat Kubach?",
            "Kubach gehört zu Weilburg und hat die Postleitzahl 35781.",
        ),
        (
            "Wie weit ist es nach Frankfurt?",
            "Luftlinie sind es bis Frankfurt am Main etwa 51 Kilometer, Richtung Südosten.",
        ),
        (
            "Entfernung Weilburg Gießen",
            "Luftlinie sind es von Weilburg nach Gießen etwa 32 Kilometer, Richtung Osten.",
        ),
        (
            "Wie weit ist Berlin von München entfernt?",
            "Luftlinie sind es von München nach Berlin etwa 505 Kilometer, Richtung Norden.",
        ),
        ("In welchem Bundesland liegt Wetzlar?", "Wetzlar liegt in Hessen."),
        (
            "Zu welchem Kreis gehört Runkel?",
            "Runkel gehört zum Landkreis Limburg-Weilburg in Hessen.",
        ),
        (
            "Wie weit ist es nach Neustadt?",
            "Welches Neustadt meinst du – Neustadt an der Weinstraße oder Neustadt in Hessen?",
        ),
    ],
)
def test_place_skills(question, answer):
    from .skills_util import ask

    assert ask(question) == answer


def test_home_skill_names_the_place_and_how_it_is_set():
    from .skills_util import ask

    text = ask("Wo bin ich?")
    assert text and text.startswith(
        "Dein Heimatort ist Weilburg, 35781 im Landkreis Limburg-Weilburg, Hessen."
    )

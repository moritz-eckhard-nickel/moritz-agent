# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Offline directory of places and postcodes (docs/plan/13 §4.4, §11, ADR-031).

Sources, all in ``assets/data/geo/``:

* ``seed-places.tsv``      hand-kept places shipped with the repo (always loaded)
* ``plz-bereiche.tsv``     postcode ranges of big cities
* ``world-cities.tsv``     well-known cities abroad with their German names
* ``de-places.tsv`` / ``de-postcodes.tsv``  full GeoNames data, optional, written by
  ``scripts/build_geodata.py`` (same column layout as the seed file)

Name lookup goes exact → without additions ("an der Lahn", "Bad", "St.") → district of a
town → fuzzy (difflib) → phonetic (Kölner Phonetik). Fuzzy and phonetic hits are always reported
as such so the answer can say "Ich nehme an, du meinst …".
"""

from __future__ import annotations

import bisect
import csv
import difflib
import math
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from moritz_agent.skills.geo.distance import haversine_km
from moritz_agent.skills.text.phonetic import phonetic_code

STATES = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}
_STATE_BY_NAME = {name.lower(): code for code, name in STATES.items()}

# "Neustadt (Hessen)" is spoken "Neustadt in Hessen", "Halle (Saale)" "Halle an der Saale"
_SPOKEN_SUFFIX = {
    "hessen": "in Hessen",
    "saale": "an der Saale",
    "oder": "an der Oder",
    "eder": "an der Eder",
    "taunus": "im Taunus",
    "westerwald": "im Westerwald",
    "schwarzwald": "im Schwarzwald",
    "allgäu": "im Allgäu",
}
_DE_TZ = "Europe/Berlin"
_STOP_PREFIXES = ("bad ", "sankt ", "sankt-")
_SUFFIX = re.compile(
    r"\s+(?:(?:an|am|im|in|bei|ob|vor|unter|auf) (?:der |dem |den |die |das )?[a-zäöüß.-]+"
    r"(?: [a-zäöüß.-]+)?)$"
)
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss", "é": "e", "è": "e", "ç": "c"})


def fold(text: str) -> str:
    """Matching key of a name: lower case, umlauts folded, punctuation out, "St." → "sankt"."""
    text = text.lower().strip()
    text = re.sub(r"\bst\.?(?=\s|-)", "sankt", text)
    text = text.translate(_FOLD)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Place:
    name: str
    postal_codes: tuple[str, ...] = ()
    district: str = ""
    state: str = ""  # two-letter code for Germany ("HE"), empty abroad
    country: str = "Deutschland"
    lat: float = 0.0
    lon: float = 0.0
    tz: str = _DE_TZ
    population: int = 0
    parent: str = ""  # a district ("Kubach") belongs to a town ("Weilburg")
    source: str = "seed"
    queried_postcode: str = ""  # the postcode that led here, if any

    @property
    def spoken(self) -> str:
        """Name for the voice: "Neustadt (Hessen)" → "Neustadt in Hessen"."""
        match = re.match(r"^(.*?)\s*\((.+)\)$", self.name)
        if not match:
            return self.name
        base, extra = match.group(1), match.group(2)
        suffix = _SPOKEN_SUFFIX.get(extra.lower())
        return f"{base} {suffix}" if suffix else base

    @property
    def state_name(self) -> str:
        return STATES.get(self.state, "")

    @property
    def domestic(self) -> bool:
        return self.country == "Deutschland"

    @property
    def key(self) -> str:
        return f"{self.lat:.2f},{self.lon:.2f}"

    def location_phrase(self) -> str:
        """ "im Landkreis Limburg-Weilburg, Hessen" / "in Frankreich"."""
        if not self.domestic:
            return f"in {self.country}" if self.country else ""
        parts = []
        if self.district and self.district != self.name:
            parts.append(_district_phrase(self.district))
        if self.state_name and self.state_name != self.name:
            parts.append(self.state_name)
        return ", ".join(parts)


def _district_phrase(district: str) -> str:
    if district.startswith(("Landkreis", "Kreis", "Region", "Stadtkreis")):
        return f"im {district}"
    return f"im Landkreis {district}"


@dataclass(frozen=True)
class Hit:
    place: Place
    how: str  # exact | stripped | district | fuzzy | phonetic
    score: float
    matched: str = ""


@dataclass
class Lookup:
    """Result of a name search: one place, several equally good ones, or nothing."""

    hits: list[Hit] = field(default_factory=list)
    ambiguous: bool = False

    @property
    def best(self) -> Hit | None:
        return self.hits[0] if self.hits else None


@dataclass
class _Entry:
    place: Place
    weight: float
    how: str


class Gazetteer:
    def __init__(self) -> None:
        self.places: list[Place] = []
        self._by_key: dict[str, list[_Entry]] = defaultdict(list)
        self._by_plz: dict[str, list[Place]] = defaultdict(list)
        self._ranges: list[tuple[int, int, Place]] = []
        self._phonetic: dict[str, list[tuple[str, Place]]] = defaultdict(list)
        self._keys: list[str] = []
        self.home: Place | None = None

    # -- loading -----------------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> Gazetteer:
        geo = root / "assets" / "data" / "geo"
        gaz = cls()
        gaz._read_places(geo / "seed-places.tsv", source="seed")
        gaz._read_places(geo / "de-places.tsv", source="geonames")
        gaz._read_postcodes(geo / "de-postcodes.tsv")
        gaz._read_world(geo / "world-cities.tsv")
        gaz._read_ranges(geo / "plz-bereiche.tsv")
        gaz._index()
        gaz._read_aliases(geo / "aliases.de.toml")
        return gaz

    @classmethod
    def from_places(cls, places: list[Place], ranges: list[tuple[int, int, str]] | None = None):
        gaz = cls()
        for place in places:
            gaz._add(place)
        for low, high, name in ranges or []:
            target = next((p for p in places if p.name == name), None)
            if target:
                gaz._ranges.append((low, high, target))
        gaz._index()
        return gaz

    @staticmethod
    def _rows(path: Path):
        if not path.is_file():
            return
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if not row or row[0].startswith("#"):
                    continue
                yield row

    def _read_places(self, path: Path, *, source: str) -> None:
        # hand-kept places win over the bulk data: skip what the seed file already has
        known = {(fold(p.name), p.state) for p in self.places} if source != "seed" else set()
        for row in self._rows(path):
            row = [*row, *[""] * (8 - len(row))]
            name, plz, district, state, lat, lon, pop, parent = row[:8]
            try:
                place = Place(
                    name=name.strip(),
                    postal_codes=(plz,) if plz else (),
                    district=district.strip(),
                    state=state.strip(),
                    lat=float(lat),
                    lon=float(lon),
                    population=int(pop or 0),
                    parent=parent.strip(),
                    source=source,
                )
            except ValueError:
                continue
            if (fold(place.name), place.state) in known:
                continue
            self._add(place)

    def _read_postcodes(self, path: Path) -> None:
        """Full postcode list: ``plz name kreis land lat lon`` (adds postcodes to known places)."""
        for row in self._rows(path):
            if len(row) < 6:
                continue
            plz, name, district, state, lat, lon = row[:6]
            try:
                place = Place(
                    name=name,
                    postal_codes=(plz,),
                    district=district,
                    state=state,
                    lat=float(lat),
                    lon=float(lon),
                    source="geonames",
                )
            except ValueError:
                continue
            self._by_plz[plz].append(place)

    def _read_world(self, path: Path) -> None:
        for row in self._rows(path):
            if len(row) < 6:
                continue
            name, country, lat, lon, tz, pop = row[:6]
            try:
                self._add(
                    Place(
                        name=name,
                        country=country,
                        lat=float(lat),
                        lon=float(lon),
                        tz=tz,
                        population=int(pop or 0),
                        source="world",
                    )
                )
            except ValueError:
                continue

    def _read_ranges(self, path: Path) -> None:
        by_name = {p.name: p for p in self.places if p.domestic and not p.parent}
        for row in self._rows(path):
            if len(row) < 3:
                continue
            low, high, name = row[:3]
            place = by_name.get(name)
            if place and low.isdigit() and high.isdigit():
                self._ranges.append((int(low), int(high), place))

    def _read_aliases(self, path: Path) -> None:
        """Colloquial names ("Malle") and countries (capital) pointing at places already loaded."""
        if not path.is_file():
            return
        try:
            tables = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        by_name = {fold(p.name): p for p in self.places if not p.parent}
        for table in ("orte", "laender"):
            for alias, target in (tables.get(table) or {}).items():
                place = by_name.get(fold(str(target)))
                key = fold(alias)
                if place is not None and key and key not in self._by_key:
                    self._by_key[key].append(_Entry(place, 1.0, "alias"))
        self._keys = sorted(self._by_key)

    def _add(self, place: Place) -> None:
        self.places.append(place)
        for plz in place.postal_codes:
            self._by_plz[plz].append(place)

    def _index(self) -> None:
        for place in self.places:
            for variant, weight, how in _variants(place):
                self._by_key[variant].append(_Entry(place, weight, how))
                if how == "exact":
                    compact = variant.replace(" ", "")
                    self._phonetic[phonetic_code(compact)].append((variant, place))
        self._keys = sorted(self._by_key)

    def set_home(self, postal_code: str, name: str, lat: float = 0.0, lon: float = 0.0) -> Place:
        """Resolve ``skills.home``; coordinates from the settings override the table."""
        place = None
        for candidate in self._by_plz.get(postal_code, []):
            if fold(candidate.name) == fold(name) or not place:
                place = candidate
        if place is None:
            looked = self.find(name)
            place = looked.best.place if looked.best else None
        if place is None:
            place = Place(name=name, postal_codes=(postal_code,), lat=lat, lon=lon, source="config")
        if lat or lon:
            place = replace(place, lat=lat, lon=lon)
        if postal_code and postal_code not in place.postal_codes:
            place = replace(place, postal_codes=(postal_code, *place.postal_codes))
        self.home = replace(place, queried_postcode="")
        return self.home

    # -- postcodes ---------------------------------------------------------------------------
    def by_postcode(self, plz: str) -> Place | None:
        plz = plz.strip()
        if not re.fullmatch(r"\d{5}", plz):
            return None
        found = self._by_plz.get(plz)
        if found:
            main = max(found, key=lambda p: (not p.parent, p.population))
            if main.parent:  # a district: the postcode belongs to its town
                town = self._town_of(main)
                main = town or main
            return replace(main, queried_postcode=plz)
        number = int(plz)
        for low, high, place in self._ranges:
            if low <= number <= high:
                return replace(place, queried_postcode=plz)
        return None

    def _town_of(self, place: Place) -> Place | None:
        for entry in self._by_key.get(fold(place.parent), []):
            if entry.place.name == place.parent and not entry.place.parent:
                return entry.place
        return None

    def similar_postcodes(self, plz: str) -> list[Place]:
        """Postcodes that differ in exactly one digit (for "Die PLZ kenne ich nicht – meinst du …?")."""
        found: list[Place] = []
        if not re.fullmatch(r"\d{5}", plz):
            return found
        for known in self._by_plz:
            if sum(a != b for a, b in zip(plz, known, strict=True)) == 1:
                place = self.by_postcode(known)
                if place and place.name not in {p.name for p in found}:
                    found.append(place)
        return sorted(found, key=lambda p: -p.population)[:3]

    def postcodes_of(self, place: Place) -> list[str]:
        codes = {c for c in place.postal_codes}
        for plz, places in self._by_plz.items():
            if any(p.name == place.name and p.state == place.state for p in places):
                codes.add(plz)
        for low, high, target in self._ranges:
            if target.name == place.name:
                codes.update(f"{n:05d}" for n in range(low, high + 1))
        return sorted(codes)

    # -- names -------------------------------------------------------------------------------
    def find(self, name: str, *, near: Place | None = None, limit: int = 4) -> Lookup:
        """Search ``name`` (as spoken); ``near`` prefers places close to it."""
        key = fold(_spoken_to_name(name))
        if not key:
            return Lookup()
        near = near or self.home
        entries = self._by_key.get(key)
        if entries:
            return self._rank(entries, near, limit, matched=key)
        for how, found in self._fuzzy(key):
            if found:
                hits = [Hit(p, how, score, matched=key) for p, score in found[:limit]]
                return Lookup(
                    hits=hits, ambiguous=len(hits) > 1 and hits[0].score - hits[1].score < 0.03
                )
        return Lookup()

    def suggest(self, text: str, limit: int = 25) -> list[Place]:
        """Places whose name or postcode starts with what is typed so far (autocomplete)."""
        typed = text.strip()
        if not typed:
            return []
        if typed.isdigit():
            places = [p for p in self.places if any(c.startswith(typed) for c in p.postal_codes)]
        else:
            key = fold(typed)
            start = bisect.bisect_left(self._keys, key)
            places = []
            for candidate in self._keys[start:]:
                if not candidate.startswith(key):
                    break
                places.extend(entry.place for entry in self._by_key[candidate])
        places.sort(key=lambda p: (bool(p.parent), -p.population, p.name))
        unique: list[Place] = []
        seen: set[tuple[str, str]] = set()
        for place in places:
            ident = (place.name, place.state or place.country)
            if ident not in seen:
                seen.add(ident)
                unique.append(place)
        return unique[:limit]

    def _rank(
        self, entries: list[_Entry], near: Place | None, limit: int, *, matched: str
    ) -> Lookup:
        scored: list[tuple[float, _Entry]] = []
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            ident = (entry.place.name, entry.place.state or entry.place.country)
            if ident in seen:
                continue
            seen.add(ident)
            scored.append((self._score(entry, near), entry))
        scored.sort(key=lambda item: -item[0])
        hits = [Hit(e.place, e.how, s, matched=matched) for s, e in scored[:limit]]
        ambiguous = len(hits) > 1 and hits[0].score < 1.3 * hits[1].score
        return Lookup(hits=hits, ambiguous=ambiguous)

    @staticmethod
    def _score(entry: _Entry, near: Place | None) -> float:
        place = entry.place
        size = math.log10(place.population + 10)
        closeness = 1.0
        if near is not None and (near.lat or near.lon):
            closeness += max(
                0.0, 1.0 - haversine_km(place.lat, place.lon, near.lat, near.lon) / 300
            )
        penalty = 0.6 if place.parent else 1.0  # prefer the town over its district
        return entry.weight * size * closeness * penalty

    def _fuzzy(self, key: str):
        """Yield ("fuzzy"|"phonetic", [(place, score)]) – the first non-empty stage wins."""
        if len(key) < 4:
            return
        best: list[tuple[float, str]] = []
        matcher = difflib.SequenceMatcher(autojunk=False)
        matcher.set_seq2(key)
        for candidate in self._keys:
            if abs(len(candidate) - len(key)) > 3 or candidate[0] != key[0]:
                continue
            matcher.set_seq1(candidate)
            if matcher.real_quick_ratio() < 0.86 or matcher.quick_ratio() < 0.86:
                continue
            ratio = matcher.ratio()
            if ratio >= 0.86:
                best.append((ratio, candidate))
        if best:
            best.sort(reverse=True)
            top = best[0][0]
            found: list[tuple[Place, float]] = []
            for ratio, candidate in best:
                if ratio < top - 0.04:
                    break
                for entry in self._by_key[candidate]:
                    if entry.place not in [p for p, _ in found]:
                        found.append((entry.place, ratio * entry.weight))
            found.sort(key=lambda item: (-item[1], -item[0].population))
            yield "fuzzy", found
        code = phonetic_code(key.replace(" ", ""))
        if len(code) >= 3:
            phon: list[tuple[Place, float]] = []
            for variant, place in self._phonetic.get(code, []):
                if abs(len(variant) - len(key)) <= 2:
                    phon.append((place, 0.8 + min(0.1, math.log10(place.population + 10) / 100)))
            phon.sort(key=lambda item: -item[1])
            yield "phonetic", phon

    def exact_names(self, name: str) -> list[Place]:
        """All places called exactly (or after stripping additions) like ``name``."""
        return [e.place for e in self._by_key.get(fold(_spoken_to_name(name)), [])]

    def known_prefix(self, tokens: list[str]) -> int:
        """Number of leading ``tokens`` forming a known name (longest first), 0 if none."""
        for size in range(min(len(tokens), 6), 0, -1):
            if fold(_spoken_to_name(" ".join(tokens[:size]))) in self._by_key:
                return size
        return 0

    def is_known(self, name: str) -> bool:
        return fold(_spoken_to_name(name)) in self._by_key


def _spoken_to_name(text: str) -> str:
    """Undo how speech recognition and the cleaner mangle abbreviations in place names."""
    text = f" {text.lower()} "
    text = re.sub(r"\ba\.? ?d\.?(?= )", "an der", text)
    text = re.sub(r"\bi\.? ?d\.?(?= )", "in der", text)
    text = re.sub(r"\ba\.? ?m\.?(?= )", "am", text)
    text = re.sub(r"\bi\.? ?t\.?(?= )", "im taunus", text)
    return text.strip()


def _variants(place: Place) -> list[tuple[str, float, str]]:
    """Lookup keys of a place with weights: the full name, and the name without additions."""
    out: list[tuple[str, float, str]] = []
    full = fold(place.name)
    if not full:
        return out
    weight = 1.0
    how = "district" if place.parent else "exact"
    out.append((full, weight, how))
    spoken = fold(place.spoken)  # "Frankfurt (Oder)" is said "Frankfurt an der Oder"
    if spoken and spoken != full:
        out.append((spoken, weight, how))
    bare = fold(re.sub(r"\s*\(.*?\)", "", place.name))
    if bare and bare != full:
        out.append((bare, 0.9, "stripped"))
    base = _SUFFIX.sub("", bare or full)
    if base and base not in {full, bare}:
        out.append((base, 0.85, "stripped"))
    for prefix in _STOP_PREFIXES:
        if base.startswith(prefix) and len(base) > len(prefix) + 3:
            out.append((base[len(prefix) :].lstrip("-"), 0.75, "stripped"))
    if place.parent:
        out.append((fold(f"{place.parent} {place.name}"), 0.9, "district"))
    return out


def state_code(text: str) -> str:
    """ "hessen" → "HE" (also two-letter codes)."""
    text = text.strip().lower()
    if text.upper() in STATES:
        return text.upper()
    return _STATE_BY_NAME.get(text, "")

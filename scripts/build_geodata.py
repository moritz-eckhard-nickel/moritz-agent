#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Build the full German place and postcode lists from GeoNames (docs/plan/13 §11, ADR-031).

    python scripts/build_geodata.py            # download from download.geonames.org
    python scripts/build_geodata.py --from DIR # use DE.zip (postcodes) and DE-places.zip already there

Writes ``assets/data/geo/de-postcodes.tsv`` and ``de-places.tsv`` (read by the gazetteer next to the
shipped seed file) and ``assets/data/geo/SOURCES.md`` with the SHA-256 of the raw downloads.
GeoNames data are licensed CC BY 4.0 (https://www.geonames.org/) – see THIRD_PARTY_NOTICES.md.
The files are *not* edited by hand; run this script again to renew them.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "assets" / "data" / "geo"
POSTCODES_URL = "https://download.geonames.org/export/zip/DE.zip"
PLACES_URL = "https://download.geonames.org/export/dump/DE.zip"
PLACE_FEATURES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLG", "PPLS", "PPLX"}
HEADER = (
    "# SPDX-License-Identifier: LicenseRef-MSOL-1.1\n"
    "# Erzeugt von scripts/build_geodata.py aus GeoNames (CC BY 4.0, https://www.geonames.org/), {when}.\n"
    "# Nicht von Hand ändern – das Skript erneut ausführen. Spalten: {columns}\n"
)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "moritz-agent build_geodata"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def read_zip(blob: bytes, member: str) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive, archive.open(member) as handle:
        text = handle.read().decode("utf-8")
    return [line.split("\t") for line in text.splitlines() if line.strip()]


def parse_postcodes(rows: list[list[str]]) -> list[tuple[str, str, str, str, float, float]]:
    """GeoNames postal codes: country, plz, place, state, state code, region, code, district …"""
    out = []
    for row in rows:
        if len(row) < 11 or row[0] != "DE":
            continue
        try:
            out.append((row[1], row[2], row[7], row[4], float(row[9]), float(row[10])))
        except ValueError:
            continue
    return out


def parse_places(rows: list[list[str]]) -> list[tuple[str, float, float, int, str]]:
    """GeoNames dump: id, name, ascii, alternatives, lat, lon, class, feature code, … population."""
    out = []
    for row in rows:
        if len(row) < 15 or row[7] not in PLACE_FEATURES or row[8] != "DE":
            continue
        try:
            out.append((row[1], float(row[4]), float(row[5]), int(row[14] or 0), row[7]))
        except ValueError:
            continue
    return out


class Grid:
    """Nearest postcode entry of a coordinate (0.1° cells)."""

    def __init__(self, postcodes: list[tuple[str, str, str, str, float, float]]) -> None:
        self.cells: dict[tuple[int, int], list[tuple[str, str, str, str, float, float]]] = (
            defaultdict(list)
        )
        for entry in postcodes:
            self.cells[(int(entry[4] * 10), int(entry[5] * 10))].append(entry)

    def nearest(self, lat: float, lon: float):
        best, best_d = None, 1e9
        cx, cy = int(lat * 10), int(lon * 10)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for entry in self.cells.get((cx + dx, cy + dy), ()):
                    d = (entry[4] - lat) ** 2 + (entry[5] - lon) ** 2
                    if d < best_d:
                        best, best_d = entry, d
        return best


def build(postcode_rows: list[list[str]], place_rows: list[list[str]]) -> tuple[str, str]:
    postcodes = parse_postcodes(postcode_rows)
    places = parse_places(place_rows)
    when = date.today().isoformat()
    pc_lines = [
        f"{plz}\t{name}\t{district}\t{state}\t{lat:.4f}\t{lon:.4f}"
        for plz, name, district, state, lat, lon in sorted(postcodes)
    ]
    grid = Grid(postcodes)
    place_lines = []
    for name, lat, lon, population, feature in sorted(places):
        near = grid.nearest(lat, lon)
        if near is None:
            continue
        parent = near[1] if feature == "PPLX" and near[1] != name else ""
        place_lines.append(
            f"{name}\t{near[0]}\t{near[2]}\t{near[3]}\t{lat:.4f}\t{lon:.4f}\t{population}\t{parent}"
        )
    pc_text = (
        HEADER.format(when=when, columns="plz name kreis land breite länge")
        + "\n".join(pc_lines)
        + "\n"
    )
    place_text = (
        HEADER.format(when=when, columns="name plz kreis land breite länge einwohner gehört_zu")
        + "\n".join(place_lines)
        + "\n"
    )
    return pc_text, place_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--from", dest="source", type=Path, help="directory with DE.zip and DE-places.zip"
    )
    args = parser.parse_args(argv)
    if args.source:
        postal_blob = (args.source / "DE.zip").read_bytes()
        places_blob = (args.source / "DE-places.zip").read_bytes()
    else:
        print(f"Lade {POSTCODES_URL} …")
        postal_blob = fetch(POSTCODES_URL)
        print(f"Lade {PLACES_URL} …")
        places_blob = fetch(PLACES_URL)
    postcodes_text, places_text = build(
        read_zip(postal_blob, "DE.txt"), read_zip(places_blob, "DE.txt")
    )
    GEO.mkdir(parents=True, exist_ok=True)
    (GEO / "de-postcodes.tsv").write_text(postcodes_text, encoding="utf-8")
    (GEO / "de-places.tsv").write_text(places_text, encoding="utf-8")
    (GEO / "SOURCES.md").write_text(
        "# Herkunft der Ortsdaten\n\n"
        "GeoNames (https://www.geonames.org/), Lizenz CC BY 4.0. Erzeugt von "
        "`scripts/build_geodata.py` am "
        f"{date.today().isoformat()}.\n\n"
        "| Rohdatei | SHA-256 |\n| --- | --- |\n"
        f"| {POSTCODES_URL} | `{hashlib.sha256(postal_blob).hexdigest()}` |\n"
        f"| {PLACES_URL} | `{hashlib.sha256(places_blob).hexdigest()}` |\n",
        encoding="utf-8",
    )
    print(
        f"{len(postcodes_text.splitlines()) - 3} Postleitzahlen, "
        f"{len(places_text.splitlines()) - 3} Orte → {GEO}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

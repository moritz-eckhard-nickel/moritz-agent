# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""ECB euro foreign exchange reference rates (docs/plan/13 §6.12)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from moritz_agent.skills.providers.http import HttpClient, HttpError

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


@dataclass(frozen=True)
class Rates:
    day: date
    rates: dict[str, float]  # 1 euro = rate × currency

    def per_euro(self, code: str) -> float | None:
        return 1.0 if code == "EUR" else self.rates.get(code)

    def convert(self, amount: float, source: str, target: str) -> float | None:
        a, b = self.per_euro(source), self.per_euro(target)
        if a is None or b is None or a <= 0:
            return None
        return amount / a * b


async def fetch(http: HttpClient) -> str:
    raw = await http.get_bytes(URL)
    return raw.decode("utf-8", errors="replace")


def parse(text: str) -> Rates:
    """Parse the daily XML; documents with a DTD or entities are refused (nothing to expand)."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise HttpError("bad_data", "ecb: unexpected document type")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise HttpError("bad_data", "ecb: invalid XML") from exc
    rates: dict[str, float] = {}
    day: date | None = None
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag != "Cube":
            continue
        if "time" in node.attrib:
            try:
                day = date.fromisoformat(node.attrib["time"])
            except ValueError as exc:
                raise HttpError("bad_data", "ecb: invalid date") from exc
        elif "currency" in node.attrib and "rate" in node.attrib:
            try:
                value = float(node.attrib["rate"])
            except ValueError:
                continue
            if 0 < value < 1e7:
                rates[node.attrib["currency"].upper()] = value
    if day is None or not rates:
        raise HttpError("bad_data", "ecb: no rates")
    return Rates(day, rates)

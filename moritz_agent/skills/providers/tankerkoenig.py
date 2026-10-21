# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Fuel prices from Tankerkönig / MTS-K (CC BY 4.0, personal API key needed)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from moritz_agent.config.secrets import Secret
from moritz_agent.skills.providers.http import HttpClient, HttpError

URL = "https://creativecommons.tankerkoenig.de/json/list.php"


@dataclass(frozen=True)
class Station:
    name: str
    brand: str
    place: str
    distance_km: float
    price: float  # euro per litre


async def fetch(
    http: HttpClient, lat: float, lon: float, radius_km: float, fuel: str, key: Secret
) -> dict[str, Any]:
    raw = await http.get_json(
        URL,
        {
            "lat": f"{lat:.3f}",
            "lng": f"{lon:.3f}",
            "rad": f"{radius_km:g}",
            "sort": "price",
            "type": fuel,
            "apikey": key.reveal(),
        },
    )
    if not isinstance(raw, dict) or raw.get("ok") is not True:
        # the service's message may repeat the key; never pass it on
        raise HttpError("bad_data", "tankerkoenig: request refused")
    return raw


def stations(raw: dict[str, Any]) -> list[Station]:
    found = []
    for item in raw.get("stations", []):
        if not isinstance(item, dict) or not item.get("isOpen") or item.get("price") in (None, 0):
            continue
        price = float(item["price"])
        if not 0.5 <= price <= 5.0:
            continue
        found.append(
            Station(
                name=str(item.get("name") or item.get("brand") or "Tankstelle").title(),
                brand=str(item.get("brand") or "").title(),
                place=str(item.get("place") or "").title(),
                distance_km=float(item.get("dist") or 0.0),
                price=price,
            )
        )
    return sorted(found, key=lambda s: s.price)

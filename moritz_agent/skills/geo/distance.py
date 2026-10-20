# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Great-circle distance and compass direction between two points (docs/plan/13 §6.10)."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088

_DIRECTIONS = (
    "Norden",
    "Nordosten",
    "Osten",
    "Südosten",
    "Süden",
    "Südwesten",
    "Westen",
    "Nordwesten",
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance over the ground ("Luftlinie") in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, 0 = north, clockwise."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass_de(bearing: float) -> str:
    """ "Südosten" for 135° (dative-free form that goes after "Richtung")."""
    return _DIRECTIONS[int(((bearing % 360) + 22.5) // 45) % 8]


def wind_from_de(degrees: float) -> str:
    """Direction the wind blows *from*, as in "aus Südwest"."""
    return compass_de(degrees).removesuffix("en")

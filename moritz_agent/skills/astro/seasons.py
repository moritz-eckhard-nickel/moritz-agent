# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Equinoxes and solstices (J. Meeus "Astronomical Algorithms" ch. 27, accurate to about a minute)."""

from __future__ import annotations

import math
from datetime import datetime

from moritz_agent.skills.astro.moon import delta_t
from moritz_agent.skills.astro.sun import from_julian_day

# (A, B, C): S = Σ A · cos(B + C · T)
_TERMS = (
    (485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186),
    (182, 27.85, 445267.112), (156, 73.14, 45036.886), (136, 171.52, 22518.443),
    (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513),
    (58, 119.81, 33718.147), (52, 297.17, 150.678), (50, 21.02, 2281.226),
    (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
    (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029),
    (14, 199.76, 31436.921), (12, 95.39, 14577.848), (12, 287.11, 31931.756),
    (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074),
)  # fmt: skip
_BASE = {
    "spring": (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
    "summer": (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030),
    "autumn": (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
    "winter": (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032),
}
NAMES = {"spring": "Frühling", "summer": "Sommer", "autumn": "Herbst", "winter": "Winter"}
# the astronomical beginning of each season and what happens then
EVENTS = {
    "spring": "Frühlingsanfang",
    "summer": "Sommeranfang",
    "autumn": "Herbstanfang",
    "winter": "Winteranfang",
}


def season_start(year: int, season: str, tz: str = "Europe/Berlin") -> datetime:
    """Moment of the equinox (spring, autumn) or solstice (summer, winter) of ``year``."""
    a, b, c, d, e = _BASE[season]
    y = (year - 2000) / 1000.0
    jde0 = a + b * y + c * y**2 + d * y**3 + e * y**4
    t = (jde0 - 2451545.0) / 36525.0
    w = 35999.373 * t - 2.47
    delta = 1 + 0.0334 * math.cos(math.radians(w)) + 0.0007 * math.cos(math.radians(2 * w))
    s = sum(amp * math.cos(math.radians(phase + freq * t)) for amp, phase, freq in _TERMS)
    jde = jde0 + 0.00001 * s / delta
    return from_julian_day(jde - delta_t(year) / 86400.0, tz)


def meteorological_start(year: int, season: str) -> tuple[int, int]:
    """(month, day) of the meteorological season: spring 1.3., summer 1.6., autumn 1.9., winter 1.12."""
    return {"spring": (3, 1), "summer": (6, 1), "autumn": (9, 1), "winter": (12, 1)}[season]

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Moon phases (J. Meeus "Astronomical Algorithms" ch. 49), illumination, rise and set.

Phase times are accurate to about a minute, rise and set (low-precision lunar position with
parallax) to a few minutes – enough for "etwa".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from moritz_agent.skills.astro.sun import from_julian_day, julian_day

SYNODIC_MONTH = 29.530588861
_NAMES = ("new", "first_quarter", "full", "last_quarter")


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cos(deg: float) -> float:
    return math.cos(math.radians(deg))


def delta_t(year: float) -> float:
    """TT − UT in seconds (polynomial of Espenak/Meeus for 2005–2050, rough elsewhere)."""
    t = year - 2000
    return 62.92 + 0.32217 * t + 0.005589 * t * t if 2005 <= year <= 2050 else 69.0


def phase_jde(k: float) -> float:
    """Julian ephemeris day of the new moon (k integer), first quarter (k + .25), full moon (k + .5)
    or last quarter (k + .75)."""
    t = k / 1236.85
    jde = (
        2451550.09766
        + SYNODIC_MONTH * k
        + 0.00015437 * t**2
        - 0.00000015 * t**3
        + 0.00000000073 * t**4
    )
    e = 1 - 0.002516 * t - 0.0000074 * t**2
    m = 2.5534 + 29.1053567 * k - 0.0000014 * t**2 - 0.00000011 * t**3
    mp = 201.5643 + 385.81693528 * k + 0.0107582 * t**2 + 0.00001238 * t**3 - 0.000000058 * t**4
    f = 160.7108 + 390.67050284 * k - 0.0016118 * t**2 - 0.00000227 * t**3 + 0.000000011 * t**4
    om = 124.7746 - 1.56375588 * k + 0.0020672 * t**2 + 0.00000215 * t**3
    kind = round((k % 1) * 4) % 4
    if kind in (0, 2):
        a, b, c = (-0.4072, 0.17241, 0.01608) if kind == 0 else (-0.40614, 0.17302, 0.01614)
        d, ee, ff = (0.01039, 0.00739, -0.00514) if kind == 0 else (0.01043, 0.00734, -0.00515)
        corr = (
            a * _sin(mp)
            + b * e * _sin(m)
            + c * _sin(2 * mp)
            + d * _sin(2 * f)
            + ee * e * _sin(mp - m)
            + ff * e * _sin(mp + m)
            + 0.00208 * e * e * _sin(2 * m)
            - 0.00111 * _sin(mp - 2 * f)
            - 0.00057 * _sin(mp + 2 * f)
            + 0.00056 * e * _sin(2 * mp + m)
            - 0.00042 * _sin(3 * mp)
            + 0.00042 * e * _sin(m + 2 * f)
            + 0.00038 * e * _sin(m - 2 * f)
            - 0.00024 * e * _sin(2 * mp - m)
            - 0.00017 * _sin(om)
            - 0.00007 * _sin(mp + 2 * m)
            + 0.00004 * _sin(2 * mp - 2 * f)
            + 0.00004 * _sin(3 * m)
            + 0.00003 * _sin(mp + m - 2 * f)
            + 0.00003 * _sin(2 * mp + 2 * f)
            - 0.00003 * _sin(mp + m + 2 * f)
            + 0.00003 * _sin(mp - m + 2 * f)
            - 0.00002 * _sin(mp - m - 2 * f)
            - 0.00002 * _sin(3 * mp + m)
            + 0.00002 * _sin(4 * mp)
        )
    else:
        corr = (
            -0.62801 * _sin(mp)
            + 0.17172 * e * _sin(m)
            - 0.01183 * e * _sin(mp + m)
            + 0.00862 * _sin(2 * mp)
            + 0.00804 * _sin(2 * f)
            + 0.00454 * e * _sin(mp - m)
            + 0.00204 * e * e * _sin(2 * m)
            - 0.0018 * _sin(mp - 2 * f)
            - 0.0007 * _sin(mp + 2 * f)
            - 0.0004 * _sin(3 * mp)
            - 0.00034 * e * _sin(2 * mp - m)
            + 0.00032 * e * _sin(m + 2 * f)
            + 0.00032 * e * _sin(m - 2 * f)
            - 0.00028 * e * e * _sin(mp + 2 * m)
            + 0.00027 * e * _sin(2 * mp + m)
            - 0.00017 * _sin(om)
            - 0.00005 * _sin(mp - m - 2 * f)
            + 0.00004 * _sin(2 * mp + 2 * f)
            - 0.00004 * _sin(mp + m + 2 * f)
            + 0.00004 * _sin(mp - 2 * m)
            + 0.00003 * _sin(mp + m - 2 * f)
            + 0.00003 * _sin(3 * m)
            + 0.00002 * _sin(2 * mp - 2 * f)
            + 0.00002 * _sin(mp - m + 2 * f)
            - 0.00002 * _sin(3 * mp + m)
        )
        w = (
            0.00306
            - 0.00038 * e * _cos(m)
            + 0.00026 * _cos(mp)
            - 0.00002 * _cos(mp - m)
            + 0.00002 * _cos(mp + m)
            + 0.00002 * _cos(2 * f)
        )
        corr += w if kind == 1 else -w
    return jde + corr


def phase_time(k: float, tz: str = "UTC") -> datetime:
    year = 2000 + k / 12.3685
    jd = phase_jde(k) - delta_t(year) / 86400.0
    return from_julian_day(jd, tz)


def _first_k(moment: datetime, offset: float) -> float:
    return math.floor((julian_day(moment) - 2451550.09766) / SYNODIC_MONTH) - 2 + offset


def next_phase(kind: str, after: datetime) -> datetime:
    """The next ``kind`` of phase (new, first_quarter, full, last_quarter) after ``after``."""
    k = _first_k(after, _NAMES.index(kind) / 4)
    while True:
        moment = phase_time(k).astimezone(after.tzinfo)
        if moment > after:
            return moment
        k += 1


def previous_phase(kind: str, before: datetime) -> datetime:
    k = _first_k(before, _NAMES.index(kind) / 4) + 4
    while True:
        moment = phase_time(k).astimezone(before.tzinfo)
        if moment < before:
            return moment
        k -= 1


# -- position, illumination, rise and set ------------------------------------------------------------
@dataclass(frozen=True)
class MoonPosition:
    longitude: float  # ecliptic, degrees
    latitude: float
    distance_km: float
    right_ascension: float  # degrees
    declination: float


def moon_position(jd: float) -> MoonPosition:
    d = jd - 2451545.0
    l0 = 218.316 + 13.176396 * d
    m = 134.963 + 13.064993 * d
    f = 93.272 + 13.229350 * d
    dd = 297.850 + 12.190749 * d
    ms = 357.529 + 0.98560028 * d
    lon = (
        l0
        + 6.289 * _sin(m)
        + 1.274 * _sin(2 * dd - m)
        + 0.658 * _sin(2 * dd)
        + 0.214 * _sin(2 * m)
        - 0.186 * _sin(ms)
        - 0.114 * _sin(2 * f)
    ) % 360
    lat = 5.128 * _sin(f) + 0.281 * _sin(m + f) + 0.278 * _sin(m - f) + 0.173 * _sin(2 * dd - f)
    dist = 385001 - 20905 * _cos(m) - 3699 * _cos(2 * dd - m) - 2956 * _cos(2 * dd)
    eps = 23.439 - 0.0000004 * d
    ra = (
        math.degrees(
            math.atan2(_sin(lon) * _cos(eps) - math.tan(math.radians(lat)) * _sin(eps), _cos(lon))
        )
        % 360
    )
    dec = math.degrees(math.asin(_sin(lat) * _cos(eps) + _cos(lat) * _sin(eps) * _sin(lon)))
    return MoonPosition(lon, lat, dist, ra, dec)


def elongation(jd: float) -> float:
    """Angle sun–moon along the ecliptic, 0° = new moon, 180° = full moon (0 … 360)."""
    t = (jd - 2451545.0) / 36525.0
    sun_lon = (280.46646 + 36000.76983 * t + 1.9146 * _sin(357.52911 + 35999.05029 * t)) % 360
    return (moon_position(jd).longitude - sun_lon) % 360


def illumination(jd: float) -> float:
    """Lit fraction of the moon's disc (0 … 1)."""
    return (1 - _cos(elongation(jd))) / 2


def phase_name(angle: float) -> str:
    """German name for the elongation angle."""
    for limit, name in (
        (12, "Neumond"),
        (78, "zunehmende Sichel"),
        (102, "zunehmender Halbmond"),
        (168, "zunehmender Mond"),
        (192, "Vollmond"),
        (258, "abnehmender Mond"),
        (282, "abnehmender Halbmond"),
        (348, "abnehmende Sichel"),
    ):
        if angle < limit:
            return name
    return "Neumond"


def _altitude(lat: float, lon: float, jd: float) -> float:
    pos = moon_position(jd)
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360
    hour_angle = gmst + lon - pos.right_ascension
    phi, dec = math.radians(lat), math.radians(pos.declination)
    alt = math.degrees(
        math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * _cos(hour_angle))
    )
    parallax = math.degrees(math.asin(6378.14 / pos.distance_km))
    return alt - parallax * _cos(alt)


def rise_set(lat: float, lon: float, day: date, tz: str) -> tuple[datetime | None, datetime | None]:
    """Moonrise and moonset in the local calendar day (None when the moon does not rise or set)."""
    zone = ZoneInfo(tz)
    start = datetime(day.year, day.month, day.day, tzinfo=zone)
    jd0 = julian_day(start)
    h0 = -0.5667 - 0.2725 * math.degrees(math.asin(6378.14 / 384400))  # refraction + radius
    step = 1 / 144  # 10 minutes
    rise = set_ = None
    previous = _altitude(lat, lon, jd0) - h0
    for i in range(1, 145):
        jd = jd0 + i * step
        current = _altitude(lat, lon, jd) - h0
        if previous < 0 <= current and rise is None:
            rise = _bisect(lat, lon, jd - step, jd, h0)
        elif previous >= 0 > current and set_ is None:
            set_ = _bisect(lat, lon, jd - step, jd, h0)
        previous = current
    return (
        from_julian_day(rise, tz) if rise else None,
        from_julian_day(set_, tz) if set_ else None,
    )


def _bisect(lat: float, lon: float, low: float, high: float, h0: float) -> float:
    rising = _altitude(lat, lon, low) < h0
    for _ in range(30):
        mid = (low + high) / 2
        above = _altitude(lat, lon, mid) >= h0
        if above == rising:
            high = mid
        else:
            low = mid
    return (low + high) / 2

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Sunrise, sunset, twilight and day length (NOAA solar calculator, J. Meeus "Astronomical
Algorithms"); accurate to about a minute for latitudes up to 65°."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

SUNRISE_ZENITH = 90.833  # centre of the sun 50 arc minutes below the horizon (refraction + radius)
CIVIL_ZENITH = 96.0
GOLDEN_ZENITH = 84.0  # sun lower than 6° above the horizon


def julian_day(moment: datetime) -> float:
    """Julian day of an aware datetime."""
    utc = moment.astimezone(UTC)
    year, month = utc.year, utc.month
    if month <= 2:
        year, month = year - 1, month + 12
    a = year // 100
    b = 2 - a + a // 4
    day = utc.day + (utc.hour + (utc.minute + utc.second / 60) / 60) / 24
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def from_julian_day(jd: float, tz: str) -> datetime:
    """Aware datetime in ``tz`` for a Julian day (UT)."""
    unix = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(unix, UTC).astimezone(ZoneInfo(tz))


@dataclass(frozen=True)
class SunPosition:
    declination: float  # degrees
    equation_of_time: float  # minutes


def sun_position(jd: float) -> SunPosition:
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (
        math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * mr) * 0.000289
    )
    omega = 125.04 - 1934.136 * t
    lam = l0 + c - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam))))
    y = math.tan(math.radians(eps) / 2) ** 2
    l0r = math.radians(l0)
    eq = 4 * math.degrees(
        y * math.sin(2 * l0r)
        - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr)
    )
    return SunPosition(decl, eq)


def elevation(lat: float, lon: float, moment: datetime) -> float:
    """Height of the sun above the horizon in degrees (no refraction)."""
    jd = julian_day(moment)
    pos = sun_position(jd)
    utc = moment.astimezone(UTC)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    true_solar = (minutes + pos.equation_of_time + 4 * lon) % 1440
    hour_angle = math.radians(true_solar / 4 - 180)
    phi, decl = math.radians(lat), math.radians(pos.declination)
    value = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, value))))


def _event_minutes(
    lat: float, lon: float, jd_noon: float, zenith: float
) -> tuple[float, float, float] | None:
    """(solar noon, rise, set) in minutes UTC of the day, or None in polar day/night."""
    pos = sun_position(jd_noon)
    phi, decl = math.radians(lat), math.radians(pos.declination)
    cos_h = math.cos(math.radians(zenith)) / (math.cos(phi) * math.cos(decl)) - math.tan(
        phi
    ) * math.tan(decl)
    if not -1.0 <= cos_h <= 1.0:
        return None
    hour_angle = math.degrees(math.acos(cos_h))
    noon = 720 - 4 * lon - pos.equation_of_time
    return noon, noon - 4 * hour_angle, noon + 4 * hour_angle


@dataclass(frozen=True)
class SunDay:
    noon: datetime
    sunrise: datetime | None
    sunset: datetime | None
    dawn: datetime | None  # civil twilight begins
    dusk: datetime | None  # civil twilight ends
    golden_start: datetime | None  # in the evening: sun drops below 6°
    noon_elevation: float

    @property
    def daylight(self) -> timedelta | None:
        if self.sunrise is None or self.sunset is None:
            return None
        return self.sunset - self.sunrise


def sun_day(lat: float, lon: float, day: date, tz: str) -> SunDay:
    """Sun times of the calendar day ``day`` at a place (polar day or night: fields are None)."""
    zone = ZoneInfo(tz)
    midnight_utc = datetime(day.year, day.month, day.day, tzinfo=UTC)

    def at(minutes: float) -> datetime:
        return (midnight_utc + timedelta(minutes=minutes)).astimezone(zone)

    def refined(zenith: float) -> tuple[float, float, float] | None:
        first = _event_minutes(lat, lon, julian_day(midnight_utc) + 0.5 - lon / 360, zenith)
        if first is None:
            return None
        noon, rise, set_ = first
        # second pass with the sun's position at the estimated events
        rise_pass = _event_minutes(lat, lon, julian_day(midnight_utc) + rise / 1440, zenith)
        set_pass = _event_minutes(lat, lon, julian_day(midnight_utc) + set_ / 1440, zenith)
        if rise_pass is None or set_pass is None:
            return None
        return noon, rise_pass[1], set_pass[2]

    main = refined(SUNRISE_ZENITH)
    civil = refined(CIVIL_ZENITH)
    golden = refined(GOLDEN_ZENITH)
    noon_minutes = (
        main[0]
        if main
        else 720 - 4 * lon - sun_position(julian_day(midnight_utc) + 0.5).equation_of_time
    )
    noon_time = at(noon_minutes)
    return SunDay(
        noon=noon_time,
        sunrise=at(main[1]) if main else None,
        sunset=at(main[2]) if main else None,
        dawn=at(civil[1]) if civil else None,
        dusk=at(civil[2]) if civil else None,
        golden_start=at(golden[2]) if golden else None,
        noon_elevation=elevation(lat, lon, noon_time),
    )

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Provider-independent weather data: one pack per place answers every weather skill (13 §7.2)."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, TypeVar


@dataclass(frozen=True)
class Current:
    time: datetime
    temperature: float | None = None
    apparent: float | None = None
    humidity: float | None = None
    is_day: bool = True
    precipitation: float | None = None  # mm in the last interval
    rain: float | None = None
    snowfall: float | None = None
    code: int | None = None
    cloud_cover: float | None = None
    pressure: float | None = None
    wind: float | None = None  # km/h
    wind_dir: float | None = None
    gusts: float | None = None


@dataclass(frozen=True)
class HourPoint:
    time: datetime
    temperature: float | None = None
    apparent: float | None = None
    humidity: float | None = None
    dew_point: float | None = None
    precip_prob: float | None = None  # 0 … 100
    precipitation: float = 0.0  # mm
    rain: float | None = None
    showers: float | None = None
    snowfall: float | None = None  # cm
    snow_depth: float | None = None
    code: int | None = None
    cloud_cover: float | None = None
    visibility: float | None = None  # m
    pressure: float | None = None
    wind: float | None = None  # km/h
    wind_dir: float | None = None
    gusts: float | None = None
    uv: float | None = None
    is_day: bool = True
    sunshine_s: float | None = None  # seconds of sunshine in this hour
    cape: float | None = None
    soil_temperature: float | None = None


@dataclass(frozen=True)
class DayPoint:
    day: date
    code: int | None = None
    tmax: float | None = None
    tmin: float | None = None
    apparent_max: float | None = None
    apparent_min: float | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None
    daylight_s: float | None = None
    sunshine_s: float | None = None
    uv_max: float | None = None
    precipitation: float | None = None
    rain: float | None = None
    showers: float | None = None
    snowfall: float | None = None
    precip_hours: float | None = None
    precip_prob_max: float | None = None
    wind_max: float | None = None
    gusts_max: float | None = None
    wind_dir: float | None = None
    et0: float | None = None


@dataclass(frozen=True)
class Minute15:
    time: datetime
    precipitation: float = 0.0
    code: int | None = None


@dataclass
class WeatherPack:
    """Current values, 15-minute, hourly and daily series for one place."""

    lat: float
    lon: float
    tz: str
    fetched_at: datetime
    source: str  # open-meteo | brightsky
    model: str = ""
    current: Current | None = None
    minutes: list[Minute15] = field(default_factory=list)
    hours: list[HourPoint] = field(default_factory=list)
    days: list[DayPoint] = field(default_factory=list)
    station: str = ""  # DWD station name (Bright Sky)
    station_km: float | None = None

    # -- access -----------------------------------------------------------------------------
    def _hour_times(self) -> list[datetime]:
        return [h.time for h in self.hours]

    def hour_at(self, moment: datetime) -> HourPoint | None:
        """The hourly point that covers ``moment`` (the hour starting at or before it)."""
        if not self.hours:
            return None
        index = bisect_right(self._hour_times(), moment) - 1
        if index < 0 or moment - self.hours[index].time >= timedelta(hours=1, minutes=30):
            return None
        return self.hours[index]

    def hours_between(self, start: datetime, end: datetime) -> list[HourPoint]:
        """Hourly points with ``start`` <= time < ``end``."""
        return [h for h in self.hours if start <= h.time < end]

    def day(self, day: date) -> DayPoint | None:
        return next((d for d in self.days if d.day == day), None)

    def days_between(self, first: date, last: date) -> list[DayPoint]:
        return [d for d in self.days if first <= d.day <= last]

    def minutes_between(self, start: datetime, end: datetime) -> list[Minute15]:
        return [m for m in self.minutes if start <= m.time < end]

    @property
    def first_day(self) -> date | None:
        return self.days[0].day if self.days else None

    @property
    def last_day(self) -> date | None:
        return self.days[-1].day if self.days else None

    def age_s(self, now: datetime) -> float:
        return max(0.0, (now - self.fetched_at).total_seconds())

    def has(self, attr: str) -> bool:
        return any(getattr(h, attr) is not None for h in self.hours)


# -- interval semantics ------------------------------------------------------------------------
# Open-Meteo and Bright Sky stamp sums (precipitation, its probability, sunshine) at the END of
# their interval ("preceding hour" / "preceding 15 minutes"). The pack keeps every point at the
# START of the interval it describes, so ``hour_at(T)`` and ``hours_between`` read [T, T+1h).
HOUR_INTERVAL_FIELDS = ("precipitation", "rain", "showers", "snowfall", "precip_prob", "sunshine_s")
MINUTE_INTERVAL_FIELDS = ("precipitation",)
_P = TypeVar("_P", HourPoint, Minute15)


def interval_start(points: Sequence[_P], step: timedelta, fields: Sequence[str]) -> list[_P]:
    """Move the interval values of ``fields`` from the point stamped at the end of the interval
    onto the point at its start. The last point (no successor) gets no value (0 mm / None)."""
    by_stamp = {point.time.timestamp(): point for point in points}
    seconds = step.total_seconds()
    out: list[_P] = []
    for point in points:
        following = by_stamp.get(point.time.timestamp() + seconds)
        values: dict[str, Any] = {}
        for name in fields:
            if following is not None:
                values[name] = getattr(following, name)
            else:
                values[name] = 0.0 if name == "precipitation" else None
        out.append(replace(point, **values))
    return out

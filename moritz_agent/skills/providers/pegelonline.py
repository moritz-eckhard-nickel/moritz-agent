# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Water levels from PEGELONLINE (WSV, Datenlizenz Deutschland – Namensnennung 2.0)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.skills.geo.distance import haversine_km
from moritz_agent.skills.geo.gazetteer import fold
from moritz_agent.skills.providers.http import HttpClient, HttpError

URL = "https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json"
# a gauge sends a value every 15 minutes; older than this it is not "the current level" any more
STALE_AFTER = timedelta(hours=3)


@dataclass(frozen=True)
class Gauge:
    name: str
    river: str
    value_cm: float
    trend: int | None  # -1 falling, 0 steady, 1 rising, None unknown (PEGELONLINE: -999)
    state: str  # low | normal | high | unknown | out-dated | commented
    measured: datetime | None
    mean_cm: float | None = None  # MW
    high_cm: float | None = None  # MHW
    distance_km: float | None = None

    def is_stale(self, now: datetime) -> bool:
        """True when the gauge itself has nothing current (``out-dated`` or an old timestamp)."""
        if self.state == "out-dated" or self.measured is None:
            return True
        return now - self.measured > STALE_AFTER


def _trend(value: Any) -> int | None:
    try:
        trend = int(value)
    except (TypeError, ValueError):
        return None
    return trend if trend in (-1, 0, 1) else None


async def fetch(http: HttpClient, river: str) -> list[Any]:
    raw = await http.get_json(
        URL,
        {
            "waters": river.upper(),
            "includeTimeseries": "true",
            "includeCurrentMeasurement": "true",
            "includeCharacteristicValues": "true",
        },
    )
    if not isinstance(raw, list):
        raise HttpError("bad_data", "pegelonline: unexpected answer")
    return raw


def parse(raw: list[Any], tz: str, lat: float, lon: float) -> list[Gauge]:
    zone = ZoneInfo(tz)
    gauges: list[Gauge] = []
    for station in raw:
        if not isinstance(station, dict):
            continue
        series = next(
            (
                t
                for t in station.get("timeseries", [])
                if isinstance(t, dict) and t.get("shortname") == "W"
            ),
            None,
        )
        measurement = (series or {}).get("currentMeasurement")
        if not isinstance(measurement, dict) or measurement.get("value") is None:
            continue
        value = float(measurement["value"])
        if not -500 <= value <= 3000:
            raise HttpError("bad_data", "pegelonline: implausible level")
        values = {
            v.get("shortname"): v.get("value")
            for v in (series or {}).get("characteristicValues", [])
            if isinstance(v, dict)
        }
        measured = None
        if measurement.get("timestamp"):
            try:
                measured = datetime.fromisoformat(str(measurement["timestamp"])).astimezone(zone)
            except ValueError:
                measured = None
        distance = None
        if station.get("latitude") is not None and station.get("longitude") is not None:
            distance = haversine_km(
                lat, lon, float(station["latitude"]), float(station["longitude"])
            )
        gauges.append(
            Gauge(
                name=str(station.get("longname") or station.get("shortname") or "").title(),
                river=str((station.get("water") or {}).get("longname") or "").title(),
                value_cm=value,
                trend=_trend(measurement.get("trend")),
                state=str(measurement.get("stateMnwMhw") or "unknown"),
                measured=measured,
                mean_cm=float(values["MW"]) if values.get("MW") is not None else None,
                high_cm=float(values["MHW"]) if values.get("MHW") is not None else None,
                distance_km=distance,
            )
        )
    return gauges


def choose(gauges: list[Gauge], wanted: str) -> Gauge | None:
    """The configured station by name, else the one closest to home."""
    if wanted and wanted != "auto":
        target = fold(wanted)
        for gauge in gauges:
            if fold(gauge.name) == target:
                return gauge
    candidates = [g for g in gauges if g.distance_km is not None]
    return (
        min(candidates, key=lambda g: g.distance_km or 0.0)
        if candidates
        else (gauges[0] if gauges else None)
    )

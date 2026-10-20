# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Synthetic but schema-faithful Open-Meteo and Bright Sky answers for the weather tests.

The sandbox of the developers cannot reach the services, so these are *built* from the documented
response layout (docs/plan/13 §7.2), not recorded. ``-m network`` tests compare the real services
with the same expectations. Every scenario is a list of days; ``Day`` describes one calendar day.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from moritz_agent.skills.providers.http import HttpClient  # noqa: F401  (re-export for tests)


@dataclass
class Day:
    tmin: float = 8.0
    tmax: float = 14.0
    cloud: float = 60.0  # mean cloud cover %
    wind: float = 12.0  # km/h
    gust: float = 25.0
    wind_dir: float = 225.0
    # (first hour, last hour exclusive, mm per hour, WMO code)
    rain: list[tuple[int, int, float, int]] = field(default_factory=list)
    code: int | None = None  # force the code of dry hours
    uv_max: float = 2.0
    pressure: float = 1015.0
    snowfall: bool = False
    humidity: float = 80.0
    fog_hours: tuple[int, int] | None = None
    thunder_hours: tuple[int, int] | None = None
    freezing_rain: tuple[int, int] | None = None


SUNDAY_EVENING_SCENARIO: list[Day] = [
    Day(7, 13, 70, 10, 25, rain=[(14, 16, 0.4, 61)]),  # Thu 15
    Day(6, 12, 50, 12, 28),  # Fri 16
    Day(5, 14, 40, 10, 22),  # Sat 17
    Day(8, 15, 85, 18, 45, rain=[(20, 24, 0.6, 61)]),  # Sun 18  (today)
    Day(8, 13, 75, 20, 50, rain=[(6, 11, 1.2, 80)]),  # Mon 19  Schauer vormittags
    Day(7, 14, 55, 14, 30),  # Tue 20
    Day(6, 15, 30, 10, 20, uv_max=3.0),  # Wed 21
    Day(5, 16, 20, 8, 18, uv_max=3.0),  # Thu 22
    Day(7, 12, 90, 24, 55, rain=[(0, 24, 1.1, 63)]),  # Fri 23
    Day(8, 16, 25, 10, 20),  # Sat 24
    Day(7, 12, 85, 22, 50, rain=[(9, 22, 0.9, 63)]),  # Sun 25
    Day(6, 11, 70, 14, 30),  # Mon 26
    Day(5, 10, 60, 12, 28),  # Tue 27
    Day(4, 9, 80, 16, 35, rain=[(15, 19, 0.5, 80)]),  # Wed 28
]
FIRST_DAY = date(2026, 10, 15)


def _hour_values(day: Day, hour: int) -> dict[str, Any]:
    span = day.tmax - day.tmin
    phase = math.cos((hour - 15) / 24 * 2 * math.pi)  # warmest at 15 h
    temp = day.tmin + span * (phase + 1) / 2
    rain = next((r for r in day.rain if r[0] <= hour < r[1]), None)
    amount = rain[2] if rain else 0.0
    code = rain[3] if rain else day.code
    cloud = day.cloud
    if code is None:
        code = 0 if cloud < 20 else 1 if cloud < 45 else 2 if cloud < 75 else 3
    if day.fog_hours and day.fog_hours[0] <= hour < day.fog_hours[1]:
        code = 45
    if day.thunder_hours and day.thunder_hours[0] <= hour < day.thunder_hours[1]:
        code, amount = 95, max(amount, 2.5)
    if day.freezing_rain and day.freezing_rain[0] <= hour < day.freezing_rain[1]:
        code, amount = 66, max(amount, 0.5)
    if day.snowfall and rain:
        code = 73
    prob = 85.0 if amount > 0 else 5.0
    if not amount and any(r[0] - 2 <= hour < r[1] + 1 for r in day.rain):
        prob = 40.0
    is_day = 1 if 7 <= hour < 18 else 0
    return {
        "temperature_2m": round(temp, 1),
        "apparent_temperature": round(temp - 0.05 * day.wind, 1),
        "relative_humidity_2m": day.humidity,
        "dew_point_2m": round(temp - 3, 1),
        "precipitation_probability": prob,
        "precipitation": amount,
        "rain": 0.0 if day.snowfall else amount,
        "showers": amount if code in (80, 81, 82) else 0.0,
        "snowfall": round(amount * 0.7, 1) if day.snowfall else 0.0,
        "snow_depth": 0.02 if day.snowfall and amount else 0.0,
        "weather_code": code,
        "cloud_cover": 100.0 if amount else cloud,
        "visibility": 400.0 if code == 45 else 24000.0,
        "pressure_msl": day.pressure,
        "wind_speed_10m": day.wind,
        "wind_direction_10m": day.wind_dir,
        "wind_gusts_10m": day.gust,
        "uv_index": round(day.uv_max * max(0.0, math.sin((hour - 6) / 12 * math.pi)), 1)
        if 7 <= hour < 18
        else 0.0,
        "is_day": is_day,
        "sunshine_duration": 0.0
        if amount or cloud > 80
        else (3600.0 if is_day else 0.0) * (1 - cloud / 100),
        "cape": 1800.0 if day.thunder_hours else 20.0,
        "soil_temperature_0cm": round(temp - 1.5, 1),
    }


def open_meteo_answer(
    days: list[Day] | None = None,
    *,
    first: date = FIRST_DAY,
    now: datetime | None = None,
    lat: float = 50.48,
    lon: float = 8.26,
    minutely: bool = True,
    tz: str = "Europe/Berlin",
) -> dict[str, Any]:
    """An answer shaped like ``/v1/forecast`` with ``timezone=Europe/Berlin``."""
    days = days or SUNDAY_EVENING_SCENARIO
    now = now or datetime(2026, 10, 18, 19, 12)
    hourly: dict[str, list[Any]] = {"time": []}
    daily: dict[str, list[Any]] = {"time": []}
    minutely_block: dict[str, list[Any]] = {"time": [], "precipitation": [], "weather_code": []}
    current_values: dict[str, Any] = {}
    for offset, day in enumerate(days):
        current = first + timedelta(days=offset)
        values = [_hour_values(day, hour) for hour in range(24)]
        for hour, row in enumerate(values):
            hourly["time"].append(f"{current.isoformat()}T{hour:02d}:00")
            for name, value in row.items():
                hourly.setdefault(name, []).append(value)
            if minutely:
                for quarter in range(4):
                    minutely_block["time"].append(
                        f"{current.isoformat()}T{hour:02d}:{quarter * 15:02d}"
                    )
                    minutely_block["precipitation"].append(round(row["precipitation"] / 4, 2))
                    minutely_block["weather_code"].append(row["weather_code"])
            if current == now.date() and hour == now.hour:
                current_values = dict(row)
        temps = [v["temperature_2m"] for v in values]
        wet = [v["precipitation"] for v in values]
        daily["time"].append(current.isoformat())
        for name, value in {
            "weather_code": max(v["weather_code"] for v in values),
            "temperature_2m_max": max(temps),
            "temperature_2m_min": min(temps),
            "apparent_temperature_max": max(v["apparent_temperature"] for v in values),
            "apparent_temperature_min": min(v["apparent_temperature"] for v in values),
            "sunrise": f"{current.isoformat()}T07:45",
            "sunset": f"{current.isoformat()}T18:25",
            "daylight_duration": 38000.0,
            "sunshine_duration": sum(v["sunshine_duration"] for v in values),
            "uv_index_max": day.uv_max,
            "precipitation_sum": round(sum(wet), 1),
            "rain_sum": round(sum(v["rain"] for v in values), 1),
            "showers_sum": round(sum(v["showers"] for v in values), 1),
            "snowfall_sum": round(sum(v["snowfall"] for v in values), 1),
            "precipitation_hours": float(sum(1 for w in wet if w > 0)),
            "precipitation_probability_max": max(v["precipitation_probability"] for v in values),
            "wind_speed_10m_max": day.wind,
            "wind_gusts_10m_max": day.gust,
            "wind_direction_10m_dominant": day.wind_dir,
            "et0_fao_evapotranspiration": 0.8,
        }.items():
            daily.setdefault(name, []).append(value)
    answer: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "generationtime_ms": 0.4,
        "utc_offset_seconds": 7200,
        "timezone": tz,
        "timezone_abbreviation": "CEST",
        "elevation": 170.0,
        "current": {
            "time": now.strftime("%Y-%m-%dT%H:00"),
            "interval": 900,
            **{
                key: current_values.get(key)
                for key in (
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "is_day",
                    "precipitation",
                    "rain",
                    "snowfall",
                    "weather_code",
                    "cloud_cover",
                    "pressure_msl",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                )
            },
        },
        "hourly": hourly,
        "daily": daily,
    }
    if minutely:
        answer["minutely_15"] = minutely_block
    return answer


def bright_sky_weather(days: list[Day] | None = None, first: date = FIRST_DAY) -> dict[str, Any]:
    days = days or SUNDAY_EVENING_SCENARIO
    rows = []
    for offset, day in enumerate(days[:10]):
        current = first + timedelta(days=offset)
        for hour in range(24):
            v = _hour_values(day, hour)
            icon = {0: "clear-day", 1: "clear-day", 2: "partly-cloudy-day", 3: "cloudy"}.get(
                v["weather_code"], "rain"
            )
            if not v["is_day"] and icon.endswith("-day"):
                icon = icon.replace("-day", "-night")
            rows.append(
                {
                    "timestamp": f"{current.isoformat()}T{hour:02d}:00:00+02:00",
                    "source_id": 1,
                    "cloud_cover": v["cloud_cover"],
                    "condition": "rain" if v["precipitation"] else "dry",
                    "dew_point": v["dew_point_2m"],
                    "icon": icon,
                    "precipitation": v["precipitation"],
                    "pressure_msl": v["pressure_msl"],
                    "relative_humidity": v["relative_humidity_2m"],
                    "sunshine": 0.0,
                    "temperature": v["temperature_2m"],
                    "visibility": v["visibility"],
                    "wind_direction": v["wind_direction_10m"],
                    "wind_speed": v["wind_speed_10m"],
                    "wind_gust_speed": v["wind_gusts_10m"],
                }
            )
    return {"weather": rows, "sources": [{"id": 1, "station_name": "Weilburg", "distance": 5200}]}


def bright_sky_current() -> dict[str, Any]:
    return {
        "weather": {
            "source_id": 1,
            "timestamp": "2026-10-18T19:00:00+02:00",
            "cloud_cover": 90,
            "condition": "dry",
            "icon": "cloudy",
            "pressure_msl": 1015.0,
            "relative_humidity": 82,
            "temperature": 10.8,
            "visibility": 12000,
            "wind_direction_10": 220,
            "wind_speed_10": 14.0,
            "wind_gust_speed_10": 30.0,
            "precipitation_10": 0.0,
        },
        "sources": [
            {
                "id": 1,
                "dwd_station_id": "04271",
                "station_name": "Weilburg-Kubach",
                "distance": 5200,
            }
        ],
    }


def alerts_answer(
    events: list[dict[str, Any]] | None = None, *, cell: int = 806533017
) -> dict[str, Any]:
    return {
        "alerts": events or [],
        "location": {"warn_cell_id": cell, "name": "Weilburg", "name_short": "Weilburg"},
    }


def storm_alert() -> dict[str, Any]:
    return {
        "id": 1,
        "alert_id": "2.49.0.0.276.0.DWD.PVW.1",
        "status": "actual",
        "effective": "2026-10-18T17:00:00+02:00",
        "onset": "2026-10-18T18:00:00+02:00",
        "expires": "2026-10-18T22:00:00+02:00",
        "category": "met",
        "response_type": "prepare",
        "urgency": "immediate",
        "severity": "severe",
        "certainty": "likely",
        "event_en": "storm gusts",
        "event_de": "STURMBÖEN",
        "headline_en": "Official WARNING of STORM GUSTS",
        "headline_de": "Amtliche WARNUNG vor STURMBÖEN",
        "description_de": "Es treten Sturmböen mit Geschwindigkeiten um 80 km/h (22m/s, 43kn, Bft 9) aus westlicher Richtung auf. https://example.invalid/x",
        "instruction_de": "ACHTUNG! Hinweis auf mögliche Gefahren: Es können zum Beispiel einzelne Äste herabstürzen.",
        "level": 3,
    }


Handler = Any


def mock_transport(routes: dict[str, Any], calls: list[httpx.Request] | None = None):
    """MockTransport answering by URL path; a value may be JSON-able, a callable or an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        key = f"{request.url.host}{request.url.path}"
        answer = routes.get(key)
        if answer is None:
            return httpx.Response(404, json={"error": "not found"})
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(request)
            if isinstance(answer, httpx.Response):
                return answer
        return httpx.Response(200, json=answer)

    return httpx.MockTransport(handler)


def scenario(**changes: dict[str, Any]) -> list[Day]:
    """The default week with single days changed: ``scenario(mon={"tmin": -2})``.

    Keys: thu fri sat sun mon tue wed thu2 fri2 … (Thu 15 … Wed 28); values are ``Day`` fields.
    """
    names = [
        "thu",
        "fri",
        "sat",
        "sun",
        "mon",
        "tue",
        "wed",
        "thu2",
        "fri2",
        "sat2",
        "sun2",
        "mon2",
        "tue2",
        "wed2",
    ]
    days = [Day(**{**d.__dict__}) for d in SUNDAY_EVENING_SCENARIO]
    for key, fields in changes.items():
        index = names.index(key)
        for name, value in fields.items():
            setattr(days[index], name, value)
    return days


def pollen_answer(levels: dict[str, tuple[str, str, str]] | None = None) -> dict[str, Any]:
    """DWD s31fg.json: only the part regions of Hesse; ``levels`` maps an allergen to its three days."""
    keys = ["Hasel", "Erle", "Esche", "Birke", "Graeser", "Roggen", "Beifuss", "Ambrosia"]
    levels = levels or {}

    def block(shift: int = 0) -> dict[str, Any]:
        pollen = {}
        for key in keys:
            today, tomorrow, after = levels.get(key, ("0", "0", "0"))
            pollen[key] = {"today": today, "tomorrow": tomorrow, "dayafter_to": after}
        return {"Pollen": pollen}

    return {
        "name": "Pollenflug-Gefahrenindex für Deutschland ausgegeben vom Deutschen Wetterdienst",
        "last_update": "2026-10-18 11:00 Uhr",
        "next_update": "2026-10-19 11:00 Uhr",
        "sender": "Deutscher Wetterdienst - Medizin-Meteorologie",
        "content": [
            {
                "region_id": 90,
                "region_name": "Hessen",
                "partregion_id": 91,
                "partregion_name": "Rhein-Main",
                **block(),
            },
            {
                "region_id": 90,
                "region_name": "Hessen",
                "partregion_id": 92,
                "partregion_name": "Nordhessen und hessische Mittelgebirge",
                **block(),
            },
            {
                "region_id": 120,
                "region_name": "Bayern",
                "partregion_id": 121,
                "partregion_name": "Allgäu/Oberbayern/Bay. Wald",
                **block(),
            },
        ],
    }


def nina_answer(warnings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    return warnings or []


def nina_flood() -> dict[str, Any]:
    return {
        "id": "lhp.DE-HE-W-0042",
        "payload": {
            "version": 1,
            "type": "Alert",
            "id": "lhp.DE-HE-W-0042",
            "data": {
                "headline": "Hochwasserinformation Lahn",
                "provider": "LHP",
                "severity": "Minor",
                "msgType": "Alert",
            },
        },
        "i18nTitle": {"de": "Hochwasserinformation Lahn: Pegel Leun über Meldegrenze"},
        "sent": "2026-10-18T15:30:00+02:00",
    }


def nina_dwd_duplicate() -> dict[str, Any]:
    return {
        "id": "dwd.2.49.0.0.276",
        "payload": {
            "data": {
                "headline": "Sturmböen",
                "provider": "DWD",
                "severity": "Severe",
                "msgType": "Alert",
            }
        },
        "i18nTitle": {"de": "Amtliche WARNUNG vor STURMBÖEN"},
        "sent": "2026-10-18T17:00:00+02:00",
    }


def air_quality_answer(
    aqi: float = 18.0, ozone: float = 60.0, ozone_peak: float = 70.0
) -> dict[str, Any]:
    times = [f"2026-10-18T{hour:02d}:00" for hour in range(24)] + [
        f"2026-10-19T{hour:02d}:00" for hour in range(24)
    ]
    return {
        "latitude": 50.48,
        "longitude": 8.26,
        "timezone": "Europe/Berlin",
        "current": {
            "time": "2026-10-18T19:00",
            "european_aqi": aqi,
            "pm10": 9.0,
            "pm2_5": 5.0,
            "ozone": ozone,
            "nitrogen_dioxide": 12.0,
        },
        "hourly": {
            "time": times,
            "ozone": [ozone_peak if 12 <= i % 24 <= 18 else ozone for i in range(len(times))],
        },
    }

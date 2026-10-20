# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Open-Meteo (software AGPL-3.0, data CC BY 4.0): forecast, air quality, geocoding (13 §7.2).

The pack is parsed from the raw JSON, which is what the cache stores. Every answer is checked
(equal series lengths, value ranges, local time zone) before it is used.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.config.settings import SkillsWeather
from moritz_agent.skills.geo.gazetteer import Place
from moritz_agent.skills.providers.http import HttpClient, HttpError
from moritz_agent.skills.weather.model import (
    Current,
    DayPoint,
    HourPoint,
    Minute15,
    WeatherPack,
)

CURRENT_VARS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,is_day,precipitation,rain,snowfall,"
    "weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
)
MINUTELY_VARS = "precipitation,weather_code"
HOURLY_VARS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,precipitation_probability,"
    "precipitation,rain,showers,snowfall,snow_depth,weather_code,cloud_cover,visibility,pressure_msl,"
    "wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,is_day,sunshine_duration,cape,"
    "soil_temperature_0cm"
)
DAILY_VARS = (
    "weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,"
    "apparent_temperature_min,sunrise,sunset,daylight_duration,sunshine_duration,uv_index_max,"
    "precipitation_sum,rain_sum,showers_sum,snowfall_sum,precipitation_hours,"
    "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,"
    "wind_direction_10m_dominant,et0_fao_evapotranspiration"
)

# value ranges after which an answer is rejected as implausible (13 §7.2)
_RANGES = {
    "temperature": (-60.0, 60.0),
    "wind": (0.0, 400.0),
    "prob": (0.0, 100.0),
    "precipitation": (0.0, 500.0),
}


def forecast_params(place: Place, cfg: SkillsWeather, tz: str, *, minutely: bool) -> dict[str, Any]:
    digits = cfg.coordinate_decimals
    params: dict[str, Any] = {
        "latitude": f"{place.lat:.{digits}f}",
        "longitude": f"{place.lon:.{digits}f}",
        "timezone": tz,
        "models": cfg.model,
        "wind_speed_unit": "kmh",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "past_days": cfg.past_days,
        "forecast_days": cfg.forecast_days,
        "current": CURRENT_VARS,
        "hourly": HOURLY_VARS,
        "daily": DAILY_VARS,
    }
    if minutely:
        params["minutely_15"] = MINUTELY_VARS
    return params


async def fetch_forecast(
    http: HttpClient, place: Place, cfg: SkillsWeather, tz: str
) -> dict[str, Any]:
    """Raw forecast JSON; retries once without ``minutely_15`` (some servers lack it)."""
    url = cfg.open_meteo_url.rstrip("/") + "/v1/forecast"
    try:
        raw = await http.get_json(url, forecast_params(place, cfg, tz, minutely=True))
    except HttpError as exc:
        if exc.kind != "status" or exc.status != 400:
            raise
        raw = await http.get_json(url, forecast_params(place, cfg, tz, minutely=False))
    if not isinstance(raw, dict) or raw.get("error"):
        raise HttpError("bad_data", "open-meteo: unexpected answer")
    return raw


# -- parsing -------------------------------------------------------------------------------
def _num(series: dict[str, Any], name: str, index: int) -> float | None:
    values = series.get(name)
    if not values or index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


def _stamp(text: str, zone: ZoneInfo) -> datetime:
    moment = datetime.fromisoformat(text)
    return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment.astimezone(zone)


def _check(name: str, value: float | None, kind: str) -> None:
    if value is None:
        return
    low, high = _RANGES[kind]
    if not low <= value <= high:
        raise HttpError("bad_data", f"open-meteo: implausible {name} ({value})")


def _series(block: Any, label: str) -> dict[str, Any]:
    if not isinstance(block, dict) or "time" not in block:
        raise HttpError("bad_data", f"open-meteo: {label} missing")
    length = len(block["time"])
    for name, values in block.items():
        if isinstance(values, list) and len(values) != length:
            raise HttpError("bad_data", f"open-meteo: {label}.{name} has the wrong length")
    return block


def _weather_code(value: float | None) -> int | None:
    return None if value is None else int(value)


def parse_forecast(raw: dict[str, Any], fetched_at: datetime, tz: str) -> WeatherPack:
    try:
        return _parse_forecast(raw, fetched_at, tz)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise HttpError(
            "bad_data", f"open-meteo: unreadable answer ({type(exc).__name__})"
        ) from exc


def _parse_forecast(raw: dict[str, Any], fetched_at: datetime, tz: str) -> WeatherPack:
    zone = ZoneInfo(tz)
    if raw.get("timezone") not in {tz, None}:
        raise HttpError("bad_data", "open-meteo: wrong time zone in the answer")
    pack = WeatherPack(
        lat=float(raw["latitude"]),
        lon=float(raw["longitude"]),
        tz=tz,
        fetched_at=fetched_at.astimezone(zone),
        source="open-meteo",
        model=str(raw.get("model", "")),
    )
    cur = raw.get("current")
    if isinstance(cur, dict) and cur.get("time"):
        temp = cur.get("temperature_2m")
        _check("temperature", temp, "temperature")
        _check("wind", cur.get("wind_speed_10m"), "wind")
        pack.current = Current(
            time=_stamp(cur["time"], zone),
            temperature=temp,
            apparent=cur.get("apparent_temperature"),
            humidity=cur.get("relative_humidity_2m"),
            is_day=bool(cur.get("is_day", 1)),
            precipitation=cur.get("precipitation"),
            rain=cur.get("rain"),
            snowfall=cur.get("snowfall"),
            code=_weather_code(cur.get("weather_code")),
            cloud_cover=cur.get("cloud_cover"),
            pressure=cur.get("pressure_msl"),
            wind=cur.get("wind_speed_10m"),
            wind_dir=cur.get("wind_direction_10m"),
            gusts=cur.get("wind_gusts_10m"),
        )
    minutely = raw.get("minutely_15")
    if isinstance(minutely, dict) and minutely.get("time"):
        block = _series(minutely, "minutely_15")
        for i, stamp in enumerate(block["time"]):
            pack.minutes.append(
                Minute15(
                    _stamp(stamp, zone),
                    precipitation=_num(block, "precipitation", i) or 0.0,
                    code=_weather_code(_num(block, "weather_code", i)),
                )
            )
    hourly = _series(raw.get("hourly"), "hourly")
    for i, stamp in enumerate(hourly["time"]):
        temp = _num(hourly, "temperature_2m", i)
        wind = _num(hourly, "wind_speed_10m", i)
        prob = _num(hourly, "precipitation_probability", i)
        precip = _num(hourly, "precipitation", i)
        _check("temperature", temp, "temperature")
        _check("wind", wind, "wind")
        _check("probability", prob, "prob")
        _check("precipitation", precip, "precipitation")
        sunshine = _num(hourly, "sunshine_duration", i)
        pack.hours.append(
            HourPoint(
                time=_stamp(stamp, zone),
                temperature=temp,
                apparent=_num(hourly, "apparent_temperature", i),
                humidity=_num(hourly, "relative_humidity_2m", i),
                dew_point=_num(hourly, "dew_point_2m", i),
                precip_prob=prob,
                precipitation=precip or 0.0,
                rain=_num(hourly, "rain", i),
                showers=_num(hourly, "showers", i),
                snowfall=_num(hourly, "snowfall", i),
                snow_depth=_num(hourly, "snow_depth", i),
                code=_weather_code(_num(hourly, "weather_code", i)),
                cloud_cover=_num(hourly, "cloud_cover", i),
                visibility=_num(hourly, "visibility", i),
                pressure=_num(hourly, "pressure_msl", i),
                wind=wind,
                wind_dir=_num(hourly, "wind_direction_10m", i),
                gusts=_num(hourly, "wind_gusts_10m", i),
                uv=_num(hourly, "uv_index", i),
                is_day=bool(
                    _num(hourly, "is_day", i) if _num(hourly, "is_day", i) is not None else 1
                ),
                sunshine_s=sunshine,
                cape=_num(hourly, "cape", i),
                soil_temperature=_num(hourly, "soil_temperature_0cm", i),
            )
        )
    daily = _series(raw.get("daily"), "daily")
    for i, stamp in enumerate(daily["time"]):
        sunrise = daily.get("sunrise", [None] * (i + 1))[i]
        sunset = daily.get("sunset", [None] * (i + 1))[i]
        tmax, tmin = _num(daily, "temperature_2m_max", i), _num(daily, "temperature_2m_min", i)
        _check("temperature", tmax, "temperature")
        _check("temperature", tmin, "temperature")
        pack.days.append(
            DayPoint(
                day=date.fromisoformat(stamp),
                code=_weather_code(_num(daily, "weather_code", i)),
                tmax=tmax,
                tmin=tmin,
                apparent_max=_num(daily, "apparent_temperature_max", i),
                apparent_min=_num(daily, "apparent_temperature_min", i),
                sunrise=_stamp(sunrise, zone) if sunrise else None,
                sunset=_stamp(sunset, zone) if sunset else None,
                daylight_s=_num(daily, "daylight_duration", i),
                sunshine_s=_num(daily, "sunshine_duration", i),
                uv_max=_num(daily, "uv_index_max", i),
                precipitation=_num(daily, "precipitation_sum", i),
                rain=_num(daily, "rain_sum", i),
                showers=_num(daily, "showers_sum", i),
                snowfall=_num(daily, "snowfall_sum", i),
                precip_hours=_num(daily, "precipitation_hours", i),
                precip_prob_max=_num(daily, "precipitation_probability_max", i),
                wind_max=_num(daily, "wind_speed_10m_max", i),
                gusts_max=_num(daily, "wind_gusts_10m_max", i),
                wind_dir=_num(daily, "wind_direction_10m_dominant", i),
                et0=_num(daily, "et0_fao_evapotranspiration", i),
            )
        )
    if not pack.hours or not pack.days:
        raise HttpError("bad_data", "open-meteo: no hourly or daily values")
    return pack


# -- geocoding and air quality -------------------------------------------------------------
async def geocode(http: HttpClient, name: str, language: str = "de") -> Place | None:
    """Open-Meteo geocoding (names and postcodes); the best hit or None."""
    raw = await http.get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": name, "count": 5, "language": language, "format": "json"},
    )
    results = raw.get("results") if isinstance(raw, dict) else None
    if not results:
        return None
    best = max(results, key=lambda r: r.get("population") or 0)
    try:
        country = best.get("country") or best.get("country_code") or ""
        domestic = best.get("country_code") == "DE"
        return Place(
            name=str(best["name"]),
            postal_codes=tuple(str(p) for p in (best.get("postcodes") or [])[:1]),
            district=str(best.get("admin2") or ""),
            state=_state_code(best.get("admin1")) if domestic else "",
            country="Deutschland" if domestic else str(country),
            lat=float(best["latitude"]),
            lon=float(best["longitude"]),
            tz=str(best.get("timezone") or "Europe/Berlin"),
            population=int(best.get("population") or 0),
            source="open-meteo-geocoding",
        )
    except (KeyError, TypeError, ValueError):
        return None


def _state_code(name: Any) -> str:
    from moritz_agent.skills.geo.gazetteer import state_code

    return state_code(str(name or ""))


async def fetch_air_quality(http: HttpClient, place: Place, tz: str) -> dict[str, Any]:
    raw = await http.get_json(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        {
            "latitude": f"{place.lat:.2f}",
            "longitude": f"{place.lon:.2f}",
            "timezone": tz,
            "current": "european_aqi,pm10,pm2_5,ozone,nitrogen_dioxide",
            "hourly": "european_aqi,ozone,pm10,pm2_5",
            "forecast_days": 2,
        },
    )
    if not isinstance(raw, dict) or "current" not in raw:
        raise HttpError("bad_data", "open-meteo air quality: unexpected answer")
    return raw

# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Bright Sky (software MIT, data DWD Open Data CC BY 4.0): fallback forecast, station
measurements and DWD weather warnings (docs/plan/13 §7.1, §7.6)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.config.settings import SkillsWeather
from moritz_agent.skills.geo.gazetteer import Place
from moritz_agent.skills.providers.http import HttpClient, HttpError
from moritz_agent.skills.weather.model import Current, DayPoint, HourPoint, WeatherPack

# Bright Sky icon → WMO weather code (the precipitation amount refines rain)
_ICON_CODE = {
    "clear-day": 0,
    "clear-night": 0,
    "partly-cloudy-day": 2,
    "partly-cloudy-night": 2,
    "cloudy": 3,
    "fog": 45,
    "wind": 3,
    "rain": 63,
    "sleet": 67,
    "snow": 73,
    "hail": 96,
    "thunderstorm": 95,
}


def _code(icon: str | None, precipitation: float | None) -> int | None:
    if icon is None:
        return None
    code = _ICON_CODE.get(icon)
    if icon == "rain" and precipitation is not None:
        code = 61 if precipitation < 0.5 else 65 if precipitation >= 4 else 63
    return code


def _stamp(text: str, zone: ZoneInfo) -> datetime:
    return datetime.fromisoformat(text).astimezone(zone)


def weather_params(place: Place, cfg: SkillsWeather, tz: str, today: date) -> dict[str, Any]:
    digits = cfg.coordinate_decimals
    return {
        "lat": f"{place.lat:.{digits}f}",
        "lon": f"{place.lon:.{digits}f}",
        "tz": tz,
        "units": "dwd",
        "date": (today - timedelta(days=cfg.past_days)).isoformat(),
        "last_date": (today + timedelta(days=min(cfg.forecast_days, 9))).isoformat(),
    }


async def fetch_weather(
    http: HttpClient, place: Place, cfg: SkillsWeather, tz: str, today: date
) -> dict[str, Any]:
    raw = await http.get_json(
        cfg.brightsky_url.rstrip("/") + "/weather", weather_params(place, cfg, tz, today)
    )
    if not isinstance(raw, dict) or not raw.get("weather"):
        raise HttpError("bad_data", "brightsky: no weather values")
    try:
        current = await http.get_json(
            cfg.brightsky_url.rstrip("/") + "/current_weather",
            {"lat": f"{place.lat:.2f}", "lon": f"{place.lon:.2f}", "tz": tz, "units": "dwd"},
        )
        raw["_current"] = current
    except HttpError:
        pass  # forecast only
    return raw


def parse_weather(raw: dict[str, Any], fetched_at: datetime, tz: str, place: Place) -> WeatherPack:
    try:
        return _parse_weather(raw, fetched_at, tz, place)
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpError("bad_data", f"brightsky: unreadable answer ({type(exc).__name__})") from exc


def _parse_weather(raw: dict[str, Any], fetched_at: datetime, tz: str, place: Place) -> WeatherPack:
    zone = ZoneInfo(tz)
    pack = WeatherPack(
        lat=place.lat,
        lon=place.lon,
        tz=tz,
        fetched_at=fetched_at.astimezone(zone),
        source="brightsky",
        model="MOSMIX",
    )
    for row in raw["weather"]:
        temp = row.get("temperature")
        wind = row.get("wind_speed")
        if temp is not None and not -60 <= temp <= 60:
            raise HttpError("bad_data", "brightsky: implausible temperature")
        if wind is not None and not 0 <= wind <= 400:
            raise HttpError("bad_data", "brightsky: implausible wind")
        precipitation = row.get("precipitation") or 0.0
        icon = row.get("icon")
        pack.hours.append(
            HourPoint(
                time=_stamp(row["timestamp"], zone),
                temperature=temp,
                humidity=row.get("relative_humidity"),
                dew_point=row.get("dew_point"),
                precip_prob=row.get("precipitation_probability"),
                precipitation=precipitation,
                code=_code(icon, precipitation),
                cloud_cover=row.get("cloud_cover"),
                visibility=row.get("visibility"),
                pressure=row.get("pressure_msl"),
                wind=wind,
                wind_dir=row.get("wind_direction"),
                gusts=row.get("wind_gust_speed"),
                is_day=not (icon or "").endswith("night"),
                sunshine_s=(row["sunshine"] * 60.0) if row.get("sunshine") is not None else None,
            )
        )
    if not pack.hours:
        raise HttpError("bad_data", "brightsky: no hourly values")
    by_day: dict[date, list[HourPoint]] = {}
    for hour in pack.hours:
        by_day.setdefault(hour.time.date(), []).append(hour)
    for day, hours in sorted(by_day.items()):
        temps = [h.temperature for h in hours if h.temperature is not None]
        winds = [h.wind for h in hours if h.wind is not None]
        gusts = [h.gusts for h in hours if h.gusts is not None]
        codes = [h.code for h in hours if h.code is not None]
        pack.days.append(
            DayPoint(
                day=day,
                code=max(codes) if codes else None,
                tmax=max(temps) if temps else None,
                tmin=min(temps) if temps else None,
                precipitation=sum(h.precipitation for h in hours),
                precip_prob_max=max(
                    (h.precip_prob for h in hours if h.precip_prob is not None), default=None
                ),
                wind_max=max(winds) if winds else None,
                gusts_max=max(gusts) if gusts else None,
                sunshine_s=sum(h.sunshine_s or 0.0 for h in hours),
            )
        )
    current, station, km = parse_current(raw.get("_current"), tz)
    if current is not None:
        pack.current, pack.station, pack.station_km = current, station, km
    return pack


def parse_current(raw: Any, tz: str) -> tuple[Current | None, str, float | None]:
    """Latest station measurement of ``/current_weather``: (values, station name, km away)."""
    zone = ZoneInfo(tz)
    if not isinstance(raw, dict) or not isinstance(raw.get("weather"), dict):
        return None, "", None
    row = raw["weather"]
    precipitation = row.get("precipitation_10") or row.get("precipitation_30")
    current = Current(
        time=_stamp(row["timestamp"], zone),
        temperature=row.get("temperature"),
        humidity=row.get("relative_humidity"),
        is_day=not (row.get("icon") or "").endswith("night"),
        precipitation=precipitation,
        code=_code(row.get("icon"), precipitation),
        cloud_cover=row.get("cloud_cover"),
        pressure=row.get("pressure_msl"),
        wind=row.get("wind_speed_10") or row.get("wind_speed"),
        wind_dir=row.get("wind_direction_10") or row.get("wind_direction"),
        gusts=row.get("wind_gust_speed_10") or row.get("wind_gust_speed"),
    )
    station, km = "", None
    sources = raw.get("sources") or []
    if sources and isinstance(sources[0], dict):
        station = str(sources[0].get("station_name") or "")
        distance = sources[0].get("distance")
        km = round(distance / 1000, 1) if isinstance(distance, int | float) else None
    return current, station, km


# -- warnings --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Warning:
    """One DWD warning for a place (``level`` 1 … 4, see docs/plan/13 §7.6)."""

    event: str  # "Sturmböen", "Frost", "Starkregen" … (normal case)
    level: int
    severity: str  # minor | moderate | severe | extreme
    start: datetime
    end: datetime | None
    headline: str = ""
    description: str = ""
    instruction: str = ""
    source: str = "DWD"
    uid: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)


_SEVERITY_LEVEL = {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}


def clean_text(text: str | None, limit: int = 300) -> str:
    """Warning free text is data from outside: control characters, links and shouting go."""
    if not text:
        return ""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.isupper():
        text = text.capitalize()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + " …"
    return text


def _event_name(alert: dict[str, Any]) -> str:
    name = alert.get("event_de") or alert.get("event_en") or ""
    name = clean_text(name, 60)
    return name.replace("UNWETTER", "Unwetter").strip()


def _naive_title(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


async def fetch_alerts(
    http: HttpClient, place: Place, cfg: SkillsWeather, tz: str
) -> dict[str, Any]:
    raw = await http.get_json(
        cfg.brightsky_url.rstrip("/") + "/alerts",
        {"lat": f"{place.lat:.2f}", "lon": f"{place.lon:.2f}", "tz": tz},
    )
    if not isinstance(raw, dict) or "alerts" not in raw:
        raise HttpError("bad_data", "brightsky: unexpected alerts answer")
    return raw


def parse_alerts(raw: dict[str, Any], tz: str) -> list[Warning]:
    zone = ZoneInfo(tz)
    found: list[Warning] = []
    for alert in raw.get("alerts", []):
        try:
            severity = str(alert.get("severity") or "minor").lower()
            start = _stamp(alert.get("onset") or alert["effective"], zone)
            end_text = alert.get("expires") or alert.get("ends")
            found.append(
                Warning(
                    event=_naive_title(_event_name(alert)),
                    level=int(alert.get("level") or _SEVERITY_LEVEL.get(severity, 1)),
                    severity=severity,
                    start=start,
                    end=_stamp(end_text, zone) if end_text else None,
                    headline=clean_text(alert.get("headline_de") or alert.get("headline_en"), 120),
                    description=clean_text(alert.get("description_de")),
                    instruction=clean_text(alert.get("instruction_de")),
                    uid=str(alert.get("alert_id") or alert.get("id") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    found.sort(key=lambda w: (-w.level, w.start))
    return found


def warn_cell(raw: dict[str, Any]) -> str:
    location = raw.get("location") or {}
    return str(location.get("warn_cell_id") or "")

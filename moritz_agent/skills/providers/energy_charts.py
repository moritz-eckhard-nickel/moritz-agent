# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Day-ahead electricity price from Energy-Charts (Fraunhofer ISE, CC BY 4.0)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from moritz_agent.skills.providers.http import HttpClient, HttpError

URL = "https://api.energy-charts.info/price"


@dataclass(frozen=True)
class PricePoint:
    start: datetime
    eur_per_mwh: float

    @property
    def ct_per_kwh(self) -> float:
        return self.eur_per_mwh / 10.0


async def fetch(http: HttpClient, zone: str, first: date, last: date) -> dict[str, Any]:
    raw = await http.get_json(
        URL, {"bzn": zone, "start": first.isoformat(), "end": last.isoformat()}
    )
    if not isinstance(raw, dict) or "price" not in raw or "unix_seconds" not in raw:
        raise HttpError("bad_data", "energy-charts: unexpected answer")
    return raw


def hourly(raw: dict[str, Any], tz: str) -> list[PricePoint]:
    """Prices averaged per hour (the market moved to 15-minute steps in 2025)."""
    zone = ZoneInfo(tz)
    seconds, prices = raw["unix_seconds"], raw["price"]
    if len(seconds) != len(prices):
        raise HttpError("bad_data", "energy-charts: series of different length")
    # bucket by UTC hour: on the night the clocks go back, the two local 02:00 hours stay apart
    buckets: dict[int, list[float]] = {}
    for stamp, price in zip(seconds, prices, strict=True):
        if price is None:
            continue
        if not -1000 <= price <= 5000:
            raise HttpError("bad_data", "energy-charts: implausible price")
        buckets.setdefault(int(stamp) // 3600 * 3600, []).append(float(price))
    return [
        PricePoint(datetime.fromtimestamp(hour, zone), sum(v) / len(v))
        for hour, v in sorted(buckets.items())
    ]


def _hours_apart(a: datetime, b: datetime) -> float:
    """Real elapsed hours (aware datetimes of one zone subtract as wall-clock time)."""
    return (b.timestamp() - a.timestamp()) / 3600


def cheapest_window(
    points: list[PricePoint], hours: int = 2
) -> tuple[datetime, datetime, float] | None:
    """Start, end and mean price (ct/kWh) of the cheapest block of ``hours`` consecutive hours."""
    best: tuple[float, int] | None = None
    for i in range(len(points) - hours + 1):
        block = points[i : i + hours]
        if any(_hours_apart(block[j].start, block[j + 1].start) != 1 for j in range(hours - 1)):
            continue
        mean = sum(p.ct_per_kwh for p in block) / hours
        if best is None or mean < best[0]:
            best = (mean, i)
    if best is None:
        return None
    start = points[best[1]].start
    end = (start.astimezone(UTC) + timedelta(hours=hours)).astimezone(start.tzinfo)
    return start, end, best[0]

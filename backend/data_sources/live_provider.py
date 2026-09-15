"""
Live data provider — attempts to fetch real marine/weather data from
free public APIs (Open-Meteo Marine API for wave/wind/SST) plus real
satellite chlorophyll-a from Copernicus Marine Service.

Falls back gracefully if the network call fails.  The mock provider
will catch the exception upstream in get_marine_conditions().
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
import logging
from typing import Optional

import httpx

import config
from data_sources.copernicus_provider import climatology_chlorophyll, fetch_chlorophyll
from data_sources.imd_provider import get_imd_marine_data
from data_sources.interface import MarineConditions

logger = logging.getLogger("orca.data_sources.live")


# Open-Meteo Marine API — free, no API key, good global coverage
_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Live PFZ grid sampling (gated behind config.ENABLE_LIVE_PFZ_GRID)
_GRID_RADIUS_KM = 35.0
_GRID_POINTS = 8


async def _safe_imd_fetch(lat: float, lon: float, location_name: Optional[str]) -> dict:
    """Wrap get_imd_marine_data so a failure never aborts the rest of the gather()."""
    try:
        return await get_imd_marine_data(lat, lon, location_name or "")
    except Exception as e:
        logger.warning(f"Could not retrieve IMD data: {e}")
        return {}


async def fetch_live_conditions(
    lat: float,
    lon: float,
    date: str = "today",
    location_name: Optional[str] = None,
) -> MarineConditions:
    """
    Fetch current marine + weather conditions from Open-Meteo, plus
    real chlorophyll-a from Copernicus Marine Service.

    Raises on any failure of the load-bearing Open-Meteo calls so the
    caller can fall back to mock. Copernicus and IMD are best-effort —
    their failure degrades individual fields rather than the whole call.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        marine_call = client.get(
            _MARINE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "wave_height,wave_period,wave_direction",
                "hourly": "sea_surface_temperature",
                "forecast_days": 1,
            },
        )
        weather_call = client.get(
            _WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "weather_code,wind_speed_10m,wind_direction_10m,visibility"
                ),
            },
        )

        # Independent network calls — run them concurrently rather than
        # paying for each round trip in sequence.
        marine_resp, weather_resp, imd_data, chl_result = await asyncio.gather(
            marine_call,
            weather_call,
            _safe_imd_fetch(lat, lon, location_name),
            fetch_chlorophyll(lat, lon),
        )

    marine_resp.raise_for_status()
    marine = marine_resp.json()

    weather_resp.raise_for_status()
    weather = weather_resp.json()

    marine_current = marine.get("current", {})
    weather_current = weather.get("current", {})
    sst_list = marine.get("hourly", {}).get("sea_surface_temperature", [])
    sst_val = float(sst_list[0]) if sst_list and sst_list[0] is not None else 28.0

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Map wind direction degrees → cardinal
    wind_deg = weather_current.get("wind_direction_10m", 0)
    wind_dir = _degrees_to_cardinal(wind_deg)

    active_alerts = imd_data.get("alerts", [])
    imd_source = imd_data.get("data_source", "imd")

    # Chlorophyll: real Copernicus reading when available, otherwise a
    # labelled regional/seasonal climatology fallback — never a silent
    # 0.0, which would misleadingly read as "no fish anywhere".
    if chl_result is not None:
        chlorophyll_val = chl_result["chlorophyll_mg_m3"]
        chl_source = "copernicus"
    else:
        chlorophyll_val = climatology_chlorophyll(lat, lon, now)
        chl_source = "copernicus_fallback_climatology"

    data_source_label = f"open_meteo + {imd_source} + {chl_source}"

    # Use IMD coastal bulletin condition if available to enrich Open-Meteo description
    weather_cond = _weather_code_to_text(weather_current.get("weather_code", 0))
    bulletin = imd_data.get("coastal_bulletin", {})
    if bulletin.get("Weather"):
        weather_cond = f"{weather_cond} ({bulletin['Weather'].strip()})"

    pfz_zones = []
    if config.ENABLE_LIVE_PFZ_GRID:
        try:
            pfz_zones = await _build_live_pfz_grid(lat, lon, now)
        except Exception as e:
            logger.warning(f"Live PFZ grid sampling failed: {e}")

    return MarineConditions(
        lat=lat,
        lon=lon,
        location_name=location_name or f"{lat:.2f}°N, {lon:.2f}°E",
        timestamp=now_iso,
        data_timestamp=now_iso,
        sst=sst_val,
        chlorophyll=chlorophyll_val,
        wave_height=marine_current.get("wave_height", 0.0),
        wave_period=marine_current.get("wave_period", 0.0),
        wind_speed=weather_current.get("wind_speed_10m", 0.0),
        wind_direction=wind_dir,
        visibility=round(
            weather_current.get("visibility", 10000) / 1000, 1
        ),  # metres → km
        air_temperature=weather_current.get("temperature_2m", 0.0),
        humidity=weather_current.get("relative_humidity_2m", 0),
        weather_condition=weather_cond,
        tide_info={},  # Not available from Open-Meteo
        active_alerts=active_alerts,
        pfz_zones=pfz_zones,
        data_source=data_source_label,
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _generate_grid_points(lat: float, lon: float) -> list[tuple[float, float]]:
    """Ring of _GRID_POINTS points ~_GRID_RADIUS_KM around (lat, lon)."""
    lon_scale = math.cos(math.radians(lat)) or 1e-9  # guard against poles
    points = []
    for i in range(_GRID_POINTS):
        bearing = 2 * math.pi * i / _GRID_POINTS
        d_lat = (_GRID_RADIUS_KM / 111.0) * math.cos(bearing)
        d_lon = (_GRID_RADIUS_KM / (111.0 * lon_scale)) * math.sin(bearing)
        points.append((lat + d_lat, lon + d_lon))
    return points


async def _fetch_grid_sst(client: httpx.AsyncClient, lat: float, lon: float) -> Optional[float]:
    """SST at one grid point, via the same Open-Meteo hourly field used for the query point."""
    try:
        resp = await client.get(
            _MARINE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "sea_surface_temperature",
                "forecast_days": 1,
            },
        )
        resp.raise_for_status()
        sst_list = resp.json().get("hourly", {}).get("sea_surface_temperature", [])
        return float(sst_list[0]) if sst_list and sst_list[0] is not None else None
    except Exception as e:
        logger.warning(f"Grid SST fetch failed at ({lat:.2f}, {lon:.2f}): {e}")
        return None


async def _build_live_pfz_grid(lat: float, lon: float, now: datetime) -> list[dict]:
    """
    Sample a small ring of points around the query location and build
    RAW PFZ candidate zones from live SST (Open-Meteo) + chlorophyll
    (Copernicus, with climatology fallback per point).

    Gated behind config.ENABLE_LIVE_PFZ_GRID since it multiplies the
    number of outbound API calls per query.

    Returns zone dicts in the same raw shape mock_data/*.json uses
    (id, lat, lon, distance_km, confidence, sst, chlorophyll,
    species_likely, valid_until) — scoring/suitability is intentionally
    left to agents/pfz.py's existing _evaluate_zone/find_nearby_pfz,
    exactly as it already runs for mock-provider zones.
    """
    points = _generate_grid_points(lat, lon)

    async with httpx.AsyncClient(timeout=10.0) as client:
        sst_results, chl_results = await asyncio.gather(
            asyncio.gather(*(_fetch_grid_sst(client, plat, plon) for plat, plon in points)),
            asyncio.gather(*(fetch_chlorophyll(plat, plon) for plat, plon in points)),
        )

    valid_until = now.isoformat()  # daily-updated product — treat as valid for today
    zones = []
    for idx, ((plat, plon), sst_val, chl_result) in enumerate(zip(points, sst_results, chl_results)):
        if sst_val is None:
            continue  # can't evaluate a zone with no SST at all

        if chl_result is not None:
            chl_val = chl_result["chlorophyll_mg_m3"]
            confidence = "medium"  # real satellite reading, but a coarse 4km/daily grid
        else:
            chl_val = climatology_chlorophyll(plat, plon, now)
            confidence = "low"  # climatology fallback, not a real reading

        zones.append({
            "id": f"PFZ-LIVE-{idx + 1:02d}",
            "lat": round(plat, 4),
            "lon": round(plon, 4),
            "distance_km": round(_haversine_km(lat, lon, plat, plon), 1),
            "confidence": confidence,
            "sst": round(sst_val, 2),
            "chlorophyll": round(chl_val, 2),
            "species_likely": [],  # not inferable from SST/chlorophyll alone
            "valid_until": valid_until,
        })

    return zones


def _degrees_to_cardinal(deg: float) -> str:
    """Convert wind direction in degrees to cardinal abbreviation."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = round(deg / 45) % 8
    return dirs[idx]


def _weather_code_to_text(code: int) -> str:
    """Convert WMO weather code to human-readable text (subset)."""
    codes = {
        0: "Clear Sky",
        1: "Mainly Clear",
        2: "Partly Cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing Rime Fog",
        51: "Light Drizzle",
        53: "Moderate Drizzle",
        55: "Dense Drizzle",
        61: "Slight Rain",
        63: "Moderate Rain",
        65: "Heavy Rain",
        71: "Slight Snow",
        73: "Moderate Snow",
        75: "Heavy Snow",
        80: "Slight Rain Showers",
        81: "Moderate Rain Showers",
        82: "Violent Rain Showers",
        95: "Thunderstorms",
        96: "Thunderstorm with Slight Hail",
        99: "Thunderstorm with Heavy Hail",
    }
    return codes.get(code, f"Weather Code {code}")


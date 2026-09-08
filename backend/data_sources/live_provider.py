"""
Live data provider — attempts to fetch real marine/weather data from
free public APIs (Open-Meteo Marine API for wave/wind/SST).

Falls back gracefully if the network call fails.  The mock provider
will catch the exception upstream in get_marine_conditions().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from data_sources.interface import MarineConditions


# Open-Meteo Marine API — free, no API key, good global coverage
_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_live_conditions(
    lat: float,
    lon: float,
    date: str = "today",
    location_name: Optional[str] = None,
) -> MarineConditions:
    """
    Fetch current marine + weather conditions from Open-Meteo.

    Raises on any failure so the caller can fall back to mock.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # --- Marine data (wave height, wave period, SST) ---
        marine_resp = await client.get(
            _MARINE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "wave_height,wave_period,ocean_temperature",
            },
        )
        marine_resp.raise_for_status()
        marine = marine_resp.json()

        # --- Weather data (wind, visibility, temperature, humidity) ---
        weather_resp = await client.get(
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
        weather_resp.raise_for_status()
        weather = weather_resp.json()

    marine_current = marine.get("current", {})
    weather_current = weather.get("current", {})

    now_iso = datetime.now(timezone.utc).isoformat()

    # Map wind direction degrees → cardinal
    wind_deg = weather_current.get("wind_direction_10m", 0)
    wind_dir = _degrees_to_cardinal(wind_deg)

    return MarineConditions(
        lat=lat,
        lon=lon,
        location_name=location_name or f"{lat:.2f}°N, {lon:.2f}°E",
        timestamp=now_iso,
        data_timestamp=now_iso,
        sst=marine_current.get("ocean_temperature", 0.0),
        chlorophyll=0.0,  # Not available from Open-Meteo — agents handle gracefully
        wave_height=marine_current.get("wave_height", 0.0),
        wave_period=marine_current.get("wave_period", 0.0),
        wind_speed=weather_current.get("wind_speed_10m", 0.0),
        wind_direction=wind_dir,
        visibility=round(
            weather_current.get("visibility", 10000) / 1000, 1
        ),  # metres → km
        air_temperature=weather_current.get("temperature_2m", 0.0),
        humidity=weather_current.get("relative_humidity_2m", 0),
        weather_condition=_weather_code_to_text(
            weather_current.get("weather_code", 0)
        ),
        tide_info={},  # Not available from Open-Meteo
        active_alerts=[],  # Not available from Open-Meteo
        pfz_zones=[],  # Requires satellite data — handled by PFZ agent logic
        data_source="open_meteo",
    )


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


"""
Mock data provider — reads from the mock_data/ JSON files and returns
a MarineConditions instance for the closest available city.

Adds slight random jitter to numeric values so repeated demo queries
don't look identical.
"""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path
from typing import Optional

from data_sources.interface import MarineConditions


# Resolve mock_data/ relative to this file's location
# backend/data_sources/mock_provider.py → ../../mock_data/
_MOCK_DIR = Path(__file__).resolve().parent.parent.parent / "mock_data"


def _load_mock_files() -> list[dict]:
    """Load all .json files from mock_data/ into memory."""
    files = []
    for json_file in sorted(_MOCK_DIR.glob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["_filename"] = json_file.stem
            files.append(data)
    return files


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    R = 6371.0  # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_nearest(lat: float, lon: float, mock_files: list[dict]) -> dict:
    """Return the mock file whose location is closest to (lat, lon)."""
    best = mock_files[0]
    best_dist = float("inf")
    for mf in mock_files:
        loc = mf["location"]
        d = _haversine_km(lat, lon, loc["lat"], loc["lon"])
        if d < best_dist:
            best_dist = d
            best = mf
    return best


def _jitter(value: float, pct: float = 0.05) -> float:
    """Add ±pct random jitter to a numeric value."""
    return round(value * (1 + random.uniform(-pct, pct)), 2)


def _mock_to_conditions(
    raw: dict,
    query_lat: float,
    query_lon: float,
    location_name: Optional[str],
) -> MarineConditions:
    """Convert a raw mock JSON dict into a MarineConditions instance."""
    loc = raw["location"]
    ocean = raw["ocean"]
    weather = raw["weather"]

    return MarineConditions(
        lat=query_lat,
        lon=query_lon,
        location_name=location_name or loc["name"],
        timestamp=raw["timestamp"],
        data_timestamp=raw["data_timestamp"],
        # Ocean — with jitter
        sst=_jitter(ocean["sst"]),
        chlorophyll=_jitter(ocean["chlorophyll"]),
        wave_height=_jitter(ocean["wave_height"]),
        wave_period=_jitter(ocean["wave_period"]),
        # Weather — with jitter
        wind_speed=_jitter(weather["wind_speed"]),
        wind_direction=weather["wind_direction"],
        visibility=_jitter(weather["visibility"]),
        air_temperature=_jitter(weather["temperature"]),
        humidity=weather["humidity"],
        weather_condition=weather["condition"],
        # Tide
        tide_info=raw.get("tide", {}),
        # Alerts & PFZ — passed through as-is
        active_alerts=raw.get("alerts", []),
        pfz_zones=raw.get("pfz_zones", []),
        # Provenance
        data_source="mock",
    )


async def fetch_mock_conditions(
    lat: float,
    lon: float,
    date: str = "today",
    location_name: Optional[str] = None,
) -> MarineConditions:
    """
    Load mock data for the nearest available city and return
    a MarineConditions instance.
    """
    mock_files = _load_mock_files()
    if not mock_files:
        raise FileNotFoundError(
            f"No mock JSON files found in {_MOCK_DIR}. "
            "Add at least one <city>.json file."
        )

    nearest = _find_nearest(lat, lon, mock_files)
    return _mock_to_conditions(nearest, lat, lon, location_name)


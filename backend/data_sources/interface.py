"""
MarineConditions dataclass and the single entry-point function
`get_marine_conditions(lat, lon, date)`.

Everything in the system calls this interface — never a raw API directly.
Swap providers (mock ↔ live) here without touching any agent logic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("orca.data_sources")

# A numeric reading the source couldn't provide — e.g. Open-Meteo returns
# wave_height: null for coordinates outside its marine grid. Serialises as
# JSON null. Consumers must check is_unavailable() before comparing or
# formatting a reading; never substitute 0.0 or a "typical" value, which
# would read as a real, reassuring measurement.
DATA_UNAVAILABLE = None


def is_unavailable(value) -> bool:
    """True if a reading is DATA_UNAVAILABLE (see above)."""
    return value is DATA_UNAVAILABLE


@dataclass
class MarineConditions:
    """Unified container for all marine/weather data at a single point."""

    # Location
    lat: float
    lon: float
    location_name: str

    # Timestamps
    timestamp: str  # ISO 8601 — query reference time
    data_timestamp: str  # when the underlying source data was last updated

    # Ocean parameters — any numeric reading may be DATA_UNAVAILABLE
    sst: Optional[float]  # Sea Surface Temperature (°C)
    chlorophyll: Optional[float]  # mg/m³
    wave_height: Optional[float]  # metres (significant wave height)
    wave_period: Optional[float]  # seconds

    # Weather parameters — any numeric reading may be DATA_UNAVAILABLE
    wind_speed: Optional[float]  # km/h
    wind_direction: str  # "NE", "SW", etc., or "Unknown"
    visibility: Optional[float]  # km
    air_temperature: Optional[float]  # °C
    humidity: Optional[float]  # %
    weather_condition: str  # human-readable, e.g. "Partly Cloudy"

    # Tide
    tide_info: dict = field(default_factory=dict)
    # {"current": "high"|"low", "next_change": "HH:MM",
    #  "next_type": "high"|"low", "tidal_range_m": float}

    # Alerts (empty list = no alerts)
    active_alerts: list[dict] = field(default_factory=list)
    # Each: {"type": "cyclone"|"tsunami"|"high_wave"|"lightning"|"weather_warning"|"port_warning"|...,
    #         "severity": "watch"|"warning"|"alert",
    #         "title": str, "message": str,
    #         "issued_at": str, "valid_until": str, "source": str}

    # Potential Fishing Zones (empty list = none nearby)
    pfz_zones: list[dict] = field(default_factory=list)
    # Each: {"id": str, "lat": float, "lon": float,
    #         "distance_km": float, "confidence": "high"|"medium"|"low",
    #         "sst": float, "chlorophyll": float,
    #         "species_likely": [str], "valid_until": str}

    # Provenance
    data_source: str = "mock"  # "mock" | "open_meteo" | "incois" | ...

    # Which day the readings describe, vs. the day the user asked about
    conditions_type: str = "current"  # "current" | "forecast"
    conditions_date: Optional[str] = None  # IST date (YYYY-MM-DD); None when unknown, e.g. demo data
    requested_date: str = "today"  # the date phrase from the query

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON responses."""
        return {
            "lat": self.lat,
            "lon": self.lon,
            "location_name": self.location_name,
            "timestamp": self.timestamp,
            "data_timestamp": self.data_timestamp,
            "sst": self.sst,
            "chlorophyll": self.chlorophyll,
            "wave_height": self.wave_height,
            "wave_period": self.wave_period,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "visibility": self.visibility,
            "air_temperature": self.air_temperature,
            "humidity": self.humidity,
            "weather_condition": self.weather_condition,
            "tide_info": self.tide_info,
            "active_alerts": self.active_alerts,
            "pfz_zones": self.pfz_zones,
            "data_source": self.data_source,
            "conditions_type": self.conditions_type,
            "conditions_date": self.conditions_date,
            "requested_date": self.requested_date,
        }


async def get_marine_conditions(
    lat: float,
    lon: float,
    date: str = "today",
    location_name: Optional[str] = None,
) -> MarineConditions:
    """
    Single entry point for all marine/weather data.

    Tries the live provider first (if USE_LIVE_DATA is set), then falls
    back to the mock provider.  Callers never need to know which source
    actually served the data — check `result.data_source` if you care.
    """
    use_live = os.getenv("USE_LIVE_DATA", "false").lower() in ("true", "1", "yes")

    if use_live:
        try:
            from data_sources.live_provider import fetch_live_conditions

            return await fetch_live_conditions(lat, lon, date, location_name)
        except Exception as e:
            # Fall through to mock — but never silently.
            logger.warning(f"Live data fetch failed ({type(e).__name__}: {e}); falling back to mock data")

    from data_sources.mock_provider import fetch_mock_conditions

    return await fetch_mock_conditions(lat, lon, date, location_name)


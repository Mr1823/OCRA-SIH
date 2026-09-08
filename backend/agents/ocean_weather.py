"""
Ocean/Weather Data Agent — fetches and formats marine + weather conditions
for a given location.

This is the data-retrieval layer that other agents consume. It wraps
`get_marine_conditions()` and returns a structured dict ready for
LLM tool-calling and downstream agent consumption.
"""

from __future__ import annotations

from data_sources.interface import MarineConditions, get_marine_conditions


async def get_ocean_weather_data(
    lat: float,
    lon: float,
    date: str = "today",
    location_name: str | None = None,
) -> dict:
    """
    Fetch ocean + weather conditions and return a formatted summary.

    Returns a dict with sections: location, ocean, weather, tide, alerts,
    pfz_zones, and metadata (data_source, timestamps).
    """
    mc: MarineConditions = await get_marine_conditions(
        lat, lon, date, location_name
    )

    return format_conditions(mc)


def format_conditions(mc: MarineConditions) -> dict:
    """
    Transform a MarineConditions instance into a structured dict
    that's easy for the orchestrator / other agents to consume.
    """
    return {
        "location": {
            "name": mc.location_name,
            "lat": mc.lat,
            "lon": mc.lon,
        },
        "ocean": {
            "sst_celsius": mc.sst,
            "chlorophyll_mg_m3": mc.chlorophyll,
            "wave_height_m": mc.wave_height,
            "wave_period_s": mc.wave_period,
        },
        "weather": {
            "wind_speed_kmh": mc.wind_speed,
            "wind_direction": mc.wind_direction,
            "visibility_km": mc.visibility,
            "air_temperature_celsius": mc.air_temperature,
            "humidity_pct": mc.humidity,
            "condition": mc.weather_condition,
        },
        "tide": mc.tide_info,
        "alerts": mc.active_alerts,
        "pfz_zones": mc.pfz_zones,
        "metadata": {
            "data_source": mc.data_source,
            "query_timestamp": mc.timestamp,
            "data_timestamp": mc.data_timestamp,
        },
    }


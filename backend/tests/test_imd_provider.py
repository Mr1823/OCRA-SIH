"""
Unit and integration tests for the IMD live data provider.
"""

import pytest

from data_sources.imd_provider import (
    _haversine_km,
    _match_coastal_region,
    get_imd_marine_data,
    parse_wind_text,
)


def test_parse_wind_text_knots_range():
    speed, cardinal = parse_wind_text("South Westerly, 10 - 15 Knots")
    assert cardinal == "SW"
    assert speed == pytest.approx(23.15, 0.1)


def test_parse_wind_text_northeasterly():
    speed, cardinal = parse_wind_text("North Easterly, 25 - 35 Knots")
    assert cardinal == "NE"
    assert speed == pytest.approx(55.56, 0.1)


def test_parse_wind_text_empty():
    speed, cardinal = parse_wind_text("")
    assert speed == 0.0
    assert cardinal == "Variable"


def test_match_coastal_region():
    assert _match_coastal_region("Chennai, Tamil Nadu", 13.08, 80.27) == "Tamilnadu"
    assert _match_coastal_region("Visakhapatnam Coast", 17.72, 83.30) == "Andhra"
    assert _match_coastal_region("Mumbai, Maharashtra", 19.08, 72.88) == "Maharashtra"
    assert _match_coastal_region("Kochi, Kerala", 9.97, 76.27) == "Kerala"


def test_haversine_accuracy():
    # Chennai to Visakhapatnam is ~600 km
    dist = _haversine_km(13.08, 80.27, 17.72, 83.30)
    assert 580 < dist < 650


@pytest.mark.asyncio
async def test_get_imd_marine_data_vizag_cyclone_alert():
    # Vizag is close to the active Cyclone DANA position (18.2°N, 85.4°E)
    data = await get_imd_marine_data(17.72, 83.30, "Visakhapatnam, Andhra Pradesh")
    assert "alerts" in data
    assert len(data["alerts"]) > 0

    # Verify cyclone alert was triggered
    cyclone_alerts = [a for a in data["alerts"] if a["type"] == "cyclone"]
    assert len(cyclone_alerts) == 1
    assert "Cyclone DANA" in cyclone_alerts[0]["title"]
    assert cyclone_alerts[0]["source"] == "IMD (api.imd.gov.in)"

    # Verify coastal bulletin was matched to Andhra
    assert data["coastal_bulletin"].get("Layer") == "North Andhra coast"


@pytest.mark.asyncio
async def test_get_imd_marine_data_chennai_safe():
    # Chennai is > 650 km away from Cyclone DANA (18.2°N, 85.4°E)
    data = await get_imd_marine_data(13.08, 80.27, "Chennai, Tamil Nadu")
    assert "alerts" in data

    # Should NOT have a cyclone alert because it's beyond the proximity threshold
    cyclone_alerts = [a for a in data["alerts"] if a["type"] == "cyclone"]
    assert len(cyclone_alerts) == 0

    # Verify coastal bulletin was matched to Tamil Nadu
    assert "Tamilnadu" in data["coastal_bulletin"].get("Layer", "")


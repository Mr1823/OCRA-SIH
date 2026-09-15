"""
Integration tests for fetch_live_conditions() — specifically the
Copernicus chlorophyll wiring: a None from Copernicus must fall back to
the labelled climatology value, never silently become 0.0.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from data_sources.live_provider import fetch_live_conditions

CHENNAI = (13.08, 80.27)  # east coast
KOCHI = (9.93, 76.26)  # west coast


def _fake_response(json_data: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _marine_json(sst=28.0, wave_height=1.0, wave_period=8.0, wave_direction=180):
    return {
        "current": {
            "wave_height": wave_height,
            "wave_period": wave_period,
            "wave_direction": wave_direction,
        },
        "hourly": {"sea_surface_temperature": [sst]},
    }


def _weather_json():
    return {
        "current": {
            "temperature_2m": 30.0,
            "relative_humidity_2m": 70,
            "weather_code": 1,
            "wind_speed_10m": 15.0,
            "wind_direction_10m": 180,
            "visibility": 10000,
        }
    }


@pytest.fixture
def mock_httpx_get():
    """Route AsyncClient.get to the right fake payload by URL."""

    async def _get(self, url, params=None, **kwargs):
        if "marine-api" in url:
            return _fake_response(_marine_json())
        return _fake_response(_weather_json())

    with patch("httpx.AsyncClient.get", new=_get):
        yield


@pytest.fixture
def mock_imd_empty():
    with patch(
        "data_sources.live_provider.get_imd_marine_data",
        new=AsyncMock(return_value={"alerts": [], "data_source": "imd_baseline", "coastal_bulletin": {}}),
    ):
        yield


# ══════════════════════════════════════════════
#  Copernicus None must not become 0.0
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_chlorophyll_falls_back_to_climatology_when_copernicus_returns_none(
    mock_httpx_get, mock_imd_empty
):
    with patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        result = await fetch_live_conditions(*KOCHI, location_name="Kochi")

    # Must NOT be the old silent default...
    assert result.chlorophyll != 0.0
    # ...and must be a real, positive climatology figure.
    assert result.chlorophyll > 0.0
    # ...and the data source must say so explicitly, not claim it's a real reading.
    assert "copernicus_fallback_climatology" in result.data_source
    assert "copernicus " not in result.data_source.replace("copernicus_fallback_climatology", "")


@pytest.mark.asyncio
async def test_chlorophyll_uses_real_copernicus_value_when_available(
    mock_httpx_get, mock_imd_empty
):
    fake_reading = {"chlorophyll_mg_m3": 0.62, "data_timestamp": "2026-09-12T00:00:00Z"}
    with patch(
        "data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=fake_reading)
    ):
        result = await fetch_live_conditions(*CHENNAI, location_name="Chennai")

    assert result.chlorophyll == pytest.approx(0.62)
    assert result.data_source.endswith("+ copernicus")
    assert "fallback" not in result.data_source


@pytest.mark.asyncio
async def test_west_vs_east_coast_fallback_differs(mock_httpx_get, mock_imd_empty):
    """Sanity check that the fallback is actually regional, not one flat constant."""
    with patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        west = await fetch_live_conditions(*KOCHI, location_name="Kochi")
        east = await fetch_live_conditions(*CHENNAI, location_name="Chennai")

    assert west.chlorophyll != east.chlorophyll


# ══════════════════════════════════════════════
#  Live PFZ grid — gated behind config.ENABLE_LIVE_PFZ_GRID
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pfz_grid_disabled_by_default(mock_httpx_get, mock_imd_empty, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_LIVE_PFZ_GRID", False)
    with patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        result = await fetch_live_conditions(*CHENNAI, location_name="Chennai")

    assert result.pfz_zones == []


@pytest.mark.asyncio
async def test_pfz_grid_populated_when_enabled(mock_httpx_get, mock_imd_empty, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_LIVE_PFZ_GRID", True)
    with patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        result = await fetch_live_conditions(*CHENNAI, location_name="Chennai")

    assert len(result.pfz_zones) > 0
    zone = result.pfz_zones[0]
    for key in ("id", "lat", "lon", "distance_km", "confidence", "sst", "chlorophyll", "species_likely", "valid_until"):
        assert key in zone
    # No real Copernicus reading was available, so every grid point should
    # be honestly labelled as a climatology-derived, lower-confidence value.
    assert zone["confidence"] == "low"

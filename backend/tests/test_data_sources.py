"""
Unit tests for the data sources layer.

Tests:
  1. Mock provider returns a valid MarineConditions for each preloaded city.
  2. get_marine_conditions() entry point works and falls back to mock.
  3. MarineConditions.to_dict() produces a serialisable dict.
  4. Nearest-city selection returns the correct file.
"""

from __future__ import annotations

import asyncio
import math

import pytest

# Allow imports from backend/
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources.interface import MarineConditions, get_marine_conditions
from data_sources.mock_provider import (
    _find_nearest,
    _haversine_km,
    _load_mock_files,
    fetch_mock_conditions,
)


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

CHENNAI = (13.08, 80.27)
VIZAG = (17.72, 83.30)
MUMBAI = (19.08, 72.88)

# A point much closer to Chennai than to the other two
PUDUCHERRY = (11.93, 79.83)

# A point roughly equidistant between Vizag and Chennai — should pick one deterministically
KAKINADA = (16.94, 82.24)


# ──────────────────────────────────────────────
#  Test: mock files load correctly
# ──────────────────────────────────────────────


def test_mock_files_load():
    """All three mock JSON files should load without error."""
    files = _load_mock_files()
    assert len(files) >= 3, f"Expected ≥3 mock files, got {len(files)}"
    for f in files:
        assert "location" in f
        assert "ocean" in f
        assert "weather" in f


# ──────────────────────────────────────────────
#  Test: haversine distance sanity
# ──────────────────────────────────────────────


def test_haversine_same_point():
    """Distance from a point to itself should be ~0."""
    d = _haversine_km(*CHENNAI, *CHENNAI)
    assert d < 0.01


def test_haversine_known_distance():
    """Chennai ↔ Mumbai is roughly 1,030 km by great circle."""
    d = _haversine_km(*CHENNAI, *MUMBAI)
    assert 1000 < d < 1100, f"Chennai-Mumbai distance: {d:.0f} km"


# ──────────────────────────────────────────────
#  Test: nearest-city selection
# ──────────────────────────────────────────────


def test_nearest_to_puducherry_is_chennai():
    """Puducherry is ~130 km south of Chennai — should pick Chennai."""
    files = _load_mock_files()
    nearest = _find_nearest(*PUDUCHERRY, files)
    assert "chennai" in nearest["_filename"].lower()


def test_nearest_to_vizag_is_vizag():
    """Querying at Vizag's own coords should return Vizag."""
    files = _load_mock_files()
    nearest = _find_nearest(*VIZAG, files)
    assert "visakhapatnam" in nearest["_filename"].lower()


# ──────────────────────────────────────────────
#  Test: fetch_mock_conditions returns valid MarineConditions
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_mock_chennai():
    """Mock fetch for Chennai should return a populated MarineConditions."""
    mc = await fetch_mock_conditions(*CHENNAI)
    assert isinstance(mc, MarineConditions)
    assert mc.data_source == "mock"
    # SST should be in a reasonable range (jittered from 28.5)
    assert 25.0 < mc.sst < 32.0
    # Chennai mock has no alerts
    assert mc.active_alerts == []
    # Chennai mock has PFZ zones
    assert len(mc.pfz_zones) >= 1


@pytest.mark.asyncio
async def test_fetch_mock_vizag_has_alerts():
    """Vizag mock should have active cyclone + high_wave alerts."""
    mc = await fetch_mock_conditions(*VIZAG)
    assert len(mc.active_alerts) >= 2
    alert_types = {a["type"] for a in mc.active_alerts}
    assert "cyclone" in alert_types
    assert "high_wave" in alert_types


@pytest.mark.asyncio
async def test_fetch_mock_mumbai_has_lightning():
    """Mumbai mock should have a lightning alert."""
    mc = await fetch_mock_conditions(*MUMBAI)
    alert_types = {a["type"] for a in mc.active_alerts}
    assert "lightning" in alert_types


# ──────────────────────────────────────────────
#  Test: MarineConditions.to_dict()
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_to_dict_is_serialisable():
    """to_dict() should return a plain dict that's JSON-serialisable."""
    import json

    mc = await fetch_mock_conditions(*CHENNAI)
    d = mc.to_dict()
    assert isinstance(d, dict)
    # Should not raise
    json_str = json.dumps(d)
    assert len(json_str) > 100


@pytest.mark.asyncio
async def test_to_dict_keys():
    """to_dict() should contain all expected top-level keys."""
    mc = await fetch_mock_conditions(*MUMBAI)
    d = mc.to_dict()
    expected_keys = {
        "lat", "lon", "location_name", "timestamp", "data_timestamp",
        "sst", "chlorophyll", "wave_height", "wave_period",
        "wind_speed", "wind_direction", "visibility",
        "air_temperature", "humidity", "weather_condition",
        "tide_info", "active_alerts", "pfz_zones", "data_source",
    }
    assert expected_keys.issubset(d.keys()), f"Missing keys: {expected_keys - d.keys()}"


# ──────────────────────────────────────────────
#  Test: get_marine_conditions() entry point
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_marine_conditions_entry_point():
    """The main entry point should work with USE_LIVE_DATA unset (→ mock)."""
    import os

    os.environ.pop("USE_LIVE_DATA", None)
    mc = await get_marine_conditions(*CHENNAI, location_name="Chennai")
    assert isinstance(mc, MarineConditions)
    assert mc.location_name == "Chennai"


@pytest.mark.asyncio
async def test_get_marine_conditions_with_custom_name():
    """Passing a location_name should override the mock's default name."""
    mc = await get_marine_conditions(*MUMBAI, location_name="Gateway of India")
    assert mc.location_name == "Gateway of India"


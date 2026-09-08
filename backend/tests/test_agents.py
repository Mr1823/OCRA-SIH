"""
Unit tests for the three agent handlers:
  1. ocean_weather — output structure
  2. risk_assessment — threshold logic and verdict correctness
  3. pfz — zone evaluation and ranking
"""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.ocean_weather import get_ocean_weather_data, format_conditions
from agents.risk_assessment import assess_safety, RiskResult
from agents.pfz import find_nearby_pfz, PFZResult, _evaluate_zone


# ──────────────────────────────────────────────
#  Coordinates
# ──────────────────────────────────────────────

CHENNAI = (13.08, 80.27)
VIZAG = (17.72, 83.30)
MUMBAI = (19.08, 72.88)


# ══════════════════════════════════════════════
#  Ocean/Weather agent tests
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ocean_weather_returns_expected_sections():
    """Output dict should have location, ocean, weather, tide, alerts, pfz_zones, metadata."""
    data = await get_ocean_weather_data(*CHENNAI, location_name="Chennai")
    for key in ("location", "ocean", "weather", "tide", "alerts", "pfz_zones", "metadata"):
        assert key in data, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_ocean_weather_ocean_fields():
    """Ocean section should contain sst, chlorophyll, wave_height, wave_period."""
    data = await get_ocean_weather_data(*CHENNAI)
    ocean = data["ocean"]
    for field in ("sst_celsius", "chlorophyll_mg_m3", "wave_height_m", "wave_period_s"):
        assert field in ocean, f"Missing ocean field: {field}"
        assert isinstance(ocean[field], (int, float)), f"{field} should be numeric"


@pytest.mark.asyncio
async def test_ocean_weather_metadata():
    """Metadata should include data_source."""
    data = await get_ocean_weather_data(*MUMBAI)
    assert "data_source" in data["metadata"]


# ══════════════════════════════════════════════
#  Risk Assessment agent tests
# ══════════════════════════════════════════════


def _make_conditions(
    wave: float = 1.0,
    wind: float = 20.0,
    vis: float = 10.0,
    alerts: list | None = None,
) -> dict:
    """Helper to build a minimal ocean_weather_data dict for testing."""
    return {
        "ocean": {
            "sst_celsius": 28.0,
            "chlorophyll_mg_m3": 0.4,
            "wave_height_m": wave,
            "wave_period_s": 8.0,
        },
        "weather": {
            "wind_speed_kmh": wind,
            "wind_direction": "SW",
            "visibility_km": vis,
            "air_temperature_celsius": 30.0,
            "humidity_pct": 75,
            "condition": "Clear",
        },
        "alerts": alerts or [],
    }


def test_safe_conditions():
    """Calm seas, light wind, good visibility, no alerts → safe."""
    result = assess_safety(_make_conditions(wave=1.0, wind=20.0, vis=10.0))
    assert isinstance(result, RiskResult)
    assert result.verdict == "safe"
    assert result.risk_score < 20


def test_caution_moderate_waves():
    """Waves in 2.0–3.5 m range → caution."""
    result = assess_safety(_make_conditions(wave=2.5, wind=20.0, vis=10.0))
    assert result.verdict == "caution"


def test_unsafe_high_waves():
    """Waves > 3.5 m → unsafe."""
    result = assess_safety(_make_conditions(wave=4.0))
    assert result.verdict == "unsafe"
    assert result.risk_score >= 30


def test_unsafe_high_wind():
    """Wind > 50 km/h → unsafe."""
    result = assess_safety(_make_conditions(wind=60.0))
    assert result.verdict == "unsafe"


def test_unsafe_low_visibility():
    """Visibility < 2 km → unsafe."""
    result = assess_safety(_make_conditions(vis=1.5))
    assert result.verdict == "unsafe"


def test_cyclone_instant_unsafe():
    """Active cyclone alert → instant unsafe regardless of other conditions."""
    alerts = [{"type": "cyclone", "severity": "warning", "title": "Cyclone X"}]
    result = assess_safety(_make_conditions(wave=1.0, wind=10.0, vis=15.0, alerts=alerts))
    assert result.verdict == "unsafe"
    assert result.risk_score >= 30
    assert any("CYCLONE" in r for r in result.reasons)


def test_lightning_causes_caution():
    """Lightning alert with otherwise safe conditions → caution."""
    alerts = [{"type": "lightning", "severity": "watch", "title": "Lightning Activity"}]
    result = assess_safety(_make_conditions(wave=1.0, wind=15.0, vis=10.0, alerts=alerts))
    assert result.verdict == "caution"


def test_risk_result_to_dict():
    """RiskResult.to_dict() should have verdict, risk_score, reasons, thresholds_applied."""
    result = assess_safety(_make_conditions())
    d = result.to_dict()
    assert "verdict" in d
    assert "risk_score" in d
    assert "reasons" in d
    assert "thresholds_applied" in d
    assert isinstance(d["thresholds_applied"], dict)


def test_thresholds_applied_contains_all_params():
    """thresholds_applied should cover wave_height, wind_speed, visibility, alerts."""
    result = assess_safety(_make_conditions())
    th = result.thresholds_applied
    for key in ("wave_height", "wind_speed", "visibility", "alerts"):
        assert key in th, f"Missing threshold: {key}"
        assert "status" in th[key]


@pytest.mark.asyncio
async def test_risk_with_real_vizag_data():
    """Vizag mock (cyclone active) should assess as unsafe."""
    data = await get_ocean_weather_data(*VIZAG)
    result = assess_safety(data)
    assert result.verdict == "unsafe"


@pytest.mark.asyncio
async def test_risk_with_real_chennai_data():
    """Chennai mock (calm conditions) should assess as safe."""
    data = await get_ocean_weather_data(*CHENNAI)
    result = assess_safety(data)
    assert result.verdict == "safe"


# ══════════════════════════════════════════════
#  PFZ agent tests
# ══════════════════════════════════════════════


def test_evaluate_zone_excellent():
    """A zone with optimal SST and high chlorophyll + high confidence → excellent."""
    zone = {
        "id": "PFZ-TEST-01",
        "lat": 13.0,
        "lon": 80.5,
        "distance_km": 30.0,
        "confidence": "high",
        "sst": 27.5,
        "chlorophyll": 0.6,
        "species_likely": ["Sardine"],
        "valid_until": "2026-09-08T18:00:00+05:30",
    }
    result = _evaluate_zone(zone)
    assert result["suitability"] == "excellent"
    assert result["score"] >= 0.7


def test_evaluate_zone_poor():
    """A zone with bad SST and low chlorophyll → poor."""
    zone = {
        "id": "PFZ-TEST-02",
        "lat": 13.0,
        "lon": 80.5,
        "distance_km": 50.0,
        "confidence": "low",
        "sst": 33.0,
        "chlorophyll": 0.1,
        "species_likely": [],
        "valid_until": "2026-09-08T18:00:00+05:30",
    }
    result = _evaluate_zone(zone)
    assert result["suitability"] == "poor"
    assert result["score"] < 0.2


def test_find_nearby_pfz_with_zones():
    """When PFZ zones exist, should find and rank them."""
    data = _make_conditions()
    data["pfz_zones"] = [
        {"id": "PFZ-1", "lat": 13.0, "lon": 80.5, "distance_km": 30,
         "confidence": "high", "sst": 27.5, "chlorophyll": 0.6,
         "species_likely": ["Sardine"], "valid_until": "2026-09-08T18:00:00+05:30"},
        {"id": "PFZ-2", "lat": 12.9, "lon": 80.7, "distance_km": 50,
         "confidence": "medium", "sst": 28.0, "chlorophyll": 0.35,
         "species_likely": ["Tuna"], "valid_until": "2026-09-08T18:00:00+05:30"},
    ]
    result = find_nearby_pfz(data)
    assert isinstance(result, PFZResult)
    assert result.zones_found >= 1
    # Best zone should be first
    assert result.zones[0]["score"] >= result.zones[1]["score"]
    assert result.recommendation != ""


def test_find_nearby_pfz_no_zones():
    """When no PFZ zones exist, recommendation should say so."""
    data = _make_conditions()
    data["pfz_zones"] = []
    result = find_nearby_pfz(data)
    assert result.zones_found == 0
    assert "no suitable" in result.recommendation.lower() or "no" in result.recommendation.lower()


def test_pfz_result_to_dict():
    """PFZResult.to_dict() should have zones_found, zones, analysis, recommendation."""
    data = _make_conditions()
    data["pfz_zones"] = []
    result = find_nearby_pfz(data)
    d = result.to_dict()
    for key in ("zones_found", "zones", "analysis", "recommendation"):
        assert key in d


@pytest.mark.asyncio
async def test_pfz_with_real_chennai_data():
    """Chennai mock has PFZ zones — should find them."""
    data = await get_ocean_weather_data(*CHENNAI)
    result = find_nearby_pfz(data)
    assert result.zones_found >= 1


@pytest.mark.asyncio
async def test_pfz_with_real_vizag_data():
    """Vizag mock has no PFZ zones (cyclone active)."""
    data = await get_ocean_weather_data(*VIZAG)
    result = find_nearby_pfz(data)
    assert result.zones_found == 0


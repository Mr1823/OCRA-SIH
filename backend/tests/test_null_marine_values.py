"""
Null / missing numeric readings from Open-Meteo.

Reproduced: Kolkata's coordinates return wave_height: null from the
marine API. That None reached `wave > WAVE_CAUTION` in risk_assessment.py
and the user got an HTTP 500. Missing readings must now be reported as
unavailable — never a crash, and never a fabricated value (0.0, 28.0 °C,
10 km) that reads as calm.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.risk_assessment import assess_safety
from agents.synthesis import _build_data_summary, synthesise_response
from data_sources.interface import get_marine_conditions
from data_sources.live_provider import fetch_live_conditions

KOLKATA = (22.57, 88.36)
MISSING_DATA_NOTE = "Some marine data isn't available for this location right now"


# ──────────────────────────────────────────────
#  Fake Open-Meteo responses
# ──────────────────────────────────────────────


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _marine_json(overrides: dict | None = None, drop: tuple = (), sst=29.0) -> dict:
    current = {"wave_height": 1.0, "wave_period": 8.0, "wave_direction": 180}
    current.update(overrides or {})
    for key in drop:
        current.pop(key)
    return {"current": current, "hourly": {"sea_surface_temperature": [sst]}}


def _weather_json(overrides: dict | None = None) -> dict:
    current = {
        "temperature_2m": 30.0,
        "relative_humidity_2m": 70,
        "weather_code": 1,
        "wind_speed_10m": 15.0,
        "wind_direction_10m": 180,
        "visibility": 10000,
    }
    current.update(overrides or {})
    return {"current": current}


@contextmanager
def _open_meteo(marine: dict, weather: dict, patch_imd: bool = True):
    async def _get(self, url, params=None, **kwargs):
        return _fake_response(marine if "marine-api" in url else weather)

    imd = {"alerts": [], "data_source": "imd_baseline", "coastal_bulletin": {}}
    with patch("httpx.AsyncClient.get", new=_get), \
         patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        if patch_imd:
            with patch("data_sources.live_provider.get_imd_marine_data", new=AsyncMock(return_value=imd)):
                yield
        else:
            yield


# ══════════════════════════════════════════════
#  live_provider parsing
# ══════════════════════════════════════════════


def test_data_unavailable_sentinel_is_documented_and_json_null():
    from data_sources.interface import DATA_UNAVAILABLE, is_unavailable

    assert is_unavailable(DATA_UNAVAILABLE)
    assert not is_unavailable(0.0)
    assert json.dumps({"wave_height": DATA_UNAVAILABLE}) == '{"wave_height": null}'


@pytest.mark.asyncio
async def test_null_wave_height_and_sst_are_unavailable_not_fabricated():
    with _open_meteo(_marine_json({"wave_height": None}, sst=None), _weather_json()):
        mc = await fetch_live_conditions(*KOLKATA, location_name="Kolkata, West Bengal")

    assert mc.wave_height is None
    assert mc.sst is None  # previously a made-up 28.0
    assert mc.data_source.startswith("open_meteo")


@pytest.mark.asyncio
async def test_missing_or_null_weather_fields_are_unavailable_not_defaults():
    weather = _weather_json({"visibility": None, "wind_direction_10m": None, "weather_code": None})
    with _open_meteo(_marine_json(drop=("wave_period",)), weather):
        mc = await fetch_live_conditions(*KOLKATA, location_name="Kolkata, West Bengal")

    assert mc.visibility is None  # null used to crash; a missing key became a fabricated 10 km
    assert mc.wave_period is None  # a missing key used to become 0.0
    assert mc.wind_direction == "Unknown"
    assert mc.weather_condition == "Unknown"


@pytest.mark.asyncio
async def test_null_values_do_not_silently_switch_to_mock_data(monkeypatch):
    monkeypatch.setenv("USE_LIVE_DATA", "true")
    with _open_meteo(_marine_json({"wave_height": None}), _weather_json({"visibility": None})):
        mc = await get_marine_conditions(*KOLKATA, location_name="Kolkata, West Bengal")

    assert mc.data_source.startswith("open_meteo")


# ══════════════════════════════════════════════
#  risk_assessment
# ══════════════════════════════════════════════


def _conditions(wave=0.8, wind=12.0, vis=15.0) -> dict:
    return {
        "ocean": {"sst_celsius": 28.0, "chlorophyll_mg_m3": 0.4, "wave_height_m": wave, "wave_period_s": 8.0},
        "weather": {
            "wind_speed_kmh": wind,
            "wind_direction": "SW",
            "visibility_km": vis,
            "air_temperature_celsius": 30.0,
            "humidity_pct": 70,
            "condition": "Clear Sky",
        },
        "alerts": [],
    }


@pytest.mark.parametrize(
    "kwargs,expected_reason,threshold_key",
    [
        ({"wave": None}, "Wave height data unavailable for this location", "wave_height"),
        ({"wind": None}, "Wind speed data unavailable for this location", "wind_speed"),
        ({"vis": None}, "Visibility data unavailable for this location", "visibility"),
    ],
    ids=["wave_height", "wind_speed", "visibility"],
)
def test_unavailable_reading_is_reported_and_verdict_is_not_safe(kwargs, expected_reason, threshold_key):
    result = assess_safety(_conditions(**kwargs))

    assert result.verdict == "caution"
    assert any(r.startswith(expected_reason) for r in result.reasons)
    assert result.thresholds_applied[threshold_key]["status"] == "unavailable"
    assert result.thresholds_applied[threshold_key]["value"] is None


def test_unavailable_reading_cannot_mask_an_unsafe_one():
    result = assess_safety(_conditions(wave=None, wind=60.0))
    assert result.verdict == "unsafe"


# ══════════════════════════════════════════════
#  synthesis
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_answer_says_data_is_missing_instead_of_implying_calm(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")

    ocean_weather = _conditions(wave=None)
    ocean_weather.update({
        "location": {"name": "Kolkata, West Bengal", "lat": KOLKATA[0], "lon": KOLKATA[1]},
        "tide": {},
        "pfz_zones": [],
        "metadata": {"data_source": "open_meteo + imd_live + copernicus", "query_timestamp": "", "data_timestamp": ""},
    })
    handler_result = {
        "success": True,
        "intent": "assess_sea_safety",
        "location": ocean_weather["location"],
        "date": "today",
        "ocean_weather": ocean_weather,
        "risk_assessment": assess_safety(ocean_weather).to_dict(),
        "agents_invoked": ["ocean_weather", "risk_assessment"],
    }

    response = await synthesise_response(handler_result, "Is it safe to go to sea near Kolkata today?")
    answer = response["answer_text"]

    assert not answer.startswith("✅")
    assert "Wave height data unavailable for this location" in answer
    assert MISSING_DATA_NOTE in answer
    assert "Wave height: unavailable" in _build_data_summary(handler_result)


# ══════════════════════════════════════════════
#  The reported reproduction, through the real HTTP endpoint
# ══════════════════════════════════════════════


def test_reproduced_case_kolkata_null_wave_height_returns_honest_200(monkeypatch):
    """POST /query for Kolkata used to return HTTP 500: "'>' not supported between 'NoneType' and 'float'"."""
    import main

    monkeypatch.setenv("USE_LIVE_DATA", "true")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "IMD_API_KEY", "")

    marine = _marine_json({"wave_height": None, "wave_period": None}, sst=None)
    with _open_meteo(marine, _weather_json(), patch_imd=False):
        with TestClient(main.app) as client:
            response = client.post("/query", json={"query": "Is it safe to go to sea near Kolkata today?"})

    assert response.status_code == 200
    body = response.json()
    assert "Wave height data unavailable for this location" in body["answer_text"]
    assert MISSING_DATA_NOTE in body["answer_text"]
    assert body["evidence"]["risk_assessment"]["thresholds_applied"]["wave_height"]["status"] == "unavailable"

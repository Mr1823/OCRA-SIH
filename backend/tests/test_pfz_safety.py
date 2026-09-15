"""
Fishing-zone (PFZ) answers and safety.

The PFZ handler never ran risk_assessment.py, so "here's a good fishing
zone near Mumbai" could go out with an active lightning warning nowhere in
the response. PFZ answers now carry the same risk assessment as a safety
question and lead with a safety caveat whenever it isn't clean.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.orchestrator import handle_query
from agents.pfz import find_nearby_pfz
from agents.risk_assessment import assess_safety
from agents.synthesis import synthesise_response

SAFETY_CAVEAT = "**Safety check:"

ZONE = {
    "id": "PFZ-TEST-01",
    "lat": 13.15,
    "lon": 80.55,
    "distance_km": 32.0,
    "confidence": "high",
    "sst": 27.8,
    "chlorophyll": 0.62,
    "species_likely": ["Sardine"],
    "valid_until": "2026-09-15T18:00:00+05:30",
}


@pytest.fixture(autouse=True)
def _template_answers_only(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")


def _alert(alert_type: str, title: str) -> dict:
    return {"type": alert_type, "severity": "warning", "title": title, "message": "Test", "source": "IMD (api.imd.gov.in)"}


def _pfz_handler_result(alerts: list, zones: list | None = None, wave: float = 0.8) -> dict:
    ocean_weather = {
        "location": {"name": "Chennai, Tamil Nadu", "lat": 13.08, "lon": 80.27},
        "ocean": {"sst_celsius": 28.5, "chlorophyll_mg_m3": 0.45, "wave_height_m": wave, "wave_period_s": 8.0},
        "weather": {
            "wind_speed_kmh": 12.0, "wind_direction": "SW", "visibility_km": 15.0,
            "air_temperature_celsius": 30.0, "humidity_pct": 70, "condition": "Clear Sky",
        },
        "tide": {},
        "alerts": alerts,
        "pfz_zones": [ZONE] if zones is None else zones,
        "metadata": {
            "data_source": "open_meteo + imd_live + copernicus",
            "query_timestamp": "",
            "data_timestamp": "",
            "conditions_type": "current",
            "conditions_date": None,
            "requested_date": "today",
        },
    }
    return {
        "success": True,
        "intent": "find_nearest_pfz",
        "location": ocean_weather["location"],
        "date": "today",
        "ocean_weather": ocean_weather,
        "pfz_result": find_nearby_pfz(ocean_weather).to_dict(),
        "risk_assessment": assess_safety(ocean_weather).to_dict(),
        "agents_invoked": ["ocean_weather", "pfz", "risk_assessment"],
    }


# ══════════════════════════════════════════════
#  Through the real pipeline (demo data)
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pfz_answer_for_location_with_active_alert_includes_safety_caveat():
    """Mumbai demo data: PFZ-MUM-001 alongside an active IMD lightning warning."""
    response = await handle_query("Where is the nearest PFZ near Mumbai?")
    answer = response["answer_text"]
    caveat = answer.split("\n\n")[0]

    assert caveat.startswith("⚠️ **Safety check:")
    assert "lightning alert" in caveat
    assert "verify safety before heading out" in caveat
    assert "PFZ-MUM-001" in answer  # the recommendation itself is still there
    assert "risk_assessment" in response["evidence"]["agents_invoked"]
    assert response["evidence"]["risk_assessment"]["verdict"] == "caution"


@pytest.mark.asyncio
async def test_pfz_answer_for_calm_location_has_no_safety_caveat():
    response = await handle_query("Where is the nearest PFZ near Chennai?")

    assert SAFETY_CAVEAT not in response["answer_text"]
    assert response["evidence"]["risk_assessment"]["verdict"] == "safe"


# ══════════════════════════════════════════════
#  synthesis
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_caveat_names_the_zone_and_the_active_warning():
    handler = _pfz_handler_result([_alert("weather_warning", "IMD Coastal Advisory — Maharashtra-Goa coast")])
    answer = (await synthesise_response(handler, "Where is the nearest PFZ near Chennai?"))["answer_text"]

    assert answer.startswith(
        "⚠️ **Safety check: CAUTION.** While **PFZ-TEST-01** looks like a promising fishing zone, "
        "current conditions include an active weather warning (IMD Coastal Advisory — Maharashtra-Goa coast)"
    )
    assert "verify safety before heading out" in answer


@pytest.mark.asyncio
async def test_unsafe_conditions_say_do_not_head_out():
    handler = _pfz_handler_result([_alert("cyclone", "IMD: Cyclone DANA — CYCLONIC STORM")])
    answer = (await synthesise_response(handler, "Where is the nearest PFZ near Chennai?"))["answer_text"]

    assert answer.startswith("🚫 **Safety check: NOT SAFE.**")
    assert "an active cyclone alert (IMD: Cyclone DANA — CYCLONIC STORM)" in answer
    assert "do not head out until conditions improve" in answer


@pytest.mark.asyncio
async def test_rough_sea_without_alerts_is_also_flagged():
    handler = _pfz_handler_result([], wave=2.8)
    answer = (await synthesise_response(handler, "Where is the nearest PFZ near Chennai?"))["answer_text"]

    assert answer.startswith("⚠️ **Safety check: CAUTION.**")
    assert "wave height 2.8 m (caution)" in answer


@pytest.mark.asyncio
async def test_caveat_still_shown_when_no_zone_is_viable():
    handler = _pfz_handler_result([_alert("lightning", "Lightning Activity Warning")], zones=[])
    answer = (await synthesise_response(handler, "Where is the nearest PFZ near Chennai?"))["answer_text"]

    assert answer.startswith("⚠️ **Safety check: CAUTION.** Current conditions include an active lightning alert")
    assert "promising" not in answer


@pytest.mark.asyncio
async def test_caveat_is_applied_even_when_an_llm_writes_the_answer(monkeypatch):
    llm = AsyncMock(return_value="🐟 Great news — PFZ-TEST-01 is a fantastic spot today!")
    monkeypatch.setattr("agents.synthesis._generate_groq_answer", llm)
    handler = _pfz_handler_result([_alert("lightning", "Lightning Activity Warning")])

    answer = (await synthesise_response(handler, "Where is the nearest PFZ near Chennai?"))["answer_text"]

    assert answer.startswith("⚠️ **Safety check: CAUTION.**")
    assert "Safety verdict for heading out: caution" in llm.call_args.args[2]


@pytest.mark.asyncio
async def test_tamil_pfz_safety_caveat():
    handler = _pfz_handler_result([_alert("lightning", "Lightning Activity Warning")])
    answer = (await synthesise_response(handler, "சென்னை அருகில் மீன்பிடி மண்டலம் எங்கே?", language="ta"))["answer_text"]

    assert answer.startswith("⚠️ **பாதுகாப்பு சோதனை: எச்சரிக்கை.**")


@pytest.mark.asyncio
async def test_evidence_and_map_reflect_the_pfz_safety_verdict():
    handler = _pfz_handler_result([_alert("lightning", "Lightning Activity Warning")])
    response = await synthesise_response(handler, "Where is the nearest PFZ near Chennai?")

    assert response["evidence"]["risk_assessment"]["verdict"] == "caution"
    assert response["evidence"]["pfz_analysis"]  # still present
    location_marker = response["map_data"]["markers"][0]
    assert location_marker["color"] == "orange"


# ══════════════════════════════════════════════
#  Live mode: the IMD advisory that used to be ignored
# ══════════════════════════════════════════════


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.asyncio
async def test_live_mumbai_pfz_answer_mentions_the_imd_advisory(monkeypatch):
    monkeypatch.setenv("USE_LIVE_DATA", "true")
    monkeypatch.setattr(config, "IMD_API_KEY", "")  # baseline bulletins: Maharashtra has a thunderstorm advisory

    async def _calm_open_meteo(self, url, params=None, **kwargs):
        if "marine-api" in url:
            return _fake_response({
                "current": {"wave_height": 1.0, "wave_period": 8.0, "wave_direction": 250},
                "hourly": {"sea_surface_temperature": [29.0]},
            })
        return _fake_response({"current": {
            "temperature_2m": 29.0, "relative_humidity_2m": 80, "weather_code": 3,
            "wind_speed_10m": 19.0, "wind_direction_10m": 250, "visibility": 16000,
        }})

    with patch("httpx.AsyncClient.get", new=_calm_open_meteo), \
         patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        response = await handle_query("Where is the nearest PFZ near Mumbai?")

    caveat = response["answer_text"].split("\n\n")[0]
    assert caveat.startswith("⚠️ **Safety check: CAUTION.**")
    assert "an active weather warning (IMD Coastal Advisory — Maharashtra-Goa coast)" in caveat

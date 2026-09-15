"""
The "not live IMD data" disclaimer follows the alert data's provenance,
not whether the alert list happens to be non-empty.

An empty list from IMD's baseline fallback used to render as a confident
"No active weather or marine alerts" / "Conditions appear normal" with no
disclaimer at all — a fabricated all-clear.
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
from agents.risk_assessment import assess_safety
from agents.synthesis import synthesise_response
from data_sources import imd_provider

BASELINE_SOURCE = "open_meteo + imd_baseline + copernicus_fallback_climatology"
LIVE_SOURCE = "open_meteo + imd_live + copernicus"

# Distinct phrases from the two synthesis.py qualifiers
NO_LIVE_ALERTS_NOTE = "Live IMD alert data isn't currently connected, so"
ILLUSTRATIVE_ALERTS_NOTE = "illustrative baseline/example data"

CYCLONE_ALERT = {
    "type": "cyclone",
    "severity": "warning",
    "title": "IMD: Cyclone DANA — CYCLONIC STORM",
    "message": "Cyclonic disturbance located approximately 228 km from the area.",
    "source": "IMD (api.imd.gov.in)",
}


@pytest.fixture(autouse=True)
def _template_answers_only(monkeypatch):
    """Deterministic template text — no Groq/Claude calls."""
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")


def _handler_result(intent: str, data_source: str, alerts: list) -> dict:
    ocean_weather = {
        "location": {"name": "Chennai, Tamil Nadu", "lat": 13.08, "lon": 80.27},
        "ocean": {"sst_celsius": 30.1, "chlorophyll_mg_m3": 0.35, "wave_height_m": 0.6, "wave_period_s": 11.0},
        "weather": {
            "wind_speed_kmh": 6.0,
            "wind_direction": "E",
            "visibility_km": 16.4,
            "air_temperature_celsius": 31.0,
            "humidity_pct": 68,
            "condition": "Clear Sky",
        },
        "tide": {},
        "alerts": alerts,
        "pfz_zones": [],
        "metadata": {
            "data_source": data_source,
            "query_timestamp": "2026-09-15T06:00:00+00:00",
            "data_timestamp": "2026-09-15T06:00:00+00:00",
        },
    }
    result = {
        "success": True,
        "intent": intent,
        "location": ocean_weather["location"],
        "date": "today",
        "ocean_weather": ocean_weather,
    }
    if intent == "assess_sea_safety":
        result["risk_assessment"] = assess_safety(ocean_weather).to_dict()
        result["agents_invoked"] = ["ocean_weather", "risk_assessment"]
    else:
        result["alerts_summary"] = {
            "active_alerts": alerts,
            "alert_count": len(alerts),
            "has_critical": any(a.get("type") == "cyclone" for a in alerts),
        }
        result["agents_invoked"] = ["ocean_weather"]
    return result


INTENT_QUERIES = [
    ("assess_sea_safety", "Is it safe to go to sea near Chennai today?"),
    ("check_alerts", "Any weather alerts near Chennai today?"),
]


# ══════════════════════════════════════════════
#  Baseline (not live) alert data
# ══════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,query", INTENT_QUERIES)
async def test_disclaimer_shown_for_imd_baseline_with_empty_alert_list(intent, query):
    response = await synthesise_response(_handler_result(intent, BASELINE_SOURCE, []), query)
    answer = response["answer_text"]

    assert NO_LIVE_ALERTS_NOTE in answer
    assert "confirmed all-clear" in answer
    assert "mausam.imd.gov.in" in answer


@pytest.mark.asyncio
async def test_alerts_answer_does_not_claim_all_clear_on_baseline_data():
    response = await synthesise_response(
        _handler_result("check_alerts", BASELINE_SOURCE, []), "Any weather alerts near Chennai today?"
    )
    answer = response["answer_text"]

    assert not answer.startswith("✅")
    assert "Conditions appear normal" not in answer


@pytest.mark.asyncio
async def test_disclaimer_shown_for_imd_baseline_with_populated_alert_list():
    response = await synthesise_response(
        _handler_result("assess_sea_safety", BASELINE_SOURCE, [CYCLONE_ALERT]),
        "Is it safe to go to sea near Chennai today?",
    )
    answer = response["answer_text"]

    assert ILLUSTRATIVE_ALERTS_NOTE in answer
    assert NO_LIVE_ALERTS_NOTE not in answer  # the populated-list wording applies instead


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data_source",
    ["open_meteo + imd + copernicus_fallback_climatology", "", "mock"],
    ids=["imd-fetch-failed", "missing-source", "mock"],
)
async def test_degraded_missing_or_mock_alert_source_is_not_treated_as_live(data_source):
    response = await synthesise_response(
        _handler_result("assess_sea_safety", data_source, []), "Is it safe to go to sea near Chennai today?"
    )
    assert NO_LIVE_ALERTS_NOTE in response["answer_text"]


@pytest.mark.asyncio
async def test_tamil_disclaimer_shown_for_empty_baseline_list():
    response = await synthesise_response(
        _handler_result("assess_sea_safety", BASELINE_SOURCE, []),
        "சென்னை அருகில் கடலுக்குச் செல்வது பாதுகாப்பானதா?",
        language="ta",
    )
    assert "உறுதிசெய்யப்பட்ட பாதுகாப்பு அறிவிப்பு அல்ல" in response["answer_text"]


# ══════════════════════════════════════════════
#  Live alert data
# ══════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("intent,query", INTENT_QUERIES)
async def test_no_disclaimer_when_alert_data_is_live(intent, query):
    response = await synthesise_response(_handler_result(intent, LIVE_SOURCE, []), query)
    assert "isn't currently connected" not in response["answer_text"]


@pytest.mark.asyncio
async def test_live_empty_alert_list_still_reads_as_all_clear():
    response = await synthesise_response(
        _handler_result("check_alerts", LIVE_SOURCE, []), "Any weather alerts near Chennai today?"
    )
    assert response["answer_text"].startswith("✅ **No active alerts**")


@pytest.mark.asyncio
async def test_evidence_flags_whether_alert_data_is_live():
    baseline = await synthesise_response(
        _handler_result("check_alerts", BASELINE_SOURCE, []), "Any weather alerts near Chennai today?"
    )
    assert baseline["evidence"]["alert_data_is_live"] is False
    assert baseline["evidence"]["alerts"]["data_is_synthetic"] is True

    live = await synthesise_response(
        _handler_result("check_alerts", LIVE_SOURCE, []), "Any weather alerts near Chennai today?"
    )
    assert live["evidence"]["alert_data_is_live"] is True
    assert live["evidence"]["alerts"]["data_is_synthetic"] is False


# ══════════════════════════════════════════════
#  imd_provider only claims "imd_live" when IMD actually answered
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_imd_key_configured_but_unreachable_is_labelled_baseline(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "test-key")

    async def _unreachable(self, url, **kwargs):
        raise httpx.ConnectError("IMD unreachable")

    with patch("httpx.AsyncClient.get", new=_unreachable):
        data = await imd_provider.get_imd_marine_data(13.08, 80.27, "Chennai, Tamil Nadu")

    assert data["data_source"] == "imd_baseline"


@pytest.mark.asyncio
async def test_imd_labelled_live_only_when_both_feeds_answer(monkeypatch):
    monkeypatch.setattr(config, "IMD_API_KEY", "test-key")
    live_track = {"data": {"observed": [], "forecast": []}}
    live_bulletins = [{"Layer": "North Tamilnadu coast", "TTT Warning": "NIL", "Port Signal": "NIL"}]

    with patch.object(imd_provider, "fetch_cyclone_track", new=AsyncMock(return_value=live_track)), \
         patch.object(imd_provider, "fetch_coastal_bulletins", new=AsyncMock(return_value=live_bulletins)):
        data = await imd_provider.get_imd_marine_data(13.08, 80.27, "Chennai, Tamil Nadu")
    assert data["data_source"] == "imd_live"

    # One feed silently falling back to the baseline is enough to lose the live label.
    with patch.object(imd_provider, "fetch_cyclone_track", new=AsyncMock(return_value=live_track)), \
         patch.object(
             imd_provider,
             "fetch_coastal_bulletins",
             new=AsyncMock(return_value=imd_provider._FALLBACK_COASTAL_BULLETINS),
         ):
        data = await imd_provider.get_imd_marine_data(13.08, 80.27, "Chennai, Tamil Nadu")
    assert data["data_source"] == "imd_baseline"


# ══════════════════════════════════════════════
#  The reported reproduction, end to end
# ══════════════════════════════════════════════


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.asyncio
async def test_reproduced_case_chennai_live_mode_empty_baseline_alerts(monkeypatch):
    """Live mode with no IMD key: Chennai used to get an unqualified all-clear."""
    monkeypatch.setenv("USE_LIVE_DATA", "true")
    monkeypatch.setattr(config, "IMD_API_KEY", "")

    async def _open_meteo(self, url, params=None, **kwargs):
        if "marine-api" in url:
            return _fake_response({
                "current": {"wave_height": 0.6, "wave_period": 11.0, "wave_direction": 90},
                "hourly": {"sea_surface_temperature": [30.1]},
            })
        return _fake_response({
            "current": {
                "temperature_2m": 31.0,
                "relative_humidity_2m": 68,
                "weather_code": 0,
                "wind_speed_10m": 6.0,
                "wind_direction_10m": 100,
                "visibility": 16400,
            }
        })

    with patch("httpx.AsyncClient.get", new=_open_meteo), \
         patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        response = await handle_query("Any weather alerts near Chennai today?")

    assert "imd_baseline" in response["evidence"]["data_source"]
    answer = response["answer_text"]
    assert "Conditions appear normal" not in answer
    assert NO_LIVE_ALERTS_NOTE in answer

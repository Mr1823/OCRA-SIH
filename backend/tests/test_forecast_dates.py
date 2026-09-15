"""
"Tomorrow" queries.

Both providers ignored the requested date: a query about tomorrow got
today's live conditions (or a fixed demo timestamp) and the answer still
said "It appears safe ... tomorrow". Live mode now fetches Open-Meteo's
forecast for that day; whenever no forecast for the requested day is
available (demo data, past or too-distant dates) the answer says it only
checked current conditions.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.orchestrator import _extract_date_from_query, _keyword_intent_detection, handle_query
from agents.risk_assessment import assess_safety
from agents.synthesis import synthesise_response
from data_sources.live_provider import fetch_live_conditions

FIXED_TODAY = date(2026, 9, 15)
NOT_CHECKED_NOTE = "📅 **I can only check current conditions right now, not forecasts for tomorrow**"


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    """Pin 'today' and use template answers — no Groq calls."""
    for module_name in ("utils.dates", "data_sources.live_provider", "agents.synthesis"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        monkeypatch.setattr(module, "today_ist", lambda: FIXED_TODAY, raising=False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "")


# ══════════════════════════════════════════════
#  Working out which day was asked about
# ══════════════════════════════════════════════


@pytest.mark.parametrize(
    "phrase,days_ahead",
    [
        ("today", 0), ("", 0), (None, 0), ("this evening", 0),
        ("tomorrow", 1), ("tomorrow morning", 1), ("day after tomorrow", 2),
        ("நாளை", 1), ("நாளை மறுநாள்", 2), ("2026-09-18", 3),
    ],
)
def test_resolve_requested_date(phrase, days_ahead):
    from utils.dates import resolve_requested_date

    assert resolve_requested_date(phrase) == FIXED_TODAY + timedelta(days=days_ahead)


def test_unparseable_date_phrase_resolves_to_none():
    from utils.dates import resolve_requested_date

    assert resolve_requested_date("next monday") is None


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Is it safe to go fishing tomorrow near Chennai?", "tomorrow"),
        ("Is it safe to venture into the sea day after tomorrow near Chennai?", "day after tomorrow"),
        ("நாளை சென்னை அருகில் கடலுக்குச் செல்வது பாதுகாப்பானதா?", "tomorrow"),
        ("Is it safe near Chennai on 2026-09-18?", "2026-09-18"),
        ("Is it safe near Mumbai?", "today"),
    ],
)
def test_keyword_date_extraction(query, expected):
    assert _extract_date_from_query(query) == expected


@pytest.mark.parametrize(
    "query,intent",
    [
        ("Where is the nearest fishing zone near Mumbai tomorrow?", "find_nearest_pfz"),
        ("Any cyclone alerts near Vizag tomorrow?", "check_alerts"),
    ],
)
def test_keyword_pfz_and_alert_intents_carry_the_date(query, intent):
    tool_call = _keyword_intent_detection(query)
    assert tool_call["name"] == intent
    assert tool_call["args"]["date"] == "tomorrow"


# ══════════════════════════════════════════════
#  live_provider: forecast vs current conditions
# ══════════════════════════════════════════════


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


HOURS = [f"2026-09-16T{h:02d}:00" for h in range(24)]
FORECAST_MARINE = {"hourly": {
    "time": HOURS,
    "wave_height": [0.5] * 20 + [2.6, 1.0, None, 0.8],
    "wave_period": [8.0] * 20 + [12.5, 8.0, 8.0, 8.0],
    "sea_surface_temperature": [30.0] * 24,
}}
FORECAST_WEATHER = {"hourly": {
    "time": HOURS,
    "temperature_2m": [30.0] * 24,
    "relative_humidity_2m": [70] * 24,
    "weather_code": [1] * 23 + [95],
    "wind_speed_10m": [10.0] * 18 + [42.0] + [10.0] * 5,
    "wind_direction_10m": [180] * 18 + [45] + [180] * 5,
    "visibility": [20000] * 23 + [3500],
}}
CURRENT_MARINE = {
    "current": {"wave_height": 0.6, "wave_period": 11.0, "wave_direction": 90},
    "hourly": {"sea_surface_temperature": [30.1]},
}
CURRENT_WEATHER = {"current": {
    "temperature_2m": 31.0, "relative_humidity_2m": 68, "weather_code": 0,
    "wind_speed_10m": 6.0, "wind_direction_10m": 100, "visibility": 16400,
}}


@contextmanager
def _open_meteo(calls: list):
    """Answer with forecast or current payloads depending on what was requested."""

    async def _get(self, url, params=None, **kwargs):
        params = dict(params or {})
        calls.append((url, params))
        forecast = "start_date" in params
        if "marine-api" in url:
            return _fake_response(FORECAST_MARINE if forecast else CURRENT_MARINE)
        return _fake_response(FORECAST_WEATHER if forecast else CURRENT_WEATHER)

    imd = {"alerts": [], "data_source": "imd_baseline", "coastal_bulletin": {}}
    with patch("httpx.AsyncClient.get", new=_get), \
         patch("data_sources.live_provider.get_imd_marine_data", new=AsyncMock(return_value=imd)), \
         patch("data_sources.live_provider.fetch_chlorophyll", new=AsyncMock(return_value=None)):
        yield


@pytest.mark.asyncio
async def test_live_provider_fetches_the_forecast_for_tomorrow():
    calls = []
    with _open_meteo(calls):
        mc = await fetch_live_conditions(13.08, 80.27, "tomorrow", "Chennai, Tamil Nadu")

    assert len(calls) == 2
    for _, params in calls:
        assert params["start_date"] == params["end_date"] == "2026-09-16"
        assert params["timezone"] == "Asia/Kolkata"
        assert "current" not in params

    assert mc.conditions_type == "forecast"
    assert mc.conditions_date == "2026-09-16"
    assert mc.requested_date == "tomorrow"
    # The roughest hour of that day — not the first hour, not an average
    assert mc.wave_height == 2.6
    assert mc.wave_period == 12.5  # at the peak-wave hour
    assert mc.wind_speed == 42.0
    assert mc.wind_direction == "NE"  # at the peak-wind hour
    assert mc.visibility == 3.5
    assert mc.weather_condition == "Thunderstorms"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested",
    ["today", "2026-09-10", "2026-10-10", "next monday"],
    ids=["today", "past-date", "beyond-horizon", "unparseable"],
)
async def test_live_provider_uses_current_conditions_when_no_forecast_applies(requested):
    calls = []
    with _open_meteo(calls):
        mc = await fetch_live_conditions(13.08, 80.27, requested, "Chennai, Tamil Nadu")

    assert all("current" in params and "start_date" not in params for _, params in calls)
    assert mc.conditions_type == "current"
    assert mc.conditions_date == "2026-09-15"
    assert mc.requested_date == requested


# ══════════════════════════════════════════════
#  synthesis: what the answer says about the date
# ══════════════════════════════════════════════


def _handler_result(
    date_phrase: str,
    conditions_type: str = "current",
    conditions_date: str | None = "2026-09-15",
) -> dict:
    ocean_weather = {
        "location": {"name": "Chennai, Tamil Nadu", "lat": 13.08, "lon": 80.27},
        "ocean": {"sst_celsius": 30.1, "chlorophyll_mg_m3": 0.35, "wave_height_m": 0.6, "wave_period_s": 11.0},
        "weather": {
            "wind_speed_kmh": 6.0, "wind_direction": "E", "visibility_km": 16.4,
            "air_temperature_celsius": 31.0, "humidity_pct": 68, "condition": "Clear Sky",
        },
        "tide": {},
        "alerts": [],
        "pfz_zones": [],
        "metadata": {
            "data_source": "open_meteo + imd_live + copernicus",
            "query_timestamp": "",
            "data_timestamp": "",
            "conditions_type": conditions_type,
            "conditions_date": conditions_date,
            "requested_date": date_phrase,
        },
    }
    return {
        "success": True,
        "intent": "assess_sea_safety",
        "location": ocean_weather["location"],
        "date": date_phrase,
        "ocean_weather": ocean_weather,
        "risk_assessment": assess_safety(ocean_weather).to_dict(),
        "agents_invoked": ["ocean_weather", "risk_assessment"],
    }


@pytest.mark.asyncio
async def test_tomorrow_without_a_forecast_says_only_current_conditions_were_checked():
    response = await synthesise_response(_handler_result("tomorrow"), "Is it safe to go to sea near Chennai tomorrow?")
    answer = response["answer_text"]

    assert answer.startswith(NOT_CHECKED_NOTE)
    assert "here's today's data for reference" in answer
    assert "near **Chennai, Tamil Nadu** tomorrow" not in answer
    assert "near **Chennai, Tamil Nadu** today" in answer


@pytest.mark.asyncio
async def test_tomorrow_with_a_matching_forecast_is_labelled_as_a_forecast():
    response = await synthesise_response(
        _handler_result("tomorrow", "forecast", "2026-09-16"), "Is it safe to go to sea near Chennai tomorrow?"
    )
    answer = response["answer_text"]

    assert answer.startswith("📅 **Forecast for tomorrow")
    assert "near **Chennai, Tamil Nadu** tomorrow" in answer
    assert "I can only check current conditions" not in answer


@pytest.mark.asyncio
async def test_a_forecast_for_a_different_day_does_not_count():
    response = await synthesise_response(
        _handler_result("tomorrow", "forecast", "2026-09-17"), "Is it safe to go to sea near Chennai tomorrow?"
    )
    assert response["answer_text"].startswith(NOT_CHECKED_NOTE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("2026-09-10", "I can't look up past conditions for"),
        ("2026-10-10", "only reach 7 days ahead"),
        ("next monday", "couldn't tell which day"),
    ],
    ids=["past-date", "beyond-horizon", "unparseable"],
)
async def test_dates_that_cannot_be_forecast_are_explained(phrase, expected):
    response = await synthesise_response(_handler_result(phrase), f"Is it safe near Chennai {phrase}?")
    answer = response["answer_text"]

    assert answer.startswith("📅")
    assert expected in answer
    assert "here's today's data for reference" in answer


@pytest.mark.asyncio
async def test_today_gets_no_date_notice():
    response = await synthesise_response(_handler_result("today"), "Is it safe to go to sea near Chennai today?")
    assert not response["answer_text"].startswith("📅")


@pytest.mark.asyncio
async def test_caveat_is_applied_even_when_an_llm_writes_the_answer(monkeypatch):
    llm = AsyncMock(return_value="✅ Calm seas — safe to head out tomorrow!")
    monkeypatch.setattr("agents.synthesis._generate_groq_answer", llm)

    response = await synthesise_response(_handler_result("tomorrow"), "Is it safe to go to sea near Chennai tomorrow?")

    assert response["answer_text"].startswith(NOT_CHECKED_NOTE)
    data_summary_sent_to_llm = llm.call_args.args[2]
    assert "IMPORTANT: the user asked about tomorrow" in data_summary_sent_to_llm


@pytest.mark.asyncio
async def test_tamil_tomorrow_caveat():
    response = await synthesise_response(
        _handler_result("tomorrow"), "நாளை சென்னை அருகில் கடலுக்குச் செல்வது பாதுகாப்பானதா?", language="ta"
    )
    first_line = response["answer_text"].splitlines()[0]
    assert "முன்னறிவிப்பை என்னால் இப்போது சரிபார்க்க" in first_line
    assert "நாளை" in first_line


@pytest.mark.asyncio
async def test_evidence_records_requested_and_described_dates():
    response = await synthesise_response(
        _handler_result("tomorrow", "forecast", "2026-09-16"), "Is it safe to go to sea near Chennai tomorrow?"
    )
    evidence = response["evidence"]
    assert evidence["requested_date"] == "tomorrow"
    assert evidence["conditions_type"] == "forecast"
    assert evidence["conditions_date"] == "2026-09-16"


# ══════════════════════════════════════════════
#  The reported reproduction, end to end
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reproduced_case_tomorrow_query_on_demo_data():
    """Demo data used to answer "It appears safe ... tomorrow" from a fixed timestamp."""
    response = await handle_query("Is it safe to go to sea near Chennai tomorrow?")
    answer = response["answer_text"]

    assert answer.startswith(NOT_CHECKED_NOTE)
    assert "near **Chennai, Tamil Nadu** tomorrow" not in answer


@pytest.mark.asyncio
async def test_reproduced_case_tomorrow_query_in_live_mode_uses_the_forecast(monkeypatch):
    """Live mode used to answer a "tomorrow" question with today's current conditions."""
    monkeypatch.setenv("USE_LIVE_DATA", "true")
    calls = []
    with _open_meteo(calls):
        response = await handle_query("Is it safe to go to sea near Chennai tomorrow?")

    assert calls and all(params.get("start_date") == "2026-09-16" for _, params in calls)
    answer = response["answer_text"]
    assert answer.startswith("📅 **Forecast for tomorrow")
    assert "near **Chennai, Tamil Nadu** tomorrow" in answer
    assert response["evidence"]["conditions_type"] == "forecast"
    assert response["evidence"]["risk_assessment"]["thresholds_applied"]["wave_height"]["value"] == 2.6

"""
Integration tests for orchestrator + synthesis (keyword fallback mode).

These tests verify the full pipeline: query → intent detection →
geocoding → handler execution → synthesis, WITHOUT requiring a
Gemini API key (uses keyword-based fallback).
"""

from __future__ import annotations

import json
import os
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure no API key is set so we test the keyword fallback path
os.environ.pop("GEMINI_API_KEY", None)

from agents.orchestrator import (
    handle_query,
    _keyword_intent_detection,
    _extract_location_from_query,
    _extract_date_from_query,
)
from utils.geocoding import geocode


# ══════════════════════════════════════════════
#  Geocoding tests
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_geocode_known_city():
    lat, lon, name = await geocode("Chennai")
    assert abs(lat - 13.08) < 0.5
    assert abs(lon - 80.27) < 0.5
    assert "Chennai" in name


@pytest.mark.asyncio
async def test_geocode_alias():
    """'Vizag' should resolve to Visakhapatnam."""
    lat, lon, name = await geocode("Vizag")
    assert abs(lat - 17.72) < 0.5
    assert "Visakhapatnam" in name


@pytest.mark.asyncio
async def test_geocode_with_prefix():
    """'near Mumbai' should strip the prefix and resolve."""
    lat, lon, name = await geocode("near Mumbai")
    assert abs(lat - 19.08) < 0.5


@pytest.mark.asyncio
async def test_geocode_unknown_raises():
    """Unknown location should raise ValueError (when Nominatim is unreachable)."""
    # Use a nonsense string; if Nominatim is reachable it might still resolve,
    # so we test that either ValueError is raised OR a valid tuple comes back.
    try:
        result = await geocode("xyzzy_no_such_place_999")
        # If Nominatim somehow resolved it, result must still be a valid tuple
        assert isinstance(result, tuple) and len(result) == 3
    except ValueError:
        pass  # Expected when Nominatim can't resolve


# ══════════════════════════════════════════════
#  Keyword intent detection tests
# ══════════════════════════════════════════════


def test_safety_intent():
    result = _keyword_intent_detection("Is it safe to go to sea near Chennai?")
    assert result is not None
    assert result["name"] == "assess_sea_safety"
    assert "chennai" in result["args"]["location"].lower()


def test_pfz_intent():
    result = _keyword_intent_detection("Where is the nearest fishing zone near Mumbai?")
    assert result is not None
    assert result["name"] == "find_nearest_pfz"


def test_alert_intent():
    result = _keyword_intent_detection("Are there any cyclone alerts near Vizag?")
    assert result is not None
    assert result["name"] == "check_alerts"


def test_date_extraction_tomorrow():
    date = _extract_date_from_query("Is it safe to go fishing tomorrow near Chennai?")
    assert date == "tomorrow"


def test_date_extraction_default():
    date = _extract_date_from_query("Is it safe near Mumbai?")
    assert date == "today"


def test_location_extraction():
    loc = _extract_location_from_query("Is it safe to venture into the sea near Chennai?")
    assert loc is not None
    assert "chennai" in loc.lower()


# ══════════════════════════════════════════════
#  Full pipeline tests (keyword fallback)
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_pipeline_safety():
    """Full pipeline for a safety query should return answer + evidence + map."""
    result = await handle_query("Is it safe to venture into the sea near Chennai today?")

    assert "answer_text" in result
    assert "evidence" in result
    assert "map_data" in result

    # Safety query should have a verdict in the answer
    answer = result["answer_text"].lower()
    assert any(word in answer for word in ["safe", "caution", "unsafe"])

    # Evidence should show which agents ran
    evidence = result["evidence"]
    assert "agents_invoked" in evidence
    assert "ocean_weather" in evidence["agents_invoked"]
    assert "risk_assessment" in evidence["agents_invoked"]

    # Map should have at least one marker
    assert result["map_data"] is not None
    assert len(result["map_data"]["markers"]) >= 1


@pytest.mark.asyncio
async def test_full_pipeline_pfz():
    """Full pipeline for a PFZ query should return zones."""
    result = await handle_query("Where is the nearest PFZ near Chennai?")

    assert "answer_text" in result
    assert result["map_data"] is not None
    # Chennai mock has PFZ zones, so map should have PFZ markers
    markers = result["map_data"]["markers"]
    pfz_markers = [m for m in markers if m.get("type") == "pfz"]
    assert len(pfz_markers) >= 1


@pytest.mark.asyncio
async def test_full_pipeline_alerts_vizag():
    """Vizag has active alerts — should report them."""
    result = await handle_query("Are there any cyclone alerts near Visakhapatnam?")

    assert "answer_text" in result
    answer = result["answer_text"].lower()
    assert "alert" in answer or "cyclone" in answer

    evidence = result["evidence"]
    assert "alerts" in evidence or "alerts_summary" in evidence


@pytest.mark.asyncio
async def test_full_pipeline_alerts_chennai():
    """Chennai has no alerts — should say so."""
    result = await handle_query("Any alerts near Chennai?")

    assert "answer_text" in result
    answer = result["answer_text"].lower()
    assert "no" in answer or "none" in answer or "no active" in answer


@pytest.mark.asyncio
async def test_full_pipeline_vizag_safety():
    """Vizag has a cyclone — should be unsafe."""
    result = await handle_query("Is it safe to go fishing near Vizag?")

    answer = result["answer_text"].lower()
    assert "unsafe" in answer or "not safe" in answer
    evidence = result["evidence"]
    risk = evidence.get("risk_assessment", {})
    assert risk.get("verdict") == "unsafe"


@pytest.mark.asyncio
async def test_full_pipeline_no_location():
    """Query with no recognisable location should return a helpful error."""
    result = await handle_query("What's the weather like?")
    assert "answer_text" in result
    # Should contain guidance about how to ask
    answer = result["answer_text"].lower()
    assert "location" in answer or "city" in answer or "couldn't" in answer


@pytest.mark.asyncio
async def test_response_json_serialisable():
    """Full response should be JSON-serialisable."""
    result = await handle_query("Is it safe near Mumbai?")
    json_str = json.dumps(result)
    assert len(json_str) > 100

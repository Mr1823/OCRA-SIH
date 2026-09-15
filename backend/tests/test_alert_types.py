"""
Default-deny alert handling in risk_assessment.py.

Only cyclone / high_wave / lightning used to affect the verdict, so
IMD's weather_warning and port_warning alerts (and anything else, e.g.
tsunami) sat in the evidence panel while the answer said "safe, 0/100".
Any alert type not explicitly recognised as benign must now leave the
verdict at "caution" or worse.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.risk_assessment import WEIGHT_ALERTS, assess_safety
from agents.synthesis import _translate_reason_to_ta
from data_sources.imd_provider import get_imd_marine_data


def _calm_conditions(alerts: list | None = None) -> dict:
    """Wave, wind and visibility all comfortably safe, so only the alerts can change the verdict."""
    return {
        "ocean": {"sst_celsius": 28.0, "chlorophyll_mg_m3": 0.4, "wave_height_m": 0.8, "wave_period_s": 8.0},
        "weather": {
            "wind_speed_kmh": 12.0,
            "wind_direction": "SW",
            "visibility_km": 15.0,
            "air_temperature_celsius": 30.0,
            "humidity_pct": 70,
            "condition": "Clear Sky",
        },
        "alerts": alerts or [],
    }


def _alert(alert_type, title: str = "Test alert") -> dict:
    return {
        "type": alert_type,
        "severity": "warning",
        "title": title,
        "message": "Test message",
        "source": "IMD (api.imd.gov.in)",
    }


def test_calm_conditions_without_alerts_are_safe():
    """Control case: the fixture alone is 'safe', so the tests below isolate the alert's effect."""
    result = assess_safety(_calm_conditions())
    assert result.verdict == "safe"
    assert result.risk_score == 0


def test_weather_warning_alert_is_not_safe():
    result = assess_safety(
        _calm_conditions([_alert("weather_warning", "IMD Coastal Advisory — Maharashtra-Goa coast")])
    )
    assert result.verdict == "caution"
    assert result.risk_score > 0
    assert "🌩️ WEATHER WARNING: IMD Coastal Advisory — Maharashtra-Goa coast" in result.reasons
    assert result.thresholds_applied["alerts"]["status"] == "caution"


def test_port_warning_alert_is_not_safe():
    result = assess_safety(
        _calm_conditions([_alert("port_warning", "IMD Port Warning — North Andhra coast")])
    )
    assert result.verdict == "caution"
    assert result.risk_score > 0
    assert "⚓ PORT WARNING: IMD Port Warning — North Andhra coast" in result.reasons


def test_tsunami_is_treated_at_least_as_severely_as_cyclone():
    tsunami = assess_safety(_calm_conditions([_alert("tsunami", "Tsunami Warning")]))
    cyclone = assess_safety(_calm_conditions([_alert("cyclone", "Cyclone Warning")]))
    assert tsunami.verdict == "unsafe"
    assert tsunami.risk_score >= cyclone.risk_score
    assert "🌊 TSUNAMI ALERT: Tsunami Warning" in tsunami.reasons


@pytest.mark.parametrize(
    "alert",
    [
        _alert("storm_surge", "Storm surge expected"),
        {"title": "Alert with no type field"},
        _alert(None, "Alert with a null type"),
        _alert("", "Alert with an empty type"),
    ],
    ids=["unknown-type", "missing-type", "null-type", "empty-type"],
)
def test_unrecognised_or_missing_alert_type_defaults_to_caution(alert):
    result = assess_safety(_calm_conditions([alert]))
    assert result.verdict == "caution"
    assert result.risk_score > 0
    assert any(r.startswith("⚠️ UNRECOGNISED ALERT") for r in result.reasons)
    assert result.thresholds_applied["alerts"]["unrecognised_types"]


def test_alert_type_matching_is_case_insensitive():
    result = assess_safety(_calm_conditions([_alert("Cyclone", "Cyclone Z")]))
    assert result.verdict == "unsafe"
    assert "🌀 CYCLONE ALERT: Cyclone Z" in result.reasons


def test_lesser_alerts_do_not_dilute_an_unsafe_alert():
    result = assess_safety(
        _calm_conditions([_alert("storm_surge"), _alert("lightning"), _alert("cyclone", "Cyclone Z")])
    )
    assert result.verdict == "unsafe"
    assert result.risk_score == WEIGHT_ALERTS
    alert_lines = [r for r in result.reasons if "ALERT" in r]
    assert alert_lines[0] == "🌀 CYCLONE ALERT: Cyclone Z"  # most severe listed first


def test_existing_alert_reason_strings_still_match_the_tamil_translator():
    for alert_type in ("cyclone", "high_wave", "lightning"):
        result = assess_safety(_calm_conditions([_alert(alert_type)]))
        reason = next(r for r in result.reasons if "ALERT" in r)
        assert _translate_reason_to_ta(reason) != reason


@pytest.mark.asyncio
async def test_every_alert_type_the_imd_provider_emits_is_explicitly_handled(monkeypatch):
    from agents.risk_assessment import ALERT_RULES

    monkeypatch.setattr(config, "IMD_API_KEY", "")  # baseline bulletins, no network
    emitted = set()
    for lat, lon, name in [
        (17.72, 83.30, "Visakhapatnam, Andhra Pradesh"),
        (19.08, 72.88, "Mumbai, Maharashtra"),
        (13.08, 80.27, "Chennai, Tamil Nadu"),
    ]:
        emitted |= {a["type"] for a in (await get_imd_marine_data(lat, lon, name))["alerts"]}

    assert emitted == {"cyclone", "port_warning", "weather_warning"}
    # high_wave is emitted when a bulletin's TTT warning mentions waves.
    assert emitted | {"high_wave"} <= set(ALERT_RULES)


@pytest.mark.asyncio
async def test_imd_baseline_mumbai_advisory_no_longer_reads_safe(monkeypatch):
    """The reproduced bug: Mumbai's IMD thunderstorm advisory came through as 'safe, 0/100'."""
    monkeypatch.setattr(config, "IMD_API_KEY", "")
    imd = await get_imd_marine_data(19.08, 72.88, "Mumbai, Maharashtra")
    assert [a["type"] for a in imd["alerts"]] == ["weather_warning"]

    result = assess_safety(_calm_conditions(imd["alerts"]))
    assert result.verdict == "caution"
    assert result.risk_score > 0

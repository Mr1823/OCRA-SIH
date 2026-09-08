"""
Risk Assessment Agent — applies simple threshold rules to ocean/weather
data and produces a safety verdict with reasons.

Thresholds (from implementation plan):
  Wave height:  < 2.0 m safe │ 2.0–3.5 m caution │ > 3.5 m unsafe
  Wind speed:   < 35 km/h safe │ 35–50 km/h caution │ > 50 km/h unsafe
  Visibility:   > 5 km safe │ 2–5 km caution │ < 2 km unsafe
  Active cyclone alert → instant unsafe
  Active high-wave warning → escalate one level
  Active lightning watch → caution at minimum
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ──────────────────────────────────────────────
#  Threshold constants
# ──────────────────────────────────────────────

WAVE_SAFE = 2.0  # metres
WAVE_CAUTION = 3.5

WIND_SAFE = 35.0  # km/h
WIND_CAUTION = 50.0

VIS_SAFE = 5.0  # km
VIS_CAUTION = 2.0

# Risk score weights (sum = 100 max when all unsafe)
WEIGHT_WAVE = 30
WEIGHT_WIND = 25
WEIGHT_VIS = 15
WEIGHT_ALERTS = 30


# ──────────────────────────────────────────────
#  Result container
# ──────────────────────────────────────────────

@dataclass
class RiskResult:
    verdict: str  # "safe" | "caution" | "unsafe"
    risk_score: int  # 0-100
    reasons: list[str] = field(default_factory=list)
    thresholds_applied: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "risk_score": self.risk_score,
            "reasons": self.reasons,
            "thresholds_applied": self.thresholds_applied,
        }


# ──────────────────────────────────────────────
#  Assessment logic
# ──────────────────────────────────────────────

def assess_safety(ocean_weather_data: dict) -> RiskResult:
    """
    Evaluate sea-venture safety from ocean/weather data.

    Parameters
    ----------
    ocean_weather_data : dict
        Output from ``ocean_weather.get_ocean_weather_data()`` — must
        contain ``ocean``, ``weather``, and ``alerts`` keys.

    Returns
    -------
    RiskResult with verdict, risk_score (0-100), reasons, and thresholds.
    """
    ocean = ocean_weather_data["ocean"]
    weather = ocean_weather_data["weather"]
    alerts = ocean_weather_data.get("alerts", [])

    reasons: list[str] = []
    score = 0  # accumulates towards 100 = maximum danger

    # ── Wave height ──
    wave = ocean["wave_height_m"]
    wave_status = "safe"
    if wave > WAVE_CAUTION:
        wave_status = "unsafe"
        score += WEIGHT_WAVE
        reasons.append(
            f"Wave height {wave:.1f} m exceeds unsafe threshold ({WAVE_CAUTION} m)"
        )
    elif wave > WAVE_SAFE:
        wave_status = "caution"
        score += WEIGHT_WAVE * 0.5
        reasons.append(
            f"Wave height {wave:.1f} m is in the caution range "
            f"({WAVE_SAFE}–{WAVE_CAUTION} m)"
        )
    else:
        reasons.append(f"Wave height {wave:.1f} m is within safe limits (< {WAVE_SAFE} m)")

    # ── Wind speed ──
    wind = weather["wind_speed_kmh"]
    wind_status = "safe"
    if wind > WIND_CAUTION:
        wind_status = "unsafe"
        score += WEIGHT_WIND
        reasons.append(
            f"Wind speed {wind:.0f} km/h exceeds unsafe threshold ({WIND_CAUTION} km/h)"
        )
    elif wind > WIND_SAFE:
        wind_status = "caution"
        score += WEIGHT_WIND * 0.5
        reasons.append(
            f"Wind speed {wind:.0f} km/h is in the caution range "
            f"({WIND_SAFE}–{WIND_CAUTION} km/h)"
        )
    else:
        reasons.append(
            f"Wind speed {wind:.0f} km/h is within safe limits (< {WIND_SAFE} km/h)"
        )

    # ── Visibility ──
    vis = weather["visibility_km"]
    vis_status = "safe"
    if vis < VIS_CAUTION:
        vis_status = "unsafe"
        score += WEIGHT_VIS
        reasons.append(
            f"Visibility {vis:.1f} km is below unsafe threshold ({VIS_CAUTION} km)"
        )
    elif vis < VIS_SAFE:
        vis_status = "caution"
        score += WEIGHT_VIS * 0.5
        reasons.append(
            f"Visibility {vis:.1f} km is in the caution range "
            f"({VIS_CAUTION}–{VIS_SAFE} km)"
        )
    else:
        reasons.append(
            f"Visibility {vis:.1f} km is good (> {VIS_SAFE} km)"
        )

    # ── Alerts ──
    alert_status = "safe"
    alert_types = {a.get("type", "").lower() for a in alerts}

    if "cyclone" in alert_types:
        alert_status = "unsafe"
        score += WEIGHT_ALERTS
        cyclone_alerts = [a for a in alerts if a.get("type") == "cyclone"]
        for ca in cyclone_alerts:
            reasons.append(f"🌀 CYCLONE ALERT: {ca.get('title', 'Active cyclone warning')}")

    if "high_wave" in alert_types:
        if alert_status != "unsafe":
            alert_status = "caution"
            score += WEIGHT_ALERTS * 0.5
        hw_alerts = [a for a in alerts if a.get("type") == "high_wave"]
        for hw in hw_alerts:
            reasons.append(f"🌊 HIGH WAVE ALERT: {hw.get('title', 'High wave warning')}")

    if "lightning" in alert_types:
        if alert_status == "safe":
            alert_status = "caution"
            score += WEIGHT_ALERTS * 0.3
        lightning_alerts = [a for a in alerts if a.get("type") == "lightning"]
        for la in lightning_alerts:
            reasons.append(f"⚡ LIGHTNING ALERT: {la.get('title', 'Lightning activity')}")

    if alert_status == "safe" and not alerts:
        reasons.append("No active weather or marine alerts")

    # ── Overall verdict ──
    statuses = [wave_status, wind_status, vis_status, alert_status]
    if "unsafe" in statuses:
        verdict = "unsafe"
    elif "caution" in statuses:
        verdict = "caution"
    else:
        verdict = "safe"

    score = min(int(score), 100)

    thresholds = {
        "wave_height": {
            "value": wave,
            "unit": "m",
            "safe_below": WAVE_SAFE,
            "caution_below": WAVE_CAUTION,
            "status": wave_status,
        },
        "wind_speed": {
            "value": wind,
            "unit": "km/h",
            "safe_below": WIND_SAFE,
            "caution_below": WIND_CAUTION,
            "status": wind_status,
        },
        "visibility": {
            "value": vis,
            "unit": "km",
            "safe_above": VIS_SAFE,
            "caution_above": VIS_CAUTION,
            "status": vis_status,
        },
        "alerts": {
            "active_count": len(alerts),
            "types": list(alert_types) if alert_types else [],
            "status": alert_status,
        },
    }

    return RiskResult(
        verdict=verdict,
        risk_score=score,
        reasons=reasons,
        thresholds_applied=thresholds,
    )


"""
Risk Assessment Agent — applies simple threshold rules to ocean/weather
data and produces a safety verdict with reasons.

Thresholds (from implementation plan):
  Wave height:  < 2.0 m safe │ 2.0–3.5 m caution │ > 3.5 m unsafe
  Wind speed:   < 35 km/h safe │ 35–50 km/h caution │ > 50 km/h unsafe
  Visibility:   > 5 km safe │ 2–5 km caution │ < 2 km unsafe

Alerts are default-deny (see ALERT_RULES):
  cyclone, tsunami                                     → unsafe
  high_wave, weather_warning, port_warning, lightning  → caution at minimum
  any other type, or a missing type                    → caution, never ignored

A reading the data source couldn't provide (data_sources.interface.
DATA_UNAVAILABLE) is reported as unavailable and forces at least
"caution" — missing data is never assumed to be calm.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from data_sources.interface import is_unavailable

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
#  Alert rules (default-deny)
# ──────────────────────────────────────────────

# alert type → (minimum status it forces, score weight as a fraction of
# WEIGHT_ALERTS, reason label, default title). The cyclone / high_wave /
# lightning labels must stay exactly as they are: synthesis.py's Tamil
# reason translator pattern-matches them.
ALERT_RULES: dict[str, tuple[str, float, str, str]] = {
    "cyclone": ("unsafe", 1.0, "🌀 CYCLONE ALERT", "Active cyclone warning"),
    "tsunami": ("unsafe", 1.0, "🌊 TSUNAMI ALERT", "Active tsunami warning"),
    "high_wave": ("caution", 0.5, "🌊 HIGH WAVE ALERT", "High wave warning"),
    "weather_warning": ("caution", 0.5, "🌩️ WEATHER WARNING", "Weather warning"),
    "port_warning": ("caution", 0.5, "⚓ PORT WARNING", "Port warning signal"),
    "lightning": ("caution", 0.3, "⚡ LIGHTNING ALERT", "Lightning activity"),
}

# Alert types known to carry no risk. Deliberately empty: no provider
# emits an informational alert type today. Anything in neither this set
# nor ALERT_RULES — a new IMD category, a typo, a missing "type" — is
# treated as caution, so an unrecognised warning can never read as "safe".
BENIGN_ALERT_TYPES: frozenset[str] = frozenset()
UNRECOGNISED_ALERT_WEIGHT = 0.5

_STATUS_RANK = {"safe": 0, "caution": 1, "unsafe": 2}


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
    wave = ocean.get("wave_height_m")
    wave_status = "safe"
    if is_unavailable(wave):
        wave_status = "unavailable"
        reasons.append("Wave height data unavailable for this location — sea state could not be checked")
    elif wave > WAVE_CAUTION:
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
    wind = weather.get("wind_speed_kmh")
    wind_status = "safe"
    if is_unavailable(wind):
        wind_status = "unavailable"
        reasons.append("Wind speed data unavailable for this location — wind could not be checked")
    elif wind > WIND_CAUTION:
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
    vis = weather.get("visibility_km")
    vis_status = "safe"
    if is_unavailable(vis):
        vis_status = "unavailable"
        reasons.append("Visibility data unavailable for this location — visibility could not be checked")
    elif vis < VIS_CAUTION:
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

    # ── Alerts (default-deny — see ALERT_RULES) ──
    alert_status = "safe"
    alert_weight = 0.0
    alert_types: set[str] = set()
    unrecognised_types: list[str] = []
    alert_reasons: list[tuple[int, float, str]] = []

    for alert in alerts:
        alert_type = str(alert.get("type") or "").strip().lower()
        alert_types.add(alert_type)
        if alert_type in BENIGN_ALERT_TYPES:
            continue

        rule = ALERT_RULES.get(alert_type)
        if rule is None:
            unrecognised_types.append(alert_type or "(missing type)")
            status, weight = "caution", UNRECOGNISED_ALERT_WEIGHT
            reason = (
                f"⚠️ UNRECOGNISED ALERT ({alert_type or 'no type'}): "
                f"{alert.get('title') or 'Untitled alert'} — treated as caution until reviewed"
            )
        else:
            status, weight, label, default_title = rule
            reason = f"{label}: {alert.get('title') or default_title}"

        if _STATUS_RANK[status] > _STATUS_RANK[alert_status]:
            alert_status = status
        alert_weight = max(alert_weight, weight)
        alert_reasons.append((_STATUS_RANK[status], weight, reason))

    # Most severe first, so a cyclone/tsunami line always leads.
    for _, _, reason in sorted(alert_reasons, key=lambda r: (-r[0], -r[1])):
        reasons.append(reason)
    score += WEIGHT_ALERTS * alert_weight

    if not alerts:
        reasons.append("No active weather or marine alerts")

    # ── Overall verdict ──
    statuses = [wave_status, wind_status, vis_status, alert_status]
    if "unsafe" in statuses:
        verdict = "unsafe"
    elif "caution" in statuses or "unavailable" in statuses:
        # Missing core data can't be assumed calm.
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
            "types": sorted(alert_types),
            "unrecognised_types": unrecognised_types,
            "status": alert_status,
        },
    }

    return RiskResult(
        verdict=verdict,
        risk_score=score,
        reasons=reasons,
        thresholds_applied=thresholds,
    )


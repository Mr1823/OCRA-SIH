"""
PFZ (Potential Fishing Zone) Agent — applies SST/chlorophyll threshold
logic to identify and rank nearby fishing zones.

PFZ criteria (simplified for prototype):
  SST:          24–30 °C  → suitable temperature range
  Chlorophyll:  > 0.3 mg/m³ → productive (high primary productivity)
  Confidence boosted if both criteria met strongly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ──────────────────────────────────────────────
#  Threshold constants
# ──────────────────────────────────────────────

SST_MIN = 24.0  # °C — too cold below this
SST_MAX = 30.0  # °C — too warm above this
SST_OPTIMAL_MIN = 26.0
SST_OPTIMAL_MAX = 29.0

CHLOROPHYLL_MIN = 0.3  # mg/m³ — minimum for productive zone
CHLOROPHYLL_GOOD = 0.5  # mg/m³ — strong productivity


# ──────────────────────────────────────────────
#  Result container
# ──────────────────────────────────────────────

@dataclass
class PFZResult:
    zones_found: int
    zones: list[dict] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "zones_found": self.zones_found,
            "zones": self.zones,
            "analysis": self.analysis,
            "recommendation": self.recommendation,
        }


# ──────────────────────────────────────────────
#  PFZ evaluation logic
# ──────────────────────────────────────────────

def _evaluate_zone(zone: dict) -> dict:
    """
    Score a single PFZ zone dict (from MarineConditions.pfz_zones)
    against SST/chlorophyll thresholds.

    Returns an enriched copy with ``suitability``, ``score``, and
    ``reasons`` added.
    """
    sst = zone.get("sst", 0.0)
    chl = zone.get("chlorophyll", 0.0)
    reasons: list[str] = []
    score = 0.0  # 0–1

    # ── SST evaluation ──
    if SST_OPTIMAL_MIN <= sst <= SST_OPTIMAL_MAX:
        score += 0.4
        reasons.append(f"SST {sst:.1f} °C is in the optimal range ({SST_OPTIMAL_MIN}–{SST_OPTIMAL_MAX} °C)")
    elif SST_MIN <= sst <= SST_MAX:
        score += 0.2
        reasons.append(f"SST {sst:.1f} °C is within acceptable range ({SST_MIN}–{SST_MAX} °C)")
    else:
        reasons.append(f"SST {sst:.1f} °C is outside the suitable range ({SST_MIN}–{SST_MAX} °C)")

    # ── Chlorophyll evaluation ──
    if chl >= CHLOROPHYLL_GOOD:
        score += 0.4
        reasons.append(
            f"Chlorophyll {chl:.2f} mg/m³ indicates strong productivity (≥ {CHLOROPHYLL_GOOD})"
        )
    elif chl >= CHLOROPHYLL_MIN:
        score += 0.2
        reasons.append(
            f"Chlorophyll {chl:.2f} mg/m³ indicates moderate productivity (≥ {CHLOROPHYLL_MIN})"
        )
    else:
        reasons.append(
            f"Chlorophyll {chl:.2f} mg/m³ is below productive threshold ({CHLOROPHYLL_MIN})"
        )

    # ── Confidence from original data ──
    original_confidence = zone.get("confidence", "medium")
    conf_bonus = {"high": 0.2, "medium": 0.1, "low": 0.0}
    score += conf_bonus.get(original_confidence, 0.0)

    score = min(round(score, 2), 1.0)

    if score >= 0.7:
        suitability = "excellent"
    elif score >= 0.4:
        suitability = "good"
    elif score >= 0.2:
        suitability = "fair"
    else:
        suitability = "poor"

    enriched = {
        **zone,
        "suitability": suitability,
        "score": score,
        "reasons": reasons,
    }
    return enriched


def find_nearby_pfz(ocean_weather_data: dict) -> PFZResult:
    """
    Analyse PFZ zones from ocean/weather data and rank them by suitability.

    Parameters
    ----------
    ocean_weather_data : dict
        Output from ``ocean_weather.get_ocean_weather_data()``.

    Returns
    -------
    PFZResult with ranked zones, overall analysis, and a recommendation.
    """
    raw_zones = ocean_weather_data.get("pfz_zones", [])
    ocean = ocean_weather_data.get("ocean", {})

    # Current conditions at the query location
    current_sst = ocean.get("sst_celsius", 0.0)
    current_chl = ocean.get("chlorophyll_mg_m3", 0.0)

    # Evaluate and rank each zone
    evaluated = [_evaluate_zone(z) for z in raw_zones]
    evaluated.sort(key=lambda z: z["score"], reverse=True)

    # Filter out poor zones for recommendations
    viable = [z for z in evaluated if z["score"] >= 0.2]

    # Overall analysis of current conditions at query point
    analysis = {
        "current_location_sst": current_sst,
        "current_location_chlorophyll": current_chl,
        "sst_range_suitable": f"{SST_MIN}–{SST_MAX} °C",
        "sst_range_optimal": f"{SST_OPTIMAL_MIN}–{SST_OPTIMAL_MAX} °C",
        "chlorophyll_threshold": f"≥ {CHLOROPHYLL_MIN} mg/m³",
        "chlorophyll_good": f"≥ {CHLOROPHYLL_GOOD} mg/m³",
        "total_zones_checked": len(raw_zones),
        "viable_zones": len(viable),
    }

    # Build recommendation text
    if not viable:
        recommendation = (
            "No suitable Potential Fishing Zones were identified near your location. "
            "Current ocean conditions may not support high fish aggregation in this area."
        )
    elif len(viable) == 1:
        best = viable[0]
        recommendation = (
            f"One Potential Fishing Zone found: {best.get('id', 'PFZ')} is "
            f"{best['distance_km']:.0f} km away with {best['suitability']} suitability "
            f"(score: {best['score']:.0%}). "
            f"Likely species: {', '.join(best.get('species_likely', ['various']))}."
        )
    else:
        best = viable[0]
        recommendation = (
            f"{len(viable)} Potential Fishing Zones found. "
            f"Best option: {best.get('id', 'PFZ')} at {best['distance_km']:.0f} km "
            f"with {best['suitability']} suitability (score: {best['score']:.0%}). "
            f"Likely species: {', '.join(best.get('species_likely', ['various']))}."
        )

    return PFZResult(
        zones_found=len(viable),
        zones=evaluated,
        analysis=analysis,
        recommendation=recommendation,
    )


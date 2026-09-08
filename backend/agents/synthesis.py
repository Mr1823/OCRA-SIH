"""
Synthesis Agent — combines handler outputs into a final response with:
  1. answer_text  — natural-language summary (LLM-generated or template)
  2. evidence     — structured data for the "why this answer" panel
  3. map_data     — markers/center/zoom for the Leaflet map

Uses Gemini for natural-language generation if available, otherwise
falls back to clean template-based responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import config

logger = logging.getLogger("orca.synthesis")


# ──────────────────────────────────────────────
#  Map data construction
# ──────────────────────────────────────────────


def _build_map_data(handler_result: dict) -> dict:
    """Build map markers and viewport from handler results."""
    intent = handler_result["intent"]
    loc = handler_result["location"]
    center = [loc["lat"], loc["lon"]]
    markers = []

    # User's query location marker
    markers.append({
        "lat": loc["lat"],
        "lon": loc["lon"],
        "label": loc["name"],
        "type": "location",
        "color": "blue",
        "popup": f"📍 {loc['name']}",
    })

    if intent == "assess_sea_safety":
        risk = handler_result.get("risk_assessment", {})
        verdict = risk.get("verdict", "safe")
        color_map = {"safe": "green", "caution": "orange", "unsafe": "red"}
        emoji_map = {"safe": "✅", "caution": "⚠️", "unsafe": "🚫"}
        markers[0]["color"] = color_map.get(verdict, "blue")
        markers[0]["popup"] = (
            f"{emoji_map.get(verdict, '')} {loc['name']}: {verdict.upper()}\n"
            f"Risk score: {risk.get('risk_score', 'N/A')}/100"
        )

    elif intent == "find_nearest_pfz":
        pfz = handler_result.get("pfz_result", {})
        for zone in pfz.get("zones", []):
            if zone.get("score", 0) >= 0.2:  # Only viable zones
                markers.append({
                    "lat": zone["lat"],
                    "lon": zone["lon"],
                    "label": zone.get("id", "PFZ"),
                    "type": "pfz",
                    "color": "green" if zone.get("suitability") == "excellent" else "cyan",
                    "popup": (
                        f"🐟 {zone.get('id', 'PFZ')}\n"
                        f"Distance: {zone.get('distance_km', '?')} km\n"
                        f"Suitability: {zone.get('suitability', '?')}\n"
                        f"Species: {', '.join(zone.get('species_likely', []))}"
                    ),
                })

    elif intent == "check_alerts":
        alerts = handler_result.get("alerts_summary", {})
        for alert in alerts.get("active_alerts", []):
            markers[0]["color"] = "red"
            markers[0]["popup"] = (
                f"⚠️ {alert.get('title', 'Alert')}\n"
                f"Type: {alert.get('type', '?')}\n"
                f"Severity: {alert.get('severity', '?')}"
            )

    return {
        "center": center,
        "zoom": 9,
        "markers": markers,
    }


# ──────────────────────────────────────────────
#  Evidence construction
# ──────────────────────────────────────────────


def _build_evidence(handler_result: dict) -> dict:
    """Build the structured evidence object for the frontend panel."""
    intent = handler_result["intent"]
    ow = handler_result.get("ocean_weather", {})
    metadata = ow.get("metadata", {})

    evidence = {
        "intent": intent,
        "agents_invoked": handler_result.get("agents_invoked", []),
        "data_source": metadata.get("data_source", "unknown"),
        "data_timestamp": metadata.get("data_timestamp", ""),
        "query_timestamp": metadata.get("query_timestamp", ""),
        "location": handler_result.get("location", {}),
        "conditions_summary": {
            "ocean": ow.get("ocean", {}),
            "weather": ow.get("weather", {}),
            "tide": ow.get("tide", {}),
        },
    }

    if intent == "assess_sea_safety":
        risk = handler_result.get("risk_assessment", {})
        evidence["risk_assessment"] = {
            "verdict": risk.get("verdict"),
            "risk_score": risk.get("risk_score"),
            "thresholds_applied": risk.get("thresholds_applied", {}),
        }

    elif intent == "find_nearest_pfz":
        pfz = handler_result.get("pfz_result", {})
        evidence["pfz_analysis"] = pfz.get("analysis", {})

    elif intent == "check_alerts":
        evidence["alerts"] = handler_result.get("alerts_summary", {})

    return evidence


# ──────────────────────────────────────────────
#  Template-based answer generation (fallback)
# ──────────────────────────────────────────────


def _template_safety_answer(handler_result: dict) -> str:
    """Generate a safety answer from templates."""
    risk = handler_result.get("risk_assessment", {})
    loc = handler_result["location"]["name"]
    verdict = risk.get("verdict", "unknown")
    score = risk.get("risk_score", 0)
    reasons = risk.get("reasons", [])
    date = handler_result.get("date", "today")

    verdict_text = {
        "safe": f"✅ **It appears safe** to venture into the sea near **{loc}** {date}.",
        "caution": f"⚠️ **Exercise caution** if venturing into the sea near **{loc}** {date}.",
        "unsafe": f"🚫 **It is NOT safe** to venture into the sea near **{loc}** {date}.",
    }

    lines = [verdict_text.get(verdict, f"Sea conditions near {loc} are {verdict}.")]
    lines.append(f"\n**Risk Score:** {score}/100\n")
    lines.append("**Key factors:**")
    for r in reasons:
        lines.append(f"- {r}")

    # Add alert details if present
    ow = handler_result.get("ocean_weather", {})
    alerts = ow.get("alerts", [])
    if alerts:
        lines.append("\n**Active Alerts:**")
        for a in alerts:
            lines.append(f"- **{a.get('title', 'Alert')}** ({a.get('source', '')}): {a.get('message', '')}")

    return "\n".join(lines)


def _template_pfz_answer(handler_result: dict) -> str:
    """Generate a PFZ answer from templates."""
    pfz = handler_result.get("pfz_result", {})
    loc = handler_result["location"]["name"]
    zones = pfz.get("zones", [])
    viable = [z for z in zones if z.get("score", 0) >= 0.2]

    if not viable:
        return (
            f"🐟 **No suitable Potential Fishing Zones** were found near **{loc}** at this time.\n\n"
            f"Current ocean conditions may not support high fish aggregation in this area. "
            f"Check back later or try a different location."
        )

    lines = [f"🐟 **{len(viable)} Potential Fishing Zone(s)** found near **{loc}**:\n"]

    for i, z in enumerate(viable, 1):
        lines.append(
            f"**{i}. {z.get('id', 'PFZ')}** — {z['distance_km']:.0f} km away\n"
            f"   - Suitability: **{z.get('suitability', '?')}** (score: {z.get('score', 0):.0%})\n"
            f"   - SST: {z.get('sst', '?')} °C | Chlorophyll: {z.get('chlorophyll', '?')} mg/m³\n"
            f"   - Likely species: {', '.join(z.get('species_likely', ['various']))}"
        )

    # Add analysis context
    analysis = pfz.get("analysis", {})
    lines.append(
        f"\n**Current conditions at {loc}:** "
        f"SST {analysis.get('current_location_sst', '?')} °C, "
        f"Chlorophyll {analysis.get('current_location_chlorophyll', '?')} mg/m³"
    )
    lines.append(f"*Suitable SST range: {analysis.get('sst_range_optimal', '26–29 °C')}*")

    return "\n".join(lines)


def _template_alerts_answer(handler_result: dict) -> str:
    """Generate an alerts answer from templates."""
    alerts_summary = handler_result.get("alerts_summary", {})
    loc = handler_result["location"]["name"]
    alerts = alerts_summary.get("active_alerts", [])
    count = len(alerts)

    if count == 0:
        return (
            f"✅ **No active alerts** near **{loc}** at this time.\n\n"
            f"No cyclone, lightning, or high-wave warnings are currently in effect. "
            f"Conditions appear normal."
        )

    severity_emoji = {"alert": "🔴", "warning": "🟠", "watch": "🟡"}
    type_emoji = {"cyclone": "🌀", "lightning": "⚡", "high_wave": "🌊"}

    lines = [f"⚠️ **{count} active alert(s)** near **{loc}**:\n"]

    for a in alerts:
        emoji = type_emoji.get(a.get("type", ""), "⚠️")
        sev_emoji = severity_emoji.get(a.get("severity", ""), "⚠️")
        lines.append(
            f"{sev_emoji} {emoji} **{a.get('title', 'Alert')}**\n"
            f"   - Severity: {a.get('severity', '?').upper()}\n"
            f"   - Source: {a.get('source', '?')}\n"
            f"   - {a.get('message', 'No details available.')}\n"
            f"   - Valid until: {a.get('valid_until', '?')}"
        )

    if alerts_summary.get("has_critical"):
        lines.append(
            "\n🚨 **CRITICAL: Active cyclone alert — DO NOT venture into the sea.**"
        )

    return "\n".join(lines)


def _generate_template_answer(handler_result: dict) -> str:
    """Route to the correct template based on intent."""
    intent = handler_result["intent"]
    if intent == "assess_sea_safety":
        return _template_safety_answer(handler_result)
    elif intent == "find_nearest_pfz":
        return _template_pfz_answer(handler_result)
    elif intent == "check_alerts":
        return _template_alerts_answer(handler_result)
    return "I processed your query but couldn't generate a formatted response."


# ──────────────────────────────────────────────
#  LLM-based answer generation (if Gemini available)
# ──────────────────────────────────────────────


async def _generate_llm_answer(handler_result: dict, user_query: str) -> str | None:
    """
    Use Gemini to generate a natural, conversational answer from the
    structured handler results.  Returns None on failure.
    """
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_gemini_api_key_here":
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        return None

    genai.configure(api_key=config.GEMINI_API_KEY)

    # Prepare a concise data summary for the LLM
    intent = handler_result["intent"]
    loc = handler_result["location"]["name"]
    ow = handler_result.get("ocean_weather", {})
    ocean = ow.get("ocean", {})
    weather = ow.get("weather", {})

    data_summary = (
        f"Location: {loc}\n"
        f"SST: {ocean.get('sst_celsius', '?')} °C\n"
        f"Chlorophyll: {ocean.get('chlorophyll_mg_m3', '?')} mg/m³\n"
        f"Wave height: {ocean.get('wave_height_m', '?')} m\n"
        f"Wind: {weather.get('wind_speed_kmh', '?')} km/h {weather.get('wind_direction', '')}\n"
        f"Visibility: {weather.get('visibility_km', '?')} km\n"
        f"Condition: {weather.get('condition', '?')}\n"
    )

    if intent == "assess_sea_safety":
        risk = handler_result.get("risk_assessment", {})
        data_summary += (
            f"\nSafety verdict: {risk.get('verdict', '?')}\n"
            f"Risk score: {risk.get('risk_score', '?')}/100\n"
            f"Reasons: {'; '.join(risk.get('reasons', []))}\n"
        )
    elif intent == "find_nearest_pfz":
        pfz = handler_result.get("pfz_result", {})
        data_summary += f"\nPFZ recommendation: {pfz.get('recommendation', '?')}\n"
    elif intent == "check_alerts":
        alerts = handler_result.get("alerts_summary", {})
        alert_list = alerts.get("active_alerts", [])
        if alert_list:
            data_summary += "\nActive alerts:\n"
            for a in alert_list:
                data_summary += f"- {a.get('title', 'Alert')}: {a.get('message', '')}\n"
        else:
            data_summary += "\nNo active alerts.\n"

    prompt = (
        f"You are ORCA, a marine intelligence assistant for Indian fishermen and "
        f"coastal users. A user asked: \"{user_query}\"\n\n"
        f"Based on this data:\n{data_summary}\n"
        f"Write a helpful, concise answer (3-5 sentences). Use markdown formatting. "
        f"Include relevant emoji. Be specific with numbers. "
        f"If unsafe, be clear and firm. If safe, be encouraging but remind about general precautions."
    )

    try:
        model = genai.GenerativeModel(config.GEMINI_MODEL)
        response = model.generate_content(prompt)
        if response.text:
            return response.text.strip()
    except Exception as e:
        logger.warning(f"LLM answer generation failed: {e}")

    return None


# ──────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────


async def synthesise_response(handler_result: dict, user_query: str) -> dict:
    """
    Combine handler outputs into the final API response.

    Returns:
        {
            "answer_text": str,
            "evidence": dict,
            "map_data": dict
        }
    """
    # Build evidence and map data (always deterministic)
    evidence = _build_evidence(handler_result)
    map_data = _build_map_data(handler_result)

    # Generate answer text — try LLM first, fall back to templates
    answer_text = await _generate_llm_answer(handler_result, user_query)
    if answer_text is None:
        answer_text = _generate_template_answer(handler_result)

    return {
        "answer_text": answer_text,
        "evidence": evidence,
        "map_data": map_data,
    }

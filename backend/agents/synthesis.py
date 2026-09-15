"""
Synthesis Agent — combines handler outputs into a final response with:
  1. answer_text  — natural-language summary (LLM-generated or template)
  2. evidence     — structured data for the "why this answer" panel
  3. map_data     — markers/center/zoom for the Leaflet map

Tries LLM providers in priority order for natural-language generation
(Groq → Claude), otherwise falls back to clean template-based responses.

Supports language="en" | "ta" (Tamil) throughout — see the
PENDING HUMAN REVIEW block below for the Tamil strings that carry
actual safety meaning and have not been checked by a native speaker.

CRITICAL: alert data can come from data_sources/imd_provider.py's
"imd_baseline" fallback (fictional example alerts like "Cyclone DANA",
used whenever IMD isn't configured or doesn't answer) or the mock
provider's fixture data — not a real live feed. _has_synthetic_alert_data()
and the qualifiers appended in synthesise_response() exist so that neither
a fabricated cyclone NOR a fabricated all-clear (an empty baseline alert
list) is presented with the same confidence as real IMD data. Do not
remove that check without replacing it with something equivalent.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import config
from data_sources.interface import is_unavailable
from utils.dates import MAX_FORECAST_DAYS, describe_date, is_forecastable, resolve_requested_date, today_ist

logger = logging.getLogger("orca.synthesis")


def _reading(value, unit: str, unavailable_text: str = "unavailable") -> str:
    """A reading with its unit for display — or the word for "unavailable", never "None"."""
    return unavailable_text if is_unavailable(value) else f"{value} {unit}"


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
        verdict = handler_result.get("risk_assessment", {}).get("verdict")
        if verdict in ("caution", "unsafe"):
            markers[0]["color"] = "orange" if verdict == "caution" else "red"
            markers[0]["popup"] = f"⚠️ {loc['name']}: safety {verdict.upper()} — check before heading out"
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


def _has_synthetic_alert_data(handler_result: dict) -> bool:
    """
    True unless the alert data behind this response came from a genuinely
    live IMD feed ("imd_live" in data_source).

    Decided by provenance, never by whether any alerts were found: an
    empty list from IMD's "imd_baseline" fallback (no IMD_API_KEY, or IMD
    unreachable) or from the mock provider means "we have no real alert
    data", not "there are no alerts". Default-deny — a missing or
    unrecognised source counts as synthetic too. A fabricated cyclone, or
    a fabricated all-clear, must never reach a fisherman with the same
    confidence as a real one.
    """
    ow = handler_result.get("ocean_weather", {})
    data_source = ow.get("metadata", {}).get("data_source") or ""
    return "imd_live" not in data_source


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
        "requested_date": handler_result.get("date", "today"),
        "conditions_type": metadata.get("conditions_type", "current"),
        "conditions_date": metadata.get("conditions_date"),
        "location": handler_result.get("location", {}),
        "conditions_summary": {
            "ocean": ow.get("ocean", {}),
            "weather": ow.get("weather", {}),
            "tide": ow.get("tide", {}),
        },
        # Whether the alert data — including an empty "no alerts" result —
        # came from a live IMD feed. Set for every intent, since safety and
        # PFZ answers lean on alerts too; same source of truth as the
        # answer_text disclaimer.
        "alert_data_is_live": not _has_synthetic_alert_data(handler_result),
    }

    # Safety answers and fishing-zone answers both carry a risk assessment.
    risk = handler_result.get("risk_assessment")
    if risk:
        evidence["risk_assessment"] = {
            "verdict": risk.get("verdict"),
            "risk_score": risk.get("risk_score"),
            "thresholds_applied": risk.get("thresholds_applied", {}),
        }

    if intent == "find_nearest_pfz":
        pfz = handler_result.get("pfz_result", {})
        evidence["pfz_analysis"] = pfz.get("analysis", {})

    elif intent == "check_alerts":
        alerts_summary = dict(handler_result.get("alerts_summary", {}))
        # Single source of truth shared with the answer_text disclaimer
        # below — the frontend badges alert cards off this flag rather
        # than re-deriving it from the raw data_source string itself.
        alerts_summary["data_is_synthetic"] = _has_synthetic_alert_data(handler_result)
        evidence["alerts"] = alerts_summary

    return evidence


# ──────────────────────────────────────────────
#  Template-based answer generation (fallback) — English
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
        f"SST {_reading(analysis.get('current_location_sst', '?'), '°C')}, "
        f"Chlorophyll {_reading(analysis.get('current_location_chlorophyll', '?'), 'mg/m³')}"
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
        if _has_synthetic_alert_data(handler_result):
            # No live IMD feed behind this — an empty list is not an all-clear.
            return (
                f"ℹ️ **No alerts found** near **{loc}** in the alert data available right now — "
                f"but this is **not** a confirmed all-clear (see the note below)."
            )
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


# ══════════════════════════════════════════════════════════════════
#  ⚠️  TAMIL TRANSLATIONS — PENDING HUMAN REVIEW  ⚠️
#
#  Everything from here to the "END PENDING HUMAN REVIEW" marker is
#  AI-generated Tamil covering SAFETY-CRITICAL wording: the safe /
#  caution / unsafe verdict text, the numeric threshold explanations,
#  and the PFZ/alert template structures a fisherman would act on.
#
#  None of this has been checked by a native Tamil speaker. Do not
#  treat it as production-ready — a mistranslation here (e.g. "safe"
#  read as "unsafe", or a garbled threshold number) is a real-world
#  safety risk, not a cosmetic bug. Review every string in this block
#  before this goes live for real users.
#
#  The reason-string translator below (_translate_reason_to_ta) is
#  pattern-matched against risk_assessment.py's fixed set of ~13
#  English templates and only substitutes words around the numbers
#  risk_assessment.py already computed — it never invents a number —
#  but the Tamil wording itself still needs a native-speaker check.
# ══════════════════════════════════════════════════════════════════

_DATE_WORD_TA = {"today": "இன்று", "tomorrow": "நாளை", "the day after tomorrow": "நாளை மறுநாள்"}

_SUITABILITY_TA = {
    "excellent": "மிகச் சிறந்தது",
    "good": "நல்லது",
    "fair": "மிதமானது",
    "poor": "மோசமானது",
}

_SEVERITY_LABEL_TA = {
    "alert": "🔴 எச்சரிக்கை",
    "warning": "🟠 எச்சரிக்கை",
    "watch": "🟡 கண்காணிப்பு",
}

_ALERT_TYPE_EMOJI = {"cyclone": "🌀", "lightning": "⚡", "high_wave": "🌊"}

# (compiled English pattern, Tamil-rendering function) — matched in
# order against each risk_assessment.py reason string. Falls back to
# the original English string if nothing matches, so an unrecognized
# future reason template never crashes or silently mistranslates.
_REASON_PATTERNS_TA = [
    (re.compile(r"^Wave height ([\d.]+) m exceeds unsafe threshold \(([\d.]+) m\)$"),
     lambda m: f"அலை உயரம் {m.group(1)} மீ., பாதுகாப்பற்ற வரம்பை ({m.group(2)} மீ.) மீறுகிறது"),
    (re.compile(r"^Wave height ([\d.]+) m is in the caution range \(([\d.]+)–([\d.]+) m\)$"),
     lambda m: f"அலை உயரம் {m.group(1)} மீ., எச்சரிக்கை வரம்பில் உள்ளது ({m.group(2)}–{m.group(3)} மீ.)"),
    (re.compile(r"^Wave height ([\d.]+) m is within safe limits \(< ([\d.]+) m\)$"),
     lambda m: f"அலை உயரம் {m.group(1)} மீ., பாதுகாப்பான வரம்பிற்குள் உள்ளது (< {m.group(2)} மீ.)"),
    (re.compile(r"^Wind speed ([\d.]+) km/h exceeds unsafe threshold \(([\d.]+) km/h\)$"),
     lambda m: f"காற்றின் வேகம் {m.group(1)} கிமீ/மணி, பாதுகாப்பற்ற வரம்பை ({m.group(2)} கிமீ/மணி) மீறுகிறது"),
    (re.compile(r"^Wind speed ([\d.]+) km/h is in the caution range \(([\d.]+)–([\d.]+) km/h\)$"),
     lambda m: f"காற்றின் வேகம் {m.group(1)} கிமீ/மணி, எச்சரிக்கை வரம்பில் உள்ளது ({m.group(2)}–{m.group(3)} கிமீ/மணி)"),
    (re.compile(r"^Wind speed ([\d.]+) km/h is within safe limits \(< ([\d.]+) km/h\)$"),
     lambda m: f"காற்றின் வேகம் {m.group(1)} கிமீ/மணி, பாதுகாப்பான வரம்பிற்குள் உள்ளது (< {m.group(2)} கிமீ/மணி)"),
    (re.compile(r"^Visibility ([\d.]+) km is below unsafe threshold \(([\d.]+) km\)$"),
     lambda m: f"பார்வைத் தூரம் {m.group(1)} கிமீ, பாதுகாப்பற்ற வரம்பிற்குக் கீழே உள்ளது ({m.group(2)} கிமீ)"),
    (re.compile(r"^Visibility ([\d.]+) km is in the caution range \(([\d.]+)–([\d.]+) km\)$"),
     lambda m: f"பார்வைத் தூரம் {m.group(1)} கிமீ, எச்சரிக்கை வரம்பில் உள்ளது ({m.group(2)}–{m.group(3)} கிமீ)"),
    (re.compile(r"^Visibility ([\d.]+) km is good \(> ([\d.]+) km\)$"),
     lambda m: f"பார்வைத் தூரம் {m.group(1)} கிமீ, நல்ல நிலையில் உள்ளது (> {m.group(2)} கிமீ)"),
    (re.compile(r"^🌀 CYCLONE ALERT: (.+)$"), lambda m: f"🌀 புயல் எச்சரிக்கை: {m.group(1)}"),
    (re.compile(r"^🌊 HIGH WAVE ALERT: (.+)$"), lambda m: f"🌊 உயர் அலை எச்சரிக்கை: {m.group(1)}"),
    (re.compile(r"^⚡ LIGHTNING ALERT: (.+)$"), lambda m: f"⚡ மின்னல் எச்சரிக்கை: {m.group(1)}"),
    (re.compile(r"^No active weather or marine alerts$"),
     lambda m: "செயலில் வானிலை அல்லது கடல்சார் எச்சரிக்கைகள் இல்லை"),
]


def _translate_reason_to_ta(reason: str) -> str:
    """Translate one risk_assessment.py reason string into Tamil. See block header above."""
    for pattern, builder in _REASON_PATTERNS_TA:
        m = pattern.match(reason)
        if m:
            return builder(m)
    return reason  # unrecognized template — left in English rather than guessed


def _template_safety_answer_ta(handler_result: dict) -> str:
    """Tamil version of _template_safety_answer. PENDING HUMAN REVIEW — see block header."""
    risk = handler_result.get("risk_assessment", {})
    loc = handler_result["location"]["name"]
    verdict = risk.get("verdict", "unknown")
    score = risk.get("risk_score", 0)
    reasons = risk.get("reasons", [])
    date_ta = _DATE_WORD_TA.get(handler_result.get("date", "today"), handler_result.get("date", "today"))

    verdict_text = {
        "safe": f"✅ **{loc}** அருகில் {date_ta} கடலுக்குச் செல்வது **பாதுகாப்பானது** எனத் தெரிகிறது.",
        "caution": f"⚠️ **{loc}** அருகில் {date_ta} கடலுக்குச் செல்ல **எச்சரிக்கையாக** இருங்கள்.",
        "unsafe": f"🚫 **{loc}** அருகில் {date_ta} கடலுக்குச் செல்வது **பாதுகாப்பானது அல்ல**.",
    }

    lines = [verdict_text.get(verdict, f"{loc} அருகில் கடல் நிலைமைகள் {verdict}.")]
    lines.append(f"\n**ஆபத்து மதிப்பெண்:** {score}/100\n")
    lines.append("**முக்கிய காரணிகள்:**")
    for r in reasons:
        lines.append(f"- {_translate_reason_to_ta(r)}")

    ow = handler_result.get("ocean_weather", {})
    alerts = ow.get("alerts", [])
    if alerts:
        lines.append("\n**செயலில் உள்ள எச்சரிக்கைகள்:**")
        for a in alerts:
            # Alert title/message come from IMD bulletins (English source
            # text) — left untranslated rather than guessed.
            lines.append(f"- **{a.get('title', 'Alert')}** ({a.get('source', '')}): {a.get('message', '')}")

    return "\n".join(lines)


def _template_pfz_answer_ta(handler_result: dict) -> str:
    """Tamil version of _template_pfz_answer. PENDING HUMAN REVIEW — see block header."""
    pfz = handler_result.get("pfz_result", {})
    loc = handler_result["location"]["name"]
    zones = pfz.get("zones", [])
    viable = [z for z in zones if z.get("score", 0) >= 0.2]

    if not viable:
        return (
            f"🐟 **{loc}** அருகில் தற்போது பொருத்தமான மீன்பிடி மண்டலங்கள் எதுவும் கிடைக்கவில்லை.\n\n"
            f"தற்போதைய கடல் நிலைமைகள் இந்தப் பகுதியில் அதிக மீன் திரட்சியை ஆதரிக்காமல் "
            f"இருக்கலாம். பிறகு மீண்டும் பாருங்கள் அல்லது வேறு இருப்பிடத்தை முயற்சிக்கவும்."
        )

    lines = [f"🐟 **{loc}** அருகில் **{len(viable)} சாத்தியமான மீன்பிடி மண்டல(ங்கள்)** கண்டறியப்பட்டன:\n"]

    for i, z in enumerate(viable, 1):
        species_list = z.get("species_likely") or []
        species = ", ".join(species_list) if species_list else "பலவகை"
        suitability = _SUITABILITY_TA.get(z.get("suitability"), z.get("suitability", "?"))
        lines.append(
            f"**{i}. {z.get('id', 'PFZ')}** — {z['distance_km']:.0f} கிமீ தொலைவில்\n"
            f"   - தகுதி: **{suitability}** (மதிப்பெண்: {z.get('score', 0):.0%})\n"
            f"   - கடல் வெப்பநிலை: {z.get('sst', '?')} °C | குளோரோஃபில்: {z.get('chlorophyll', '?')} mg/m³\n"
            f"   - சாத்தியமான மீன் வகைகள்: {species}"
        )

    analysis = pfz.get("analysis", {})
    lines.append(
        f"\n**{loc}-இல் தற்போதைய நிலைமைகள்:** "
        f"கடல் வெப்பநிலை {_reading(analysis.get('current_location_sst', '?'), '°C', 'கிடைக்கவில்லை')}, "
        f"குளோரோஃபில் {_reading(analysis.get('current_location_chlorophyll', '?'), 'mg/m³', 'கிடைக்கவில்லை')}"
    )
    lines.append(f"*பொருத்தமான கடல் வெப்பநிலை வரம்பு: {analysis.get('sst_range_optimal', '26–29 °C')}*")

    return "\n".join(lines)


def _template_alerts_answer_ta(handler_result: dict) -> str:
    """Tamil version of _template_alerts_answer. PENDING HUMAN REVIEW — see block header."""
    alerts_summary = handler_result.get("alerts_summary", {})
    loc = handler_result["location"]["name"]
    alerts = alerts_summary.get("active_alerts", [])
    count = len(alerts)

    if count == 0:
        if _has_synthetic_alert_data(handler_result):
            return (
                f"ℹ️ **{loc}** அருகில் தற்போது கிடைக்கும் எச்சரிக்கை தரவில் **எச்சரிக்கைகள் எதுவும் இல்லை** — "
                f"ஆனால் இது **உறுதிசெய்யப்பட்ட பாதுகாப்பு அறிவிப்பு அல்ல** (கீழே உள்ள குறிப்பைப் பார்க்கவும்)."
            )
        return (
            f"✅ **{loc}** அருகில் தற்போது செயலில் எச்சரிக்கைகள் இல்லை.\n\n"
            f"தற்போது புயல், மின்னல் அல்லது உயர் அலை எச்சரிக்கைகள் எதுவும் "
            f"நடைமுறையில் இல்லை. நிலைமைகள் இயல்பாகத் தெரிகின்றன."
        )

    lines = [f"⚠️ **{loc}** அருகில் **{count} செயலில் உள்ள எச்சரிக்கை(கள்)**:\n"]

    for a in alerts:
        emoji = _ALERT_TYPE_EMOJI.get(a.get("type", ""), "⚠️")
        sev_label = _SEVERITY_LABEL_TA.get(a.get("severity", ""), f"⚠️ {a.get('severity', '?')}")
        # Alert title/message/source come from IMD bulletins (English
        # source text) — left untranslated rather than guessed.
        lines.append(
            f"{sev_label} {emoji} **{a.get('title', 'Alert')}**\n"
            f"   - தீவிரம்: {a.get('severity', '?').upper()}\n"
            f"   - மூலம்: {a.get('source', '?')}\n"
            f"   - {a.get('message', 'விவரங்கள் இல்லை.')}\n"
            f"   - செல்லுபடியாகும் தேதி: {a.get('valid_until', '?')}"
        )

    if alerts_summary.get("has_critical"):
        lines.append(
            "\n🚨 **முக்கியம்: செயலில் புயல் எச்சரிக்கை — கடலுக்குச் செல்ல வேண்டாம்.**"
        )

    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════
#  END PENDING HUMAN REVIEW BLOCK
# ══════════════════════════════════════════════════════════════════


# A general-safety phrase always wins — "is it safe to check the wind" still
# wants the full report, not a wind-only answer.
_SAFETY_OVERRIDE_KEYWORDS = (
    "safe", "safety", "venture", "should i go", "should we go", "risk",
    "hazard", "dangerous", "full report", "summary", "overall",
    # Tamil equivalents
    "பாதுகாப்பானதா", "பாதுகாப்பு", "ஆபத்து", "செல்லலாமா", "முழு அறிக்கை", "சுருக்கம்",
)

# query keyword -> ocean_weather topic name (English + Tamil)
_NARROW_TOPIC_KEYWORDS = (
    ("wind", "wind"), ("காற்று", "wind"),
    ("wave", "wave"), ("அலை", "wave"),
    ("visibility", "visibility"), ("பார்வை", "visibility"),
    ("temperature", "temperature"), ("temp", "temperature"), ("வெப்பநிலை", "temperature"),
)


def _detect_narrow_topic(user_query: str) -> str | None:
    """
    Return "wind" / "wave" / "visibility" / "temperature" if the query
    asks about exactly one of those and isn't a general safety question
    — else None, meaning "give the full report". Recognizes both
    English and Tamil keywords.
    """
    q = user_query.lower()
    if any(kw in q for kw in _SAFETY_OVERRIDE_KEYWORDS):
        return None
    for keyword, topic in _NARROW_TOPIC_KEYWORDS:
        if keyword in q:
            return topic
    return None


def _narrow_topic_answer(handler_result: dict, topic: str, language: str = "en") -> str | None:
    """
    A one-line answer covering just the topic the user actually asked
    about, pulled straight from ocean_weather_data — no LLM required.
    Returns None if the relevant field isn't available (caller then
    falls back to the full report rather than a broken one-liner).
    """
    loc = handler_result["location"]["name"]
    ow = handler_result.get("ocean_weather", {})
    ocean = ow.get("ocean", {})
    weather = ow.get("weather", {})

    if language == "ta":
        # PENDING HUMAN REVIEW — see block above. These are short,
        # numbers-only sentences (lower risk than the safety verdict),
        # but still AI-translated and unchecked.
        if topic == "wind":
            speed = weather.get("wind_speed_kmh")
            direction = weather.get("wind_direction")
            if speed is None:
                return None
            return f"💨 **{loc}** அருகில் காற்றின் வேகம் தற்போது **{speed} கிமீ/மணி** ({direction} திசையிலிருந்து)."
        if topic == "wave":
            height = ocean.get("wave_height_m")
            if height is None:
                return None
            period = ocean.get("wave_period_s")
            period_note = f" (காலஅளவு: {period} வி.)" if period is not None else ""
            return f"🌊 **{loc}** அருகில் அலை உயரம் தற்போது **{height} மீ.**{period_note}."
        if topic == "visibility":
            vis = weather.get("visibility_km")
            if vis is None:
                return None
            return f"👁️ **{loc}** அருகில் பார்வைத் தூரம் தற்போது **{vis} கிமீ**."
        if topic == "temperature":
            air_temp = weather.get("air_temperature_celsius")
            sst = ocean.get("sst_celsius")
            if air_temp is None and sst is None:
                return None
            parts = []
            if air_temp is not None:
                parts.append(f"வளிமண்டல வெப்பநிலை **{air_temp} °C**")
            if sst is not None:
                parts.append(f"கடல் மேற்பரப்பு வெப்பநிலை **{sst} °C**")
            return f"🌡️ **{loc}** அருகில், " + " மற்றும் ".join(parts) + "."
        return None

    if topic == "wind":
        speed = weather.get("wind_speed_kmh")
        direction = weather.get("wind_direction")
        if speed is None:
            return None
        return f"💨 Wind near **{loc}** is currently **{speed} km/h** from the **{direction}**."

    if topic == "wave":
        height = ocean.get("wave_height_m")
        if height is None:
            return None
        period = ocean.get("wave_period_s")
        period_note = f" (period: {period} s)" if period is not None else ""
        return f"🌊 Wave height near **{loc}** is currently **{height} m**{period_note}."

    if topic == "visibility":
        vis = weather.get("visibility_km")
        if vis is None:
            return None
        return f"👁️ Visibility near **{loc}** is currently **{vis} km**."

    if topic == "temperature":
        air_temp = weather.get("air_temperature_celsius")
        sst = ocean.get("sst_celsius")
        if air_temp is None and sst is None:
            return None
        parts = []
        if air_temp is not None:
            parts.append(f"air temperature is **{air_temp} °C**")
        if sst is not None:
            parts.append(f"sea surface temperature is **{sst} °C**")
        return f"🌡️ Near **{loc}**, " + " and ".join(parts) + "."

    return None


def _generate_template_answer(handler_result: dict, user_query: str = "", language: str = "en") -> str:
    """
    Route to the correct template based on intent and language —
    narrowing to a single-topic one-liner when the query asked about
    just one thing and the intent is the (default, report-heavy)
    sea-safety one.
    """
    intent = handler_result["intent"]

    # The one-liners say "currently", so they only fit current conditions.
    is_forecast = handler_result.get("ocean_weather", {}).get("metadata", {}).get("conditions_type") == "forecast"
    if intent == "assess_sea_safety" and user_query and not is_forecast:
        topic = _detect_narrow_topic(user_query)
        if topic:
            narrow = _narrow_topic_answer(handler_result, topic, language)
            if narrow:
                return narrow

    if language == "ta":
        if intent == "assess_sea_safety":
            return _template_safety_answer_ta(handler_result)
        elif intent == "find_nearest_pfz":
            return _template_pfz_answer_ta(handler_result)
        elif intent == "check_alerts":
            return _template_alerts_answer_ta(handler_result)
        return "உங்கள் கேள்வியை நான் செயலாக்கினேன், ஆனால் ஒரு வடிவமைக்கப்பட்ட பதிலை உருவாக்க முடியவில்லை."

    if intent == "assess_sea_safety":
        return _template_safety_answer(handler_result)
    elif intent == "find_nearest_pfz":
        return _template_pfz_answer(handler_result)
    elif intent == "check_alerts":
        return _template_alerts_answer(handler_result)
    return "I processed your query but couldn't generate a formatted response."


# ──────────────────────────────────────────────
#  Shared prompt construction (used by every LLM provider below)
# ──────────────────────────────────────────────


def _build_data_summary(handler_result: dict) -> str:
    """
    Build a concise plain-text summary of the handler's data, shared by
    every LLM provider's answer-generation prompt. Kept in English
    regardless of UI language — it's model input, not user-facing text,
    and the target model reads English data labels fine while
    generating a Tamil answer per the prompt instruction below.
    """
    intent = handler_result["intent"]
    loc = handler_result["location"]["name"]
    ow = handler_result.get("ocean_weather", {})
    ocean = ow.get("ocean", {})
    weather = ow.get("weather", {})

    data_summary = (
        f"Location: {loc}\n"
        f"SST: {_reading(ocean.get('sst_celsius', '?'), '°C')}\n"
        f"Chlorophyll: {_reading(ocean.get('chlorophyll_mg_m3', '?'), 'mg/m³')}\n"
        f"Wave height: {_reading(ocean.get('wave_height_m', '?'), 'm')}\n"
        f"Wind: {_reading(weather.get('wind_speed_kmh', '?'), 'km/h')} {weather.get('wind_direction', '')}\n"
        f"Visibility: {_reading(weather.get('visibility_km', '?'), 'km')}\n"
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
        risk = handler_result.get("risk_assessment", {})
        data_summary += (
            f"\nPFZ recommendation: {pfz.get('recommendation', '?')}\n"
            f"Safety verdict for heading out: {risk.get('verdict', 'not assessed')}\n"
            f"Safety reasons: {'; '.join(risk.get('reasons', [])) or 'none'}\n"
        )
    elif intent == "check_alerts":
        alerts = handler_result.get("alerts_summary", {})
        alert_list = alerts.get("active_alerts", [])
        if alert_list:
            data_summary += "\nActive alerts:\n"
            for a in alert_list:
                data_summary += f"- {a.get('title', 'Alert')}: {a.get('message', '')}\n"
        else:
            data_summary += "\nNo active alerts.\n"

    return data_summary


def _build_prompt(user_query: str, data_summary: str, language: str = "en") -> str:
    """
    Build the final answer-generation prompt, shared by every LLM
    provider. When language="ta", instructs the model to answer
    entirely in plain, everyday Tamil — this is a prompt instruction,
    not hardcoded output text, so it isn't part of the PENDING HUMAN
    REVIEW block above; the model's actual Tamil output should still be
    spot-checked (see the live test results reported alongside this
    change).
    """
    if language == "ta":
        return (
            f"நீங்கள் ORCA, இந்திய மீனவர்கள் மற்றும் கடலோர மக்களுக்கான கடல் "
            f"நுண்ணறிவு உதவியாளர். ஒரு பயனர் கேட்டார்: \"{user_query}\"\n\n"
            f"இந்தத் தரவின் அடிப்படையில்:\n{data_summary}\n"
            f"பயனர் ஒரு குறிப்பிட்ட விஷயத்தை (காற்று, அலைகள், வெப்பநிலை, "
            f"பார்வைத் தூரம், ஒரு குறிப்பிட்ட எச்சரிக்கை வகை) பற்றி மட்டும் "
            f"கேட்டிருந்தால், அதை மட்டும் 1-2 வாக்கியங்களில், உரையாடல் "
            f"தொனியில் பதிலளிக்கவும் — முழு அறிக்கையை உருவாக்க வேண்டாம். "
            f"பொதுவான பாதுகாப்பு கேள்வி (\"பாதுகாப்பானதா\", \"செல்லலாமா\") "
            f"கேட்டால் அல்லது வெளிப்படையாக முழு அறிக்கை/சுருக்கம் கேட்டால் "
            f"மட்டுமே முழு பல-புள்ளி பாதுகாப்பு அறிக்கையை வழங்கவும்.\n"
            f"பதிலை முழுவதுமாகத் தமிழில் மட்டுமே எழுதவும் — எளிய, அன்றாடப் "
            f"பேச்சுத் தமிழில், ஒரு மீனவருக்குப் புரியும் வகையில், மிகவும் "
            f"முறையான அல்லது இலக்கியத் தமிழில் அல்ல. Markdown வடிவமைப்பைப் "
            f"பயன்படுத்தவும். பொருத்தமான ஈமோஜிகளைச் சேர்க்கவும். எண்களைத் "
            f"தெளிவாகக் குறிப்பிடவும். பாதுகாப்பற்றது எனில் தெளிவாகவும் "
            f"உறுதியாகவும் இருங்கள். பாதுகாப்பானது எனில் ஊக்கமளிக்கும் "
            f"வகையில் இருந்தாலும் பொதுவான முன்னெச்சரிக்கைகளை நினைவூட்டவும்."
        )

    return (
        f"You are ORCA, a marine intelligence assistant for Indian fishermen and "
        f"coastal users. A user asked: \"{user_query}\"\n\n"
        f"Based on this data:\n{data_summary}\n"
        f"If the user asked about ONE specific thing (wind, waves, temperature, "
        f"visibility, a specific alert type), answer ONLY that in 1-2 sentences, "
        f"conversationally — don't produce the full report. Only give the full "
        f"multi-point safety report if they asked a general safety question "
        f"(\"is it safe\", \"should I go out\") or explicitly asked for a full "
        f"report or summary.\n"
        f"Use markdown formatting. Include relevant emoji. Be specific with numbers. "
        f"If unsafe, be clear and firm. If safe, be encouraging but remind about general precautions."
    )


# ──────────────────────────────────────────────
#  LLM-based answer generation (Groq → Claude, if available)
# ──────────────────────────────────────────────


async def _generate_groq_answer(
    handler_result: dict, user_query: str, data_summary: str, language: str = "en"
) -> str | None:
    """
    Use Groq to generate a natural, conversational answer from the
    structured handler results. Returns None on failure.
    """
    if not config.GROQ_API_KEY or config.GROQ_API_KEY == "your_groq_api_key_here":
        return None

    try:
        import groq
    except ImportError:
        return None

    client = groq.Groq(api_key=config.GROQ_API_KEY)
    prompt = _build_prompt(user_query, data_summary, language)

    try:
        response = client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content
        if text:
            return text.strip()
    except Exception as e:
        logger.warning(f"Groq answer generation failed: {e}")

    return None


async def _generate_llm_answer(
    handler_result: dict, user_query: str, data_summary: str, language: str = "en"
) -> str | None:
    """
    Use Claude to generate a natural, conversational answer from the
    structured handler results.  Returns None on failure.
    """
    if not config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEY == "your_key_here":
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = _build_prompt(user_query, data_summary, language)

    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        if text:
            return text.strip()
    except Exception as e:
        logger.warning(f"LLM answer generation failed: {e}")

    return None


# ──────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────


# Appended verbatim after ANY answer_text (LLM-generated or template)
# whenever _has_synthetic_alert_data() is true — deterministic
# post-processing, not a prompt instruction, so it can never be
# silently dropped by an LLM that doesn't follow the disclaimer
# instruction in its own prompt. See CRITICAL note in module docstring.
_SYNTHETIC_ALERT_QUALIFIER_EN = (
    "\n\n⚠️ **Note:** Live IMD alert data isn't currently connected — the "
    "alert(s) above are illustrative baseline/example data, not a real "
    "active cyclone or warning. For real alerts, check IMD's official "
    "site at mausam.imd.gov.in."
)

_SYNTHETIC_ALERT_QUALIFIER_TA = (
    "\n\n⚠️ **குறிப்பு:** நேரடி IMD எச்சரிக்கை தரவு தற்போது இணைக்கப்படவில்லை "
    "— மேலே உள்ள எச்சரிக்கை(கள்) விளக்கத்திற்கான அடிப்படை/எடுத்துக்காட்டுத் "
    "தரவு, உண்மையான செயலில் உள்ள புயல் அல்லது எச்சரிக்கை அல்ல. உண்மையான "
    "எச்சரிக்கைகளுக்கு, IMD-இன் அதிகாரப்பூர்வ தளமான mausam.imd.gov.in-ஐப் "
    "பார்க்கவும். (PENDING HUMAN REVIEW — see synthesis.py module docstring)"
)

# Same rule for an EMPTY alert list that isn't from live IMD data: "no
# alerts found" in baseline/mock data is not "no alerts in effect", and
# must never read as a confirmed all-clear.
_NO_LIVE_ALERTS_QUALIFIER_EN = (
    "\n\n⚠️ **Note:** Live IMD alert data isn't currently connected, so \"no "
    "active alerts\" here is **not** a confirmed all-clear — a real cyclone, "
    "lightning or high-wave warning could be in effect. Check IMD's official "
    "site at mausam.imd.gov.in before heading out."
)

_NO_LIVE_ALERTS_QUALIFIER_TA = (
    "\n\n⚠️ **குறிப்பு:** நேரடி IMD எச்சரிக்கை தரவு தற்போது இணைக்கப்படவில்லை — "
    "எனவே இங்கு \"செயலில் எச்சரிக்கைகள் இல்லை\" என்பது உறுதிசெய்யப்பட்ட பாதுகாப்பு "
    "அறிவிப்பு அல்ல; உண்மையான புயல், மின்னல் அல்லது உயர் அலை எச்சரிக்கை "
    "நடைமுறையில் இருக்கலாம். கடலுக்குச் செல்லும் முன் IMD-இன் அதிகாரப்பூர்வ "
    "தளமான mausam.imd.gov.in-ஐப் பார்க்கவும். (PENDING HUMAN REVIEW — see "
    "synthesis.py module docstring)"
)

# Only 3 mock profiles exist (chennai/mumbai/visakhapatnam — see
# mock_provider.py). Any other queried location silently borrows
# whichever is "nearest", even from 600+ km away, unless flagged here.
_MOCK_BORROWED_PATTERN = re.compile(r"^mock \(borrowed from (\w+), (\d+) km away\)$")


def _mock_data_qualifier(handler_result: dict, language: str = "en") -> str | None:
    """
    Returns a disclaimer to append whenever this response is built on
    mock/demo data rather than live conditions — distinguishing "this
    genuinely is <city>'s own demo profile" from the more seriously
    misleading "no profile exists for this place, so it's silently
    reusing a city hundreds of km away" (mock_provider.py's
    nearest-match fallback). Returns None when live data was used.
    """
    ow = handler_result.get("ocean_weather", {})
    data_source = ow.get("metadata", {}).get("data_source", "")
    if not data_source.startswith("mock"):
        return None

    borrowed = _MOCK_BORROWED_PATTERN.match(data_source)
    if borrowed:
        city, distance_km = borrowed.group(1).title(), borrowed.group(2)
        if language == "ta":
            return (
                f"\n\n⚠️ **குறிப்பு:** இந்த இருப்பிடத்திற்கென தனியான டெமோ "
                f"தரவு இல்லை — எனவே இந்தப் பதில் **{city}**-இன் "
                f"({distance_km} கிமீ தொலைவில்) மாதிரி நிலைமைகளைப் "
                f"பயன்படுத்துகிறது, இது இங்குள்ள உண்மையான நிலைமைகளைக் "
                f"காட்டவில்லை. உண்மையான, இருப்பிடம்-குறிப்பிட்ட தரவுக்கு "
                f"பின்தளத்தில் USE_LIVE_DATA=true ஐ அமைக்கவும். "
                f"(PENDING HUMAN REVIEW)"
            )
        return (
            f"\n\n⚠️ **Note:** No demo profile exists for this exact location, so "
            f"this answer is borrowing **{city}**'s mock conditions from **"
            f"{distance_km} km away** — it does not reflect real conditions here. "
            f"Set `USE_LIVE_DATA=true` in the backend for real, location-specific data."
        )

    if language == "ta":
        return (
            "\n\n⚠️ **குறிப்பு:** இது டெமோ/மாதிரி தரவு, இன்றைய நேரடி "
            "நிலைமைகள் அல்ல. உண்மையான தரவுக்கு பின்தளத்தில் "
            "USE_LIVE_DATA=true ஐ அமைக்கவும். (PENDING HUMAN REVIEW)"
        )
    return (
        "\n\n⚠️ **Note:** This is demo/mock data, not live conditions for today. "
        "Set `USE_LIVE_DATA=true` in the backend for real Open-Meteo/IMD/Copernicus data."
    )


# ──────────────────────────────────────────────
#  Requested date vs. what the data describes
# ──────────────────────────────────────────────


def _requested_date_status(handler_result: dict) -> dict:
    """
    Compare the day the user asked about with the day the data describes.

    Returns {"status", "label", "target"} where status is
      "today"        — asked about today; nothing to reconcile
      "forecast"     — the data is a forecast for exactly the requested day
      "not_checked"  — anything else (demo data, a past or out-of-range
                       date, an unparseable phrase): the answer must say
                       it only checked current conditions
    """
    requested = handler_result.get("date") or "today"
    metadata = handler_result.get("ocean_weather", {}).get("metadata", {})
    today = today_ist()
    target = resolve_requested_date(requested, today)

    if target == today:
        return {"status": "today", "label": "today", "target": target}

    label = describe_date(target, today) if target is not None else requested
    if (
        target is not None
        and metadata.get("conditions_type") == "forecast"
        and metadata.get("conditions_date") == target.isoformat()
    ):
        return {"status": "forecast", "label": label, "target": target}
    return {"status": "not_checked", "label": label, "target": target}


def _date_notice(date_status: dict, requested: str, language: str = "en") -> str | None:
    """Text prepended to the answer whenever it isn't simply about today."""
    status, label, target = date_status["status"], date_status["label"], date_status["target"]
    if status == "today":
        return None

    if language == "ta":
        # PENDING HUMAN REVIEW — AI-generated Tamil, see the translations block above.
        label_ta = _DATE_WORD_TA.get(label, target.isoformat() if target else requested)
        if status == "forecast":
            return (
                f"📅 **{label_ta} ({target.isoformat()}) முன்னறிவிப்பு:** அந்த நாளுக்கான Open-Meteo "
                f"முன்னறிவிப்பின் மிக மோசமான மணிநேர நிலைமைகளின் அடிப்படையில். காட்டப்படும் "
                f"எச்சரிக்கைகள் தற்போது நடைமுறையில் உள்ளவை — முன்னறிவிப்புகளும் எச்சரிக்கைகளும் "
                f"மாறலாம், கடலுக்குச் செல்லும் முன் மீண்டும் சரிபார்க்கவும். (PENDING HUMAN REVIEW)\n\n"
            )
        return (
            f"📅 **கேட்கப்பட்ட நாளுக்கான ({label_ta}) முன்னறிவிப்பை என்னால் இப்போது சரிபார்க்க "
            f"முடியாது — தற்போதைய நிலைமைகளை மட்டுமே சரிபார்க்க முடியும்.** குறிப்புக்காக "
            f"இன்றைய தரவு கீழே உள்ளது. (PENDING HUMAN REVIEW)\n\n"
        )

    if status == "forecast":
        heading = f"Forecast for {label}"
        if label in ("tomorrow", "the day after tomorrow"):
            heading += f" ({target.strftime('%a %d %b')})"
        return (
            f"📅 **{heading}:** based on the roughest hour in Open-Meteo's forecast for that day. "
            f"Alerts shown are the ones in effect now — forecasts and warnings change, so check "
            f"again before heading out.\n\n"
        )

    today = today_ist()
    if target is None:
        reason = f"I couldn't tell which day \"{requested}\" means, so I can only check current conditions"
    elif target < today:
        reason = f"I can't look up past conditions for {label}"
    elif not is_forecastable(target, today):
        reason = f"Forecasts only reach {MAX_FORECAST_DAYS} days ahead, so I can't check {label}"
    else:
        reason = f"I can only check current conditions right now, not forecasts for {label}"
    return f"📅 **{reason}** — here's today's data for reference.\n\n"


def _alert_phrase(alert: dict) -> str:
    """'an active lightning alert (title)' / 'an active weather warning (title)'."""
    alert_type = str(alert.get("type") or "unrecognised").strip().lower().replace("_", " ")
    kind = alert_type if alert_type.endswith("warning") else f"{alert_type} alert"
    return f"an active {kind} ({alert.get('title') or 'untitled'})"


def _pfz_safety_caveat(handler_result: dict, language: str = "en") -> str | None:
    """
    Safety line leading every fishing-zone answer whose risk assessment
    isn't clean — a promising zone must never be recommended without the
    warning or rough conditions that come with it. Added after the answer
    is generated, so an LLM-written answer can't drop it.
    """
    if handler_result.get("intent") != "find_nearest_pfz":
        return None
    risk = handler_result.get("risk_assessment") or {}
    verdict = risk.get("verdict")  # None if safety wasn't assessed — treated as not clean
    if verdict == "safe":
        return None

    ow = handler_result.get("ocean_weather", {})
    issues = [_alert_phrase(a) for a in ow.get("alerts", [])]
    thresholds = risk.get("thresholds_applied", {})
    for key, label, unit in (
        ("wave_height", "wave height", "m"),
        ("wind_speed", "wind speed", "km/h"),
        ("visibility", "visibility", "km"),
    ):
        info = thresholds.get(key, {})
        if info.get("status") in ("caution", "unsafe"):
            issues.append(f"{label} {info.get('value')} {unit} ({info['status']})")
        elif info.get("status") == "unavailable":
            issues.append(f"no {label} data")

    viable = [z for z in handler_result.get("pfz_result", {}).get("zones", []) if z.get("score", 0) >= 0.2]
    zone_id = viable[0].get("id", "PFZ") if viable else None
    conditions = "; ".join(issues) if issues else "conditions that couldn't be fully checked"
    emoji = "🚫" if verdict == "unsafe" else "⚠️"

    if language == "ta":
        # PENDING HUMAN REVIEW — AI-generated Tamil safety wording.
        verdict_ta = {"caution": "எச்சரிக்கை", "unsafe": "பாதுகாப்பற்றது"}.get(verdict, "சரிபார்க்கப்படவில்லை")
        if zone_id:
            lead = f"**{zone_id}** ஒரு நம்பிக்கைக்குரிய மீன்பிடி மண்டலமாகத் தெரிந்தாலும், தற்போதைய நிலைமைகளில் பின்வருவன உள்ளன: {conditions}"
        else:
            lead = f"தற்போதைய நிலைமைகளில் பின்வருவன உள்ளன: {conditions}"
        advice = (
            "நிலைமைகள் மேம்படும் வரை கடலுக்குச் செல்ல வேண்டாம்."
            if verdict == "unsafe"
            else "கடலுக்குச் செல்லும் முன் பாதுகாப்பைச் சரிபார்க்கவும்."
        )
        return f"{emoji} **பாதுகாப்பு சோதனை: {verdict_ta}.** {lead} — {advice} (PENDING HUMAN REVIEW)\n\n"

    verdict_en = {"caution": "CAUTION", "unsafe": "NOT SAFE"}.get(verdict, "NOT CHECKED")
    if zone_id:
        lead = f"While **{zone_id}** looks like a promising fishing zone, current conditions include {conditions}"
    else:
        lead = f"Current conditions include {conditions}"
    advice = "do not head out until conditions improve." if verdict == "unsafe" else "verify safety before heading out."
    return f"{emoji} **Safety check: {verdict_en}.** {lead} — {advice}\n\n"


# Readings the safety check depends on — see data_sources.interface.DATA_UNAVAILABLE.
_CORE_READINGS = (
    ("ocean", "wave_height_m", "wave height", "அலை உயரம்"),
    ("weather", "wind_speed_kmh", "wind speed", "காற்றின் வேகம்"),
    ("weather", "visibility_km", "visibility", "பார்வைத் தூரம்"),
)


def _missing_data_qualifier(handler_result: dict, language: str = "en") -> str | None:
    """
    A deterministic note whenever a safety-relevant reading couldn't be
    obtained for this location (e.g. Open-Meteo's null wave_height for
    Kolkata), so a partial check is never presented as a complete one.
    """
    if handler_result.get("intent") not in ("assess_sea_safety", "find_nearest_pfz"):
        return None

    ow = handler_result.get("ocean_weather", {})
    missing = [
        (label_en, label_ta)
        for section, key, label_en, label_ta in _CORE_READINGS
        if is_unavailable(ow.get(section, {}).get(key))
    ]
    if not missing:
        return None

    if language == "ta":
        labels = ", ".join(ta for _, ta in missing)
        return (
            f"\n\n⚠️ **குறிப்பு:** இந்த இருப்பிடத்திற்கான சில கடல் தரவு ({labels}) தற்போது "
            f"கிடைக்கவில்லை — அந்த நிலைமைகளை இந்தப் பதிலால் சரிபார்க்க முடியவில்லை, "
            f"எனவே இதை முழுமையற்ற மதிப்பீடாகக் கருதவும். (PENDING HUMAN REVIEW)"
        )
    labels = ", ".join(en for en, _ in missing)
    return (
        f"\n\n⚠️ **Note:** Some marine data isn't available for this location right now "
        f"({labels}). This answer couldn't check those conditions, so treat it as incomplete."
    )


async def synthesise_response(handler_result: dict, user_query: str, language: str = "en") -> dict:
    """
    Combine handler outputs into the final API response.

    Parameters
    ----------
    language : "en" or "ta" — see module docstring for the Tamil
        review caveat.

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

    requested_date = handler_result.get("date") or "today"
    date_status = _requested_date_status(handler_result)
    if date_status["status"] == "not_checked":
        # The readings aren't for the day the user asked about — never let a
        # template or LLM attach that day to today's verdict.
        handler_result = {**handler_result, "date": "today"}

    # Generate answer text — try providers in priority order (Groq →
    # Claude), only falling through if the previous one returned None,
    # then fall back to templates.
    data_summary = _build_data_summary(handler_result)
    if date_status["status"] == "not_checked":
        data_summary += (
            f"\nIMPORTANT: the user asked about {date_status['label']}, but no forecast was "
            f"available — these are TODAY's current conditions. Do not describe them as "
            f"conditions for {date_status['label']}.\n"
        )
    elif date_status["status"] == "forecast":
        data_summary += (
            f"\nThese readings are the forecast for {date_status['label']} (roughest hour of "
            f"that day), not current conditions. Alerts are the ones in effect now.\n"
        )

    answer_text = await _generate_groq_answer(handler_result, user_query, data_summary, language)
    if answer_text is None:
        answer_text = await _generate_llm_answer(handler_result, user_query, data_summary, language)
    if answer_text is None:
        answer_text = _generate_template_answer(handler_result, user_query, language)

    safety_caveat = _pfz_safety_caveat(handler_result, language)
    if safety_caveat:
        answer_text = f"{safety_caveat}{answer_text}"

    # CRITICAL: never let a fabricated alert (mock fixture data, or
    # IMD's "imd_baseline" fallback — e.g. the fictional "Cyclone DANA")
    # or a fabricated all-clear (an empty list from those same sources)
    # read as a confident, real answer. Applied after every path above —
    # LLM or template — so it can't be skipped by prompt non-compliance.
    if _has_synthetic_alert_data(handler_result):
        has_alerts = bool(handler_result.get("ocean_weather", {}).get("alerts"))
        if language == "ta":
            qualifier = _SYNTHETIC_ALERT_QUALIFIER_TA if has_alerts else _NO_LIVE_ALERTS_QUALIFIER_TA
        else:
            qualifier = _SYNTHETIC_ALERT_QUALIFIER_EN if has_alerts else _NO_LIVE_ALERTS_QUALIFIER_EN
        answer_text = f"{answer_text}{qualifier}"

    missing_qualifier = _missing_data_qualifier(handler_result, language)
    if missing_qualifier:
        answer_text = f"{answer_text}{missing_qualifier}"

    # Separate from the alert-specific check above: applies to every
    # intent (safety/PFZ/alerts) whenever the underlying wave/wind/etc.
    # data itself is mock/demo — including the more serious case where
    # it's silently borrowed from an unrelated city hundreds of km away.
    mock_qualifier = _mock_data_qualifier(handler_result, language)
    if mock_qualifier:
        answer_text = f"{answer_text}{mock_qualifier}"

    # The first thing the user reads whenever the answer isn't simply about today.
    date_notice = _date_notice(date_status, requested_date, language)
    if date_notice:
        answer_text = f"{date_notice}{answer_text}"

    return {
        "answer_text": answer_text,
        "evidence": evidence,
        "map_data": map_data,
    }

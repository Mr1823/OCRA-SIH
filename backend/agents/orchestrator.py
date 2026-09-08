"""
Orchestrator Agent — parses a user's natural-language query, selects the
right handler(s), runs them, and returns a synthesised response.

Uses Google Gemini (gemini-2.0-flash) with native function calling to
determine intent, extract location/date, and pick from three tools:
  1. assess_sea_safety   → ocean_weather + risk_assessment
  2. find_nearest_pfz    → ocean_weather + pfz
  3. check_alerts        → ocean_weather (alerts subset)

Falls back to keyword-based intent detection if the Gemini API key is
missing or the call fails, so the demo is always functional.

Includes exponential-backoff retry on 429 (rate limit) responses for
the Gemini free tier (~15 req/min).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

import config
from agents.ocean_weather import get_ocean_weather_data
from agents.risk_assessment import assess_safety
from agents.pfz import find_nearby_pfz
from agents.synthesis import synthesise_response
from utils.geocoding import geocode

logger = logging.getLogger("orca.orchestrator")

# ──────────────────────────────────────────────
#  Gemini tool definitions
# ──────────────────────────────────────────────

_TOOL_DEFINITIONS = [
    {
        "name": "assess_sea_safety",
        "description": (
            "Assess whether it is safe to venture into the sea near a given "
            "location. Checks wave height, wind speed, visibility, and active "
            "cyclone/weather alerts. Use this when the user asks about safety, "
            "whether it's safe to go fishing, go to sea, or venture out."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The coastal city or location name, e.g. 'Chennai', 'near Vizag', 'Mumbai coast'",
                },
                "date": {
                    "type": "string",
                    "description": "The date to check, e.g. 'today', 'tomorrow', '2026-09-08'. Defaults to 'today'.",
                },
            },
            "required": ["location"],
        },
    },
    {
        "name": "find_nearest_pfz",
        "description": (
            "Find the nearest Potential Fishing Zone (PFZ) near a location. "
            "Analyses sea surface temperature (SST) and chlorophyll concentration "
            "to identify productive fishing areas. Use this when the user asks "
            "about fishing zones, where to fish, PFZ, or fish catch areas."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The coastal city or location name",
                },
            },
            "required": ["location"],
        },
    },
    {
        "name": "check_alerts",
        "description": (
            "Check for active cyclone, lightning, or high-wave alerts near a "
            "location. Use this when the user asks about weather alerts, "
            "cyclones, storms, lightning warnings, or marine advisories."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The coastal city or location name",
                },
            },
            "required": ["location"],
        },
    },
]

_SYSTEM_PROMPT = (
    "You are ORCA, a marine intelligence assistant. You help fishermen and "
    "coastal users with sea safety assessments, fishing zone locations, and "
    "weather/cyclone alerts along the Indian coast.\n\n"
    "Given a user's question, call the most appropriate tool:\n"
    "- assess_sea_safety: for questions about safety, whether to go to sea\n"
    "- find_nearest_pfz: for questions about fishing zones, where to fish\n"
    "- check_alerts: for questions about cyclones, storms, lightning, alerts\n\n"
    "Extract the location from the query. If no location is mentioned, "
    "ask the user to specify one. If no date is mentioned, default to 'today'.\n"
    "Always call exactly one tool."
)


# ──────────────────────────────────────────────
#  Gemini API call with retry
# ──────────────────────────────────────────────


async def _call_gemini_with_retry(query: str) -> Optional[dict]:
    """
    Send the query to Gemini with tool definitions and return the
    function call result as {"name": ..., "args": {...}}.

    Returns None if the API key is missing or all retries fail.
    """
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.warning("No Gemini API key configured — falling back to keyword detection")
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai not installed — falling back to keyword detection")
        return None

    genai.configure(api_key=config.GEMINI_API_KEY)

    # Build tool spec
    tools = [genai.protos.Tool(function_declarations=[
        genai.protos.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters={
                "type_": "OBJECT",
                "properties": {
                    k: {"type_": "STRING", "description": v["description"]}
                    for k, v in t["parameters"]["properties"].items()
                },
                "required": t["parameters"].get("required", []),
            },
        )
        for t in _TOOL_DEFINITIONS
    ])]

    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        tools=tools,
        system_instruction=_SYSTEM_PROMPT,
    )

    last_error = None
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        try:
            response = model.generate_content(query)

            # Extract function call from response
            for part in response.parts:
                fn = part.function_call
                if fn and fn.name:
                    args = dict(fn.args) if fn.args else {}
                    logger.info(f"Gemini selected tool: {fn.name}({args})")
                    return {"name": fn.name, "args": args}

            # If Gemini responded with text instead of a tool call
            if response.text:
                logger.info(f"Gemini returned text (no tool call): {response.text[:100]}")
            return None

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # Retry on rate-limit (429) or transient server errors (5xx)
            if "429" in error_str or "resource_exhausted" in error_str or "500" in error_str or "503" in error_str:
                delay = config.LLM_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Gemini API error (attempt {attempt + 1}/{config.LLM_MAX_RETRIES + 1}): "
                    f"{e}. Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                continue
            else:
                # Non-retryable error
                logger.error(f"Gemini API error (non-retryable): {e}")
                break

    logger.error(f"Gemini API failed after {config.LLM_MAX_RETRIES + 1} attempts: {last_error}")
    return None


# ──────────────────────────────────────────────
#  Keyword-based fallback intent detection
# ──────────────────────────────────────────────

# Location patterns: "near X", "in X", "at X", "around X", or just a known city
_LOCATION_PATTERN = re.compile(
    r"(?:near|in|at|around|off|close to|from)\s+([A-Za-z\s]+?)(?:\s*[\?\.,!]|$|\s+(?:today|tomorrow|this|next))",
    re.IGNORECASE,
)

_KNOWN_CITIES = {
    "chennai", "visakhapatnam", "vizag", "mumbai", "kochi", "goa", "mangalore",
    "puducherry", "tuticorin", "paradip", "digha", "puri", "kolkata", "kakinada",
    "ratnagiri", "karwar", "porbandar", "veraval", "diu", "rameshwaram",
    "mangaluru", "thoothukudi", "machilipatnam", "cochin", "panaji",
    "bombay", "madras", "calcutta", "pondicherry", "paradeep",
}


def _extract_location_from_query(query: str) -> Optional[str]:
    """Try to extract a location name from the query text."""
    # Pattern match
    match = _LOCATION_PATTERN.search(query)
    if match:
        return match.group(1).strip()

    # Check for known city names in the query
    query_lower = query.lower()
    for city in _KNOWN_CITIES:
        if city in query_lower:
            return city

    return None


def _extract_date_from_query(query: str) -> str:
    """Extract a date reference from the query. Defaults to 'today'."""
    query_lower = query.lower()
    if "tomorrow" in query_lower:
        return "tomorrow"
    if "today" in query_lower:
        return "today"
    # Could add more date parsing here
    return "today"


def _keyword_intent_detection(query: str) -> Optional[dict]:
    """
    Simple keyword-based fallback for intent detection when Gemini is
    unavailable.
    """
    query_lower = query.lower()
    location = _extract_location_from_query(query)
    date = _extract_date_from_query(query)

    if not location:
        return None

    # Safety queries
    safety_keywords = ["safe", "safety", "venture", "go to sea", "dangerous", "risk", "hazard"]
    if any(kw in query_lower for kw in safety_keywords):
        return {"name": "assess_sea_safety", "args": {"location": location, "date": date}}

    # PFZ queries
    pfz_keywords = ["fishing zone", "pfz", "fish", "catch", "where to fish", "fishing area"]
    if any(kw in query_lower for kw in pfz_keywords):
        return {"name": "find_nearest_pfz", "args": {"location": location}}

    # Alert queries
    alert_keywords = ["alert", "cyclone", "storm", "lightning", "warning", "advisory", "hurricane"]
    if any(kw in query_lower for kw in alert_keywords):
        return {"name": "check_alerts", "args": {"location": location}}

    # Default: treat as safety query if we have a location
    return {"name": "assess_sea_safety", "args": {"location": location, "date": date}}


# ──────────────────────────────────────────────
#  Handler execution
# ──────────────────────────────────────────────


async def _execute_handler(tool_call: dict) -> dict:
    """
    Execute the selected handler function and return a structured response
    ready for synthesis.
    """
    name = tool_call["name"]
    args = tool_call["args"]
    location_str = args.get("location", "")
    date = args.get("date", "today")

    # Geocode the location
    try:
        lat, lon, display_name = await geocode(location_str)
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
            "intent": name,
            "location_raw": location_str,
        }

    # Fetch ocean/weather data (shared by all handlers)
    ocean_weather_data = await get_ocean_weather_data(lat, lon, date, display_name)

    result = {
        "success": True,
        "intent": name,
        "location": {"name": display_name, "lat": lat, "lon": lon},
        "date": date,
        "ocean_weather": ocean_weather_data,
    }

    if name == "assess_sea_safety":
        risk = assess_safety(ocean_weather_data)
        result["risk_assessment"] = risk.to_dict()
        result["agents_invoked"] = ["ocean_weather", "risk_assessment"]

    elif name == "find_nearest_pfz":
        pfz = find_nearby_pfz(ocean_weather_data)
        result["pfz_result"] = pfz.to_dict()
        result["agents_invoked"] = ["ocean_weather", "pfz"]

    elif name == "check_alerts":
        # Alerts are already in ocean_weather_data
        result["alerts_summary"] = {
            "active_alerts": ocean_weather_data.get("alerts", []),
            "alert_count": len(ocean_weather_data.get("alerts", [])),
            "has_critical": any(
                a.get("type") == "cyclone" for a in ocean_weather_data.get("alerts", [])
            ),
        }
        result["agents_invoked"] = ["ocean_weather"]

    return result


# ──────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────


async def handle_query(query: str) -> dict:
    """
    Main entry point: takes a raw user query string and returns a
    complete response with answer_text, evidence, and map_data.

    Flow:
      1. Parse intent + extract location/date (Gemini or keyword fallback)
      2. Geocode location → lat/lon
      3. Run selected handler(s)
      4. Synthesise into final response
    """
    logger.info(f"Processing query: {query[:100]}")

    # Step 1: Intent detection
    tool_call = await _call_gemini_with_retry(query)

    if tool_call is None:
        # Fallback to keyword-based detection
        logger.info("Using keyword fallback for intent detection")
        tool_call = _keyword_intent_detection(query)

    if tool_call is None:
        return {
            "answer_text": (
                "I couldn't determine what you're asking about or which location "
                "you mean. I can help with:\n"
                "• **Sea safety**: \"Is it safe to venture into the sea near Chennai?\"\n"
                "• **Fishing zones**: \"Where is the nearest PFZ near Mumbai?\"\n"
                "• **Weather alerts**: \"Are there any cyclone alerts near Vizag?\"\n\n"
                "Please include a coastal city name in your question."
            ),
            "evidence": {"error": "Could not parse query intent or location"},
            "map_data": None,
        }

    # Step 2-3: Execute handler
    handler_result = await _execute_handler(tool_call)

    if not handler_result.get("success"):
        return {
            "answer_text": (
                f"I understood your question but couldn't resolve the location. "
                f"{handler_result.get('error', 'Unknown error')}."
            ),
            "evidence": {"error": handler_result.get("error"), "intent": handler_result.get("intent")},
            "map_data": None,
        }

    # Step 4: Synthesise
    response = await synthesise_response(handler_result, query)
    return response

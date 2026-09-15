"""
Orchestrator Agent — parses a user's natural-language query, selects the
right handler(s), runs them, and returns a synthesised response.

Tries LLM providers in priority order to determine intent, extract
location/date, and pick from three tools:
  1. assess_sea_safety   → ocean_weather + risk_assessment
  2. find_nearest_pfz    → ocean_weather + pfz + risk_assessment
  3. check_alerts        → ocean_weather (alerts subset)

Provider chain: Groq → keyword-based fallback, so the demo is always
functional even if Groq is unavailable or unconfigured.

Calls are async, and retries on 429 (rate limit) and 5xx (server error)
follow utils/llm.py: bounded by a total wait budget, honouring
retry-after, with a cooldown for providers that can't answer at all.
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
from utils.llm import (
    is_account_error,
    mark_provider_unavailable,
    provider_available,
    retry_after_seconds,
    retry_delay,
)

logger = logging.getLogger("orca.orchestrator")

# ──────────────────────────────────────────────
#  Tool definitions
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
        "input_schema": {
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
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The coastal city or location name",
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
        "name": "check_alerts",
        "description": (
            "Check for active cyclone, lightning, or high-wave alerts near a "
            "location. Use this when the user asks about weather alerts, "
            "cyclones, storms, lightning warnings, or marine advisories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The coastal city or location name",
                },
                "date": {
                    "type": "string",
                    "description": "The date to check, e.g. 'today', 'tomorrow', '2026-09-08'. Defaults to 'today'.",
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

# Tamil version — used when the UI's active language is "ta". This is
# an instruction prompt for the LLM's tool-selection step, not
# safety-verdict wording, so it's lower-stakes than the strings flagged
# for human review in synthesis.py — but still AI-translated and worth
# a native-speaker glance before relying on it in a real demo.
_SYSTEM_PROMPT_TA = (
    "நீங்கள் ORCA, ஒரு கடல் நுண்ணறிவு உதவியாளர். இந்திய கடற்கரையோர மீனவர்களுக்கும் "
    "மக்களுக்கும் கடல் பாதுகாப்பு மதிப்பீடுகள், மீன்பிடி மண்டல இருப்பிடங்கள், "
    "வானிலை/புயல் எச்சரிக்கைகள் ஆகியவற்றில் உதவுகிறீர்கள்.\n\n"
    "பயனரின் கேள்வியின் அடிப்படையில், மிகவும் பொருத்தமான கருவியை அழையுங்கள்:\n"
    "- assess_sea_safety: பாதுகாப்பு, கடலுக்குச் செல்லலாமா என்பது பற்றிய கேள்விகளுக்கு\n"
    "- find_nearest_pfz: மீன்பிடி மண்டலங்கள், எங்கே மீன்பிடிக்கலாம் என்பது பற்றிய கேள்விகளுக்கு\n"
    "- check_alerts: புயல், புயல்காற்று, மின்னல், எச்சரிக்கைகள் பற்றிய கேள்விகளுக்கு\n\n"
    "கேள்வியிலிருந்து இருப்பிடத்தைப் பிரித்தெடுக்கவும் (தமிழ் அல்லது ஆங்கிலப் "
    "பெயராக இருந்தாலும் அப்படியே எடுத்துக்கொள்ளுங்கள்). இருப்பிடம் "
    "குறிப்பிடப்படவில்லை என்றால், பயனரிடம் ஒரு இருப்பிடத்தைக் குறிப்பிடச் "
    "சொல்லுங்கள். தேதி குறிப்பிடப்படவில்லை என்றால், 'இன்று' எனக் கருதவும்.\n"
    "எப்போதும் சரியாக ஒரு கருவியை மட்டும் அழையுங்கள்."
)


async def _after_status_error(label: str, provider: str, error, attempt: int, waited: float) -> Optional[float]:
    """
    Handle an HTTP error from an intent-detection call. Retries rate limits
    (429) and server errors (5xx) within utils.llm's budget — sleeping here
    and returning the seconds waited — or returns None when the caller
    should stop and fall back to keyword detection.
    """
    status = error.status_code
    if status == 429 or status >= 500:
        delay = retry_delay(attempt, error, waited)
        if delay is not None:
            logger.warning(f"{label} API error {status} (attempt {attempt + 1}): {error}. Retrying in {delay:.1f}s...")
            await asyncio.sleep(delay)
            return delay
        retry_after = retry_after_seconds(error)
        if status == 429 and retry_after:
            # Don't call it again until it says it's ready.
            mark_provider_unavailable(provider, f"rate limited (retry-after {retry_after:.0f}s)", retry_after)
        return None

    if is_account_error(status, str(error)):
        mark_provider_unavailable(provider, f"account error {status}: {error}")
    else:
        logger.error(f"{label} API error {status} (non-retryable): {error}")
    return None


# ──────────────────────────────────────────────
#  Groq API call with retry (primary provider)
# ──────────────────────────────────────────────


async def _call_groq_with_retry(query: str, language: str = "en") -> Optional[dict]:
    """
    Send the query to Groq (OpenAI-compatible tool calling) and return
    the tool-call result as {"name": ..., "args": {...}}.

    Returns None if the API key is missing, groq isn't installed, Groq
    responds without a tool call, or all retries fail — the caller then
    falls back to keyword detection.
    """
    system_prompt = _SYSTEM_PROMPT_TA if language == "ta" else _SYSTEM_PROMPT
    if not config.GROQ_API_KEY or config.GROQ_API_KEY == "your_groq_api_key_here":
        logger.warning("No Groq API key configured — falling back to keyword detection")
        return None
    if not provider_available("groq"):
        logger.info("Groq is paused after an earlier error (rate limit or account problem, logged above) — falling back to keyword detection")
        return None

    try:
        import groq
    except ImportError:
        logger.warning("groq package not installed — falling back to keyword detection")
        return None

    # Async client so a slow call never blocks other requests. Retries are
    # driven by the loop below, so the SDK's own are off.
    client = groq.AsyncGroq(api_key=config.GROQ_API_KEY, max_retries=0, timeout=config.LLM_REQUEST_TIMEOUT_S)

    # _TOOL_DEFINITIONS keeps each JSON schema under "input_schema" —
    # reformat into OpenAI/Groq's nested {"type": "function", "function": {...}}
    # shape, with the schema under the key Groq expects: "parameters".
    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in _TOOL_DEFINITIONS
    ]

    last_error = None
    attempts = 0
    waited = 0.0
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        attempts = attempt + 1
        try:
            response = await client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                tools=tools,
            )

            message = response.choices[0].message
            if message.tool_calls:
                call = message.tool_calls[0]
                args = json.loads(call.function.arguments) if call.function.arguments else {}
                logger.info(f"Groq selected tool: {call.function.name}({args})")
                return {"name": call.function.name, "args": args}

            # If Groq responded with text instead of a tool call
            if message.content:
                logger.info(f"Groq returned text (no tool call): {message.content[:100]}")
            return None

        except groq.APIStatusError as e:  # includes RateLimitError (429)
            last_error = e
            delay = await _after_status_error("Groq", "groq", e, attempt, waited)
            if delay is None:
                break
            waited += delay

        except Exception as e:
            last_error = e
            logger.error(f"Groq API error (not retried): {type(e).__name__}: {e}")
            break

    logger.error(f"Groq API gave up after {attempts} attempt(s) and {waited:.1f}s of backoff: {last_error}")
    return None


# ──────────────────────────────────────────────
#  Keyword-based fallback intent detection
# ──────────────────────────────────────────────

# Location patterns: "near X", "in X", "at X", "around X", or just a known city
_LOCATION_PATTERN = re.compile(
    r"\b(?:near|in|at|around|off|close to|from)\s+([A-Za-z\s]+?)(?:\s*[\?\.,!]|$|\s+(?:today|tomorrow|this|next))",
    re.IGNORECASE,
)

# Tamil has no direct equivalent of English prepositions — "near X" is
# expressed as "X அருகில்"/"X அருகே" (postpositions after the place
# name). This catches that specific, common phrasing — including what
# the frontend's Tamil UI itself generates for the district dropdown —
# but doesn't attempt full Tamil morphological analysis, so a place
# name with a fused case suffix instead of a separate postposition
# (e.g. "நாகப்பட்டினத்தில்" = Nagapattinam + locative "-இல்", glued on
# with sandhi) won't be caught by this or the substring check below.
_LOCATION_PATTERN_TA = re.compile(r"([஀-௿]+?)\s*(?:அருகில்|அருகே)")

_KNOWN_CITIES = {
    "chennai", "visakhapatnam", "vizag", "mumbai", "kochi", "goa", "mangalore",
    "puducherry", "tuticorin", "paradip", "digha", "puri", "kolkata", "kakinada",
    "ratnagiri", "karwar", "porbandar", "veraval", "diu", "rameshwaram",
    "mangaluru", "thoothukudi", "machilipatnam", "cochin", "panaji",
    "bombay", "madras", "calcutta", "pondicherry", "paradeep",
}

# Tamil names for the 13 TN coastal districts + towns (see
# utils/geocoding.py's _TN_COASTAL_DISTRICTS — verified there, not
# guessed) plus a few other major coastal cities, for the substring
# fallback when there's no "அருகில்"/"அருகே" postposition to anchor on.
_KNOWN_CITIES_TA = {
    "சென்னை", "விசாகப்பட்டினம்", "மும்பை", "கொச்சி",
    "திருவள்ளூர்", "பழவேற்காடு", "செங்கல்பட்டு", "மாமல்லபுரம்",
    "விழுப்புரம்", "மரக்காணம்", "கடலூர்", "நாகப்பட்டினம்",
    "திருவாரூர்", "வேதாரண்யம்", "தஞ்சாவூர்", "கோடியக்கரை",
    "புதுக்கோட்டை", "கோட்டைப்பட்டினம்", "இராமநாதபுரம்", "இராமேஸ்வரம்",
    "தூத்துக்குடி", "திருநெல்வேலி", "இடிந்தகரை", "கன்னியாகுமரி",
}


def _extract_location_from_query(query: str) -> Optional[str]:
    """Try to extract a location name from the query text (English or Tamil)."""
    # Pattern match — English prepositions
    match = _LOCATION_PATTERN.search(query)
    if match:
        return match.group(1).strip()

    # Pattern match — Tamil postpositions ("X அருகில்" / "X அருகே")
    match_ta = _LOCATION_PATTERN_TA.search(query)
    if match_ta:
        return match_ta.group(1).strip()

    # Check for known city names in the query (English, case-insensitive)
    query_lower = query.lower()
    for city in _KNOWN_CITIES:
        if city in query_lower:
            return city

    # Check for known Tamil place names (Tamil has no case; exact script match)
    for place in _KNOWN_CITIES_TA:
        if place in query:
            return place

    return None


_ISO_DATE_IN_QUERY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _extract_date_from_query(query: str) -> str:
    """
    Extract a date phrase from the query (English or Tamil). Defaults to
    'today'; utils.dates.resolve_requested_date() turns it into a date.
    """
    query_lower = query.lower()
    # "day after tomorrow" first — it contains "tomorrow".
    if "day after tomorrow" in query_lower or "நாளை மறுநாள்" in query:
        return "day after tomorrow"
    if "tomorrow" in query_lower or "நாளை" in query:
        return "tomorrow"
    iso_date = _ISO_DATE_IN_QUERY.search(query)
    if iso_date:
        return iso_date.group(1)
    return "today"


def _keyword_intent_detection(query: str) -> Optional[dict]:
    """
    Simple keyword-based fallback for intent detection when Groq is
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
        return {"name": "find_nearest_pfz", "args": {"location": location, "date": date}}

    # Alert queries
    alert_keywords = ["alert", "cyclone", "storm", "lightning", "warning", "advisory", "hurricane"]
    if any(kw in query_lower for kw in alert_keywords):
        return {"name": "check_alerts", "args": {"location": location, "date": date}}

    # Default: treat as safety query if we have a location
    return {"name": "assess_sea_safety", "args": {"location": location, "date": date}}


# ──────────────────────────────────────────────
#  Greeting / small-talk detection
# ──────────────────────────────────────────────

_GREETING_PATTERN = re.compile(
    r"^\s*(hi|hello|hey|hiya|yo|greetings|sup)\b|^\s*good\s*(morning|afternoon|evening|day)\b",
    re.IGNORECASE,
)

_SMALL_TALK_PHRASES = (
    "what can you do", "who are you", "what are you", "what is this",
    "how does this work", "what do you do", "thank you", "thanks", "thx",
    "bye", "goodbye", "help me", "help",
)

# Marine/location signals that mean a message is a real question, however
# short or however it happens to open (e.g. "hi, is it safe near Chennai?")
# — these must always win over the greeting/small-talk check below.
_MARINE_KEYWORDS = {
    "safe", "safety", "wave", "wind", "weather", "cyclone", "storm",
    "fish", "fishing", "pfz", "alert", "temperature", "visibility",
    "tide", "sea", "ocean", "venture", "sst", "chlorophyll", "lightning",
    "warning", "advisory", "harbor", "harbour", "coast", "coastal",
}


def _is_greeting_or_small_talk(query: str) -> bool:
    """
    Detect greetings/small talk so they get a warm conversational reply
    instead of the "couldn't determine intent" error-shaped fallback.

    Deliberately conservative: any marine keyword or recognisable
    location reference disqualifies it, so a real marine question is
    never misclassified as small talk just for being short or for
    opening with "hi".
    """
    cleaned = query.strip().lower()
    if not cleaned:
        return False

    if any(kw in cleaned for kw in _MARINE_KEYWORDS):
        return False
    if _LOCATION_PATTERN.search(query) or any(city in cleaned for city in _KNOWN_CITIES):
        return False

    if _GREETING_PATTERN.match(cleaned):
        return True

    return any(phrase in cleaned for phrase in _SMALL_TALK_PHRASES)


def _small_talk_response(query: str, language: str = "en") -> str:
    """A short, warm, conversational reply — no tool pipeline, no report."""
    cleaned = query.strip().lower()

    if language == "ta":
        if any(p in cleaned for p in ("thank", "thx")):
            return "நன்றி! 🐋 கடல் நிலைமைகள் பற்றி வேறு ஏதேனும் கேள்விகள் இருந்தால் கேளுங்கள்."
        if any(p in cleaned for p in ("bye", "goodbye")):
            return "பத்திரமாகச் செல்லுங்கள், கவனமாக இருங்கள்! 🐋👋"
        return (
            "வணக்கம்! நான் ORCA 🐋 — \"சென்னை அருகில் பாதுகாப்பானதா?\", "
            "\"நாகப்பட்டினத்தில் காற்றின் வேகம் என்ன?\", அல்லது \"கடலூர் அருகில் "
            "புயல் எச்சரிக்கை உள்ளதா?\" போன்று கேளுங்கள். நீங்கள் என்ன "
            "தெரிந்துகொள்ள விரும்புகிறீர்கள்?"
        )

    if any(p in cleaned for p in ("thank", "thx")):
        return "You're welcome! 🐋 Let me know if you have any other questions about sea conditions."

    if any(p in cleaned for p in ("bye", "goodbye")):
        return "Take care and stay safe out there! 🐋👋"

    return (
        "Hi! I'm ORCA 🐋 — ask me things like \"Is it safe near Chennai?\", "
        "\"What's the wind speed at Nagapattinam?\", or \"Any cyclone alerts "
        "near Cuddalore?\" What would you like to know?"
    )


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
    date = args.get("date") or "today"

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
        # A fishing-zone recommendation is advice to go to sea — it gets the
        # same safety check as a direct "is it safe?" question.
        result["risk_assessment"] = assess_safety(ocean_weather_data).to_dict()
        result["agents_invoked"] = ["ocean_weather", "pfz", "risk_assessment"]

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


async def handle_query(query: str, language: str = "en") -> dict:
    """
    Main entry point: takes a raw user query string and returns a
    complete response with answer_text, evidence, and map_data.

    Parameters
    ----------
    language : "en" or "ta" — UI language, used to select the LLM
        system prompt and (in synthesise_response) the answer language.
        Does not affect intent detection or data fetching.

    Flow:
      0. Greeting/small-talk check — short-circuit with a conversational
         reply, skipping the tool pipeline entirely
      1. Parse intent + extract location/date
         (Groq → keyword fallback)
      2. Geocode location → lat/lon
      3. Run selected handler(s)
      4. Synthesise into final response
    """
    logger.info(f"Processing query: {query[:100]} (language={language})")

    # Step 0: Greetings/small talk — a plain conversational reply, not a
    # report. No risk_assessment/pfz/evidence, no LLM call.
    if _is_greeting_or_small_talk(query):
        logger.info("Detected greeting/small talk — responding conversationally")
        return {
            "answer_text": _small_talk_response(query, language),
            "evidence": {},
            "map_data": None,
        }

    # Step 1: Intent detection — Groq, or keywords if Groq returns None.
    tool_call = await _call_groq_with_retry(query, language)

    if tool_call is None:
        # Fallback to keyword-based detection
        logger.info("Using keyword fallback for intent detection")
        tool_call = _keyword_intent_detection(query)

    if tool_call is None:
        if language == "ta":
            # AI-translated UI copy, not a safety verdict — see the
            # PENDING HUMAN REVIEW block in synthesis.py for the strings
            # that actually carry safety meaning.
            answer_text = (
                "நீங்கள் என்ன கேட்கிறீர்கள் அல்லது எந்த இருப்பிடம் என்பதை என்னால் "
                "புரிந்துகொள்ள முடியவில்லை. நான் இவற்றில் உதவ முடியும்:\n"
                "• **கடல் பாதுகாப்பு**: \"சென்னை அருகில் கடலுக்குச் செல்வது "
                "பாதுகாப்பானதா?\"\n"
                "• **மீன்பிடி மண்டலங்கள்**: \"மும்பை அருகில் அருகிலுள்ள PFZ எங்கே?\"\n"
                "• **வானிலை எச்சரிக்கைகள்**: \"விசாகப்பட்டினம் அருகில் புயல் "
                "எச்சரிக்கை உள்ளதா?\"\n\n"
                "தயவுசெய்து உங்கள் கேள்வியில் ஒரு கடலோர நகரத்தின் பெயரைச் "
                "சேர்க்கவும்."
            )
        else:
            answer_text = (
                "I couldn't determine what you're asking about or which location "
                "you mean. I can help with:\n"
                "• **Sea safety**: \"Is it safe to venture into the sea near Chennai?\"\n"
                "• **Fishing zones**: \"Where is the nearest PFZ near Mumbai?\"\n"
                "• **Weather alerts**: \"Are there any cyclone alerts near Vizag?\"\n\n"
                "Please include a coastal city name in your question."
            )
        return {
            "answer_text": answer_text,
            "evidence": {"error": "Could not parse query intent or location"},
            "map_data": None,
        }

    # Step 2-3: Execute handler
    handler_result = await _execute_handler(tool_call)

    if not handler_result.get("success"):
        if language == "ta":
            answer_text = (
                f"உங்கள் கேள்வியை நான் புரிந்துகொண்டேன், ஆனால் இருப்பிடத்தைக் "
                f"கண்டறிய முடியவில்லை. {handler_result.get('error', 'தெரியாத பிழை')}."
            )
        else:
            answer_text = (
                f"I understood your question but couldn't resolve the location. "
                f"{handler_result.get('error', 'Unknown error')}."
            )
        return {
            "answer_text": answer_text,
            "evidence": {"error": handler_result.get("error"), "intent": handler_result.get("intent")},
            "map_data": None,
        }

    # Step 4: Synthesise
    response = await synthesise_response(handler_result, query, language)
    return response

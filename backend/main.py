"""
ORCA FastAPI Backend — Marine Intelligence REST API.

Endpoints:
  POST /query   — accept a natural-language question, return synthesised
                   answer with evidence and map data
  GET  /health  — liveness probe
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Ensure the backend package is importable ──
# When running `uvicorn main:app` from inside backend/, the parent
# package modules (agents, config, …) must be on sys.path.
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import config  # noqa: E402  (after path fix)
from agents.orchestrator import handle_query  # noqa: E402
from utils.llm import is_account_error, mark_provider_unavailable  # noqa: E402

# ──────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orca.api")


# ──────────────────────────────────────────────
#  Request / Response schemas
# ──────────────────────────────────────────────


class QueryRequest(BaseModel):
    """Incoming user query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural-language question about sea conditions",
        examples=["Is it safe to go fishing near Chennai today?"],
    )
    language: str = Field(
        "en",
        description="UI language for the response — 'en' or 'ta' (Tamil). Defaults to English.",
        examples=["en", "ta"],
    )


class MapMarker(BaseModel):
    lat: float
    lon: float
    label: str
    type: str
    color: str
    popup: str


class MapData(BaseModel):
    center: List[float]
    zoom: int
    markers: List[MapMarker]


class QueryResponse(BaseModel):
    """Structured response from ORCA."""

    answer_text: str = Field(
        ..., description="Natural-language answer (markdown)"
    )
    evidence: dict = Field(
        ..., description="Structured evidence data for the 'why this answer' panel"
    )
    map_data: Optional[MapData] = Field(
        None, description="Leaflet map configuration with markers"
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: str
    version: str = "0.1.0"
    llm_configured: bool


# ──────────────────────────────────────────────
#  App lifecycle
# ──────────────────────────────────────────────


async def _check_groq_reachable() -> bool:
    """
    Perform a trivial live call against the configured Groq model so
    startup logs show whether the API is *actually* reachable, rather
    than just whether an API key string is present.
    """
    try:
        import groq
    except ImportError:
        logger.error("   Groq ping    : ❌ groq package is not installed")
        return False

    try:
        client = groq.AsyncGroq(
            api_key=config.GROQ_API_KEY, max_retries=0, timeout=config.LLM_REQUEST_TIMEOUT_S
        )
        await client.chat.completions.create(
            model=config.GROQ_MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True
    except Exception as e:
        logger.error(f"   Groq ping    : ❌ FAILED — {e}")
        if is_account_error(getattr(e, "status_code", None), str(e)):
            # Don't make every request rediscover a key that can't work.
            mark_provider_unavailable("groq", f"startup ping failed: {e}")
        return False


async def _check_claude_reachable() -> bool:
    """
    Perform a trivial live call against the configured Claude model so
    startup logs show whether the API is *actually* reachable, rather
    than just whether an API key string is present. A key can be set
    but the model name wrong/retired — that should be loud, not silent.
    """
    try:
        import anthropic
    except ImportError:
        logger.error("   Claude ping  : ❌ anthropic package is not installed")
        return False

    try:
        client = anthropic.AsyncAnthropic(
            api_key=config.ANTHROPIC_API_KEY, max_retries=0, timeout=config.LLM_REQUEST_TIMEOUT_S
        )
        await client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True
    except Exception as e:
        logger.error(f"   Claude ping  : ❌ FAILED — {e}")
        if is_account_error(getattr(e, "status_code", None), str(e)):
            # e.g. "credit balance is too low": skip Claude instead of paying
            # a doomed round trip on every request.
            mark_provider_unavailable("anthropic", f"startup ping failed: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    logger.info("🐋 ORCA backend starting …")

    # Which .env (if any) actually supplied config, and what USE_LIVE_DATA
    # resolved to — logged explicitly so "is this using live data or mock"
    # is never something you have to guess or infer from behavior.
    logger.info(
        f"   .env file    : {config.LOADED_ENV_PATH or '⚠️  none found — using process env / defaults'}"
    )
    logger.info(
        f"   USE_LIVE_DATA: {config.USE_LIVE_DATA} "
        f"({'live Open-Meteo/IMD/Copernicus data' if config.USE_LIVE_DATA else 'mock data from mock_data/*.json'})"
    )

    # ── Groq (primary provider) ──
    logger.info(f"   Groq model   : {config.GROQ_MODEL}")
    groq_key_set = bool(config.GROQ_API_KEY and config.GROQ_API_KEY != "your_groq_api_key_here")
    logger.info(
        f"   Groq API     : {'✅ configured' if groq_key_set else '⚠️  not set'}"
    )
    if groq_key_set:
        if await _check_groq_reachable():
            logger.info(f"   Groq ping    : ✅ reachable with model '{config.GROQ_MODEL}'")
        else:
            logger.warning(
                "   Groq ping    : falling back to the next provider at request "
                "time — see error above"
            )

    # ── Claude (fallback provider) ──
    logger.info(f"   Claude model : {config.ANTHROPIC_MODEL}")
    llm_key_set = bool(
        config.ANTHROPIC_API_KEY and config.ANTHROPIC_API_KEY != "your_key_here"
    )
    logger.info(
        f"   Claude API   : {'✅ configured' if llm_key_set else '⚠️  not set'}"
    )

    if llm_key_set:
        if await _check_claude_reachable():
            logger.info(f"   Claude ping  : ✅ reachable with model '{config.ANTHROPIC_MODEL}'")
        else:
            logger.warning(
                "   Claude ping  : falling back to keyword-based intent detection "
                "at request time — see error above"
            )

    if not groq_key_set and not llm_key_set:
        logger.warning(
            "   LLM provider : none configured — every query uses keyword-based "
            "intent detection and template answers"
        )

    logger.info(f"   Listening on : http://0.0.0.0:{config.BACKEND_PORT}")
    yield
    logger.info("🐋 ORCA backend shutting down")


# ──────────────────────────────────────────────
#  FastAPI application
# ──────────────────────────────────────────────

app = FastAPI(
    title="ORCA — Marine Intelligence API",
    description=(
        "Agentic AI platform for sea safety, fishing zone discovery, "
        "and weather alert queries along the Indian coast."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the React dev server and any explicitly configured origin
_allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
if config.FRONTEND_URL and config.FRONTEND_URL not in _allowed_origins:
    _allowed_origins.append(config.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
#  Endpoints
# ──────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Liveness probe — always returns 200 if the server is up."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        llm_configured=bool(
            (config.GROQ_API_KEY and config.GROQ_API_KEY != "your_groq_api_key_here")
            or (config.ANTHROPIC_API_KEY and config.ANTHROPIC_API_KEY != "your_key_here")
        ),
    )


@app.post("/query", response_model=QueryResponse, tags=["Query"])
async def process_query(req: QueryRequest):
    """
    Accept a natural-language question and return a synthesised answer
    with supporting evidence and map data.

    Example queries:
    - "Is it safe to venture into the sea near Chennai?"
    - "Where is the nearest PFZ near Mumbai?"
    - "Are there any cyclone alerts near Vizag?"
    """
    start = time.perf_counter()
    language = req.language if req.language in ("en", "ta") else "en"
    logger.info(f"➡️  Query received: {req.query!r} (language={language!r})")

    try:
        result = await handle_query(req.query, language=language)
    except Exception as e:
        logger.exception(f"Handler error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal processing error: {e}",
        )

    elapsed = time.perf_counter() - start
    logger.info(f"✅ Query processed in {elapsed:.2f}s")

    return QueryResponse(
        answer_text=result.get("answer_text", "No answer generated."),
        evidence=result.get("evidence", {}),
        map_data=result.get("map_data"),
    )


# ──────────────────────────────────────────────
#  Run with: uvicorn main:app --reload
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.BACKEND_PORT,
        reload=True,
    )

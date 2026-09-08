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
    gemini_configured: bool


# ──────────────────────────────────────────────
#  App lifecycle
# ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown events."""
    logger.info("🐋 ORCA backend starting …")
    logger.info(f"   Gemini model : {config.GEMINI_MODEL}")
    logger.info(
        f"   Gemini API   : {'✅ configured' if config.GEMINI_API_KEY and config.GEMINI_API_KEY != 'your_gemini_api_key_here' else '⚠️  not set (keyword fallback)'}"
    )
    logger.info(f"   Live data    : {'ON' if config.USE_LIVE_DATA else 'OFF (mock)'}")
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
        gemini_configured=bool(
            config.GEMINI_API_KEY
            and config.GEMINI_API_KEY != "your_gemini_api_key_here"
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
    logger.info(f"➡️  Query received: {req.query!r}")

    try:
        result = await handle_query(req.query)
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

"""
Application configuration — loads settings from environment variables.

All config is centralised here so agent code never reads os.environ directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend/ directory (or project root)
_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parent

# Exposed so main.py's startup log can state, unambiguously, which .env
# file (if any) actually supplied these values — "no .env file found,
# using process env / defaults" is a real and different state from
# either of the two paths below, and has bitten us before.
LOADED_ENV_PATH: str | None = None

for env_path in (_backend_dir / ".env", _project_root / ".env"):
    if env_path.exists():
        load_dotenv(env_path)
        LOADED_ENV_PATH = str(env_path)
        break


# ──────────────────────────────────────────────
#  LLM provider settings (Groq → Claude → keyword fallback)
# ──────────────────────────────────────────────

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
# "llama-3.3-70b-versatile" is not in this account's model list as of
# 2026-09-13 (verified via client.models.list()) — Groq's catalog no
# longer serves a plain Llama chat model under that name. Using
# openai/gpt-oss-120b instead, confirmed working for tool calling.
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# ──────────────────────────────────────────────
#  Claude / Anthropic settings
# ──────────────────────────────────────────────

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# ──────────────────────────────────────────────
#  Data source settings
# ──────────────────────────────────────────────

USE_LIVE_DATA: bool = os.getenv("USE_LIVE_DATA", "false").lower() in (
    "true",
    "1",
    "yes",
)

# ──────────────────────────────────────────────
#  IMD (India Meteorological Department) live data
# ──────────────────────────────────────────────

IMD_BASE_URL: str = os.getenv("IMD_BASE_URL", "https://api.imd.gov.in/api/v1")
IMD_API_KEY: str = os.getenv("IMD_API_KEY", "")
IMD_AUTH_TOKEN: str = os.getenv("IMD_AUTH_TOKEN", "")

# ──────────────────────────────────────────────
#  Copernicus Marine Service (live chlorophyll-a for PFZ)
# ──────────────────────────────────────────────

CMEMS_USERNAME: str = os.getenv("CMEMS_USERNAME", "")
CMEMS_PASSWORD: str = os.getenv("CMEMS_PASSWORD", "")

# Sample and score a small grid of nearby points for live PFZ zones
# using Copernicus chlorophyll + Open-Meteo SST. Off by default: it
# multiplies outbound API calls per query (extra Copernicus + Open-Meteo
# calls per grid point) and could burn through Copernicus rate limits
# unexpectedly if left on.
ENABLE_LIVE_PFZ_GRID: bool = os.getenv("ENABLE_LIVE_PFZ_GRID", "false").lower() in (
    "true",
    "1",
    "yes",
)

# ──────────────────────────────────────────────
#  Rate-limit / retry settings (shared by every LLM provider)
# ──────────────────────────────────────────────

LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_RETRY_BASE_DELAY: float = float(os.getenv("LLM_RETRY_BASE_DELAY", "2.0"))  # seconds

# ──────────────────────────────────────────────
#  Server settings
# ──────────────────────────────────────────────

BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

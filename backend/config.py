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

for env_path in (_backend_dir / ".env", _project_root / ".env"):
    if env_path.exists():
        load_dotenv(env_path)
        break


# ──────────────────────────────────────────────
#  Gemini / LLM settings
# ──────────────────────────────────────────────

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ──────────────────────────────────────────────
#  Data source settings
# ──────────────────────────────────────────────

USE_LIVE_DATA: bool = os.getenv("USE_LIVE_DATA", "false").lower() in (
    "true",
    "1",
    "yes",
)

# ──────────────────────────────────────────────
#  Rate-limit / retry settings (Gemini free tier)
# ──────────────────────────────────────────────

LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_RETRY_BASE_DELAY: float = float(os.getenv("LLM_RETRY_BASE_DELAY", "2.0"))  # seconds

# ──────────────────────────────────────────────
#  Server settings
# ──────────────────────────────────────────────

BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

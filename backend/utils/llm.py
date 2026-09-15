"""
Shared call policy for LLM calls (Groq, with a keyword/template fallback):
bounded retries, and a cooldown for a provider that can't serve requests
at all.

Why this exists — measured against the previous code with a local fake API
(Groq: HTTP 429 with retry-after 30 s; Claude: HTTP 400 "credit balance is
too low"), a single query took 90 s:
  - intent detection backed off 2+4+8+16 s regardless of retry-after,
    sleeping even after its final attempt;
  - answer generation used the SDK's default 2 retries, each honouring
    the 30 s retry-after;
  - Claude could never answer, so all of it ended in the keyword fallback.
These rules keep that worst case to a few seconds.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import config

logger = logging.getLogger("orca.llm")

# provider name → time.monotonic() until which it is skipped
_unavailable_until: dict[str, float] = {}


def provider_available(provider: str) -> bool:
    until = _unavailable_until.get(provider)
    if until is None:
        return True
    if time.monotonic() >= until:
        del _unavailable_until[provider]
        return True
    return False


def mark_provider_unavailable(provider: str, reason: str, seconds: Optional[float] = None) -> None:
    """Skip a provider for `seconds` (default LLM_PROVIDER_COOLDOWN_S) — for errors retrying can't fix."""
    seconds = config.LLM_PROVIDER_COOLDOWN_S if seconds is None else seconds
    already_skipped = not provider_available(provider)
    _unavailable_until[provider] = time.monotonic() + seconds
    if not already_skipped:
        logger.warning(f"{provider}: {reason} — skipping it for {seconds:.0f}s")


def reset_provider_status() -> None:
    """Forget every cooldown (used by the test suite)."""
    _unavailable_until.clear()


def is_account_error(status_code: Optional[int], message: str = "") -> bool:
    """
    Errors no retry will fix soon: an invalid or revoked key (401), no
    access (403), or an account that can't pay for requests — Anthropic
    answers that with 400 "Your credit balance is too low".
    """
    if status_code in (401, 403):
        return True
    return status_code == 400 and "credit balance" in message.lower()


def retry_after_seconds(error: Exception) -> Optional[float]:
    """The server's retry-after header, in seconds, if it sent one."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    value = headers.get("retry-after")
    try:
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None


def retry_delay(attempt: int, error: Exception, waited: float) -> Optional[float]:
    """
    Seconds to wait before retrying after `attempt` (0-based) failed with a
    retryable error, or None to stop and let the next provider answer now:
      - never after the final attempt;
      - at least the server's retry-after, so a retry isn't wasted;
      - never beyond LLM_RETRY_WAIT_BUDGET_S of total waiting per call,
        whatever LLM_MAX_RETRIES / LLM_RETRY_BASE_DELAY are set to.
    """
    if attempt >= config.LLM_MAX_RETRIES:
        return None
    delay = max(config.LLM_RETRY_BASE_DELAY * (2 ** attempt), retry_after_seconds(error) or 0.0)
    if waited + delay > config.LLM_RETRY_WAIT_BUDGET_S:
        return None
    return delay

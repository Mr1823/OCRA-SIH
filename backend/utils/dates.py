"""
Resolve the date a user asked about ("today", "tomorrow", "2026-09-16",
"நாளை") into a calendar date in Indian Standard Time.

Data sources describe either current conditions or a forecast for one
specific day. Callers use this to decide which to fetch, and whether an
answer needs to say it isn't about the date the user asked for.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# India has a single, DST-free time zone, so a fixed offset is enough.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
IST_TZ_NAME = "Asia/Kolkata"  # the same zone, as named in Open-Meteo requests

# Open-Meteo's marine forecast reaches about a week ahead.
MAX_FORECAST_DAYS = 7

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Phrases that mean "today" — current conditions answer them.
_TODAY_PHRASES = (
    "today", "now", "right now", "currently", "tonight",
    "this morning", "this afternoon", "this evening", "இன்று", "இப்போது",
)


def today_ist() -> date:
    return datetime.now(IST).date()


def resolve_requested_date(requested: Optional[str], today: Optional[date] = None) -> Optional[date]:
    """
    Map a date phrase from intent detection to a calendar date.

    An empty phrase means today. Returns None when the phrase can't be
    interpreted (e.g. "next Monday"), so callers can say so instead of
    silently answering for today.
    """
    today = today or today_ist()
    text = (requested or "").strip().lower()

    if not text or text in _TODAY_PHRASES:
        return today
    if "day after tomorrow" in text or "நாளை மறுநாள்" in text:
        return today + timedelta(days=2)
    if "tomorrow" in text or "நாளை" in text:
        return today + timedelta(days=1)
    if "today" in text or "இன்று" in text:
        return today

    match = _ISO_DATE.search(text)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    return None


def is_forecastable(target: date, today: Optional[date] = None) -> bool:
    """True for a future date within the forecast horizon."""
    today = today or today_ist()
    return today < target <= today + timedelta(days=MAX_FORECAST_DAYS)


def describe_date(target: date, today: Optional[date] = None) -> str:
    """'today' / 'tomorrow' / 'the day after tomorrow' / 'Thu 17 Sep 2026'."""
    today = today or today_ist()
    days_ahead = (target - today).days
    if days_ahead == 0:
        return "today"
    if days_ahead == 1:
        return "tomorrow"
    if days_ahead == 2:
        return "the day after tomorrow"
    return target.strftime("%a %d %b %Y")

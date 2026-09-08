"""
Geocoding utility — resolves place names to (lat, lon) coordinates.

Uses Nominatim (OpenStreetMap) with a hardcoded fallback dictionary of
~10 Indian coastal cities so the demo works without network access.
"""

from __future__ import annotations

from typing import Optional, Tuple

import httpx

# ──────────────────────────────────────────────
#  Hardcoded fallback: Indian coastal cities
# ──────────────────────────────────────────────

_COASTAL_CITIES: dict[str, Tuple[float, float, str]] = {
    # key (lowercase) → (lat, lon, display_name)
    "chennai": (13.08, 80.27, "Chennai, Tamil Nadu"),
    "madras": (13.08, 80.27, "Chennai, Tamil Nadu"),
    "visakhapatnam": (17.72, 83.30, "Visakhapatnam, Andhra Pradesh"),
    "vizag": (17.72, 83.30, "Visakhapatnam, Andhra Pradesh"),
    "mumbai": (19.08, 72.88, "Mumbai, Maharashtra"),
    "bombay": (19.08, 72.88, "Mumbai, Maharashtra"),
    "kochi": (9.97, 76.27, "Kochi, Kerala"),
    "cochin": (9.97, 76.27, "Kochi, Kerala"),
    "goa": (15.49, 73.83, "Goa"),
    "panaji": (15.49, 73.83, "Panaji, Goa"),
    "mangalore": (12.87, 74.88, "Mangalore, Karnataka"),
    "mangaluru": (12.87, 74.88, "Mangaluru, Karnataka"),
    "puducherry": (11.93, 79.83, "Puducherry"),
    "pondicherry": (11.93, 79.83, "Puducherry"),
    "tuticorin": (8.76, 78.13, "Tuticorin, Tamil Nadu"),
    "thoothukudi": (8.76, 78.13, "Thoothukudi, Tamil Nadu"),
    "paradip": (20.32, 86.61, "Paradip, Odisha"),
    "paradeep": (20.32, 86.61, "Paradip, Odisha"),
    "digha": (21.68, 87.55, "Digha, West Bengal"),
    "puri": (19.81, 85.83, "Puri, Odisha"),
    "ratnagiri": (16.99, 73.31, "Ratnagiri, Maharashtra"),
    "karwar": (14.81, 74.13, "Karwar, Karnataka"),
    "kakinada": (16.94, 82.24, "Kakinada, Andhra Pradesh"),
    "machilipatnam": (16.18, 81.14, "Machilipatnam, Andhra Pradesh"),
    "rameshwaram": (9.29, 79.31, "Rameshwaram, Tamil Nadu"),
    "diu": (20.71, 70.99, "Diu"),
    "porbandar": (21.64, 69.60, "Porbandar, Gujarat"),
    "veraval": (20.90, 70.37, "Veraval, Gujarat"),
    "kolkata": (22.57, 88.36, "Kolkata, West Bengal"),
    "calcutta": (22.57, 88.36, "Kolkata, West Bengal"),
}


# ──────────────────────────────────────────────
#  Nominatim geocoding
# ──────────────────────────────────────────────

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "ORCA-Marine-Hackathon/1.0"


async def _nominatim_geocode(
    place_name: str,
) -> Optional[Tuple[float, float, str]]:
    """
    Query Nominatim for a place name.  Returns (lat, lon, display_name)
    or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={
                    "q": place_name,
                    "format": "json",
                    "limit": 1,
                    "countrycodes": "in",  # Bias towards India
                },
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                r = results[0]
                return (
                    float(r["lat"]),
                    float(r["lon"]),
                    r.get("display_name", place_name),
                )
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────


async def geocode(place_name: str) -> Tuple[float, float, str]:
    """
    Resolve a place name to (lat, lon, display_name).

    Strategy:
      1. Check the hardcoded coastal-cities dictionary (instant, no network).
      2. Fall back to Nominatim (network call, may fail).
      3. If both fail, raise ValueError.

    Parameters
    ----------
    place_name : str
        A city/location name, e.g. "Chennai", "near Vizag", "Mumbai coast".

    Returns
    -------
    tuple of (latitude, longitude, display_name)
    """
    # Normalise: lowercase, strip common prefixes
    cleaned = place_name.lower().strip()
    for prefix in ("near ", "around ", "off ", "coast of ", "close to "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    # Also strip trailing "coast", "port", "harbour"
    for suffix in (" coast", " port", " harbour", " harbor", " beach"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()

    # 1. Hardcoded lookup
    if cleaned in _COASTAL_CITIES:
        return _COASTAL_CITIES[cleaned]

    # 2. Partial match — check if any city name is contained in the input
    for city_key, coords in _COASTAL_CITIES.items():
        if city_key in cleaned or cleaned in city_key:
            return coords

    # 3. Nominatim fallback
    result = await _nominatim_geocode(place_name)
    if result:
        return result

    raise ValueError(
        f"Could not resolve location: '{place_name}'. "
        f"Try a specific Indian coastal city name like Chennai, Mumbai, or Vizag."
    )

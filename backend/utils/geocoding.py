"""
Geocoding utility — resolves place names to (lat, lon) coordinates.

Uses Nominatim (OpenStreetMap) with a hardcoded fallback dictionary of
Indian coastal cities (plus all 13 coastal districts of Tamil Nadu) so
the demo works without network access.
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
#  Tamil Nadu's 13 coastal districts
#
#  One verified coastal fishing-harbour/town per district (not the
#  district HQ where that's inland). Coordinates checked against
#  Wikipedia and/or OSM Nominatim on 2026-09-13, not estimated.
#
#  Two substitutions from the towns most commonly suggested for these
#  districts, made because those towns are administratively in a
#  different district than expected:
#    - Ramanathapuram already had Rameshwaram in _COASTAL_CITIES above;
#      reused rather than re-verifying Mandapam separately.
#    - Tirunelveli: Manapad and Kulasekarapattinam are both actually in
#      Thoothukudi district (confirmed via Wikipedia/census records),
#      not Tirunelveli. Used Idinthakarai instead — a genuinely coastal
#      village in Radhapuram taluk, Tirunelveli district, verified via
#      OSM Nominatim (osm node 1811823206).
#
#  Note: Pazhaverkadu's verified coordinate sits on the mainland
#  (lagoon-facing) shore of Pulicat Lake, not the open-sea barrier
#  island side — see the live-data test notes for whether Open-Meteo's
#  marine grid actually covers this point.
# ──────────────────────────────────────────────

# Tamil-script names for each district and town below were verified via
# web search (Tamil Wikipedia, Government of Tamil Nadu district sites,
# census records) on 2026-09-14, not guessed — see the individual
# searches in the session transcript. Flagged here so a Tamil speaker
# can double-check them; these are place names, not the safety-verdict
# strings in synthesis.py (see the TAMIL TRANSLATIONS — PENDING HUMAN
# REVIEW block there for the ones that actually carry safety meaning).
_TN_COASTAL_DISTRICTS: list[Tuple[str, str, float, float, str, str]] = [
    # (district_en, town_en, lat, lon, district_ta, town_ta)
    ("Thiruvallur", "Pazhaverkadu (Pulicat)", 13.4177, 80.3167, "திருவள்ளூர்", "பழவேற்காடு"),
    ("Chennai", "Chennai", 13.08, 80.27, "சென்னை", "சென்னை"),
    ("Chengalpattu", "Mamallapuram", 12.6197, 80.1944, "செங்கல்பட்டு", "மாமல்லபுரம்"),
    ("Villupuram", "Marakkanam", 12.20, 79.95, "விழுப்புரம்", "மரக்காணம்"),
    ("Cuddalore", "Cuddalore", 11.7393, 79.7865, "கடலூர்", "கடலூர்"),
    ("Nagapattinam", "Nagapattinam", 10.7641, 79.8496, "நாகப்பட்டினம்", "நாகப்பட்டினம்"),
    ("Thiruvarur", "Vedaranyam", 10.3774, 79.8495, "திருவாரூர்", "வேதாரண்யம்"),
    ("Thanjavur", "Point Calimere (Kodiakkarai)", 10.2845, 79.8241, "தஞ்சாவூர்", "கோடியக்கரை"),
    ("Pudukkottai", "Kottaipattinam", 9.9791, 79.1986, "புதுக்கோட்டை", "கோட்டைப்பட்டினம்"),
    ("Ramanathapuram", "Rameshwaram", 9.29, 79.31, "இராமநாதபுரம்", "இராமேஸ்வரம்"),
    ("Thoothukudi", "Thoothukudi", 8.76, 78.13, "தூத்துக்குடி", "தூத்துக்குடி"),
    ("Tirunelveli", "Idinthakarai", 8.1787, 77.7451, "திருநெல்வேலி", "இடிந்தகரை"),
    ("Kanyakumari", "Kanyakumari", 8.0883, 77.5385, "கன்னியாகுமரி", "கன்னியாகுமரி"),
]

# Populate the lookup dict from the canonical list above — English town
# name, English district name, Tamil town name, and Tamil district name
# all resolve to the same coordinates, without clobbering entries
# already defined for Chennai/Thoothukudi/Rameshwaram/Puducherry etc.
for _district, _town, _lat, _lon, _district_ta, _town_ta in _TN_COASTAL_DISTRICTS:
    _display = f"{_town}, {_district} District, Tamil Nadu"
    _town_key = _town.split(" (")[0].lower()  # "Pazhaverkadu (Pulicat)" → "pazhaverkadu"
    _COASTAL_CITIES.setdefault(_town_key, (_lat, _lon, _display))
    _COASTAL_CITIES.setdefault(_district.lower(), (_lat, _lon, _display))
    # Tamil script has no case, so these are used exactly as written —
    # geocode()'s .lower().strip() call is a no-op on non-Latin script.
    _COASTAL_CITIES.setdefault(_town_ta, (_lat, _lon, _display))
    _COASTAL_CITIES.setdefault(_district_ta, (_lat, _lon, _display))

# A few extra common alternate names, aliased to the canonical entries above.
_TN_EXTRA_ALIASES = {
    "pulicat": "pazhaverkadu",
    "mahabalipuram": "mamallapuram",
    "kodiakkarai": "point calimere",
    "kodikkarai": "point calimere",
    "mandapam": "rameshwaram",
    "புலிகட்": "பழவேற்காடு",
    "மகாபலிபுரம்": "மாமல்லபுரம்",
}
for _alias, _canonical in _TN_EXTRA_ALIASES.items():
    if _canonical in _COASTAL_CITIES:
        _COASTAL_CITIES.setdefault(_alias, _COASTAL_CITIES[_canonical])


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


def get_all_tn_coastal_points() -> list[Tuple[str, str, float, float, str, str]]:
    """
    Return (district_en, town_en, lat, lon, district_ta, town_ta) for
    all 13 coastal districts of Tamil Nadu.

    Lets a caller — e.g. a future "browse all Tamil Nadu conditions"
    feature — iterate every district in one call, without needing to
    know each district's representative coastal town by name, in
    either language.
    """
    return list(_TN_COASTAL_DISTRICTS)

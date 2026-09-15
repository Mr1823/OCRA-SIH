"""
Copernicus Marine Service provider — real satellite ocean-color
chlorophyll-a data for the Indian Ocean / Indian coast.

Verified against Copernicus's current catalog and Python Toolbox docs
on 2026-09-13 (their product/dataset naming has changed more than once,
so re-check before assuming a failure here means "service is down"):

  Package    : copernicusmarine (pip install copernicusmarine)
               https://pypi.org/project/copernicusmarine/
  Product    : OCEANCOLOUR_GLO_BGC_L4_NRT_009_102 — "Global Ocean
               Colour (Copernicus-GlobColour), BGC, L4 (daily
               gap-free) from Satellite Observations (NRT)". This is
               real satellite ocean-color, not a biogeochemical model
               reanalysis (that would be GLOBAL_ANALYSISFORECAST_BGC).
  Dataset ID : cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km_P1D_202311
               The trailing "_202311" is a Marine Data Store
               processing-batch suffix and does get renamed over time —
               if this starts failing, check the current id at
               https://data.marine.copernicus.eu/product/OCEANCOLOUR_GLO_BGC_L4_NRT_009_102/services
  Variable   : CHL (mg/m^3) — mass_concentration_of_chlorophyll_a_in_sea_water
  Auth       : copernicusmarine.open_dataset() accepts username/password
               as direct keyword arguments (current toolbox docs) — no
               separate token exchange needed for read access.

"Gap-free" means cloud gaps are already space-time interpolated
upstream, but the most recent day or two can still come back all-NaN
while that interpolation catches up — we walk back a few days to find
the latest valid reading instead of treating that as "no data".
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger("orca.data_sources.copernicus")

_DATASET_ID = "cmems_obs-oc_glo_bgc-plankton_nrt_l4-gapfree-multi-4km_P1D_202311"
_VARIABLE = "CHL"
_TIMEOUT_S = 20.0
_MAX_DAYS_BACK = 5  # how far back to search for a non-cloud-masked reading


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _fetch_chl_sync(lat: float, lon: float) -> Optional[tuple[float, str]]:
    """Blocking call into the Copernicus Marine Toolbox — run via a thread."""
    import copernicusmarine

    ds = copernicusmarine.open_dataset(
        dataset_id=_DATASET_ID,
        variables=[_VARIABLE],
        minimum_longitude=lon,
        maximum_longitude=lon,
        minimum_latitude=lat,
        maximum_latitude=lat,
        coordinates_selection_method="nearest",
        username=config.CMEMS_USERNAME,
        password=config.CMEMS_PASSWORD,
    )

    da = ds[_VARIABLE].squeeze(drop=True)

    if "time" not in da.dims:
        value = da.values.item()
        if _is_missing(value):
            return None
        return float(value), datetime.now(timezone.utc).isoformat()

    n = da.sizes["time"]
    for i in range(1, min(n, _MAX_DAYS_BACK) + 1):
        value = da.isel(time=-i).values.item()
        if not _is_missing(value):
            import numpy as np

            time_val = ds["time"].isel(time=-i).values
            ts = str(np.datetime_as_string(time_val, unit="s")) + "Z"
            return float(value), ts

    return None  # every recent day is cloud/gap-masked at this point


async def fetch_chlorophyll(lat: float, lon: float) -> Optional[dict]:
    """
    Fetch near-real-time chlorophyll-a (mg/m^3) for the nearest available
    grid point to (lat, lon).

    Returns {"chlorophyll_mg_m3": float, "data_timestamp": str} tagged
    with the satellite pass the value came from, or None if Copernicus
    is unreachable, unauthenticated, or has no valid reading nearby.
    The caller decides the fallback — this function never invents a
    number.
    """
    if not config.CMEMS_USERNAME or not config.CMEMS_PASSWORD:
        logger.warning(
            "Copernicus Marine credentials not configured (CMEMS_USERNAME/"
            "CMEMS_PASSWORD) — skipping live chlorophyll fetch"
        )
        return None

    try:
        import copernicusmarine  # noqa: F401
    except ImportError:
        logger.warning("copernicusmarine not installed — skipping live chlorophyll fetch")
        return None

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_fetch_chl_sync, lat, lon),
            timeout=_TIMEOUT_S,
        )
    except Exception as e:
        logger.warning(f"Copernicus chlorophyll fetch failed for ({lat}, {lon}): {e}")
        return None

    if result is None:
        logger.info(f"No valid Copernicus chlorophyll reading near ({lat}, {lon}) — cloud/data gap")
        return None

    value, ts = result
    return {"chlorophyll_mg_m3": value, "data_timestamp": ts}


# ──────────────────────────────────────────────
#  Fallback climatology (NOT live data)
# ──────────────────────────────────────────────

# Rough, hand-picked seasonal/regional fallback figures for when
# Copernicus is unreachable or has no valid reading nearby. These are
# NOT a calibrated climatology product — they exist only so an outage
# shows a plausible regional figure instead of 0.0 (which misleadingly
# reads as "no fish anywhere"). Loosely backed by published ranges for
# Arabian Sea vs Bay of Bengal chlorophyll-a — e.g. SW-monsoon
# upwelling on the west coast reaching roughly 1.5-3.0 mg/m^3 versus a
# much more oligotrophic Bay of Bengal — deliberately rounded down from
# the top of that range since these numbers stand in for "typical",
# not "peak". Treat as a coarse placeholder; swap in a real multi-year
# climatology product if precision here ever matters.
#
# The west/east split uses longitude 77.5°E (near Kanyakumari, the
# southern tip of the Indian peninsula) as a simple proxy for
# "Arabian Sea side" vs "Bay of Bengal side" — a coastal heuristic,
# not a general ocean-basin classifier.
_WEST_COAST_LON_SPLIT = 77.5
_MONSOON_MONTHS = {6, 7, 8, 9}  # SW monsoon, roughly June-September

_CLIMATOLOGY_MG_M3 = {
    ("west", "monsoon"): 1.2,
    ("west", "other"): 0.4,
    ("east", "monsoon"): 0.35,
    ("east", "other"): 0.2,
}


def climatology_chlorophyll(lat: float, lon: float, when: Optional[datetime] = None) -> float:
    """
    Rough seasonal/regional fallback chlorophyll (mg/m^3) — see the
    module-level note above. Only call this when a real reading
    (Copernicus, or some future live source) isn't available; never
    use it to silently replace a genuine 0.0 reading.
    """
    when = when or datetime.now(timezone.utc)
    coast = "west" if lon < _WEST_COAST_LON_SPLIT else "east"
    season = "monsoon" if when.month in _MONSOON_MONTHS else "other"
    return _CLIMATOLOGY_MG_M3[(coast, season)]

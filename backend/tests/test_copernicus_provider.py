"""
Tests for the Copernicus Marine Service chlorophyll provider and its
climatology fallback.

The key regression this guards against: a None result from Copernicus
must never silently become 0.0 without the fallback/labelling logic in
live_provider.py explicitly kicking in (see test_live_provider.py for
the integration-level check of that).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from data_sources.copernicus_provider import climatology_chlorophyll, fetch_chlorophyll


def _make_fake_dataset(chl_values):
    """Build a minimal xarray Dataset shaped like the real CHL product."""
    xr = pytest.importorskip("xarray")
    import numpy as np
    import pandas as pd

    n = len(chl_values)
    dates = pd.date_range("2026-09-09", periods=n, freq="D")
    data = np.array(chl_values, dtype=float).reshape(n, 1, 1)
    return xr.Dataset(
        {"CHL": (("time", "latitude", "longitude"), data)},
        coords={"time": dates, "latitude": [13.0], "longitude": [80.25]},
    )


@pytest.fixture(autouse=True)
def _configure_credentials(monkeypatch):
    """Most tests need credentials configured to reach the fetch path at all."""
    monkeypatch.setattr(config, "CMEMS_USERNAME", "test_user")
    monkeypatch.setattr(config, "CMEMS_PASSWORD", "test_pass")


def _install_fake_copernicusmarine(open_dataset_return=None, open_dataset_side_effect=None):
    fake_module = MagicMock()
    if open_dataset_side_effect is not None:
        fake_module.open_dataset.side_effect = open_dataset_side_effect
    else:
        fake_module.open_dataset.return_value = open_dataset_return
    return fake_module


# ══════════════════════════════════════════════
#  fetch_chlorophyll — success paths
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_chlorophyll_success_returns_latest_value():
    """A valid latest-day reading is returned as-is, not a fallback."""
    ds = _make_fake_dataset([0.31, 0.45])
    fake_module = _install_fake_copernicusmarine(open_dataset_return=ds)

    with patch.dict(sys.modules, {"copernicusmarine": fake_module}):
        result = await fetch_chlorophyll(13.0, 80.25)

    assert result is not None
    assert result["chlorophyll_mg_m3"] == pytest.approx(0.45)
    assert "data_timestamp" in result


@pytest.mark.asyncio
async def test_fetch_chlorophyll_walks_back_past_cloud_gap():
    """Most recent day is cloud-masked (NaN) — use the prior valid day instead of failing."""
    ds = _make_fake_dataset([0.5, float("nan")])
    fake_module = _install_fake_copernicusmarine(open_dataset_return=ds)

    with patch.dict(sys.modules, {"copernicusmarine": fake_module}):
        result = await fetch_chlorophyll(13.0, 80.25)

    assert result is not None
    assert result["chlorophyll_mg_m3"] == pytest.approx(0.5)


# ══════════════════════════════════════════════
#  fetch_chlorophyll — failure paths must return None, never 0.0
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fetch_chlorophyll_all_recent_days_nan_returns_none():
    """Every recent day is cloud-masked — genuinely no data, must be None (not 0.0)."""
    ds = _make_fake_dataset([float("nan")] * 5)
    fake_module = _install_fake_copernicusmarine(open_dataset_return=ds)

    with patch.dict(sys.modules, {"copernicusmarine": fake_module}):
        result = await fetch_chlorophyll(13.0, 80.25)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_chlorophyll_auth_failure_returns_none():
    """Copernicus rejects the credentials — must return None, not raise or default to 0.0."""
    fake_module = _install_fake_copernicusmarine(
        open_dataset_side_effect=RuntimeError("401 Unauthorized")
    )

    with patch.dict(sys.modules, {"copernicusmarine": fake_module}):
        result = await fetch_chlorophyll(13.0, 80.25)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_chlorophyll_network_failure_returns_none():
    """Copernicus unreachable — must return None, not raise."""
    fake_module = _install_fake_copernicusmarine(
        open_dataset_side_effect=ConnectionError("network unreachable")
    )

    with patch.dict(sys.modules, {"copernicusmarine": fake_module}):
        result = await fetch_chlorophyll(13.0, 80.25)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_chlorophyll_missing_credentials_returns_none(monkeypatch):
    """No CMEMS_USERNAME/PASSWORD configured — should skip without even trying to import."""
    monkeypatch.setattr(config, "CMEMS_USERNAME", "")
    monkeypatch.setattr(config, "CMEMS_PASSWORD", "")

    result = await fetch_chlorophyll(13.0, 80.25)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_chlorophyll_not_installed_returns_none():
    """copernicusmarine not importable — should degrade to None, not crash the caller."""
    with patch.dict(sys.modules, {"copernicusmarine": None}):
        result = await fetch_chlorophyll(13.0, 80.25)

    assert result is None


# ══════════════════════════════════════════════
#  climatology_chlorophyll fallback — per-coast, per-season
# ══════════════════════════════════════════════


def test_climatology_west_coast_monsoon():
    when = datetime(2026, 7, 15, tzinfo=timezone.utc)
    assert climatology_chlorophyll(13.0, 74.0, when) == 1.2  # Arabian Sea side, SW monsoon


def test_climatology_west_coast_non_monsoon():
    when = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert climatology_chlorophyll(13.0, 74.0, when) == 0.4


def test_climatology_east_coast_monsoon():
    when = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert climatology_chlorophyll(13.0, 80.27, when) == 0.35  # Bay of Bengal side


def test_climatology_east_coast_non_monsoon():
    when = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert climatology_chlorophyll(13.0, 80.27, when) == 0.2


def test_climatology_never_returns_zero():
    """The whole point of this fallback is to avoid a misleading 0.0."""
    for lon in (68.0, 74.0, 77.4, 77.6, 80.0, 92.0):
        for month in range(1, 13):
            when = datetime(2026, month, 1, tzinfo=timezone.utc)
            assert climatology_chlorophyll(13.0, lon, when) > 0.0

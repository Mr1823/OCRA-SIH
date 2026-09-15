"""
Keep the test suite hermetic regardless of what's in the developer's .env.

config.py calls load_dotenv() at import time, and python-dotenv never
overrides a variable that is already set — so pinning these before
config is first imported means a test run can't spend real Groq/Anthropic
quota, call IMD/Copernicus, or silently switch to live Open-Meteo data
just because .env has USE_LIVE_DATA=true. Tests that need a key or live
mode set it explicitly with monkeypatch.
"""

import os

import pytest

for _name in (
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
    "IMD_API_KEY",
    "IMD_AUTH_TOKEN",
    "CMEMS_USERNAME",
    "CMEMS_PASSWORD",
):
    os.environ[_name] = ""

os.environ["USE_LIVE_DATA"] = "false"
os.environ["ENABLE_LIVE_PFZ_GRID"] = "false"


@pytest.fixture(autouse=True)
def _reset_llm_provider_cooldowns():
    """A provider put in cooldown by one test must not silently skip calls in the next."""
    from utils.llm import reset_provider_status

    reset_provider_status()
    yield
    reset_provider_status()

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

"""
Tests for the Groq integration in orchestrator.py and synthesis.py —
the LLM provider in front of the keyword/template fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import groq
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.orchestrator import _call_groq_with_retry
from agents.synthesis import _build_data_summary, _generate_groq_answer


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def _tool_call(name: str, arguments_json: str) -> SimpleNamespace:
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments_json))


def _fake_completion(content: str | None = None, tool_calls: list | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _rate_limit_error() -> groq.RateLimitError:
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers={}, json={"error": {"message": "rate limited"}})
    return groq.RateLimitError("rate limited", response=resp, body=None)


def _api_status_error(status_code: int) -> groq.APIStatusError:
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(status_code, request=req, headers={}, json={"error": {"message": f"{status_code} error"}})
    return groq.APIStatusError(f"{status_code} error", response=resp, body=None)


@pytest.fixture(autouse=True)
def _configure_credentials(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "gsk-test-key")
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 2)
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 0.01)


def _mock_client(create_mock: MagicMock):
    client_instance = MagicMock()
    client_instance.chat.completions.create = create_mock
    return patch("groq.AsyncGroq", return_value=client_instance)


# ══════════════════════════════════════════════
#  _call_groq_with_retry — tool_call parsing
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_groq_returns_tool_call_as_name_and_args():
    create_mock = AsyncMock(
        return_value=_fake_completion(
            tool_calls=[_tool_call("assess_sea_safety", '{"location": "Chennai", "date": "today"}')]
        )
    )
    with _mock_client(create_mock):
        result = await _call_groq_with_retry("Is it safe near Chennai?")

    assert result == {"name": "assess_sea_safety", "args": {"location": "Chennai", "date": "today"}}
    _, kwargs = create_mock.call_args
    assert kwargs["model"] == config.GROQ_MODEL
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["parameters"]  # schema carried through under "parameters"


@pytest.mark.asyncio
async def test_groq_text_only_response_returns_none():
    create_mock = AsyncMock(return_value=_fake_completion(content="Could you clarify the location?"))
    with _mock_client(create_mock):
        result = await _call_groq_with_retry("What's the weather like?")

    assert result is None


# ══════════════════════════════════════════════
#  Retry behaviour
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_groq_rate_limit_retries_then_succeeds():
    create_mock = AsyncMock(
        side_effect=[
            _rate_limit_error(),
            _fake_completion(tool_calls=[_tool_call("check_alerts", '{"location": "Vizag"}')]),
        ]
    )
    with _mock_client(create_mock):
        result = await _call_groq_with_retry("Any alerts near Vizag?")

    assert result == {"name": "check_alerts", "args": {"location": "Vizag"}}
    assert create_mock.call_count == 2


@pytest.mark.asyncio
async def test_groq_client_error_4xx_is_not_retried():
    create_mock = AsyncMock(side_effect=_api_status_error(400))
    with _mock_client(create_mock):
        result = await _call_groq_with_retry("Is it safe near Chennai?")

    assert result is None
    create_mock.assert_called_once()


# ══════════════════════════════════════════════
#  Short-circuits
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_groq_missing_api_key_returns_none_without_calling(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    create_mock = AsyncMock()
    with _mock_client(create_mock):
        result = await _call_groq_with_retry("Is it safe near Chennai?")

    assert result is None
    create_mock.assert_not_called()


@pytest.mark.asyncio
async def test_groq_not_installed_returns_none():
    with patch.dict(sys.modules, {"groq": None}):
        result = await _call_groq_with_retry("Is it safe near Chennai?")

    assert result is None


# ══════════════════════════════════════════════
#  synthesis._generate_groq_answer
# ══════════════════════════════════════════════


def _handler_result():
    return {
        "intent": "assess_sea_safety",
        "location": {"name": "Chennai", "lat": 13.08, "lon": 80.27},
        "ocean_weather": {
            "ocean": {"sst_celsius": 28.0, "chlorophyll_mg_m3": 0.4, "wave_height_m": 1.0},
            "weather": {"wind_speed_kmh": 15.0, "wind_direction": "SW", "visibility_km": 10.0, "condition": "Clear"},
        },
        "risk_assessment": {"verdict": "safe", "risk_score": 0, "reasons": ["Calm seas"]},
        "date": "today",
    }


@pytest.mark.asyncio
async def test_generate_groq_answer_success():
    create_mock = AsyncMock(return_value=_fake_completion(content=" It's safe to head out today. "))
    with _mock_client(create_mock):
        answer = await _generate_groq_answer(
            _handler_result(), "Is it safe near Chennai?", _build_data_summary(_handler_result())
        )

    assert answer == "It's safe to head out today."
    _, kwargs = create_mock.call_args
    assert kwargs["model"] == config.GROQ_MODEL
    assert "tools" not in kwargs


@pytest.mark.asyncio
async def test_generate_groq_answer_failure_returns_none():
    create_mock = AsyncMock(side_effect=_api_status_error(500))
    with _mock_client(create_mock):
        answer = await _generate_groq_answer(
            _handler_result(), "Is it safe near Chennai?", _build_data_summary(_handler_result())
        )

    assert answer is None


@pytest.mark.asyncio
async def test_generate_groq_answer_missing_key_returns_none(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    create_mock = AsyncMock()
    with _mock_client(create_mock):
        answer = await _generate_groq_answer(
            _handler_result(), "Is it safe near Chennai?", _build_data_summary(_handler_result())
        )

    assert answer is None
    create_mock.assert_not_called()

"""
Tests for the Claude (Anthropic) integration in orchestrator.py and
synthesis.py — tool-use intent detection, plain-text answer synthesis,
and the retry/fallback behaviour around anthropic.RateLimitError /
anthropic.APIStatusError.

Mocks `anthropic.Anthropic` (via its `messages.create`) the way the old
suite would have mocked `google.generativeai`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.orchestrator import _call_claude_with_retry
from agents.synthesis import _build_data_summary, _generate_llm_answer


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=input_)


def _fake_message(content: list) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def _rate_limit_error(retry_after: str = "1") -> anthropic.RateLimitError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(
        429,
        request=req,
        headers={"retry-after": retry_after},
        json={"type": "error", "error": {"type": "rate_limit_error", "message": "rate limited"}},
    )
    return anthropic.RateLimitError("rate limited", response=resp, body=None)


def _api_status_error(status_code: int) -> anthropic.APIStatusError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(
        status_code,
        request=req,
        headers={},
        json={"type": "error", "error": {"type": "api_error", "message": f"{status_code} error"}},
    )
    return anthropic.APIStatusError(f"{status_code} error", response=resp, body=None)


@pytest.fixture(autouse=True)
def _configure_credentials(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 2)
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 0.01)  # keep retry tests fast


def _mock_client(create_mock: MagicMock):
    client_instance = MagicMock()
    client_instance.messages.create = create_mock
    return patch("anthropic.Anthropic", return_value=client_instance)


# ══════════════════════════════════════════════
#  _call_claude_with_retry — tool_use parsing
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_claude_returns_tool_use_as_name_and_args():
    create_mock = MagicMock(
        return_value=_fake_message([_tool_use_block("assess_sea_safety", {"location": "Chennai", "date": "today"})])
    )
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Is it safe near Chennai?")

    assert result == {"name": "assess_sea_safety", "args": {"location": "Chennai", "date": "today"}}
    create_mock.assert_called_once()
    _, kwargs = create_mock.call_args
    assert kwargs["model"] == config.ANTHROPIC_MODEL
    assert kwargs["system"]
    assert kwargs["tools"][0]["input_schema"]  # Claude's tool key, not Gemini's "parameters"


@pytest.mark.asyncio
async def test_claude_text_only_response_returns_none():
    """Claude answered with plain text instead of calling a tool — let keyword fallback take over."""
    create_mock = MagicMock(return_value=_fake_message([_text_block("Could you clarify the location?")]))
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("What's the weather like?")

    assert result is None


# ══════════════════════════════════════════════
#  Retry behaviour — typed exceptions, not string matching
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rate_limit_error_retries_then_succeeds():
    create_mock = MagicMock(
        side_effect=[
            _rate_limit_error(),
            _fake_message([_tool_use_block("check_alerts", {"location": "Vizag"})]),
        ]
    )
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Any alerts near Vizag?")

    assert result == {"name": "check_alerts", "args": {"location": "Vizag"}}
    assert create_mock.call_count == 2


@pytest.mark.asyncio
async def test_rate_limit_error_exhausts_retries_returns_none():
    create_mock = MagicMock(side_effect=_rate_limit_error())
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Any alerts near Vizag?")

    assert result is None
    assert create_mock.call_count == config.LLM_MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_server_error_5xx_is_retried():
    create_mock = MagicMock(
        side_effect=[
            _api_status_error(503),
            _fake_message([_tool_use_block("find_nearest_pfz", {"location": "Mumbai"})]),
        ]
    )
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Where can I fish near Mumbai?")

    assert result == {"name": "find_nearest_pfz", "args": {"location": "Mumbai"}}
    assert create_mock.call_count == 2


@pytest.mark.asyncio
async def test_client_error_4xx_is_not_retried():
    """A non-retryable 4xx (e.g. bad request) should fail fast, not burn through retries."""
    create_mock = MagicMock(side_effect=_api_status_error(400))
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Is it safe near Chennai?")

    assert result is None
    create_mock.assert_called_once()  # no retries for a 4xx


# ══════════════════════════════════════════════
#  Short-circuits
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_api_key_returns_none_without_calling_claude(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    create_mock = MagicMock()
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Is it safe near Chennai?")

    assert result is None
    create_mock.assert_not_called()


@pytest.mark.asyncio
async def test_placeholder_api_key_returns_none_without_calling_claude(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "your_key_here")
    create_mock = MagicMock()
    with _mock_client(create_mock):
        result = await _call_claude_with_retry("Is it safe near Chennai?")

    assert result is None
    create_mock.assert_not_called()


@pytest.mark.asyncio
async def test_anthropic_not_installed_returns_none():
    with patch.dict(sys.modules, {"anthropic": None}):
        result = await _call_claude_with_retry("Is it safe near Chennai?")

    assert result is None


# ══════════════════════════════════════════════
#  synthesis._generate_llm_answer
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
async def test_generate_llm_answer_success():
    create_mock = MagicMock(return_value=_fake_message([_text_block(" It's safe to head out today. ")]))
    with _mock_client(create_mock):
        answer = await _generate_llm_answer(
            _handler_result(), "Is it safe near Chennai?", _build_data_summary(_handler_result())
        )

    assert answer == "It's safe to head out today."
    _, kwargs = create_mock.call_args
    assert kwargs["model"] == config.ANTHROPIC_MODEL
    assert "tools" not in kwargs  # plain text generation, no tool use


@pytest.mark.asyncio
async def test_generate_llm_answer_failure_returns_none_for_template_fallback():
    create_mock = MagicMock(side_effect=_api_status_error(500))
    with _mock_client(create_mock):
        answer = await _generate_llm_answer(
            _handler_result(), "Is it safe near Chennai?", _build_data_summary(_handler_result())
        )

    assert answer is None


@pytest.mark.asyncio
async def test_generate_llm_answer_missing_key_returns_none(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    create_mock = MagicMock()
    with _mock_client(create_mock):
        answer = await _generate_llm_answer(
            _handler_result(), "Is it safe near Chennai?", _build_data_summary(_handler_result())
        )

    assert answer is None
    create_mock.assert_not_called()

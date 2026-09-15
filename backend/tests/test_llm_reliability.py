"""
LLM call reliability — the root cause of the 80–100 s responses.

Measured against the previous code with a local fake API (Groq: HTTP 429
with retry-after 30 s; Claude: HTTP 400 "credit balance is too low", which
is what the configured Anthropic key really returns): one query took 90.4 s.
  - intent detection backed off 2+4+8+16 s regardless of retry-after, the
    last sleep coming after the final attempt (30 s);
  - answer generation's Groq client kept the SDK's 2 default retries, each
    honouring the 30 s retry-after (60 s);
  - Claude could never answer, so all of it ended in the keyword fallback.
The sync SDK clients also blocked the event loop, stalling every other
request for the whole time.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import groq
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import agents.orchestrator as orch
import agents.synthesis as synth


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def _groq_error(status: int, retry_after: str | None = None) -> groq.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(status, request=request, headers=headers, json={"error": {"message": str(status)}})
    error_class = groq.RateLimitError if status == 429 else groq.APIStatusError
    return error_class(f"Error code: {status}", response=response, body=None)


def _credit_balance_error() -> anthropic.APIStatusError:
    message = "Your credit balance is too low to access the Anthropic API."
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        400, request=request, json={"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    )
    return anthropic.BadRequestError(message, response=response, body=None)


def _tool_call_completion() -> SimpleNamespace:
    call = SimpleNamespace(function=SimpleNamespace(
        name="assess_sea_safety", arguments='{"location": "Chennai", "date": "today"}'
    ))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])


def _text_completion(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))])


def _groq_client(create):
    client = MagicMock()
    client.chat.completions.create = create
    return patch("groq.AsyncGroq", return_value=client)


def _claude_client(create):
    client = MagicMock()
    client.messages.create = create
    return patch("anthropic.AsyncAnthropic", return_value=client)


@pytest.fixture(autouse=True)
def _llm_setup(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "gsk-test-key")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("USE_LIVE_DATA", "false")
    # The shipped defaults, whatever a local .env pins
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 1)
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 0.5)
    monkeypatch.setattr(config, "LLM_RETRY_WAIT_BUDGET_S", 3.0, raising=False)
    monkeypatch.setattr(config, "LLM_REQUEST_TIMEOUT_S", 8.0, raising=False)
    monkeypatch.setattr(config, "LLM_PROVIDER_COOLDOWN_S", 600.0, raising=False)
    # A blocking sync client anywhere in the request path is a failure.
    with patch("groq.Groq", side_effect=AssertionError("sync Groq client used")), \
         patch("anthropic.Anthropic", side_effect=AssertionError("sync Anthropic client used")):
        yield


# ══════════════════════════════════════════════
#  Retry loop
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_no_sleep_after_the_final_attempt(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 2)
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 0.01)
    sleep = AsyncMock()
    monkeypatch.setattr(orch.asyncio, "sleep", sleep)
    create = AsyncMock(side_effect=_groq_error(503))

    with _groq_client(create):
        assert await orch._call_groq_with_retry("Is it safe near Chennai?") is None

    assert create.await_count == 3
    assert sleep.await_count == 2  # between attempts only — never after the last one


@pytest.mark.asyncio
async def test_retry_after_beyond_the_budget_moves_on_immediately():
    create = AsyncMock(side_effect=_groq_error(429, retry_after="30"))
    started = time.perf_counter()

    with _groq_client(create):
        assert await orch._call_groq_with_retry("Is it safe near Chennai?") is None

    assert create.await_count == 1
    assert time.perf_counter() - started < 1.0


@pytest.mark.asyncio
async def test_short_retry_after_is_honoured(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(orch.asyncio, "sleep", sleep)
    create = AsyncMock(side_effect=[_groq_error(429, retry_after="2"), _tool_call_completion()])

    with _groq_client(create):
        result = await orch._call_groq_with_retry("Is it safe near Chennai?")

    assert result["name"] == "assess_sea_safety"
    sleep.assert_awaited_once_with(2.0)  # the server's retry-after, not the 0.5 s base delay


@pytest.mark.asyncio
async def test_total_backoff_stays_within_budget_with_the_local_env_values(monkeypatch):
    """The local .env pins LLM_MAX_RETRIES=3 and LLM_RETRY_BASE_DELAY=2.0 — that can't bring back long stalls."""
    monkeypatch.setattr(config, "LLM_MAX_RETRIES", 3)
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 2.0)
    sleep = AsyncMock()
    monkeypatch.setattr(orch.asyncio, "sleep", sleep)
    create = AsyncMock(side_effect=_groq_error(503))

    with _groq_client(create):
        assert await orch._call_groq_with_retry("Is it safe near Chennai?") is None

    total_wait = sum(call.args[0] for call in sleep.await_args_list)
    assert 0 < total_wait <= config.LLM_RETRY_WAIT_BUDGET_S


@pytest.mark.asyncio
async def test_give_up_log_reports_the_real_attempt_count(caplog):
    create = AsyncMock(side_effect=_groq_error(400))

    with _groq_client(create), caplog.at_level("ERROR", logger="orca.orchestrator"):
        await orch._call_groq_with_retry("Is it safe near Chennai?")

    assert "gave up after 1 attempt(s)" in caplog.text
    assert "after 2 attempts" not in caplog.text


# ══════════════════════════════════════════════
#  Clients
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_llm_clients_are_async_with_a_timeout_and_no_hidden_sdk_retries():
    groq_ctor = MagicMock()
    groq_ctor.return_value.chat.completions.create = AsyncMock(return_value=_text_completion("Calm seas."))
    claude_ctor = MagicMock()
    claude_ctor.return_value.messages.create = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(type="text", text="Calm seas.")])
    )

    with patch("groq.AsyncGroq", groq_ctor), patch("anthropic.AsyncAnthropic", claude_ctor):
        await orch._call_groq_with_retry("Is it safe near Chennai?")
        await orch._call_claude_with_retry("Is it safe near Chennai?")
        assert await synth._generate_groq_answer({}, "q", "summary") == "Calm seas."
        assert await synth._generate_llm_answer({}, "q", "summary") == "Calm seas."

    for ctor in (groq_ctor, claude_ctor):
        assert ctor.call_count == 2  # intent detection + answer generation
        for call in ctor.call_args_list:
            assert call.kwargs["max_retries"] == 0
            assert call.kwargs["timeout"] == config.LLM_REQUEST_TIMEOUT_S


@pytest.mark.asyncio
async def test_a_slow_llm_call_does_not_block_other_requests():
    async def slow_create(**kwargs):
        await asyncio.sleep(0.4)
        return _tool_call_completion() if "tools" in kwargs else _text_completion("Calm seas near Chennai.")

    started = time.perf_counter()
    with _groq_client(AsyncMock(side_effect=slow_create)), _claude_client(AsyncMock()):
        results = await asyncio.gather(
            *(orch.handle_query("Is it safe to go to sea near Chennai today?") for _ in range(3))
        )
    elapsed = time.perf_counter() - started

    assert all(r["answer_text"] for r in results)
    # Each query makes two 0.4 s LLM calls: serialised, three queries would take ≥ 2.4 s.
    assert elapsed < 1.6


# ══════════════════════════════════════════════
#  Providers that can't answer
# ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_credit_balance_error_puts_claude_in_cooldown():
    create = AsyncMock(side_effect=_credit_balance_error())

    with _claude_client(create):
        assert await orch._call_claude_with_retry("Is it safe near Chennai?") is None
        assert await orch._call_claude_with_retry("Is it safe near Chennai?") is None
        assert await synth._generate_llm_answer({}, "q", "summary") is None

    assert create.await_count == 1  # later calls skip a provider that can't answer


def test_provider_cooldown_expires():
    from utils.llm import mark_provider_unavailable, provider_available

    mark_provider_unavailable("groq", "test", seconds=0)
    assert provider_available("groq")


@pytest.mark.asyncio
async def test_rate_limited_groq_and_unfunded_claude_answer_in_seconds_not_minutes():
    """The 90 s reproduction, in-process: Groq 429 (retry-after 30 s) + Claude credit-balance 400."""
    groq_create = AsyncMock(side_effect=_groq_error(429, retry_after="30"))
    claude_create = AsyncMock(side_effect=_credit_balance_error())

    started = time.perf_counter()
    with _groq_client(groq_create), _claude_client(claude_create):
        response = await orch.handle_query("Is it safe to go to sea near Chennai today?")
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert "It appears safe" in response["answer_text"]  # keyword fallback + template still answer
    assert groq_create.await_count == 1  # rate-limited once, then skipped for answer generation
    assert claude_create.await_count == 1  # unfunded once, then skipped for answer generation

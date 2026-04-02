"""Tests for the async model executor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from driftcut.config import ModelConfig
from driftcut.executor import _litellm_model_name, execute_prompt
from driftcut.models import ModelResponse


class _StoreStub:
    response_cache_enabled = True
    run_history_enabled = False
    backend_name = "redis"

    def __init__(self, cached: ModelResponse | None = None) -> None:
        self.get_baseline_response = AsyncMock(return_value=cached)
        self.save_baseline_response = AsyncMock()
        self.save_run_document = AsyncMock()
        self.close = AsyncMock()


def test_litellm_model_name() -> None:
    cfg = ModelConfig(provider="openai", model="gpt-4o")
    assert _litellm_model_name(cfg) == "openai/gpt-4o"


def test_litellm_model_name_anthropic() -> None:
    cfg = ModelConfig(provider="anthropic", model="claude-haiku")
    assert _litellm_model_name(cfg) == "anthropic/claude-haiku"


def test_litellm_model_name_openrouter() -> None:
    cfg = ModelConfig(provider="openrouter", model="openai/gpt-4o")
    assert _litellm_model_name(cfg) == "openrouter/openai/gpt-4o"


def test_model_config_api_base() -> None:
    cfg = ModelConfig(
        provider="openai",
        model="gpt-4o",
        api_base="https://my-proxy.example.com/v1",
    )
    assert cfg.api_base == "https://my-proxy.example.com/v1"


def test_model_config_defaults() -> None:
    cfg = ModelConfig(provider="openai", model="gpt-4o")
    assert cfg.api_key is None
    assert cfg.api_base is None


@pytest.mark.asyncio
async def test_execute_prompt_success() -> None:
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 20

    mock_choice = MagicMock()
    mock_choice.message.content = "Hello world"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    with (
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch("driftcut.executor.litellm.completion_cost", return_value=0.001),
    ):
        mock_ac.return_value = mock_response
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg)

    assert result.output == "Hello world"
    assert result.input_tokens == 10
    assert result.output_tokens == 20
    assert result.cost_usd == 0.001
    assert result.latency_ms > 0
    assert result.retry_count == 0
    assert result.is_error is False


@pytest.mark.asyncio
async def test_execute_prompt_non_retryable_api_error() -> None:
    with patch(
        "driftcut.executor.litellm.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("Authentication failed"),
    ):
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg)

    assert result.is_error is True
    assert result.error is not None
    assert "Authentication failed" in result.error
    assert result.output == ""
    assert result.latency_ms > 0
    assert result.retry_count == 0


@pytest.mark.asyncio
async def test_execute_prompt_retries_transient_error_and_succeeds() -> None:
    mock_choice = MagicMock()
    mock_choice.message.content = "Hello after retry"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    with (
        patch("driftcut.executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch("driftcut.executor.litellm.completion_cost", return_value=0.0),
    ):
        mock_ac.side_effect = [Exception("Rate limit exceeded"), mock_response]
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg)

    assert result.is_error is False
    assert result.output == "Hello after retry"
    assert result.retry_count == 1
    assert mock_ac.await_count == 2
    mock_sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_execute_prompt_gives_up_after_transient_retries() -> None:
    with (
        patch("driftcut.executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch(
            "driftcut.executor.litellm.acompletion",
            new_callable=AsyncMock,
            side_effect=Exception("Timeout while connecting"),
        ) as mock_ac,
    ):
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg)

    assert result.is_error is True
    assert result.error is not None
    assert "Timeout while connecting" in result.error
    assert result.retry_count == 2
    assert mock_ac.await_count == 3
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_execute_prompt_empty_content() -> None:
    mock_choice = MagicMock()
    mock_choice.message.content = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    with (
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch("driftcut.executor.litellm.completion_cost", return_value=0.0),
    ):
        mock_ac.return_value = mock_response
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg)

    assert result.output == ""
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.is_error is False


@pytest.mark.asyncio
async def test_execute_prompt_passes_api_base() -> None:
    mock_choice = MagicMock()
    mock_choice.message.content = "ok"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    with (
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch("driftcut.executor.litellm.completion_cost", return_value=0.0),
    ):
        mock_ac.return_value = mock_response
        cfg = ModelConfig(
            provider="openai",
            model="gpt-4o",
            api_base="https://my-proxy.example.com/v1",
        )
        await execute_prompt("test", cfg)

    call_kwargs = mock_ac.call_args[1]
    assert call_kwargs["api_base"] == "https://my-proxy.example.com/v1"


@pytest.mark.asyncio
async def test_execute_prompt_omits_api_base_when_none() -> None:
    mock_choice = MagicMock()
    mock_choice.message.content = "ok"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    with (
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch("driftcut.executor.litellm.completion_cost", return_value=0.0),
    ):
        mock_ac.return_value = mock_response
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        await execute_prompt("test", cfg)

    call_kwargs = mock_ac.call_args[1]
    assert "api_base" not in call_kwargs


@pytest.mark.asyncio
async def test_execute_prompt_keeps_output_when_cost_lookup_fails() -> None:
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 5
    mock_usage.completion_tokens = 7

    mock_choice = MagicMock()
    mock_choice.message.content = "still good"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    with (
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch(
            "driftcut.executor.litellm.completion_cost",
            side_effect=Exception("No pricing metadata"),
        ),
    ):
        mock_ac.return_value = mock_response
        cfg = ModelConfig(provider="openrouter", model="custom/model")
        result = await execute_prompt("test", cfg)

    assert result.is_error is False
    assert result.output == "still good"
    assert result.cost_usd == 0.0
    assert result.cost_error == "No pricing metadata"


@pytest.mark.asyncio
async def test_execute_prompt_returns_cached_baseline_response() -> None:
    cached = ModelResponse(
        output="cached baseline",
        latency_ms=0.0,
        cache_hit=True,
        historical_latency_ms=120.0,
        historical_cost_usd=0.01,
    )
    store = _StoreStub(cached=cached)

    with patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg, store=store, use_baseline_cache=True)

    assert result.cache_hit is True
    assert result.output == "cached baseline"
    assert result.historical_latency_ms == 120.0
    assert result.historical_cost_usd == 0.01
    mock_ac.assert_not_awaited()
    store.get_baseline_response.assert_awaited_once()
    store.save_baseline_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_prompt_saves_successful_baseline_to_cache() -> None:
    mock_choice = MagicMock()
    mock_choice.message.content = "Hello world"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    store = _StoreStub(cached=None)
    with (
        patch("driftcut.executor.litellm.acompletion", new_callable=AsyncMock) as mock_ac,
        patch("driftcut.executor.litellm.completion_cost", return_value=0.0),
    ):
        mock_ac.return_value = mock_response
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg, store=store, use_baseline_cache=True)

    assert result.output == "Hello world"
    assert result.cache_hit is False
    store.get_baseline_response.assert_awaited_once()
    store.save_baseline_response.assert_awaited_once()

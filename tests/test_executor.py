"""Tests for the async model executor."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from driftcut.config import ModelConfig
from driftcut.executor import _litellm_model_name, execute_prompt


def test_litellm_model_name():
    cfg = ModelConfig(provider="openai", model="gpt-4o")
    assert _litellm_model_name(cfg) == "openai/gpt-4o"


def test_litellm_model_name_anthropic():
    cfg = ModelConfig(provider="anthropic", model="claude-haiku")
    assert _litellm_model_name(cfg) == "anthropic/claude-haiku"


@pytest.mark.asyncio
async def test_execute_prompt_success():
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
    assert result.is_error is False


@pytest.mark.asyncio
async def test_execute_prompt_api_error():
    with patch(
        "driftcut.executor.litellm.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("Rate limit exceeded"),
    ):
        cfg = ModelConfig(provider="openai", model="gpt-4o")
        result = await execute_prompt("Say hello", cfg)

    assert result.is_error is True
    assert "Rate limit exceeded" in result.error
    assert result.output == ""
    assert result.latency_ms > 0


@pytest.mark.asyncio
async def test_execute_prompt_empty_content():
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

"""Async model executor using LiteLLM."""

from __future__ import annotations

import time
from typing import Any

import litellm

litellm.suppress_debug_info = True

from driftcut.config import ModelConfig
from driftcut.models import ModelResponse


def _litellm_model_name(config: ModelConfig) -> str:
    """Build the LiteLLM model string (e.g. 'openai/gpt-4o')."""
    return f"{config.provider}/{config.model}"


async def execute_prompt(
    prompt: str,
    model_config: ModelConfig,
) -> ModelResponse:
    """Execute a single prompt against a model and return the response.

    Tracks latency, token usage, and cost. Returns an error response
    (instead of raising) when the model call fails.
    """
    model_name = _litellm_model_name(model_config)

    start = time.perf_counter()
    try:
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
        }
        if model_config.api_key is not None:
            kwargs["api_key"] = model_config.api_key
        if model_config.api_base is not None:
            kwargs["api_base"] = model_config.api_base
        response = await litellm.acompletion(**kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        output = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        cost = 0.0
        cost_error: str | None = None
        try:
            cost = litellm.completion_cost(completion_response=response)
        except Exception as e:
            # Pricing metadata is not available for every LiteLLM provider/model.
            # Keep the successful completion instead of converting it into a hard error.
            cost_error = str(e)

        return ModelResponse(
            output=output,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            cost_error=cost_error,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ModelResponse(
            output="",
            latency_ms=elapsed_ms,
            error=str(e),
        )

"""Async model executor using LiteLLM."""

from __future__ import annotations

import time

import litellm

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
        response = await litellm.acompletion(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            api_key=model_config.api_key,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        output = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        cost = litellm.completion_cost(completion_response=response)

        return ModelResponse(
            output=output,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ModelResponse(
            output="",
            latency_ms=elapsed_ms,
            error=str(e),
        )

"""Async model executor using LiteLLM."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import litellm

from driftcut.config import ModelConfig
from driftcut.models import ModelResponse
from driftcut.store import MemoryStore

litellm.suppress_debug_info = True

_MAX_COMPLETION_ATTEMPTS = 3
_INITIAL_RETRY_DELAY_SECONDS = 0.5
_MAX_RETRY_DELAY_SECONDS = 2.0
_RETRY_MESSAGE_FRAGMENTS = (
    "rate limit",
    "too many requests",
    "timeout",
    "timed out",
    "service unavailable",
    "temporarily unavailable",
    "bad gateway",
    "internal server error",
    "connection reset",
    "connection aborted",
)


def _litellm_model_name(config: ModelConfig) -> str:
    """Build the LiteLLM model string (e.g. 'openai/gpt-4o')."""
    return f"{config.provider}/{config.model}"


def _completion_kwargs(prompt: str, model_config: ModelConfig) -> dict[str, Any]:
    """Build LiteLLM completion kwargs for one prompt."""
    kwargs: dict[str, Any] = {
        "model": _litellm_model_name(model_config),
        "messages": [{"role": "user", "content": prompt}],
    }
    if model_config.api_key is not None:
        kwargs["api_key"] = model_config.api_key
    if model_config.api_base is not None:
        kwargs["api_base"] = model_config.api_base
    return kwargs


def _load_litellm_exception(name: str) -> type[BaseException] | None:
    """Return a LiteLLM exception type when it exists in the installed version."""
    maybe_exception = getattr(litellm, name, None)
    if isinstance(maybe_exception, type) and issubclass(maybe_exception, BaseException):
        return maybe_exception
    return None


def _retryable_exception_types() -> tuple[type[BaseException], ...]:
    """Build the retryable exception tuple without depending on stub exports."""
    exception_types: list[type[BaseException]] = [httpx.TimeoutException, httpx.NetworkError]
    for name in (
        "RateLimitError",
        "Timeout",
        "APIConnectionError",
        "InternalServerError",
        "ServiceUnavailableError",
        "BadGatewayError",
    ):
        exception_type = _load_litellm_exception(name)
        if exception_type is not None:
            exception_types.append(exception_type)
    return tuple(exception_types)


_RETRYABLE_EXCEPTION_TYPES = _retryable_exception_types()


def _is_retryable_error(exc: Exception) -> bool:
    """Return whether a model-call failure is worth retrying."""
    if isinstance(exc, _RETRYABLE_EXCEPTION_TYPES):
        return True
    lowered = str(exc).lower()
    return any(fragment in lowered for fragment in _RETRY_MESSAGE_FRAGMENTS)


def _retry_delay_seconds(attempt_number: int) -> float:
    """Return exponential backoff delay for the next retry."""
    delay = _INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt_number - 1))
    return float(min(delay, _MAX_RETRY_DELAY_SECONDS))


def _response_from_completion(
    response: Any,
    *,
    latency_ms: float,
    retry_count: int,
) -> ModelResponse:
    """Convert a LiteLLM response into Driftcut's response model."""
    output = response.choices[0].message.content or ""
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    cost = 0.0
    cost_error: str | None = None
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception as exc:
        # Pricing metadata is not available for every LiteLLM provider/model.
        # Keep the successful completion instead of converting it into a hard error.
        cost_error = str(exc)

    return ModelResponse(
        output=output,
        latency_ms=latency_ms,
        retry_count=retry_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        cost_error=cost_error,
    )


async def execute_prompt(
    prompt: str,
    model_config: ModelConfig,
    *,
    store: MemoryStore | None = None,
    use_baseline_cache: bool = False,
) -> ModelResponse:
    """Execute a single prompt against a model and return the response.

    Tracks latency, token usage, and cost. Returns an error response
    (instead of raising) when the model call fails.
    """
    if use_baseline_cache and store is not None and store.response_cache_enabled:
        cached = await store.get_baseline_response(prompt, model_config)
        if cached is not None:
            return cached

    kwargs = _completion_kwargs(prompt, model_config)

    for attempt_number in range(1, _MAX_COMPLETION_ATTEMPTS + 1):
        start = time.perf_counter()
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            retry_count = attempt_number - 1
            should_retry = attempt_number < _MAX_COMPLETION_ATTEMPTS and _is_retryable_error(exc)
            if should_retry:
                await asyncio.sleep(_retry_delay_seconds(attempt_number))
                continue
            return ModelResponse(
                output="",
                latency_ms=elapsed_ms,
                retry_count=retry_count,
                error=str(exc),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result = _response_from_completion(
            response,
            latency_ms=elapsed_ms,
            retry_count=attempt_number - 1,
        )
        if use_baseline_cache and store is not None and store.response_cache_enabled:
            await store.save_baseline_response(prompt, model_config, result)
        return result

    msg = "Completion retry loop exhausted unexpectedly"
    raise RuntimeError(msg)

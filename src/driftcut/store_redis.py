"""Redis-backed optional memory store for Driftcut."""

from __future__ import annotations

import json
import logging
from typing import Any

from driftcut.config import MemoryConfig, ModelConfig
from driftcut.models import ModelResponse
from driftcut.store import baseline_cache_digest

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised via tests with fake clients
    redis_asyncio = None

logger = logging.getLogger(__name__)


class RedisStore:
    """Redis-backed store for baseline caching and run-history persistence."""

    backend_name = "redis"

    def __init__(
        self,
        *,
        redis_url: str,
        namespace: str,
        response_cache_enabled: bool,
        response_cache_ttl_seconds: int | None,
        run_history_enabled: bool,
        run_history_ttl_seconds: int | None,
        client: Any | None = None,
    ) -> None:
        self.response_cache_enabled = response_cache_enabled
        self.run_history_enabled = run_history_enabled
        self._namespace = namespace
        self._response_cache_ttl_seconds = response_cache_ttl_seconds
        self._run_history_ttl_seconds = run_history_ttl_seconds
        self._client = client if client is not None else self._build_client(redis_url)
        self._run_index_ensured = False

    @classmethod
    def from_config(cls, memory: MemoryConfig) -> RedisStore:
        return cls(
            redis_url=memory.redis_url,
            namespace=memory.namespace,
            response_cache_enabled=memory.response_cache.enabled,
            response_cache_ttl_seconds=memory.response_cache.ttl_seconds,
            run_history_enabled=memory.run_history.enabled,
            run_history_ttl_seconds=memory.run_history.ttl_seconds,
        )

    @staticmethod
    def _build_client(redis_url: str) -> Any:
        if redis_asyncio is None:
            msg = (
                "Redis memory support requires the optional 'redis' package. "
                "Install it with: pip install 'driftcut[redis]'"
            )
            raise RuntimeError(msg)
        return redis_asyncio.from_url(redis_url, decode_responses=True)

    def _baseline_cache_key(self, prompt: str, model_config: ModelConfig) -> str:
        digest = baseline_cache_digest(prompt, model_config)
        return f"{self._namespace}:cache:baseline:{digest}"

    def _run_key(self, run_id: str) -> str:
        return f"{self._namespace}:run:{run_id}"

    @property
    def _run_index_name(self) -> str:
        return f"idx:{self._namespace}:runs"

    async def get_baseline_response(
        self,
        prompt: str,
        model_config: ModelConfig,
    ) -> ModelResponse | None:
        if not self.response_cache_enabled:
            return None

        key = self._baseline_cache_key(prompt, model_config)
        try:
            raw = await self._client.execute_command("JSON.GET", key)
        except Exception as exc:  # pragma: no cover - warning path
            logger.warning("Redis baseline cache read failed: %s", exc)
            return None
        if raw in (None, ""):
            return None

        payload = json.loads(raw) if isinstance(raw, str) else raw
        response = payload["response"]
        return ModelResponse(
            output=response["output"],
            latency_ms=0.0,
            retry_count=0,
            input_tokens=response.get("input_tokens", 0),
            output_tokens=response.get("output_tokens", 0),
            cost_usd=0.0,
            cost_error=response.get("cost_error"),
            error=response.get("error"),
            cache_hit=True,
            historical_latency_ms=response.get("latency_ms"),
            historical_cost_usd=response.get("cost_usd"),
        )

    async def save_baseline_response(
        self,
        prompt: str,
        model_config: ModelConfig,
        response: ModelResponse,
    ) -> None:
        if not self.response_cache_enabled or response.is_error or response.cache_hit:
            return

        payload = {
            "provider": model_config.provider,
            "model": model_config.model,
            "api_base": model_config.api_base,
            "response": {
                "output": response.output,
                "latency_ms": response.latency_ms,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "cost_error": response.cost_error,
                "error": response.error,
            },
        }
        key = self._baseline_cache_key(prompt, model_config)
        try:
            await self._client.execute_command("JSON.SET", key, "$", json.dumps(payload))
            if self._response_cache_ttl_seconds is not None:
                await self._client.expire(key, self._response_cache_ttl_seconds)
        except Exception as exc:  # pragma: no cover - warning path
            logger.warning("Redis baseline cache write failed: %s", exc)

    async def save_run_document(
        self,
        run_id: str,
        payload: dict[str, object],
    ) -> None:
        if not self.run_history_enabled:
            return

        key = self._run_key(run_id)
        try:
            await self._ensure_run_index()
            await self._client.execute_command("JSON.SET", key, "$", json.dumps(payload))
            if self._run_history_ttl_seconds is not None:
                await self._client.expire(key, self._run_history_ttl_seconds)
        except Exception as exc:  # pragma: no cover - warning path
            logger.warning("Redis run-history write failed: %s", exc)

    async def _ensure_run_index(self) -> None:
        if self._run_index_ensured:
            return
        try:
            await self._client.execute_command(
                "FT.CREATE",
                self._run_index_name,
                "ON",
                "JSON",
                "PREFIX",
                "1",
                f"{self._namespace}:run:",
                "SCHEMA",
                "$.run_id",
                "AS",
                "run_id",
                "TAG",
                "$.mode",
                "AS",
                "mode",
                "TAG",
                "$.memory_backend",
                "AS",
                "memory_backend",
                "TAG",
                "$.baseline_model",
                "AS",
                "baseline_model",
                "TAG",
                "$.candidate_model",
                "AS",
                "candidate_model",
                "TAG",
                "$.decision.outcome",
                "AS",
                "outcome",
                "TAG",
                "$.decision.metrics.overall_risk",
                "AS",
                "overall_risk",
                "NUMERIC",
                "$.decision.metrics.schema_break_rate",
                "AS",
                "schema_break_rate",
                "NUMERIC",
                "$.decision.metrics.high_criticality_failure_rate",
                "AS",
                "high_criticality_failure_rate",
                "NUMERIC",
                "$.archetype_names[*]",
                "AS",
                "archetype",
                "TAG",
            )
        except Exception as exc:  # pragma: no cover - warning path
            if "Index already exists" not in str(exc):
                logger.warning("Redis run-history index setup failed: %s", exc)
        self._run_index_ensured = True

    async def close(self) -> None:
        for attr in ("aclose", "close"):
            close_method = getattr(self._client, attr, None)
            if close_method is None:
                continue
            maybe_awaitable = close_method()
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable
            return

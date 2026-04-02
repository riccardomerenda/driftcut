"""Optional memory-store abstractions for Driftcut."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from driftcut.config import MemoryConfig, ModelConfig
from driftcut.models import ModelResponse


class MemoryStore(Protocol):
    """Small async interface used by executor and runner."""

    backend_name: str
    response_cache_enabled: bool
    run_history_enabled: bool

    async def get_baseline_response(
        self,
        prompt: str,
        model_config: ModelConfig,
    ) -> ModelResponse | None: ...

    async def save_baseline_response(
        self,
        prompt: str,
        model_config: ModelConfig,
        response: ModelResponse,
    ) -> None: ...

    async def save_run_document(
        self,
        run_id: str,
        payload: dict[str, object],
    ) -> None: ...

    async def close(self) -> None: ...


def baseline_cache_digest(prompt: str, model_config: ModelConfig) -> str:
    """Return a stable digest for one baseline prompt execution context."""
    fingerprint = {
        "provider": model_config.provider,
        "model": model_config.model,
        "api_base": model_config.api_base,
    }
    raw = json.dumps(
        {
            "prompt": prompt,
            "model": fingerprint,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_memory_store(memory: MemoryConfig | None) -> MemoryStore:
    """Build the configured memory store or a no-op fallback."""
    if memory is None:
        from driftcut.store_null import NullMemoryStore

        return NullMemoryStore()

    if memory.backend == "redis":
        from driftcut.store_redis import RedisStore

        return RedisStore.from_config(memory)

    msg = f"Unsupported memory backend: {memory.backend}"
    raise ValueError(msg)

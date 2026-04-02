"""No-op memory store used when Driftcut memory is disabled."""

from __future__ import annotations

from driftcut.config import ModelConfig
from driftcut.models import ModelResponse


class NullMemoryStore:
    """Memory-store implementation that performs no work."""

    backend_name = "disabled"
    response_cache_enabled = False
    run_history_enabled = False

    async def get_baseline_response(
        self,
        prompt: str,
        model_config: ModelConfig,
    ) -> ModelResponse | None:
        del prompt, model_config
        return None

    async def save_baseline_response(
        self,
        prompt: str,
        model_config: ModelConfig,
        response: ModelResponse,
    ) -> None:
        del prompt, model_config, response

    async def save_run_document(
        self,
        run_id: str,
        payload: dict[str, object],
    ) -> None:
        del run_id, payload

    async def close(self) -> None:
        return None

"""Tests for optional memory-store helpers."""

import json

import pytest

from driftcut.config import ModelConfig
from driftcut.models import ModelResponse
from driftcut.store_redis import RedisStore


class _FakeRedisClient:
    def __init__(self) -> None:
        self.commands: list[tuple[object, ...]] = []
        self.storage: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.closed = False

    async def execute_command(self, *args: object) -> object:
        self.commands.append(args)
        command = args[0]
        if command == "JSON.GET":
            return self.storage.get(str(args[1]))
        if command == "JSON.SET":
            self.storage[str(args[1])] = str(args[3])
            return "OK"
        if command == "FT.CREATE":
            return "OK"
        msg = f"Unexpected command: {command}"
        raise AssertionError(msg)

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl

    async def close(self) -> None:
        self.closed = True


def _store(client: _FakeRedisClient) -> RedisStore:
    return RedisStore(
        redis_url="redis://localhost:6379/0",
        namespace="driftcut-test",
        response_cache_enabled=True,
        response_cache_ttl_seconds=600,
        run_history_enabled=True,
        run_history_ttl_seconds=3600,
        client=client,
    )


@pytest.mark.asyncio
async def test_redis_store_round_trips_cached_baseline_response() -> None:
    client = _FakeRedisClient()
    store = _store(client)
    model = ModelConfig(provider="openai", model="gpt-4o")
    response = ModelResponse(
        output="hello",
        latency_ms=125.0,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.01,
    )

    await store.save_baseline_response("Say hello", model, response)
    cached = await store.get_baseline_response("Say hello", model)

    assert cached is not None
    assert cached.cache_hit is True
    assert cached.output == "hello"
    assert cached.latency_ms == 0.0
    assert cached.historical_latency_ms == 125.0
    assert cached.cost_usd == 0.0
    assert cached.historical_cost_usd == 0.01
    assert any(command[0] == "JSON.SET" for command in client.commands)
    assert any(command[0] == "JSON.GET" for command in client.commands)
    assert all(ttl == 600 for ttl in client.expirations.values())


@pytest.mark.asyncio
async def test_redis_store_saves_run_document_and_indexes_runs() -> None:
    client = _FakeRedisClient()
    store = _store(client)
    payload: dict[str, object] = {
        "run_id": "run-123",
        "mode": "live",
        "memory_backend": "redis",
        "baseline_model": "openai/gpt-4o",
        "candidate_model": "anthropic/claude-haiku",
        "decision": {
            "outcome": "PROCEED",
            "metrics": {
                "overall_risk": 0.01,
                "schema_break_rate": 0.0,
                "high_criticality_failure_rate": 0.0,
            },
        },
        "archetype_names": ["json_invalid"],
    }

    await store.save_run_document("run-123", payload)
    await store.save_run_document("run-456", {**payload, "run_id": "run-456"})

    assert any(command[0] == "FT.CREATE" for command in client.commands)
    assert sum(1 for command in client.commands if command[0] == "FT.CREATE") == 1
    saved_payload = json.loads(client.storage["driftcut-test:run:run-123"])
    assert saved_payload["run_id"] == "run-123"
    assert saved_payload["decision"]["outcome"] == "PROCEED"
    assert client.expirations["driftcut-test:run:run-123"] == 3600

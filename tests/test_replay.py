"""Tests for replay-mode loading and execution."""

import json
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest

from driftcut.config import (
    DriftcutConfig,
    EvaluationConfig,
    LatencyConfig,
    ModelConfig,
    ModelsConfig,
    SamplingConfig,
)
from driftcut.models import JudgeResult, ModelResponse
from driftcut.replay import load_replay_dataset
from driftcut.runner import run_migration, run_replay
from driftcut.sampler import StratifiedSampler
from driftcut.store_null import NullMemoryStore


def _config(
    *,
    judge_strategy: Literal["none", "light", "tiered", "heavy"] = "none",
    track_latency: bool = True,
) -> DriftcutConfig:
    return DriftcutConfig(
        name="Replay test",
        models=ModelsConfig(
            baseline=ModelConfig(provider="openai", model="gpt-4o"),
            candidate=ModelConfig(provider="anthropic", model="claude-haiku"),
        ),
        sampling=SamplingConfig(batch_size_per_category=1, max_batches=2, min_batches=1),
        evaluation=EvaluationConfig(judge_strategy=judge_strategy),
        latency=LatencyConfig(track=track_latency),
    )


def _replay_payload(
    *,
    include_latency: bool = True,
    differing_outputs: bool = False,
) -> dict[str, object]:
    candidate_output = "Contact support tomorrow." if differing_outputs else "All good"
    baseline_output = "We can resolve this today." if differing_outputs else "All good"
    baseline: dict[str, object] = {"output": baseline_output, "cost_usd": 0.01}
    candidate: dict[str, object] = {"output": candidate_output, "cost_usd": 0.008}
    if include_latency:
        baseline["latency_ms"] = 100.0
        candidate["latency_ms"] = 90.0

    extraction_baseline: dict[str, object] = {"output": '{"ok": true}', "cost_usd": 0.01}
    extraction_candidate: dict[str, object] = {"output": '{"ok": true}', "cost_usd": 0.008}
    if include_latency:
        extraction_baseline["latency_ms"] = 120.0
        extraction_candidate["latency_ms"] = 100.0

    return {
        "format_version": 1,
        "records": [
            {
                "id": "p1",
                "category": "support",
                "prompt": "Help me",
                "criticality": "high",
                "expected_output_type": "free_text",
                "baseline": baseline,
                "candidate": candidate,
            },
            {
                "id": "p2",
                "category": "extraction",
                "prompt": "Extract entities",
                "criticality": "medium",
                "expected_output_type": "json",
                "json_required_keys": ["ok"],
                "baseline": extraction_baseline,
                "candidate": extraction_candidate,
            },
        ],
    }


def test_load_replay_dataset(tmp_path: Path) -> None:
    replay_file = tmp_path / "replay.json"
    replay_file.write_text(json.dumps(_replay_payload()), encoding="utf-8")

    dataset = load_replay_dataset(replay_file, _config())

    assert dataset.corpus.size == 2
    assert dataset.corpus.categories == ["extraction", "support"]
    assert dataset.historical_metrics_present == {"latency": True, "cost": True}
    pair = dataset.pairs_by_id["p1"]
    assert pair.baseline.output == "All good"
    assert pair.candidate.latency_ms == 90.0


def test_load_replay_dataset_requires_latency_when_tracking(tmp_path: Path) -> None:
    replay_file = tmp_path / "replay.json"
    replay_file.write_text(json.dumps(_replay_payload(include_latency=False)), encoding="utf-8")

    with pytest.raises(ValueError, match="missing baseline.latency_ms"):
        load_replay_dataset(replay_file, _config(track_latency=True))


@pytest.mark.asyncio
async def test_run_replay_end_to_end(tmp_path: Path) -> None:
    replay_file = tmp_path / "replay.json"
    replay_file.write_text(json.dumps(_replay_payload()), encoding="utf-8")
    config = _config()
    dataset = load_replay_dataset(replay_file, config)
    sampler = StratifiedSampler(dataset.corpus, config.sampling, seed=42)

    result = await run_replay(config, dataset, sampler, store=NullMemoryStore())

    assert result.mode == "replay"
    assert result.total_prompts == 2
    assert result.final_decision is not None
    assert result.final_decision.outcome == "PROCEED"
    assert result.historical_metrics_present == {"latency": True, "cost": True}


@pytest.mark.asyncio
async def test_replay_matches_live_decision_for_equivalent_outputs(tmp_path: Path) -> None:
    replay_file = tmp_path / "replay.json"
    payload = _replay_payload()
    replay_file.write_text(json.dumps(payload), encoding="utf-8")
    config = _config()
    dataset = load_replay_dataset(replay_file, config)
    replay_sampler = StratifiedSampler(dataset.corpus, config.sampling, seed=42)
    live_sampler = StratifiedSampler(dataset.corpus, config.sampling, seed=42)

    response_map: dict[tuple[str, str], ModelResponse] = {
        ("Help me", "openai"): ModelResponse(output="All good", latency_ms=100.0, cost_usd=0.01),
        ("Help me", "anthropic"): ModelResponse(output="All good", latency_ms=90.0, cost_usd=0.008),
        (
            "Extract entities",
            "openai",
        ): ModelResponse(output='{"ok": true}', latency_ms=120.0, cost_usd=0.01),
        (
            "Extract entities",
            "anthropic",
        ): ModelResponse(output='{"ok": true}', latency_ms=100.0, cost_usd=0.008),
    }

    async def side_effect(prompt: str, model: ModelConfig, **_: object) -> ModelResponse:
        return response_map[(prompt, model.provider)]

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ):
        live_result = await run_migration(config, live_sampler, store=NullMemoryStore())

    replay_result = await run_replay(config, dataset, replay_sampler, store=NullMemoryStore())

    assert live_result.final_decision is not None
    assert replay_result.final_decision is not None
    assert replay_result.final_decision.outcome == live_result.final_decision.outcome
    assert replay_result.final_decision.metrics.overall_risk == pytest.approx(
        live_result.final_decision.metrics.overall_risk
    )


@pytest.mark.asyncio
async def test_run_replay_uses_judge_for_ambiguous_outputs(tmp_path: Path) -> None:
    replay_file = tmp_path / "replay.json"
    replay_file.write_text(
        json.dumps(_replay_payload(differing_outputs=True)),
        encoding="utf-8",
    )
    config = _config(judge_strategy="light")
    dataset = load_replay_dataset(replay_file, config)
    sampler = StratifiedSampler(dataset.corpus, config.sampling, seed=42)

    with patch(
        "driftcut.runner.judge_prompt_result",
        new_callable=AsyncMock,
        return_value=JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="candidate_worse",
            confidence=0.95,
            rationale="Candidate is less direct and misses the requested action.",
            cost_usd=0.002,
        ),
    ) as judge_mock:
        result = await run_replay(config, dataset, sampler, store=NullMemoryStore())

    assert result.final_decision is not None
    assert result.final_decision.metrics.judged_prompts == 1
    assert result.final_decision.metrics.judge_worse_rate == 1.0
    judge_mock.assert_awaited_once()

"""Tests for the migration runner."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from driftcut.config import CorpusConfig, DriftcutConfig, ModelConfig, ModelsConfig, SamplingConfig
from driftcut.corpus import Corpus, PromptRecord
from driftcut.models import ModelResponse
from driftcut.runner import RunResult, _run_prompt, run_migration
from driftcut.sampler import StratifiedSampler


def _sample_config() -> DriftcutConfig:
    """Build a minimal config for testing."""
    return DriftcutConfig(
        name="Test migration",
        models=ModelsConfig(
            baseline=ModelConfig(provider="openai", model="gpt-4o"),
            candidate=ModelConfig(provider="anthropic", model="claude-haiku"),
        ),
        corpus=CorpusConfig(file=Path("prompts.csv")),
        sampling=SamplingConfig(batch_size_per_category=1, max_batches=1, min_batches=1),
    )


def _sample_corpus() -> Corpus:
    """Build a minimal corpus for testing."""
    return Corpus(
        [
            PromptRecord(
                id="p1",
                category="support",
                prompt="Help me",
                criticality="high",
                expected_output_type="free_text",
            ),
            PromptRecord(
                id="p2",
                category="extraction",
                prompt="Extract entities",
                criticality="medium",
                expected_output_type="json",
            ),
        ]
    )


def _mock_response(output: str = "response") -> ModelResponse:
    return ModelResponse(
        output=output,
        latency_ms=50.0,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.001,
    )


@pytest.mark.asyncio
async def test_run_prompt() -> None:
    config = _sample_config()
    prompt = _sample_corpus().records[0]

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        return_value=_mock_response(),
    ):
        result = await _run_prompt(prompt, config)

    assert result.prompt_id == "p1"
    assert result.category == "support"
    assert result.baseline.output == "response"
    assert result.candidate.output == "response"


@pytest.mark.asyncio
async def test_run_migration_end_to_end() -> None:
    config = _sample_config()
    corpus = _sample_corpus()
    sampler = StratifiedSampler(corpus, config.sampling, seed=42)

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        return_value=_mock_response(),
    ):
        result = await run_migration(config, sampler)

    assert isinstance(result, RunResult)
    assert result.config_name == "Test migration"
    assert result.total_batches == 1
    assert result.total_prompts == 2

    cost = result.cost.summary
    assert cost.total_usd > 0

    bl_stats = result.latency.baseline_stats()
    assert bl_stats.count == 2


@pytest.mark.asyncio
async def test_run_migration_handles_errors() -> None:
    config = _sample_config()
    corpus = _sample_corpus()
    sampler = StratifiedSampler(corpus, config.sampling, seed=42)

    error_response = ModelResponse(
        output="",
        latency_ms=10.0,
        error="API error",
    )

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        return_value=error_response,
    ):
        result = await run_migration(config, sampler)

    assert result.total_prompts == 2
    batch = result.batches[0]
    assert batch.baseline_errors == 2
    assert batch.candidate_errors == 2

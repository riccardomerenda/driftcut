"""Tests for the migration runner."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from driftcut.config import (
    CorpusConfig,
    DriftcutConfig,
    EvaluationConfig,
    ModelConfig,
    ModelsConfig,
    SamplingConfig,
)
from driftcut.corpus import Corpus, PromptRecord
from driftcut.models import JudgeResult, ModelResponse
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


def _multi_batch_corpus() -> Corpus:
    """Build a corpus large enough to exercise early decisions."""
    return Corpus(
        [
            PromptRecord(
                id="s1",
                category="support",
                prompt="Support prompt 1",
                criticality="high",
                expected_output_type="free_text",
            ),
            PromptRecord(
                id="s2",
                category="support",
                prompt="Support prompt 2",
                criticality="medium",
                expected_output_type="free_text",
            ),
            PromptRecord(
                id="s3",
                category="support",
                prompt="Support prompt 3",
                criticality="medium",
                expected_output_type="free_text",
            ),
            PromptRecord(
                id="e1",
                category="extraction",
                prompt="Extraction prompt 1",
                criticality="high",
                expected_output_type="json",
            ),
            PromptRecord(
                id="e2",
                category="extraction",
                prompt="Extraction prompt 2",
                criticality="medium",
                expected_output_type="json",
            ),
            PromptRecord(
                id="e3",
                category="extraction",
                prompt="Extraction prompt 3",
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


@pytest.mark.asyncio
async def test_run_migration_proceeds_after_min_batches() -> None:
    config = DriftcutConfig(
        name="Proceed migration",
        models=ModelsConfig(
            baseline=ModelConfig(provider="openai", model="gpt-4o"),
            candidate=ModelConfig(provider="anthropic", model="claude-haiku"),
        ),
        corpus=CorpusConfig(file=Path("prompts.csv")),
        sampling=SamplingConfig(batch_size_per_category=1, max_batches=3, min_batches=2),
    )
    sampler = StratifiedSampler(_multi_batch_corpus(), config.sampling, seed=42)

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        return_value=_mock_response(output='{"ok": true}'),
    ):
        result = await run_migration(config, sampler)

    assert result.total_batches == 2
    assert result.stopped_early is True
    assert result.final_decision is not None
    assert result.final_decision.outcome == "PROCEED"


@pytest.mark.asyncio
async def test_run_migration_stops_on_schema_break() -> None:
    config = DriftcutConfig(
        name="Stop migration",
        models=ModelsConfig(
            baseline=ModelConfig(provider="openai", model="gpt-4o"),
            candidate=ModelConfig(provider="anthropic", model="claude-haiku"),
        ),
        corpus=CorpusConfig(file=Path("prompts.csv")),
        sampling=SamplingConfig(batch_size_per_category=1, max_batches=3, min_batches=2),
    )
    sampler = StratifiedSampler(_multi_batch_corpus(), config.sampling, seed=42)

    async def side_effect(_: str, model: ModelConfig) -> ModelResponse:
        if model.provider == "openai":
            return _mock_response(output='{"ok": true}')
        return _mock_response(output="not json")

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ):
        result = await run_migration(config, sampler)

    assert result.total_batches == 1
    assert result.final_decision is not None
    assert result.final_decision.outcome == "STOP"
    assert "schema break threshold" in result.final_decision.reason


@pytest.mark.asyncio
async def test_run_prompt_uses_judge_for_ambiguous_outputs() -> None:
    config = DriftcutConfig(
        name="Judge migration",
        models=ModelsConfig(
            baseline=ModelConfig(provider="openai", model="gpt-4o"),
            candidate=ModelConfig(provider="anthropic", model="claude-haiku"),
        ),
        corpus=CorpusConfig(file=Path("prompts.csv")),
        sampling=SamplingConfig(batch_size_per_category=1, max_batches=1, min_batches=1),
        evaluation=EvaluationConfig(judge_strategy="light"),
    )
    prompt = PromptRecord(
        id="p3",
        category="support",
        prompt="Draft a reply",
        criticality="high",
        expected_output_type="free_text",
    )

    async def side_effect(_: str, model: ModelConfig) -> ModelResponse:
        if model.provider == "openai":
            return _mock_response(output="We can issue a refund today.")
        return _mock_response(output="Contact support tomorrow.")

    with patch(
        "driftcut.runner.execute_prompt",
        new_callable=AsyncMock,
        side_effect=side_effect,
    ), patch(
        "driftcut.runner.judge_prompt_result",
        new_callable=AsyncMock,
        return_value=JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="candidate_worse",
            confidence=0.9,
            rationale="Candidate misses the direct resolution path.",
            cost_usd=0.002,
        ),
    ) as judge_mock:
        result = await _run_prompt(prompt, config)

    assert result.evaluation is not None
    assert result.evaluation.needs_judge is True
    assert result.evaluation.judge is not None
    assert result.evaluation.candidate_regressed is True
    assert result.evaluation.candidate_failed is True
    judge_mock.assert_awaited_once()

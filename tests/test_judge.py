"""Tests for judge-layer helpers."""

from unittest.mock import AsyncMock, patch

import pytest

from driftcut.config import EvaluationConfig
from driftcut.judge import apply_judge_result, judge_prompt_result, prompt_needs_judge
from driftcut.models import (
    JudgeResult,
    ModelResponse,
    PromptEvaluation,
    PromptResult,
    ResponseEvaluation,
)


def _make_prompt_result(
    *,
    expected_output_type: str = "free_text",
    baseline_output: str = "Refund approved today.",
    candidate_output: str = "Refund approved today.",
) -> PromptResult:
    result = PromptResult(
        prompt_id="p1",
        category="support",
        criticality="high",
        prompt_text="Help me",
        expected_output_type=expected_output_type,
        baseline=ModelResponse(output=baseline_output, latency_ms=100.0),
        candidate=ModelResponse(output=candidate_output, latency_ms=90.0),
        evaluation=PromptEvaluation(
            baseline=ResponseEvaluation(passed=True, structure_valid=True),
            candidate=ResponseEvaluation(passed=True, structure_valid=True),
            candidate_failed=False,
            candidate_regressed=False,
            candidate_improved=False,
            schema_break=False,
        ),
    )
    return result


def test_prompt_needs_judge_false_when_outputs_match() -> None:
    result = _make_prompt_result()
    assert prompt_needs_judge(result) is False


def test_prompt_needs_judge_true_for_semantic_difference() -> None:
    result = _make_prompt_result(
        baseline_output="We can issue a refund today and close the case.",
        candidate_output="Please contact support next week for a review.",
    )
    assert prompt_needs_judge(result) is True


def test_apply_judge_result_marks_regression() -> None:
    result = _make_prompt_result(
        baseline_output="We can issue a refund today.",
        candidate_output="Contact support tomorrow.",
    )
    evaluation = PromptEvaluation(
        baseline=ResponseEvaluation(passed=True, structure_valid=True),
        candidate=ResponseEvaluation(passed=True, structure_valid=True),
        candidate_failed=False,
        candidate_regressed=False,
        candidate_improved=False,
        schema_break=False,
        needs_judge=True,
    )

    merged = apply_judge_result(
        result,
        evaluation,
        JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="candidate_worse",
            confidence=0.85,
            rationale="Candidate is materially worse than the baseline.",
        ),
    )

    assert merged.judge is not None
    assert merged.candidate_failed is True
    assert merged.candidate_regressed is True
    assert merged.candidate_improved is False
    assert merged.failure_archetypes == ["semantic_regression"]


def test_apply_judge_result_classifies_refusal_regression() -> None:
    result = _make_prompt_result(
        baseline_output="We can issue the refund and close the case today.",
        candidate_output="I'm sorry, but I can't help with that request.",
    )
    evaluation = PromptEvaluation(
        baseline=ResponseEvaluation(passed=True, structure_valid=True),
        candidate=ResponseEvaluation(passed=True, structure_valid=True),
        candidate_failed=False,
        candidate_regressed=False,
        candidate_improved=False,
        schema_break=False,
        needs_judge=True,
    )

    merged = apply_judge_result(
        result,
        evaluation,
        JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="candidate_worse",
            confidence=0.91,
            rationale="Candidate refuses the request instead of solving it.",
        ),
    )

    assert "refusal_regression" in merged.failure_archetypes
    assert "instruction_miss" in merged.failure_archetypes
    assert merged.candidate.archetype == "refusal_regression"


@pytest.mark.asyncio
async def test_tiered_judge_no_escalation_on_high_confidence() -> None:
    config = EvaluationConfig(judge_strategy="tiered", tiered_escalation_threshold=0.6)
    result = _make_prompt_result(
        baseline_output="We can issue a refund today.",
        candidate_output="Contact support tomorrow.",
    )
    with patch("driftcut.judge._call_judge_model", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="equivalent",
            confidence=0.8,
        )
        judge = await judge_prompt_result(result, config)

    assert judge.tier == "light"
    assert judge.escalated is False
    assert judge.confidence == 0.8
    mock_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_tiered_judge_escalates_on_low_confidence() -> None:
    config = EvaluationConfig(judge_strategy="tiered", tiered_escalation_threshold=0.6)
    result = _make_prompt_result(
        baseline_output="We can issue a refund today.",
        candidate_output="Contact support tomorrow.",
    )
    light_result = JudgeResult(
        model="openai/gpt-4.1-mini",
        verdict="equivalent",
        confidence=0.4,
        latency_ms=100.0,
        cost_usd=0.001,
    )
    heavy_result = JudgeResult(
        model="openai/gpt-4.1",
        verdict="candidate_worse",
        confidence=0.9,
        latency_ms=200.0,
        cost_usd=0.01,
    )
    with patch("driftcut.judge._call_judge_model", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [light_result, heavy_result]
        judge = await judge_prompt_result(result, config)

    assert judge.tier == "heavy"
    assert judge.escalated is True
    assert judge.verdict == "candidate_worse"
    assert judge.confidence == 0.9
    assert abs(judge.cost_usd - 0.011) < 1e-9
    assert abs(judge.latency_ms - 300.0) < 1e-9
    assert mock_call.await_count == 2


@pytest.mark.asyncio
async def test_tiered_judge_no_escalation_on_light_error() -> None:
    config = EvaluationConfig(judge_strategy="tiered", tiered_escalation_threshold=0.6)
    result = _make_prompt_result(
        baseline_output="We can issue a refund today.",
        candidate_output="Contact support tomorrow.",
    )
    with patch("driftcut.judge._call_judge_model", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="unavailable",
            error="API timeout",
        )
        judge = await judge_prompt_result(result, config)

    assert judge.is_error is True
    assert judge.escalated is False
    mock_call.assert_awaited_once()

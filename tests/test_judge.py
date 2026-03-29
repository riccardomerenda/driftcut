"""Tests for judge-layer helpers."""

from driftcut.judge import apply_judge_result, prompt_needs_judge
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
        evaluation,
        JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="candidate_worse",
            confidence=0.85,
            rationale="Candidate drops the concrete resolution step.",
        ),
    )

    assert merged.judge is not None
    assert merged.candidate_failed is True
    assert merged.candidate_regressed is True
    assert merged.candidate_improved is False

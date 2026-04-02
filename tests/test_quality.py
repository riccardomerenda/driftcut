"""Tests for deterministic quality checks."""

from driftcut.models import ModelResponse, PromptResult
from driftcut.quality import evaluate_prompt_result


def _make_prompt_result(
    *,
    expected_output_type: str = "json",
    baseline_output: str = '{"ok": true}',
    candidate_output: str = '{"ok": true}',
    json_required_keys: list[str] | None = None,
    required_substrings: list[str] | None = None,
    forbidden_substrings: list[str] | None = None,
    max_output_chars: int | None = None,
) -> PromptResult:
    return PromptResult(
        prompt_id="p1",
        category="test",
        criticality="high",
        prompt_text="Return JSON",
        expected_output_type=expected_output_type,
        baseline=ModelResponse(output=baseline_output, latency_ms=100.0),
        candidate=ModelResponse(output=candidate_output, latency_ms=80.0),
        json_required_keys=json_required_keys or [],
        required_substrings=required_substrings or [],
        forbidden_substrings=forbidden_substrings or [],
        max_output_chars=max_output_chars,
    )


def test_valid_json_with_required_keys_passes() -> None:
    result = _make_prompt_result(
        json_required_keys=["ok"],
        candidate_output='{"ok": true, "extra": 1}',
    )

    evaluation = evaluate_prompt_result(result)

    assert evaluation.candidate.passed is True
    assert evaluation.schema_break is False


def test_invalid_candidate_json_is_schema_break() -> None:
    result = _make_prompt_result(candidate_output="not json at all")

    evaluation = evaluate_prompt_result(result)

    assert evaluation.candidate_failed is True
    assert evaluation.schema_break is True
    assert evaluation.candidate.archetype == "json_invalid"


def test_missing_required_substring_fails() -> None:
    result = _make_prompt_result(
        expected_output_type="free_text",
        baseline_output="We can offer a refund.",
        candidate_output="We can look into it.",
        required_substrings=["refund"],
    )

    evaluation = evaluate_prompt_result(result)

    assert evaluation.candidate.passed is False
    assert evaluation.candidate.archetype == "missing_required_content"


def test_multiple_candidate_issues_produce_multiple_archetypes() -> None:
    result = _make_prompt_result(
        expected_output_type="free_text",
        baseline_output="We can offer a refund today.",
        candidate_output="Maybe we can review this request later.",
        required_substrings=["refund"],
        forbidden_substrings=["maybe"],
        max_output_chars=20,
    )

    evaluation = evaluate_prompt_result(result)

    assert evaluation.candidate.passed is False
    assert evaluation.failure_archetypes == [
        "missing_required_content",
        "forbidden_content",
        "overlong_output",
    ]

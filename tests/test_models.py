"""Tests for result models."""

from driftcut.models import (
    BatchResult,
    JudgeResult,
    ModelResponse,
    PromptEvaluation,
    PromptResult,
    ResponseEvaluation,
)


def _make_response(
    output: str = "ok",
    latency_ms: float = 100.0,
    cost_usd: float = 0.01,
    error: str | None = None,
) -> ModelResponse:
    return ModelResponse(
        output=output,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        cost_error=None,
        error=error,
    )


def _make_prompt_result(
    prompt_id: str = "p1",
    category: str = "support",
    criticality: str = "high",
    baseline_latency: float = 100.0,
    candidate_latency: float = 80.0,
    baseline_cost: float = 0.01,
    candidate_cost: float = 0.005,
) -> PromptResult:
    return PromptResult(
        prompt_id=prompt_id,
        category=category,
        criticality=criticality,
        prompt_text="test prompt",
        expected_output_type="free_text",
        baseline=_make_response(latency_ms=baseline_latency, cost_usd=baseline_cost),
        candidate=_make_response(latency_ms=candidate_latency, cost_usd=candidate_cost),
    )


class TestModelResponse:
    def test_is_error_false_by_default(self) -> None:
        r = _make_response()
        assert r.is_error is False

    def test_is_error_true_when_error_set(self) -> None:
        r = _make_response(error="timeout")
        assert r.is_error is True

    def test_defaults(self) -> None:
        r = ModelResponse(output="hello", latency_ms=50.0)
        assert r.retry_count == 0
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.cost_usd == 0.0
        assert r.cost_error is None
        assert r.error is None


class TestJudgeResult:
    def test_is_error_false_by_default(self) -> None:
        judge = JudgeResult(model="openai/gpt-4.1-mini", verdict="equivalent")
        assert judge.is_error is False

    def test_is_error_true_when_error_set(self) -> None:
        judge = JudgeResult(
            model="openai/gpt-4.1-mini",
            verdict="unavailable",
            error="Missing API key",
        )
        assert judge.is_error is True


class TestBatchResult:
    def test_empty_batch(self) -> None:
        b = BatchResult(batch_number=1)
        assert b.size == 0
        assert b.baseline_errors == 0
        assert b.candidate_errors == 0
        assert b.total_cost_usd == 0.0

    def test_batch_with_results(self) -> None:
        r1 = _make_prompt_result(baseline_cost=0.01, candidate_cost=0.005)
        r2 = _make_prompt_result(baseline_cost=0.02, candidate_cost=0.01)
        r2.evaluation = PromptEvaluation(
            baseline=ResponseEvaluation(passed=True, structure_valid=True),
            candidate=ResponseEvaluation(passed=True, structure_valid=True),
            candidate_failed=False,
            candidate_regressed=False,
            candidate_improved=False,
            schema_break=False,
            judge=JudgeResult(
                model="openai/gpt-4.1-mini",
                verdict="equivalent",
                cost_usd=0.002,
            ),
        )
        b = BatchResult(batch_number=1, results=[r1, r2])
        assert b.size == 2
        assert b.total_cost_usd == 0.047

    def test_batch_counts_errors(self) -> None:
        r_ok = _make_prompt_result()
        r_err = PromptResult(
            prompt_id="p2",
            category="support",
            criticality="high",
            prompt_text="test",
            expected_output_type="free_text",
            baseline=_make_response(),
            candidate=_make_response(error="API error"),
        )
        b = BatchResult(batch_number=1, results=[r_ok, r_err])
        assert b.baseline_errors == 0
        assert b.candidate_errors == 1

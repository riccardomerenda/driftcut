"""Tests for result models."""

from driftcut.models import BatchResult, ModelResponse, PromptResult


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
    def test_is_error_false_by_default(self):
        r = _make_response()
        assert r.is_error is False

    def test_is_error_true_when_error_set(self):
        r = _make_response(error="timeout")
        assert r.is_error is True

    def test_defaults(self):
        r = ModelResponse(output="hello", latency_ms=50.0)
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.cost_usd == 0.0
        assert r.error is None


class TestBatchResult:
    def test_empty_batch(self):
        b = BatchResult(batch_number=1)
        assert b.size == 0
        assert b.baseline_errors == 0
        assert b.candidate_errors == 0
        assert b.total_cost_usd == 0.0

    def test_batch_with_results(self):
        r1 = _make_prompt_result(baseline_cost=0.01, candidate_cost=0.005)
        r2 = _make_prompt_result(baseline_cost=0.02, candidate_cost=0.01)
        b = BatchResult(batch_number=1, results=[r1, r2])
        assert b.size == 2
        assert b.total_cost_usd == 0.045

    def test_batch_counts_errors(self):
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

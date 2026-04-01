"""Tests for latency and cost trackers."""

from driftcut.models import (
    JudgeResult,
    ModelResponse,
    PromptEvaluation,
    PromptResult,
    ResponseEvaluation,
)
from driftcut.trackers import CostTracker, LatencyTracker, _percentile


def _make_result(
    category: str = "support",
    baseline_latency: float = 100.0,
    candidate_latency: float = 80.0,
    baseline_cost: float = 0.01,
    candidate_cost: float = 0.005,
    baseline_error: str | None = None,
    candidate_error: str | None = None,
    judge_cost: float = 0.0,
) -> PromptResult:
    result = PromptResult(
        prompt_id="p1",
        category=category,
        criticality="high",
        prompt_text="test",
        expected_output_type="free_text",
        baseline=ModelResponse(
            output="b",
            latency_ms=baseline_latency,
            cost_usd=baseline_cost,
            error=baseline_error,
        ),
        candidate=ModelResponse(
            output="c",
            latency_ms=candidate_latency,
            cost_usd=candidate_cost,
            error=candidate_error,
        ),
    )
    if judge_cost > 0:
        result.evaluation = PromptEvaluation(
            baseline=ResponseEvaluation(passed=True, structure_valid=True),
            candidate=ResponseEvaluation(passed=True, structure_valid=True),
            candidate_failed=False,
            candidate_regressed=False,
            candidate_improved=False,
            schema_break=False,
            judge=JudgeResult(
                model="openai/gpt-4.1-mini",
                verdict="equivalent",
                cost_usd=judge_cost,
            ),
        )
    return result


class TestPercentile:
    def test_single_value(self) -> None:
        assert _percentile([100.0], 95) == 100.0

    def test_two_values(self) -> None:
        result = _percentile([10.0, 100.0], 50)
        assert result == 55.0

    def test_empty(self) -> None:
        assert _percentile([], 95) == 0.0

    def test_known_p95(self) -> None:
        values = [float(v) for v in range(1, 101)]  # 1..100
        p95 = _percentile(values, 95)
        assert 95.0 <= p95 <= 96.0


class TestLatencyTracker:
    def test_empty_tracker(self) -> None:
        lt = LatencyTracker()
        stats = lt.baseline_stats()
        assert stats.count == 0
        assert stats.p50_ms == 0

    def test_records_latencies(self) -> None:
        lt = LatencyTracker()
        lt.record(_make_result(baseline_latency=100, candidate_latency=50))
        lt.record(_make_result(baseline_latency=200, candidate_latency=80))
        lt.record(_make_result(baseline_latency=300, candidate_latency=120))

        bl = lt.baseline_stats()
        assert bl.count == 3
        assert bl.p50_ms == 200.0
        assert bl.min_ms == 100.0
        assert bl.max_ms == 300.0

        cd = lt.candidate_stats()
        assert cd.count == 3
        assert cd.p50_ms == 80.0

    def test_per_category(self) -> None:
        lt = LatencyTracker()
        lt.record(_make_result(category="a", baseline_latency=100, candidate_latency=50))
        lt.record(_make_result(category="b", baseline_latency=500, candidate_latency=300))

        a_stats = lt.baseline_stats("a")
        assert a_stats.count == 1
        assert a_stats.p50_ms == 100.0

        overall = lt.baseline_stats()
        assert overall.count == 2

    def test_categories_property(self) -> None:
        lt = LatencyTracker()
        lt.record(_make_result(category="b"))
        lt.record(_make_result(category="a"))
        assert lt.categories == ["a", "b"]

    def test_errors_excluded_from_latency(self) -> None:
        lt = LatencyTracker()
        lt.record(_make_result(candidate_error="timeout"))
        bl = lt.baseline_stats()
        assert bl.count == 1
        cd = lt.candidate_stats()
        assert cd.count == 0


class TestCostTracker:
    def test_empty_tracker(self) -> None:
        ct = CostTracker()
        s = ct.summary
        assert s.total_usd == 0.0
        assert s.baseline_usd == 0.0
        assert s.candidate_usd == 0.0
        assert s.judge_usd == 0.0

    def test_accumulates_cost(self) -> None:
        ct = CostTracker()
        ct.record(_make_result(baseline_cost=0.01, candidate_cost=0.005, judge_cost=0.002))
        ct.record(_make_result(baseline_cost=0.02, candidate_cost=0.01))

        s = ct.summary
        assert abs(s.baseline_usd - 0.03) < 1e-9
        assert abs(s.candidate_usd - 0.015) < 1e-9
        assert abs(s.judge_usd - 0.002) < 1e-9
        assert abs(s.total_usd - 0.047) < 1e-9

    def test_judge_cost_split_by_tier(self) -> None:
        ct = CostTracker()
        light_result = _make_result(judge_cost=0.001)
        assert light_result.evaluation is not None and light_result.evaluation.judge is not None
        light_result.evaluation.judge.tier = "light"
        ct.record(light_result)

        heavy_result = _make_result(judge_cost=0.011)
        assert heavy_result.evaluation is not None and heavy_result.evaluation.judge is not None
        heavy_result.evaluation.judge.tier = "heavy"
        heavy_result.evaluation.judge.escalated = True
        ct.record(heavy_result)

        s = ct.summary
        assert abs(s.judge_light_usd - 0.001) < 1e-9
        assert abs(s.judge_heavy_usd - 0.011) < 1e-9
        assert abs(s.judge_usd - 0.012) < 1e-9

    def test_per_category_cost(self) -> None:
        ct = CostTracker()
        ct.record(_make_result(category="a", baseline_cost=0.01, candidate_cost=0.005))
        ct.record(_make_result(category="b", baseline_cost=0.02, candidate_cost=0.01))
        ct.record(_make_result(category="a", baseline_cost=0.01, candidate_cost=0.005))

        s = ct.summary
        assert abs(s.per_category["a"] - 0.03) < 1e-9
        assert abs(s.per_category["b"] - 0.03) < 1e-9

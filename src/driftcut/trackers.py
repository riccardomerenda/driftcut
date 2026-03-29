"""Latency and cost trackers for migration runs."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from driftcut.models import PromptResult


@dataclass
class LatencyStats:
    """Computed latency statistics for a set of measurements."""

    count: int
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float


class LatencyTracker:
    """Tracks per-prompt latencies and computes p50/p95 per category and overall."""

    def __init__(self) -> None:
        self._baseline: dict[str, list[float]] = {}
        self._candidate: dict[str, list[float]] = {}

    def record(self, result: PromptResult) -> None:
        cat = result.category
        if not result.baseline.is_error:
            self._baseline.setdefault(cat, []).append(result.baseline.latency_ms)
        if not result.candidate.is_error:
            self._candidate.setdefault(cat, []).append(result.candidate.latency_ms)

    @staticmethod
    def _compute(values: list[float]) -> LatencyStats:
        if not values:
            return LatencyStats(count=0, p50_ms=0, p95_ms=0, min_ms=0, max_ms=0)
        sorted_v = sorted(values)
        return LatencyStats(
            count=len(sorted_v),
            p50_ms=statistics.median(sorted_v),
            p95_ms=_percentile(sorted_v, 95),
            min_ms=sorted_v[0],
            max_ms=sorted_v[-1],
        )

    def baseline_stats(self, category: str | None = None) -> LatencyStats:
        return self._compute(self._get_values(self._baseline, category))

    def candidate_stats(self, category: str | None = None) -> LatencyStats:
        return self._compute(self._get_values(self._candidate, category))

    @property
    def categories(self) -> list[str]:
        return sorted(set(self._baseline) | set(self._candidate))

    @staticmethod
    def _get_values(data: dict[str, list[float]], category: str | None) -> list[float]:
        if category is not None:
            return data.get(category, [])
        return [v for vals in data.values() for v in vals]


@dataclass
class CostSummary:
    """Accumulated cost information."""

    baseline_usd: float = 0.0
    candidate_usd: float = 0.0
    judge_usd: float = 0.0
    total_usd: float = 0.0
    per_category: dict[str, float] = field(default_factory=dict)


class CostTracker:
    """Tracks per-prompt and cumulative costs."""

    def __init__(self) -> None:
        self._baseline_total: float = 0.0
        self._candidate_total: float = 0.0
        self._judge_total: float = 0.0
        self._per_category: dict[str, float] = {}

    def record(self, result: PromptResult) -> None:
        self._baseline_total += result.baseline.cost_usd
        self._candidate_total += result.candidate.cost_usd
        judge_cost = 0.0
        if result.evaluation is not None and result.evaluation.judge is not None:
            judge_cost = result.evaluation.judge.cost_usd
        self._judge_total += judge_cost
        total = result.baseline.cost_usd + result.candidate.cost_usd + judge_cost
        cat = result.category
        self._per_category[cat] = self._per_category.get(cat, 0.0) + total

    @property
    def summary(self) -> CostSummary:
        return CostSummary(
            baseline_usd=self._baseline_total,
            candidate_usd=self._candidate_total,
            judge_usd=self._judge_total,
            total_usd=self._baseline_total + self._candidate_total + self._judge_total,
            per_category=dict(sorted(self._per_category.items())),
        )


def _percentile(sorted_values: Sequence[float], pct: int) -> float:
    """Compute the pct-th percentile using nearest-rank method."""
    if not sorted_values:
        return 0.0
    k = (pct / 100) * (len(sorted_values) - 1)
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[-1]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])

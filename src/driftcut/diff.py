"""Compare two Driftcut result files and surface meaningful deltas."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MetricDelta:
    """A single metric comparison between two runs."""

    name: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def improved(self) -> bool:
        """Lower is better for risk/failure rates; closer to 1.0 is better for latency ratios."""
        if "latency" in self.name:
            return self.after < self.before
        return self.after < self.before


@dataclass
class CategoryDelta:
    """Risk delta for one category across two runs."""

    category: str
    before_risk: float
    after_risk: float
    before_archetypes: dict[str, int] = field(default_factory=dict)
    after_archetypes: dict[str, int] = field(default_factory=dict)

    @property
    def risk_delta(self) -> float:
        return self.after_risk - self.before_risk


@dataclass
class DiffResult:
    """Complete comparison between two Driftcut runs."""

    before_name: str
    after_name: str
    before_decision: str
    after_decision: str
    before_reason: str
    after_reason: str
    before_prompts: int
    after_prompts: int
    before_batches: int
    after_batches: int
    before_cost: float
    after_cost: float
    metrics: list[MetricDelta] = field(default_factory=list)
    categories: list[CategoryDelta] = field(default_factory=list)
    archetypes_added: list[str] = field(default_factory=list)
    archetypes_removed: list[str] = field(default_factory=list)


def load_result(path: Path) -> dict[str, Any]:
    """Load and validate a Driftcut results.json file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        msg = f"{path.name} is not a JSON object"
        raise ValueError(msg)
    if "decision" not in data:
        msg = f"{path.name} does not look like a Driftcut results file (missing 'decision')"
        raise ValueError(msg)
    return data


def diff_results(before: dict[str, Any], after: dict[str, Any]) -> DiffResult:
    """Compare two run payloads and return structured deltas."""
    before_decision = before.get("decision", {})
    after_decision = after.get("decision", {})
    before_metrics = before_decision.get("metrics", {})
    after_metrics = after_decision.get("metrics", {})

    metric_keys = [
        ("overall_risk", "Overall risk"),
        ("candidate_failure_rate", "Candidate failure rate"),
        ("candidate_regression_rate", "Candidate regression rate"),
        ("schema_break_rate", "Schema break rate"),
        ("high_criticality_failure_rate", "High-crit failure rate"),
        ("judge_worse_rate", "Judge worse rate"),
        ("latency_p50_ratio", "Latency p50 ratio"),
        ("latency_p95_ratio", "Latency p95 ratio"),
    ]

    metrics = []
    for key, label in metric_keys:
        b = float(before_metrics.get(key, 0))
        a = float(after_metrics.get(key, 0))
        if b != a or b != 0:
            metrics.append(MetricDelta(name=label, before=b, after=a))

    # Category deltas
    before_cats = {c["category"]: c for c in before_metrics.get("category_scores", [])}
    after_cats = {c["category"]: c for c in after_metrics.get("category_scores", [])}
    all_categories = sorted(set(before_cats) | set(after_cats))

    categories = []
    for cat in all_categories:
        bc = before_cats.get(cat, {})
        ac = after_cats.get(cat, {})
        categories.append(
            CategoryDelta(
                category=cat,
                before_risk=float(bc.get("overall_risk", 0)),
                after_risk=float(ac.get("overall_risk", 0)),
                before_archetypes=bc.get("archetypes", {}),
                after_archetypes=ac.get("archetypes", {}),
            )
        )

    # Archetype diff
    before_archetype_set = set(before_metrics.get("archetypes", {}).keys())
    after_archetype_set = set(after_metrics.get("archetypes", {}).keys())

    before_cost = before.get("cost", {})
    after_cost = after.get("cost", {})

    return DiffResult(
        before_name=str(before.get("name", "run A")),
        after_name=str(after.get("name", "run B")),
        before_decision=str(before_decision.get("outcome", "?")),
        after_decision=str(after_decision.get("outcome", "?")),
        before_reason=str(before_decision.get("reason", "")),
        after_reason=str(after_decision.get("reason", "")),
        before_prompts=int(before.get("total_prompts", 0)),
        after_prompts=int(after.get("total_prompts", 0)),
        before_batches=int(before.get("total_batches", 0)),
        after_batches=int(after.get("total_batches", 0)),
        before_cost=float(before_cost.get("total_usd", 0)),
        after_cost=float(after_cost.get("total_usd", 0)),
        metrics=metrics,
        categories=categories,
        archetypes_added=sorted(after_archetype_set - before_archetype_set),
        archetypes_removed=sorted(before_archetype_set - after_archetype_set),
    )

"""Run-level decision engine for Driftcut canary execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from driftcut.config import DriftcutConfig
from driftcut.models import BatchResult, CategoryScore, DecisionMetrics, RunDecision
from driftcut.quality import has_structured_expectation
from driftcut.trackers import LatencyTracker


@dataclass
class _CategoryAccumulator:
    prompts_evaluated: int = 0
    structured_prompts: int = 0
    high_criticality_prompts: int = 0
    ambiguous_prompts: int = 0
    judged_prompts: int = 0
    candidate_failures: int = 0
    candidate_regressions: int = 0
    schema_breaks: int = 0
    high_criticality_failures: int = 0
    judge_worse: int = 0
    judge_confidence_sum: float = 0.0
    archetypes: dict[str, int] = field(default_factory=dict)


def decide_run(
    config: DriftcutConfig,
    batches: list[BatchResult],
    latency: LatencyTracker,
    *,
    total_prompts_planned: int,
    total_batches_planned: int,
    has_remaining_batches: bool,
) -> RunDecision:
    """Summarize current evidence and decide whether to stop, continue, or proceed."""
    metrics = _collect_metrics(
        batches=batches,
        latency=latency,
        high_criticality_weight=config.risk.high_criticality_weight,
    )
    metrics.batches_evaluated = len(batches)

    stop_on_schema = (
        metrics.structured_prompts > 0
        and metrics.schema_break_rate >= config.risk.stop_on_schema_break_rate
    )
    stop_on_high_criticality = metrics.high_criticality_prompts > 0 and (
        metrics.high_criticality_failure_rate >= config.risk.stop_on_high_criticality_failure_rate
    )
    latency_within_bounds = (
        metrics.latency_p50_ratio <= config.latency.regression_threshold_p50
        and metrics.latency_p95_ratio <= config.latency.regression_threshold_p95
    )
    reached_min_batches = len(batches) >= config.sampling.min_batches
    confidence = _decision_confidence(
        batches_evaluated=len(batches),
        total_batches_planned=total_batches_planned,
        total_prompts_evaluated=metrics.prompts_evaluated,
        total_prompts_planned=total_prompts_planned,
        has_remaining_batches=has_remaining_batches,
        ambiguous_prompts=metrics.ambiguous_prompts,
        judged_prompts=metrics.judged_prompts,
        judge_average_confidence=metrics.judge_average_confidence,
    )

    if stop_on_schema:
        return RunDecision(
            outcome="STOP",
            reason=(
                "Candidate exceeded the schema break threshold "
                f"({metrics.schema_break_rate:.0%} >= {config.risk.stop_on_schema_break_rate:.0%})."
                + _category_context(metrics, focus="schema", label="Most affected category")
            ),
            confidence=confidence,
            metrics=metrics,
        )

    if stop_on_high_criticality:
        return RunDecision(
            outcome="STOP",
            reason=(
                "Candidate exceeded the high-criticality failure threshold "
                f"({metrics.high_criticality_failure_rate:.0%} >= "
                f"{config.risk.stop_on_high_criticality_failure_rate:.0%})."
                + _category_context(
                    metrics,
                    focus="high_criticality",
                    label="Most affected category",
                )
            ),
            confidence=confidence,
            metrics=metrics,
        )

    if not reached_min_batches:
        return RunDecision(
            outcome="CONTINUE",
            reason=(
                f"Collected {len(batches)}/{config.sampling.min_batches} minimum batches. "
                "Need more evidence before declaring proceed."
                + _category_context(
                    metrics,
                    focus="overall",
                    label="Highest current category risk",
                )
            ),
            confidence=confidence,
            metrics=metrics,
        )

    if metrics.overall_risk <= config.risk.proceed_if_overall_risk_below and latency_within_bounds:
        return RunDecision(
            outcome="PROCEED",
            reason=(
                "Candidate stayed below the overall risk threshold and within latency limits "
                f"({metrics.overall_risk:.1%} <= {config.risk.proceed_if_overall_risk_below:.0%})."
                + _category_context(
                    metrics,
                    focus="overall",
                    label="Highest observed category risk",
                )
            ),
            confidence=confidence,
            metrics=metrics,
        )

    if not has_remaining_batches:
        return RunDecision(
            outcome="STOP",
            reason=(
                "Sample budget exhausted without reaching proceed thresholds. "
                f"Overall risk ended at {metrics.overall_risk:.1%}."
                + _category_context(
                    metrics,
                    focus="overall",
                    label="Highest final category risk",
                )
            ),
            confidence=1.0,
            metrics=metrics,
        )

    if not latency_within_bounds:
        return RunDecision(
            outcome="CONTINUE",
            reason=(
                "Candidate quality is not a stop yet, but latency regression is still above "
                "threshold. Continue sampling."
                + _category_context(
                    metrics,
                    focus="latency",
                    label="Largest latency regression",
                )
            ),
            confidence=confidence,
            metrics=metrics,
        )

    return RunDecision(
        outcome="CONTINUE",
        reason=(
            "Thresholds are not decisive yet. Continue sampling."
            + _category_context(metrics, focus="overall", label="Highest current category risk")
        ),
        confidence=confidence,
        metrics=metrics,
    )


def _collect_metrics(
    *,
    batches: list[BatchResult],
    latency: LatencyTracker,
    high_criticality_weight: float,
) -> DecisionMetrics:
    prompts = [prompt for batch in batches for prompt in batch.results]
    prompts_evaluated = len(prompts)
    if prompts_evaluated == 0:
        return DecisionMetrics()

    candidate_failures = 0
    candidate_regressions = 0
    schema_breaks = 0
    structured_prompts = 0
    high_criticality_prompts = 0
    high_criticality_failures = 0
    ambiguous_prompts = 0
    judged_prompts = 0
    escalated_prompts = 0
    judge_worse = 0
    judge_equivalent = 0
    judge_better = 0
    judge_confidence_sum = 0.0
    archetypes: dict[str, int] = {}
    category_accumulators: dict[str, _CategoryAccumulator] = {}

    for prompt in prompts:
        evaluation = prompt.evaluation
        if evaluation is None:
            msg = f"Prompt {prompt.prompt_id} is missing quality evaluation"
            raise ValueError(msg)

        category_acc = category_accumulators.setdefault(prompt.category, _CategoryAccumulator())
        category_acc.prompts_evaluated += 1

        if evaluation.needs_judge:
            ambiguous_prompts += 1
            category_acc.ambiguous_prompts += 1
        if evaluation.candidate_failed:
            candidate_failures += 1
            category_acc.candidate_failures += 1
        if evaluation.candidate_regressed:
            candidate_regressions += 1
            category_acc.candidate_regressions += 1
        if prompt.criticality == "high":
            high_criticality_prompts += 1
            category_acc.high_criticality_prompts += 1
            if evaluation.candidate_failed:
                high_criticality_failures += 1
                category_acc.high_criticality_failures += 1
        if has_structured_expectation(prompt.expected_output_type):
            structured_prompts += 1
            category_acc.structured_prompts += 1
            if evaluation.schema_break:
                schema_breaks += 1
                category_acc.schema_breaks += 1

        _record_archetypes(archetypes, evaluation.failure_archetypes)
        _record_archetypes(category_acc.archetypes, evaluation.failure_archetypes)

        if evaluation.judge is not None:
            if evaluation.judge.escalated:
                escalated_prompts += 1
            if evaluation.judge.is_error:
                continue
            if evaluation.judge.verdict != "unavailable":
                judged_prompts += 1
                category_acc.judged_prompts += 1
                judge_confidence_sum += evaluation.judge.confidence
                category_acc.judge_confidence_sum += evaluation.judge.confidence
                if evaluation.judge.verdict == "candidate_worse":
                    judge_worse += 1
                    category_acc.judge_worse += 1
                elif evaluation.judge.verdict == "candidate_better":
                    judge_better += 1
                else:
                    judge_equivalent += 1

    baseline_latency = latency.baseline_stats()
    candidate_latency = latency.candidate_stats()
    latency_p50_ratio = _safe_ratio(candidate_latency.p50_ms, baseline_latency.p50_ms)
    latency_p95_ratio = _safe_ratio(candidate_latency.p95_ms, baseline_latency.p95_ms)
    latency_risk = _latency_risk(latency_p50_ratio, latency_p95_ratio)

    candidate_failure_rate = candidate_failures / prompts_evaluated
    candidate_regression_rate = candidate_regressions / prompts_evaluated
    schema_break_rate = schema_breaks / structured_prompts if structured_prompts else 0.0
    high_criticality_failure_rate = (
        high_criticality_failures / high_criticality_prompts if high_criticality_prompts else 0.0
    )
    judge_worse_rate = judge_worse / judged_prompts if judged_prompts else 0.0
    judge_equivalent_rate = judge_equivalent / judged_prompts if judged_prompts else 0.0
    judge_better_rate = judge_better / judged_prompts if judged_prompts else 0.0
    judge_average_confidence = judge_confidence_sum / judged_prompts if judged_prompts else 0.0

    weighted_total = 4.0 + high_criticality_weight
    overall_risk = (
        candidate_regression_rate
        + candidate_failure_rate
        + schema_break_rate
        + (high_criticality_weight * high_criticality_failure_rate)
        + latency_risk
    ) / weighted_total

    category_scores = _build_category_scores(
        category_accumulators,
        latency,
        high_criticality_weight=high_criticality_weight,
    )

    return DecisionMetrics(
        prompts_evaluated=prompts_evaluated,
        structured_prompts=structured_prompts,
        high_criticality_prompts=high_criticality_prompts,
        ambiguous_prompts=ambiguous_prompts,
        judged_prompts=judged_prompts,
        escalated_prompts=escalated_prompts,
        candidate_failure_rate=candidate_failure_rate,
        candidate_regression_rate=candidate_regression_rate,
        schema_break_rate=schema_break_rate,
        high_criticality_failure_rate=high_criticality_failure_rate,
        judge_worse_rate=judge_worse_rate,
        judge_equivalent_rate=judge_equivalent_rate,
        judge_better_rate=judge_better_rate,
        judge_average_confidence=judge_average_confidence,
        overall_risk=overall_risk,
        latency_p50_ratio=latency_p50_ratio,
        latency_p95_ratio=latency_p95_ratio,
        archetypes=dict(sorted(archetypes.items())),
        category_scores=category_scores,
    )


def _build_category_scores(
    category_accumulators: dict[str, _CategoryAccumulator],
    latency: LatencyTracker,
    *,
    high_criticality_weight: float,
) -> list[CategoryScore]:
    weighted_total = 4.0 + high_criticality_weight
    scores: list[CategoryScore] = []

    for category, acc in category_accumulators.items():
        baseline_latency = latency.baseline_stats(category)
        candidate_latency = latency.candidate_stats(category)
        latency_p50_ratio = _safe_ratio(candidate_latency.p50_ms, baseline_latency.p50_ms)
        latency_p95_ratio = _safe_ratio(candidate_latency.p95_ms, baseline_latency.p95_ms)
        latency_risk = _latency_risk(latency_p50_ratio, latency_p95_ratio)

        candidate_failure_rate = acc.candidate_failures / acc.prompts_evaluated
        candidate_regression_rate = acc.candidate_regressions / acc.prompts_evaluated
        schema_break_rate = (
            acc.schema_breaks / acc.structured_prompts if acc.structured_prompts else 0.0
        )
        high_criticality_failure_rate = (
            acc.high_criticality_failures / acc.high_criticality_prompts
            if acc.high_criticality_prompts
            else 0.0
        )
        judge_worse_rate = acc.judge_worse / acc.judged_prompts if acc.judged_prompts else 0.0
        judge_average_confidence = (
            acc.judge_confidence_sum / acc.judged_prompts if acc.judged_prompts else 0.0
        )
        overall_risk = (
            candidate_regression_rate
            + candidate_failure_rate
            + schema_break_rate
            + (high_criticality_weight * high_criticality_failure_rate)
            + latency_risk
        ) / weighted_total

        scores.append(
            CategoryScore(
                category=category,
                prompts_evaluated=acc.prompts_evaluated,
                structured_prompts=acc.structured_prompts,
                high_criticality_prompts=acc.high_criticality_prompts,
                ambiguous_prompts=acc.ambiguous_prompts,
                judged_prompts=acc.judged_prompts,
                candidate_failure_rate=candidate_failure_rate,
                candidate_regression_rate=candidate_regression_rate,
                schema_break_rate=schema_break_rate,
                high_criticality_failure_rate=high_criticality_failure_rate,
                judge_worse_rate=judge_worse_rate,
                judge_average_confidence=judge_average_confidence,
                overall_risk=overall_risk,
                latency_p50_ratio=latency_p50_ratio,
                latency_p95_ratio=latency_p95_ratio,
                archetypes=dict(sorted(acc.archetypes.items())),
            )
        )

    scores.sort(key=lambda score: (-score.overall_risk, score.category))
    return scores


def _record_archetypes(target: dict[str, int], archetypes: list[str]) -> None:
    for archetype in dict.fromkeys(archetypes):
        target[archetype] = target.get(archetype, 0) + 1


def _category_context(
    metrics: DecisionMetrics,
    *,
    focus: Literal["schema", "high_criticality", "overall", "latency"],
    label: str,
) -> str:
    score = _select_category_score(metrics, focus=focus)
    if score is None:
        return ""

    if focus == "schema":
        metric_text = f"schema {score.schema_break_rate:.0%}"
    elif focus == "high_criticality":
        metric_text = f"high-crit {score.high_criticality_failure_rate:.0%}"
    elif focus == "latency":
        metric_text = f"p50 {score.latency_p50_ratio:.2f}x, p95 {score.latency_p95_ratio:.2f}x"
    else:
        metric_text = f"risk {score.overall_risk:.1%}"

    archetypes = _top_archetype_summary(score.archetypes)
    suffix = f"; {archetypes}" if archetypes else ""
    return f" {label}: {score.category} ({metric_text}{suffix})."


def _select_category_score(
    metrics: DecisionMetrics,
    *,
    focus: Literal["schema", "high_criticality", "overall", "latency"],
) -> CategoryScore | None:
    if not metrics.category_scores:
        return None

    def _focus_value(score: CategoryScore) -> float:
        if focus == "schema":
            return score.schema_break_rate
        if focus == "high_criticality":
            return score.high_criticality_failure_rate
        if focus == "latency":
            return max(score.latency_p50_ratio - 1.0, score.latency_p95_ratio - 1.0)
        return score.overall_risk

    candidates = [score for score in metrics.category_scores if _focus_value(score) > 0]
    if not candidates:
        candidates = list(metrics.category_scores)

    return max(
        candidates, key=lambda score: (_focus_value(score), score.overall_risk, score.category)
    )


def _top_archetype_summary(archetypes: dict[str, int]) -> str:
    if not archetypes:
        return ""
    top = sorted(archetypes.items(), key=lambda item: (-item[1], item[0]))[:2]
    return ", ".join(f"{name} x{count}" for name, count in top)


def _safe_ratio(candidate: float, baseline: float) -> float:
    if candidate <= 0:
        return 0.0
    if baseline <= 0:
        return 1.0
    return candidate / baseline


def _latency_risk(latency_p50_ratio: float, latency_p95_ratio: float) -> float:
    p50_penalty = max(0.0, latency_p50_ratio - 1.0)
    p95_penalty = max(0.0, latency_p95_ratio - 1.0)
    return min(1.0, (p50_penalty + p95_penalty) / 2.0)


def _decision_confidence(
    *,
    batches_evaluated: int,
    total_batches_planned: int,
    total_prompts_evaluated: int,
    total_prompts_planned: int,
    has_remaining_batches: bool,
    ambiguous_prompts: int,
    judged_prompts: int,
    judge_average_confidence: float,
) -> float:
    if not has_remaining_batches:
        return 1.0

    batch_ratio = batches_evaluated / total_batches_planned if total_batches_planned else 1.0
    prompt_ratio = total_prompts_evaluated / total_prompts_planned if total_prompts_planned else 1.0
    base_confidence = min(0.95, max(0.2, (batch_ratio + prompt_ratio) / 2.0))
    if ambiguous_prompts == 0:
        return base_confidence

    judge_coverage = judged_prompts / ambiguous_prompts if ambiguous_prompts else 1.0
    adjusted = base_confidence * (0.65 + 0.35 * judge_coverage)
    adjusted += 0.10 * judge_coverage * judge_average_confidence
    return min(0.97, max(0.2, adjusted))

"""Run-level decision engine for Driftcut canary execution."""

from __future__ import annotations

from driftcut.config import DriftcutConfig
from driftcut.models import BatchResult, DecisionMetrics, RunDecision
from driftcut.quality import has_structured_expectation
from driftcut.trackers import LatencyTracker


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
            ),
            confidence=1.0,
            metrics=metrics,
        )

    if not latency_within_bounds:
        return RunDecision(
            outcome="CONTINUE",
            reason=(
                "Candidate quality is not a stop yet, but latency regression is "
                "still above threshold. Continue sampling."
            ),
            confidence=confidence,
            metrics=metrics,
        )

    return RunDecision(
        outcome="CONTINUE",
        reason="Thresholds are not decisive yet. Continue sampling.",
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

    for prompt in prompts:
        evaluation = prompt.evaluation
        if evaluation is None:
            msg = f"Prompt {prompt.prompt_id} is missing quality evaluation"
            raise ValueError(msg)

        if evaluation.needs_judge:
            ambiguous_prompts += 1
        if evaluation.candidate_failed:
            candidate_failures += 1
            if evaluation.candidate.archetype is not None:
                archetypes[evaluation.candidate.archetype] = (
                    archetypes.get(evaluation.candidate.archetype, 0) + 1
                )
            elif (
                evaluation.judge is not None
                and not evaluation.judge.is_error
                and evaluation.judge.verdict == "candidate_worse"
            ):
                archetypes["judge_worse"] = archetypes.get("judge_worse", 0) + 1
        if evaluation.candidate_regressed:
            candidate_regressions += 1
        if evaluation.judge is not None:
            if evaluation.judge.escalated:
                escalated_prompts += 1
            if evaluation.judge.is_error:
                archetypes["judge_unavailable"] = archetypes.get("judge_unavailable", 0) + 1
            elif evaluation.judge.verdict != "unavailable":
                judged_prompts += 1
                judge_confidence_sum += evaluation.judge.confidence
                if evaluation.judge.verdict == "candidate_worse":
                    judge_worse += 1
                elif evaluation.judge.verdict == "candidate_better":
                    judge_better += 1
                else:
                    judge_equivalent += 1
        if prompt.criticality == "high":
            high_criticality_prompts += 1
            if evaluation.candidate_failed:
                high_criticality_failures += 1
        if has_structured_expectation(prompt.expected_output_type):
            structured_prompts += 1
            if evaluation.schema_break:
                schema_breaks += 1

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
    )


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

"""Migration runner - orchestrates batch execution and decisions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn

from driftcut.config import DriftcutConfig
from driftcut.corpus import PromptRecord
from driftcut.decision import decide_run
from driftcut.executor import execute_prompt
from driftcut.judge import (
    apply_judge_result,
    judge_prompt_result,
    judge_strategy_enabled,
    prompt_needs_judge,
)
from driftcut.models import BatchResult, ModelResponse, PromptResult, RunDecision
from driftcut.quality import evaluate_prompt_result
from driftcut.replay import ReplayDataset
from driftcut.sampler import Batch, StratifiedSampler
from driftcut.store import MemoryStore
from driftcut.trackers import CostTracker, LatencyTracker

console = Console()
type BatchRunner = Callable[[Batch, DriftcutConfig, Progress, TaskID], Awaitable[BatchResult]]


@dataclass
class RunResult:
    """Complete result of a migration run."""

    config_name: str
    run_id: str = field(default_factory=lambda: f"run-{uuid4().hex[:12]}")
    mode: Literal["live", "replay"] = "live"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    memory_backend: str | None = None
    batches: list[BatchResult] = field(default_factory=list)
    latency: LatencyTracker = field(default_factory=LatencyTracker)
    cost: CostTracker = field(default_factory=CostTracker)
    decision_history: list[RunDecision] = field(default_factory=list)
    final_decision: RunDecision | None = None
    stopped_early: bool = False
    historical_metrics_present: dict[str, bool] = field(default_factory=dict)
    baseline_cache_hits: int = 0
    baseline_cache_misses: int = 0

    @property
    def total_prompts(self) -> int:
        return sum(batch.size for batch in self.batches)

    @property
    def total_batches(self) -> int:
        return len(self.batches)


def build_prompt_result(
    prompt: PromptRecord,
    baseline_resp: ModelResponse,
    candidate_resp: ModelResponse,
) -> PromptResult:
    """Build a PromptResult from metadata plus paired baseline/candidate responses."""
    return PromptResult(
        prompt_id=prompt.id,
        category=prompt.category,
        criticality=prompt.criticality,
        prompt_text=prompt.prompt,
        expected_output_type=prompt.expected_output_type,
        baseline=baseline_resp,
        candidate=candidate_resp,
        notes=prompt.notes,
        required_substrings=list(prompt.required_substrings),
        forbidden_substrings=list(prompt.forbidden_substrings),
        json_required_keys=list(prompt.json_required_keys),
        max_output_chars=prompt.max_output_chars,
    )


async def finalize_prompt_result(result: PromptResult, config: DriftcutConfig) -> PromptResult:
    """Run shared post-processing for a paired prompt result."""
    result.evaluation = evaluate_prompt_result(result)
    result.evaluation.needs_judge = prompt_needs_judge(result)
    if result.evaluation.needs_judge and judge_strategy_enabled(config.evaluation):
        judge = await judge_prompt_result(result, config.evaluation)
        result.evaluation = apply_judge_result(
            result,
            result.evaluation,
            judge,
            detect_failure_archetypes=config.evaluation.detect_failure_archetypes,
        )
    return result


async def _run_prompt(
    prompt: PromptRecord,
    config: DriftcutConfig,
    store: MemoryStore,
) -> PromptResult:
    """Run a single prompt against both models concurrently."""
    baseline_task = execute_prompt(
        prompt.prompt,
        config.models.baseline,
        store=store,
        use_baseline_cache=True,
    )
    candidate_task = execute_prompt(prompt.prompt, config.models.candidate)
    baseline_resp, candidate_resp = await asyncio.gather(baseline_task, candidate_task)

    result = PromptResult(
        prompt_id=prompt.id,
        category=prompt.category,
        criticality=prompt.criticality,
        prompt_text=prompt.prompt,
        expected_output_type=prompt.expected_output_type,
        baseline=baseline_resp,
        candidate=candidate_resp,
        notes=prompt.notes,
        required_substrings=list(prompt.required_substrings),
        forbidden_substrings=list(prompt.forbidden_substrings),
        json_required_keys=list(prompt.json_required_keys),
        max_output_chars=prompt.max_output_chars,
    )
    return await finalize_prompt_result(result, config)


async def _finalize_indexed_result(
    index: int,
    result: PromptResult,
    config: DriftcutConfig,
) -> tuple[int, PromptResult]:
    return index, await finalize_prompt_result(result, config)


async def _run_batch(
    batch: Batch,
    config: DriftcutConfig,
    progress: Progress,
    task_id: TaskID,
    store: MemoryStore,
) -> BatchResult:
    """Run all prompts in a batch concurrently while preserving input order."""

    async def _run_indexed_prompt(index: int, prompt: PromptRecord) -> tuple[int, PromptResult]:
        return index, await _run_prompt(prompt, config, store)

    tasks = [_run_indexed_prompt(i, prompt) for i, prompt in enumerate(batch.prompts)]
    indexed_results: list[tuple[int, PromptResult]] = []
    for coro in asyncio.as_completed(tasks):
        indexed_results.append(await coro)
        progress.advance(task_id)
    indexed_results.sort(key=lambda item: item[0])
    results = [result for _, result in indexed_results]
    return BatchResult(batch_number=batch.batch_number, results=results)


async def _run_replay_batch(
    batch: Batch,
    config: DriftcutConfig,
    replay_dataset: ReplayDataset,
    progress: Progress,
    task_id: TaskID,
) -> BatchResult:
    """Materialize one replay batch and apply the shared evaluation pipeline."""

    async def _materialize_indexed_prompt(
        index: int,
        prompt: PromptRecord,
    ) -> tuple[int, PromptResult]:
        pair = replay_dataset.pair_for(prompt)
        result = build_prompt_result(prompt, pair.baseline, pair.candidate)
        return await _finalize_indexed_result(index, result, config)

    tasks = [_materialize_indexed_prompt(i, prompt) for i, prompt in enumerate(batch.prompts)]
    indexed_results: list[tuple[int, PromptResult]] = []
    for coro in asyncio.as_completed(tasks):
        indexed_results.append(await coro)
        progress.advance(task_id)
    indexed_results.sort(key=lambda item: item[0])
    results = [result for _, result in indexed_results]
    return BatchResult(batch_number=batch.batch_number, results=results)


def _print_run_header(config: DriftcutConfig, *, mode: Literal["live", "replay"]) -> None:
    baseline_name = f"{config.models.baseline.provider}/{config.models.baseline.model}"
    candidate_name = f"{config.models.candidate.provider}/{config.models.candidate.model}"

    console.print()
    console.print(f"[bold]{config.name}[/bold]")
    console.print(f"  Mode:      {mode}")
    console.print(f"  Baseline:  {baseline_name}")
    console.print(f"  Candidate: {candidate_name}")
    console.print()


def _record_batch_metrics(
    run_result: RunResult,
    batch_result: BatchResult,
    *,
    track_latency: bool,
    cache_enabled: bool,
) -> None:
    for prompt_result in batch_result.results:
        if track_latency:
            run_result.latency.record(prompt_result)
        run_result.cost.record(prompt_result)
        if cache_enabled:
            if prompt_result.baseline.cache_hit:
                run_result.baseline_cache_hits += 1
            else:
                run_result.baseline_cache_misses += 1


async def _execute_canary(
    config: DriftcutConfig,
    sampler: StratifiedSampler,
    batch_runner: BatchRunner,
    store: MemoryStore,
    *,
    mode: Literal["live", "replay"],
    historical_metrics_present: dict[str, bool] | None = None,
) -> RunResult:
    """Execute a live or replay canary run."""
    run_result = RunResult(
        config_name=config.name,
        mode=mode,
        memory_backend=None if store.backend_name == "disabled" else store.backend_name,
        historical_metrics_present=historical_metrics_present or {},
    )
    total_prompts = sampler.total_prompts_planned
    total_batches = sampler.total_batches_possible
    _print_run_header(config, mode=mode)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            for batch in sampler:
                task_id = progress.add_task(
                    f"Batch {batch.batch_number}",
                    total=batch.size,
                )
                batch_result = await batch_runner(batch, config, progress, task_id)
                run_result.batches.append(batch_result)
                _record_batch_metrics(
                    run_result,
                    batch_result,
                    track_latency=config.latency.track,
                    cache_enabled=mode == "live" and store.response_cache_enabled,
                )

                decision = decide_run(
                    config,
                    run_result.batches,
                    run_result.latency,
                    total_prompts_planned=total_prompts,
                    total_batches_planned=total_batches,
                    has_remaining_batches=sampler.has_next(),
                )
                run_result.decision_history.append(decision)
                run_result.final_decision = decision

                _print_batch_summary(batch_result, run_result, config)

                if decision.outcome in {"STOP", "PROCEED"}:
                    run_result.stopped_early = sampler.has_next()
                    break

        if run_result.final_decision is None:
            run_result.final_decision = decide_run(
                config,
                run_result.batches,
                run_result.latency,
                total_prompts_planned=total_prompts,
                total_batches_planned=total_batches,
                has_remaining_batches=False,
            )

        run_result.completed_at = datetime.now(UTC).isoformat()
        _print_run_summary(run_result, total_prompts, config)

        if store.run_history_enabled:
            from driftcut.reporting import build_run_payload

            await store.save_run_document(run_result.run_id, build_run_payload(config, run_result))

        return run_result
    finally:
        await store.close()


async def run_migration(
    config: DriftcutConfig,
    sampler: StratifiedSampler,
    *,
    store: MemoryStore,
) -> RunResult:
    """Execute the full migration canary run."""
    return await _execute_canary(
        config,
        sampler,
        lambda batch, batch_config, progress, task_id: _run_batch(
            batch,
            batch_config,
            progress,
            task_id,
            store,
        ),
        store,
        mode="live",
    )


async def run_replay(
    config: DriftcutConfig,
    replay_dataset: ReplayDataset,
    sampler: StratifiedSampler,
    *,
    store: MemoryStore,
) -> RunResult:
    """Replay a historical paired-output dataset through the Driftcut decision engine."""

    async def _batch_runner(
        batch: Batch,
        batch_config: DriftcutConfig,
        progress: Progress,
        task_id: TaskID,
    ) -> BatchResult:
        return await _run_replay_batch(batch, batch_config, replay_dataset, progress, task_id)

    return await _execute_canary(
        config,
        sampler,
        _batch_runner,
        store,
        mode="replay",
        historical_metrics_present=replay_dataset.historical_metrics_present,
    )


def _print_batch_summary(batch: BatchResult, run: RunResult, config: DriftcutConfig) -> None:
    """Print a short summary after each batch."""
    cost = run.cost.summary
    decision = run.final_decision
    cost_label = f"${cost.total_usd:.4f} cumulative"
    if run.mode == "replay":
        if run.historical_metrics_present.get("cost", False) or cost.judge_usd > 0:
            cost_label = f"${cost.total_usd:.4f} combined cost view"
        else:
            cost_label = "cost unavailable"

    console.print(
        f"  [dim]Batch {batch.batch_number}:[/dim] "
        f"{batch.size} prompts, "
        f"{batch.candidate_errors} API errors, "
        f"{cost_label}"
    )
    if decision is not None:
        confidence = (
            f" [dim]({decision.confidence:.0%} confidence)[/dim]"
            if config.output.show_confidence
            else ""
        )
        console.print(f"    Decision: [bold]{decision.outcome}[/bold]{confidence}")
        if decision.metrics.judged_prompts > 0:
            console.print(
                "    [dim]"
                f"Judge coverage: {decision.metrics.judged_prompts}/"
                f"{decision.metrics.ambiguous_prompts} ambiguous prompts[/dim]"
            )
        console.print(f"    [dim]{decision.reason}[/dim]")


def _print_run_summary(run: RunResult, corpus_total: int, config: DriftcutConfig) -> None:
    """Print the final run summary."""
    cost = run.cost.summary
    baseline_latency = run.latency.baseline_stats()
    candidate_latency = run.latency.candidate_stats()
    decision = run.final_decision

    console.print()
    console.print(f"[bold]{'Replay complete' if run.mode == 'replay' else 'Run complete'}[/bold]")
    console.print(f"  Prompts tested: {run.total_prompts}/{corpus_total}")
    console.print(f"  Batches tested: {run.total_batches}")
    if run.mode == "replay":
        if run.historical_metrics_present.get("cost", False):
            console.print(f"  Historical model cost: ${cost.baseline_usd + cost.candidate_usd:.4f}")
        else:
            console.print("  Historical model cost: not provided")
        if cost.judge_usd > 0:
            console.print(f"  Replay-time judge cost: ${cost.judge_usd:.4f}")
        console.print(f"  Combined cost view:     ${cost.total_usd:.4f}")
    else:
        console.print(f"  Total cost:     ${cost.total_usd:.4f}")
        if cost.judge_usd > 0:
            console.print(f"  Judge cost:     ${cost.judge_usd:.4f}")
        if cost.baseline_cache_saved_usd > 0:
            console.print(f"  Baseline saved: ${cost.baseline_cache_saved_usd:.4f}")
    if config.latency.track and baseline_latency.count > 0 and candidate_latency.count > 0:
        latency_label = "Historical latency" if run.mode == "replay" else "Latency"
        console.print(
            f"  {latency_label} p50:    "
            f"{baseline_latency.p50_ms:.0f}ms (baseline) -> "
            f"{candidate_latency.p50_ms:.0f}ms (candidate)"
        )
        console.print(
            f"  {latency_label} p95:    "
            f"{baseline_latency.p95_ms:.0f}ms (baseline) -> "
            f"{candidate_latency.p95_ms:.0f}ms (candidate)"
        )
    if decision is not None:
        confidence = (
            f" ({decision.confidence:.0%} confidence)" if config.output.show_confidence else ""
        )
        console.print(f"  Decision:       [bold]{decision.outcome}[/bold]{confidence}")
        console.print(f"  Reason:         {decision.reason}")
        if config.output.show_thresholds:
            console.print(
                "  Risk summary:   "
                f"overall={decision.metrics.overall_risk:.1%}, "
                f"high-crit={decision.metrics.high_criticality_failure_rate:.1%}, "
                f"schema={decision.metrics.schema_break_rate:.1%}"
            )
            top_category = _top_category_summary(decision.metrics)
            if top_category:
                console.print(f"  Top category:   {top_category}")
        if decision.metrics.ambiguous_prompts > 0:
            escalated_str = ""
            if decision.metrics.escalated_prompts > 0:
                escalated_str = f", escalated={decision.metrics.escalated_prompts}"
            console.print(
                "  Judge summary:  "
                f"{decision.metrics.judged_prompts}/{decision.metrics.ambiguous_prompts} judged, "
                f"worse={decision.metrics.judge_worse_rate:.1%}, "
                f"avg_conf={decision.metrics.judge_average_confidence:.0%}"
                f"{escalated_str}"
            )
    if run.memory_backend is not None:
        console.print(f"  Memory backend: {run.memory_backend}")
        if run.baseline_cache_hits or run.baseline_cache_misses:
            console.print(
                "  Baseline cache: "
                f"{run.baseline_cache_hits} hit(s), {run.baseline_cache_misses} miss(es)"
            )
    console.print()


def _top_category_summary(metrics: object) -> str:
    from driftcut.models import DecisionMetrics

    if not isinstance(metrics, DecisionMetrics) or not metrics.category_scores:
        return ""

    score = metrics.category_scores[0]
    archetypes = ""
    if score.archetypes:
        top = sorted(score.archetypes.items(), key=lambda item: (-item[1], item[0]))[:2]
        archetypes = " | " + ", ".join(f"{name} x{count}" for name, count in top)
    return f"{score.category} ({score.overall_risk:.1%} risk{archetypes})"

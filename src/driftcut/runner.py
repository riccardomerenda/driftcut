"""Migration runner - orchestrates batch execution and decisions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

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
from driftcut.models import BatchResult, PromptResult, RunDecision
from driftcut.quality import evaluate_prompt_result
from driftcut.sampler import Batch, StratifiedSampler
from driftcut.trackers import CostTracker, LatencyTracker

console = Console()


@dataclass
class RunResult:
    """Complete result of a migration run."""

    config_name: str
    batches: list[BatchResult] = field(default_factory=list)
    latency: LatencyTracker = field(default_factory=LatencyTracker)
    cost: CostTracker = field(default_factory=CostTracker)
    decision_history: list[RunDecision] = field(default_factory=list)
    final_decision: RunDecision | None = None
    stopped_early: bool = False

    @property
    def total_prompts(self) -> int:
        return sum(batch.size for batch in self.batches)

    @property
    def total_batches(self) -> int:
        return len(self.batches)


async def _run_prompt(
    prompt: PromptRecord,
    config: DriftcutConfig,
) -> PromptResult:
    """Run a single prompt against both models concurrently."""
    baseline_task = execute_prompt(prompt.prompt, config.models.baseline)
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
    result.evaluation = evaluate_prompt_result(result)
    result.evaluation.needs_judge = prompt_needs_judge(result)
    if result.evaluation.needs_judge and judge_strategy_enabled(config.evaluation):
        judge = await judge_prompt_result(result, config.evaluation)
        result.evaluation = apply_judge_result(result.evaluation, judge)
    return result


async def _run_batch(
    batch: Batch,
    config: DriftcutConfig,
    progress: Progress,
    task_id: TaskID,
) -> BatchResult:
    """Run all prompts in a batch concurrently while preserving input order."""

    async def _run_indexed_prompt(index: int, prompt: PromptRecord) -> tuple[int, PromptResult]:
        return index, await _run_prompt(prompt, config)

    tasks = [_run_indexed_prompt(i, prompt) for i, prompt in enumerate(batch.prompts)]
    indexed_results: list[tuple[int, PromptResult]] = []
    for coro in asyncio.as_completed(tasks):
        indexed_results.append(await coro)
        progress.advance(task_id)
    indexed_results.sort(key=lambda item: item[0])
    results = [result for _, result in indexed_results]
    return BatchResult(batch_number=batch.batch_number, results=results)


async def run_migration(
    config: DriftcutConfig,
    sampler: StratifiedSampler,
) -> RunResult:
    """Execute the full migration canary run."""
    run_result = RunResult(config_name=config.name)
    total_prompts = sampler.total_prompts_planned
    total_batches = sampler.total_batches_possible
    baseline_name = f"{config.models.baseline.provider}/{config.models.baseline.model}"
    candidate_name = f"{config.models.candidate.provider}/{config.models.candidate.model}"

    console.print()
    console.print(f"[bold]{config.name}[/bold]")
    console.print(f"  Baseline:  {baseline_name}")
    console.print(f"  Candidate: {candidate_name}")
    console.print()

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
            batch_result = await _run_batch(batch, config, progress, task_id)
            run_result.batches.append(batch_result)

            for prompt_result in batch_result.results:
                run_result.latency.record(prompt_result)
                run_result.cost.record(prompt_result)

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

    _print_run_summary(run_result, total_prompts, config)
    return run_result


def _print_batch_summary(batch: BatchResult, run: RunResult, config: DriftcutConfig) -> None:
    """Print a short summary after each batch."""
    cost = run.cost.summary
    decision = run.final_decision

    console.print(
        f"  [dim]Batch {batch.batch_number}:[/dim] "
        f"{batch.size} prompts, "
        f"{batch.candidate_errors} API errors, "
        f"${cost.total_usd:.4f} cumulative"
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
    console.print("[bold]Run complete[/bold]")
    console.print(f"  Prompts tested: {run.total_prompts}/{corpus_total}")
    console.print(f"  Batches tested: {run.total_batches}")
    console.print(f"  Total cost:     ${cost.total_usd:.4f}")
    if cost.judge_usd > 0:
        console.print(f"  Judge cost:     ${cost.judge_usd:.4f}")
    if baseline_latency.count > 0 and candidate_latency.count > 0:
        console.print(
            "  Latency p50:    "
            f"{baseline_latency.p50_ms:.0f}ms (baseline) -> "
            f"{candidate_latency.p50_ms:.0f}ms (candidate)"
        )
        console.print(
            "  Latency p95:    "
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
        if decision.metrics.ambiguous_prompts > 0:
            console.print(
                "  Judge summary:  "
                f"{decision.metrics.judged_prompts}/{decision.metrics.ambiguous_prompts} judged, "
                f"worse={decision.metrics.judge_worse_rate:.1%}, "
                f"avg_conf={decision.metrics.judge_average_confidence:.0%}"
            )
    console.print()

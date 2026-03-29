"""Migration runner — orchestrates batch execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn

from driftcut.config import DriftcutConfig
from driftcut.corpus import PromptRecord
from driftcut.executor import execute_prompt
from driftcut.models import BatchResult, PromptResult
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

    @property
    def total_prompts(self) -> int:
        return sum(b.size for b in self.batches)

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
    return PromptResult(
        prompt_id=prompt.id,
        category=prompt.category,
        criticality=prompt.criticality,
        prompt_text=prompt.prompt,
        expected_output_type=prompt.expected_output_type,
        baseline=baseline_resp,
        candidate=candidate_resp,
    )


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
    """Execute the full migration canary run.

    For each batch:
      1. Run all prompts against baseline and candidate concurrently.
      2. Record latency and cost.
      3. Print batch summary.
    """
    run_result = RunResult(config_name=config.name)
    total_prompts = sampler.total_prompts_planned
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

            for pr in batch_result.results:
                run_result.latency.record(pr)
                run_result.cost.record(pr)

            _print_batch_summary(batch_result, run_result)

    _print_run_summary(run_result, total_prompts)
    return run_result


def _print_batch_summary(batch: BatchResult, run: RunResult) -> None:
    """Print a short summary after each batch."""
    cost = run.cost.summary
    console.print(
        f"  [dim]Batch {batch.batch_number}:[/dim] "
        f"{batch.size} prompts, "
        f"{batch.candidate_errors} errors, "
        f"${cost.total_usd:.4f} cumulative"
    )


def _print_run_summary(run: RunResult, corpus_total: int) -> None:
    """Print the final run summary."""
    cost = run.cost.summary
    bl = run.latency.baseline_stats()
    cd = run.latency.candidate_stats()

    console.print()
    console.print("[bold]Run complete[/bold]")
    console.print(f"  Prompts tested: {run.total_prompts}/{corpus_total}")
    console.print(f"  Total cost:     ${cost.total_usd:.4f}")
    if bl.count > 0 and cd.count > 0:
        console.print(
            f"  Latency p50:    {bl.p50_ms:.0f}ms (baseline) → {cd.p50_ms:.0f}ms (candidate)"
        )
        console.print(
            f"  Latency p95:    {bl.p95_ms:.0f}ms (baseline) → {cd.p95_ms:.0f}ms (candidate)"
        )
    console.print()

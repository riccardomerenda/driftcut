"""Driftcut CLI - early-stop canary testing for LLM model migrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from driftcut import __version__
from driftcut.config import DriftcutConfig, load_config
from driftcut.corpus import Corpus, load_corpus
from driftcut.init import scaffold_project
from driftcut.replay import load_replay_dataset
from driftcut.reporting import save_run_outputs
from driftcut.sampler import StratifiedSampler
from driftcut.store import create_memory_store

app = typer.Typer(
    name="driftcut",
    help="Early-stop decision gating for LLM model migrations.",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"driftcut {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Driftcut - stop bad LLM migrations early."""


def _resolve_corpus_path(config_path: Path, corpus_file: Path) -> Path:
    """Resolve corpus path relative to the config file's directory."""
    if corpus_file.is_absolute():
        return corpus_file
    return config_path.parent / corpus_file


def _print_validation_summary(
    config_path: Path,
    cfg: DriftcutConfig,
    corpus: Corpus,
    sampler: StratifiedSampler,
) -> None:
    """Print a Rich summary of the validated config and corpus."""
    if cfg.corpus is None:
        msg = "corpus.file is required for validation"
        raise ValueError(msg)

    console.print()
    console.print(
        Panel(
            f"[bold]{cfg.name}[/bold]\n{cfg.description}",
            title="Migration Config",
            border_style="green",
        )
    )

    models_table = Table(show_header=False, box=None, padding=(0, 2))
    models_table.add_column("Role", style="dim")
    models_table.add_column("Provider")
    models_table.add_column("Model", style="bold")
    models_table.add_row("Baseline", cfg.models.baseline.provider, cfg.models.baseline.model)
    models_table.add_row("Candidate", cfg.models.candidate.provider, cfg.models.candidate.model)
    console.print(Panel(models_table, title="Models", border_style="blue"))

    cat_counts = corpus.category_counts()
    crit_counts = corpus.criticality_counts()
    cat_lines = [f"  {category}: {count}" for category, count in cat_counts.items()]
    cat_lines.append(f"  [bold]Total: {corpus.size}[/bold]")
    crit_str = " | ".join(f"{key}: {value}" for key, value in sorted(crit_counts.items()))
    corpus_body = "\n".join(cat_lines) + f"\n\nCriticality: {crit_str}"
    console.print(
        Panel(
            corpus_body,
            title=f"Corpus - {config_path.parent / cfg.corpus.file}",
            border_style="blue",
        )
    )

    total_batches = sampler.total_batches_possible
    total_prompts = sampler.total_prompts_planned
    coverage = (total_prompts / corpus.size * 100) if corpus.size > 0 else 0
    per_batch = cfg.sampling.batch_size_per_category * len(corpus.categories)
    plan_lines = [
        "Batch size: "
        f"{cfg.sampling.batch_size_per_category} prompts/category x "
        f"{len(corpus.categories)} categories = {per_batch} prompts/batch",
        "Batches planned: "
        f"{total_batches} (min: {cfg.sampling.min_batches}, max: {cfg.sampling.max_batches})",
        f"Total prompts to test: {total_prompts}/{corpus.size} ({coverage:.0f}%)",
        "Deterministic checks: expected format, required content, and optional JSON keys",
        "Judge strategy: "
        f"{cfg.evaluation.judge_strategy} "
        "(semantic comparison for ambiguous prompts when enabled)",
    ]
    if cfg.memory is not None:
        plan_lines.append(
            "Memory: "
            f"{cfg.memory.backend} "
            f"(cache={cfg.memory.response_cache.enabled}, "
            f"history={cfg.memory.run_history.enabled})"
        )
    console.print(Panel("\n".join(plan_lines), title="Sampling Plan", border_style="blue"))

    thresh_table = Table(show_header=True, box=None, padding=(0, 2))
    thresh_table.add_column("Threshold")
    thresh_table.add_column("Value", justify="right")
    thresh_table.add_row(
        "High-crit failure rate -> stop",
        f"{cfg.risk.stop_on_high_criticality_failure_rate:.0%}",
    )
    thresh_table.add_row("Schema break rate -> stop", f"{cfg.risk.stop_on_schema_break_rate:.0%}")
    thresh_table.add_row(
        "Overall risk -> proceed",
        f"<= {cfg.risk.proceed_if_overall_risk_below:.0%}",
    )
    thresh_table.add_row("High-criticality weight", f"{cfg.risk.high_criticality_weight:.1f}x")
    thresh_table.add_row("Latency p50 threshold", f"{cfg.latency.regression_threshold_p50:.2f}x")
    thresh_table.add_row("Latency p95 threshold", f"{cfg.latency.regression_threshold_p95:.2f}x")
    console.print(Panel(thresh_table, title="Risk Thresholds", border_style="yellow"))

    console.print("[green bold]Config is valid.[/green bold] Ready to run.\n")


def _load_config_and_corpus(config_path: Path) -> tuple[DriftcutConfig, Corpus]:
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        console.print(f"[red bold]Config error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    if cfg.corpus is None:
        console.print(
            "[red bold]Config error:[/red bold] corpus.file is required for live run and validate"
        )
        raise typer.Exit(code=1)

    corpus_path = _resolve_corpus_path(config_path, cfg.corpus.file)
    try:
        corpus = load_corpus(corpus_path)
    except Exception as exc:
        console.print(f"[red bold]Corpus error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    return cfg, corpus


@app.command()
def run(
    config: Path = typer.Option(
        ...,
        "--config",
        "-c",
        help="Path to migration config YAML file.",
        exists=True,
        readable=True,
    ),
    seed: int = typer.Option(
        42,
        "--seed",
        help="Random seed for reproducible sampling.",
    ),
) -> None:
    """Run a migration canary test."""
    from driftcut.runner import run_migration

    cfg, corpus = _load_config_and_corpus(config)
    sampler = StratifiedSampler(corpus, cfg.sampling, seed=seed)
    try:
        store = create_memory_store(cfg.memory)
    except Exception as exc:
        console.print(f"[red bold]Memory config error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc
    result = asyncio.run(run_migration(cfg, sampler, store=store))

    written_files = save_run_outputs(config, cfg, result)
    for path in written_files:
        console.print(f"[dim]Saved {path.name} -> {path}[/dim]")


@app.command()
def replay(
    config: Path = typer.Option(
        ...,
        "--config",
        "-c",
        help="Path to replay config YAML file.",
        exists=True,
        readable=True,
    ),
    input: Path = typer.Option(
        ...,
        "--input",
        "-i",
        help="Path to canonical replay JSON file.",
        exists=True,
        readable=True,
    ),
    seed: int = typer.Option(
        42,
        "--seed",
        help="Random seed for reproducible replay sampling.",
    ),
) -> None:
    """Replay historical paired outputs through the Driftcut decision engine."""
    from driftcut.runner import run_replay

    try:
        cfg = load_config(config)
    except Exception as exc:
        console.print(f"[red bold]Config error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        replay_dataset = load_replay_dataset(input, cfg)
    except Exception as exc:
        console.print(f"[red bold]Replay input error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    sampler = StratifiedSampler(replay_dataset.corpus, cfg.sampling, seed=seed)
    try:
        store = create_memory_store(cfg.memory)
    except Exception as exc:
        console.print(f"[red bold]Memory config error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc
    result = asyncio.run(run_replay(cfg, replay_dataset, sampler, store=store))

    written_files = save_run_outputs(config, cfg, result)
    for path in written_files:
        console.print(f"[dim]Saved {path.name} -> {path}[/dim]")


@app.command()
def init(
    directory: Path = typer.Option(
        ".",
        "--dir",
        "-d",
        help="Directory to create files in (defaults to current directory).",
    ),
    baseline: str = typer.Option(
        "openai/gpt-4o",
        "--baseline",
        "-b",
        help="Baseline model in provider/model format.",
    ),
    candidate: str = typer.Option(
        "anthropic/claude-haiku",
        "--candidate",
        "-c",
        help="Candidate model in provider/model format.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing files.",
    ),
) -> None:
    """Scaffold a new migration config and sample corpus."""
    target = directory.resolve()
    target.mkdir(parents=True, exist_ok=True)

    config_path = target / "migration.yaml"
    corpus_path = target / "prompts.csv"

    if not force:
        existing = [p for p in (config_path, corpus_path) if p.exists()]
        if existing:
            names = ", ".join(p.name for p in existing)
            console.print(
                f"[red bold]Files already exist:[/red bold] {names}\n"
                "Use [bold]--force[/bold] to overwrite."
            )
            raise typer.Exit(code=1)

    written = scaffold_project(
        target=target,
        baseline=baseline,
        candidate=candidate,
    )
    for path in written:
        console.print(f"[dim]Created {path.name} -> {path}[/dim]")
    console.print()
    console.print("[green bold]Project scaffolded.[/green bold] Next steps:")
    console.print(f"  1. Edit [bold]{corpus_path}[/bold] with your prompts")
    console.print(f"  2. Run [bold]driftcut validate --config {config_path}[/bold]")
    console.print(f"  3. Run [bold]driftcut run --config {config_path}[/bold]")


@app.command()
def validate(
    config: Path = typer.Option(
        ...,
        "--config",
        "-c",
        help="Path to migration config YAML file.",
        exists=True,
        readable=True,
    ),
) -> None:
    """Validate a migration config and corpus without running."""
    cfg, corpus = _load_config_and_corpus(config)
    sampler = StratifiedSampler(corpus, cfg.sampling, seed=42)
    _print_validation_summary(config, cfg, corpus, sampler)

"""Driftcut CLI - early-stop canary testing for LLM model migrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from driftcut import __version__
from driftcut.bootstrap import classify_prompts, load_raw_prompts, write_corpus_csv
from driftcut.config import DriftcutConfig, load_config
from driftcut.corpus import Corpus, load_corpus
from driftcut.diff import DiffResult, diff_results, load_result
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
def bootstrap(
    input_file: Path = typer.Option(
        ...,
        "--input",
        "-i",
        help="Path to raw prompts file (.txt, .csv, or .json).",
        exists=True,
        readable=True,
    ),
    output: Path = typer.Option(
        "prompts.csv",
        "--output",
        "-o",
        help="Path to write the structured corpus CSV.",
    ),
    model: str = typer.Option(
        "openai/gpt-4.1-mini",
        "--model",
        "-m",
        help="Model to use for classification (provider/model format).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing output file.",
    ),
) -> None:
    """Classify raw prompts into a structured Driftcut corpus."""
    output_path = output.resolve()

    if not force and output_path.exists():
        console.print(
            f"[red bold]File already exists:[/red bold] {output_path.name}\n"
            "Use [bold]--force[/bold] to overwrite."
        )
        raise typer.Exit(code=1)

    try:
        prompts = load_raw_prompts(input_file)
    except Exception as exc:
        console.print(f"[red bold]Input error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    if not prompts:
        console.print("[red bold]No prompts found[/red bold] in the input file.")
        raise typer.Exit(code=1)

    console.print(f"Loaded [bold]{len(prompts)}[/bold] prompts from {input_file.name}")
    console.print(f"Classifying with [bold]{model}[/bold]...")

    try:
        classifications = asyncio.run(classify_prompts(prompts, model=model))
    except Exception as exc:
        console.print(f"[red bold]Classification error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_corpus_csv(output_path, prompts, classifications)

    # Summarize what was generated
    categories: dict[str, int] = {}
    for c in classifications:
        cat = c.get("category", "uncategorized")
        categories[cat] = categories.get(cat, 0) + 1
    cat_lines = [f"  {cat}: {count}" for cat, count in sorted(categories.items())]

    console.print(f"\n[dim]Saved {output_path.name} -> {output_path}[/dim]")
    console.print(Panel("\n".join(cat_lines), title="Categories", border_style="blue"))
    console.print("[green bold]Corpus generated.[/green bold] Next steps:")
    console.print(f"  1. Review and edit [bold]{output_path}[/bold]")
    console.print("  2. Run [bold]driftcut validate --config migration.yaml[/bold]")


@app.command()
def diff(
    before: Path = typer.Option(
        ...,
        "--before",
        "-b",
        help="Path to the earlier results.json file.",
        exists=True,
        readable=True,
    ),
    after: Path = typer.Option(
        ...,
        "--after",
        "-a",
        help="Path to the later results.json file.",
        exists=True,
        readable=True,
    ),
) -> None:
    """Compare two Driftcut result files and show what changed."""
    try:
        before_data = load_result(before)
        after_data = load_result(after)
    except Exception as exc:
        console.print(f"[red bold]Load error:[/red bold] {exc}")
        raise typer.Exit(code=1) from exc

    result = diff_results(before_data, after_data)
    _print_diff(result)


def _decision_style(outcome: str) -> str:
    if outcome == "PROCEED":
        return "green bold"
    if outcome == "STOP":
        return "red bold"
    return "yellow bold"


def _delta_str(value: float, *, percent: bool = True, invert: bool = False) -> str:
    """Format a delta with color. Lower is better unless invert=True."""
    if value == 0:
        return "[dim]-[/dim]"
    sign = "+" if value > 0 else ""
    text = f"{sign}{value:.1%}" if percent else f"{sign}{value:.2f}x"
    better = value < 0 if not invert else value > 0
    color = "green" if better else "red"
    return f"[{color}]{text}[/{color}]"


def _cost_delta_str(before: float, after: float) -> str:
    delta = after - before
    if delta == 0:
        return "[dim]-[/dim]"
    sign = "+" if delta > 0 else ""
    color = "red" if delta > 0 else "green"
    return f"[{color}]{sign}${delta:.4f}[/{color}]"


def _print_diff(result: DiffResult) -> None:
    console.print()

    # Decision comparison
    before_style = _decision_style(result.before_decision)
    after_style = _decision_style(result.after_decision)
    decision_changed = result.before_decision != result.after_decision
    arrow = "[bold] -> [/bold]" if decision_changed else "[dim] -> [/dim]"
    console.print(
        Panel(
            f"[{before_style}]{result.before_decision}[/{before_style}]"
            f"{arrow}"
            f"[{after_style}]{result.after_decision}[/{after_style}]",
            title="Decision",
            border_style="green" if result.after_decision == "PROCEED" else "red",
        )
    )

    # Coverage + cost summary
    summary_table = Table(show_header=True, box=None, padding=(0, 2))
    summary_table.add_column("", style="dim")
    summary_table.add_column("Before", justify="right")
    summary_table.add_column("After", justify="right")
    summary_table.add_column("Delta", justify="right")
    summary_table.add_row(
        "Prompts",
        str(result.before_prompts),
        str(result.after_prompts),
        "",
    )
    summary_table.add_row(
        "Batches",
        str(result.before_batches),
        str(result.after_batches),
        "",
    )
    summary_table.add_row(
        "Cost",
        f"${result.before_cost:.4f}",
        f"${result.after_cost:.4f}",
        _cost_delta_str(result.before_cost, result.after_cost),
    )
    console.print(Panel(summary_table, title="Coverage", border_style="blue"))

    # Metrics table
    if result.metrics:
        metrics_table = Table(show_header=True, box=None, padding=(0, 2))
        metrics_table.add_column("Metric", style="bold")
        metrics_table.add_column("Before", justify="right")
        metrics_table.add_column("After", justify="right")
        metrics_table.add_column("Delta", justify="right")
        for m in result.metrics:
            is_latency = "latency" in m.name.lower()
            if is_latency:
                b_str = f"{m.before:.2f}x"
                a_str = f"{m.after:.2f}x"
                d_str = _delta_str(m.delta, percent=False)
            else:
                b_str = f"{m.before:.1%}"
                a_str = f"{m.after:.1%}"
                d_str = _delta_str(m.delta)
            metrics_table.add_row(m.name, b_str, a_str, d_str)
        console.print(Panel(metrics_table, title="Metrics", border_style="blue"))

    # Category deltas
    if result.categories:
        cat_table = Table(show_header=True, box=None, padding=(0, 2))
        cat_table.add_column("Category", style="bold")
        cat_table.add_column("Before risk", justify="right")
        cat_table.add_column("After risk", justify="right")
        cat_table.add_column("Delta", justify="right")
        for c in sorted(result.categories, key=lambda x: -abs(x.risk_delta)):
            cat_table.add_row(
                c.category,
                f"{c.before_risk:.1%}",
                f"{c.after_risk:.1%}",
                _delta_str(c.risk_delta),
            )
        console.print(Panel(cat_table, title="Categories", border_style="blue"))

    # Archetype changes
    if result.archetypes_added or result.archetypes_removed:
        lines: list[str] = []
        for name in result.archetypes_added:
            lines.append(f"  [red]+[/red] {name}")
        for name in result.archetypes_removed:
            lines.append(f"  [green]-[/green] {name}")
        console.print(Panel("\n".join(lines), title="Archetypes", border_style="blue"))

    console.print()


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

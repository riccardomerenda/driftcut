"""Driftcut CLI — early-stop canary testing for LLM model migrations."""

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from driftcut import __version__
from driftcut.config import load_config
from driftcut.corpus import load_corpus
from driftcut.sampler import StratifiedSampler

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
    """Driftcut — stop bad LLM migrations early."""


def _resolve_corpus_path(config_path: Path, corpus_file: Path) -> Path:
    """Resolve corpus path relative to the config file's directory."""
    if corpus_file.is_absolute():
        return corpus_file
    return config_path.parent / corpus_file


def _print_validation_summary(
    config_path: Path,
    cfg,
    corpus,
    sampler: StratifiedSampler,
) -> None:
    """Print a Rich summary of the validated config and corpus."""
    # Run info
    console.print()
    console.print(
        Panel(
            f"[bold]{cfg.name}[/bold]\n{cfg.description}",
            title="Migration Config",
            border_style="green",
        )
    )

    # Models
    models_table = Table(show_header=False, box=None, padding=(0, 2))
    models_table.add_column("Role", style="dim")
    models_table.add_column("Provider")
    models_table.add_column("Model", style="bold")
    models_table.add_row("Baseline", cfg.models.baseline.provider, cfg.models.baseline.model)
    models_table.add_row("Candidate", cfg.models.candidate.provider, cfg.models.candidate.model)
    console.print(Panel(models_table, title="Models", border_style="blue"))

    # Corpus stats
    cat_counts = corpus.category_counts()
    crit_counts = corpus.criticality_counts()

    cat_lines = [f"  {cat}: {count}" for cat, count in cat_counts.items()]
    cat_lines.append(f"  [bold]Total: {corpus.size}[/bold]")
    crit_str = " · ".join(f"{k}: {v}" for k, v in sorted(crit_counts.items()))
    corpus_body = "\n".join(cat_lines) + f"\n\nCriticality: {crit_str}"
    console.print(
        Panel(
            corpus_body,
            title=f"Corpus — {config_path.parent / cfg.corpus.file}",
            border_style="blue",
        )
    )

    # Sampling plan
    total_batches = sampler.total_batches_possible
    total_prompts = sampler.total_prompts_planned
    coverage = (total_prompts / corpus.size * 100) if corpus.size > 0 else 0

    per_batch = cfg.sampling.batch_size_per_category * len(corpus.categories)
    bpc = cfg.sampling.batch_size_per_category
    n_cats = len(corpus.categories)
    plan_lines = [
        f"Batch size: {bpc} prompts/category x {n_cats} categories = {per_batch} prompts/batch",
        f"Batches planned: {total_batches}"
        f" (min: {cfg.sampling.min_batches}, max: {cfg.sampling.max_batches})",
        f"Total prompts to test: {total_prompts}/{corpus.size} ({coverage:.0f}%)",
        f"Judge strategy: {cfg.evaluation.judge_strategy}",
    ]
    console.print(
        Panel("\n".join(plan_lines), title="Sampling Plan", border_style="blue")
    )

    # Risk thresholds
    thresh_table = Table(show_header=True, box=None, padding=(0, 2))
    thresh_table.add_column("Threshold")
    thresh_table.add_column("Value", justify="right")
    hc_rate = cfg.risk.stop_on_high_criticality_failure_rate
    thresh_table.add_row("High-crit failure rate -> stop", f"{hc_rate:.0%}")
    thresh_table.add_row("Schema break rate -> stop", f"{cfg.risk.stop_on_schema_break_rate:.0%}")
    risk_below = cfg.risk.proceed_if_overall_risk_below
    thresh_table.add_row("Overall risk -> proceed", f"< {risk_below:.0%}")
    thresh_table.add_row("High-criticality weight", f"{cfg.risk.high_criticality_weight:.1f}×")
    console.print(Panel(thresh_table, title="Risk Thresholds", border_style="yellow"))

    console.print("[green bold]Config is valid.[/green bold] Ready to run.\n")


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
) -> None:
    """Run a migration canary test."""
    console.print(f"[bold]Loading config from[/bold] {config}")
    console.print("[yellow]Migration runner not yet implemented — coming soon.[/yellow]")


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
    try:
        cfg = load_config(config)
    except Exception as e:
        console.print(f"[red bold]Config error:[/red bold] {e}")
        raise typer.Exit(code=1) from e

    corpus_path = _resolve_corpus_path(config, cfg.corpus.file)
    try:
        corpus = load_corpus(corpus_path)
    except Exception as e:
        console.print(f"[red bold]Corpus error:[/red bold] {e}")
        raise typer.Exit(code=1) from e

    sampler = StratifiedSampler(corpus, cfg.sampling, seed=42)
    _print_validation_summary(config, cfg, corpus, sampler)

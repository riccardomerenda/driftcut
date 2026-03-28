"""Driftcut CLI — early-stop canary testing for LLM model migrations."""

from pathlib import Path

import typer
from rich.console import Console

from driftcut import __version__

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
    console.print(f"[bold]Validating config:[/bold] {config}")
    console.print("[yellow]Validator not yet implemented — coming soon.[/yellow]")

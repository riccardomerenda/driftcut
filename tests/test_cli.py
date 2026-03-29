"""CLI tests for driftcut."""

from pathlib import Path

from typer.testing import CliRunner

from driftcut.cli import app

runner = CliRunner()
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "driftcut" in result.stdout


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Early-stop" in result.stdout


def test_run_missing_config():
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0


def test_validate_example_config():
    config_path = str(EXAMPLES_DIR / "migration.yaml")
    result = runner.invoke(app, ["validate", "--config", config_path])
    assert result.exit_code == 0
    assert "Config is valid" in result.stdout
    assert "GPT-4o to Claude Haiku" in result.stdout


def test_validate_shows_corpus_stats():
    config_path = str(EXAMPLES_DIR / "migration.yaml")
    result = runner.invoke(app, ["validate", "--config", config_path])
    assert "customer_support" in result.stdout
    assert "30" in result.stdout


def test_validate_shows_sampling_plan():
    config_path = str(EXAMPLES_DIR / "migration.yaml")
    result = runner.invoke(app, ["validate", "--config", config_path])
    assert "Sampling Plan" in result.stdout
    assert "tiered" in result.stdout

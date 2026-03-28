"""Basic CLI tests for driftcut."""

from typer.testing import CliRunner

from driftcut.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Early-stop" in result.stdout


def test_run_missing_config():
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0

"""CLI tests for driftcut."""

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from driftcut import __version__
from driftcut.cli import app

runner = CliRunner()
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"driftcut {__version__}"


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Early-stop" in result.stdout


def test_run_missing_config() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0


def test_validate_example_config() -> None:
    config_path = str(EXAMPLES_DIR / "migration.yaml")
    result = runner.invoke(app, ["validate", "--config", config_path])
    assert result.exit_code == 0
    assert "Config is valid" in result.stdout
    assert "GPT-4o to Claude Haiku" in result.stdout


def test_validate_shows_corpus_stats() -> None:
    config_path = str(EXAMPLES_DIR / "migration.yaml")
    result = runner.invoke(app, ["validate", "--config", config_path])
    assert "customer_support" in result.stdout
    assert "30" in result.stdout


def test_validate_shows_sampling_plan() -> None:
    config_path = str(EXAMPLES_DIR / "migration.yaml")
    result = runner.invoke(app, ["validate", "--config", config_path])
    assert "Sampling Plan" in result.stdout
    assert "light" in result.stdout


def test_replay_command_writes_outputs(tmp_path: Path) -> None:
    config_file = tmp_path / "replay.yaml"
    config_file.write_text(
        yaml.dump(
            {
                "name": "Replay run",
                "models": {
                    "baseline": {"provider": "openai", "model": "gpt-4o"},
                    "candidate": {"provider": "anthropic", "model": "claude-haiku"},
                },
                "sampling": {
                    "batch_size_per_category": 1,
                    "max_batches": 1,
                    "min_batches": 1,
                },
                "evaluation": {"judge_strategy": "none"},
                "latency": {"track": True},
            }
        ),
        encoding="utf-8",
    )
    replay_file = tmp_path / "replay.json"
    replay_file.write_text(
        json.dumps(
            {
                "format_version": 1,
                "records": [
                    {
                        "id": "p1",
                        "category": "support",
                        "prompt": "Help me",
                        "criticality": "high",
                        "expected_output_type": "free_text",
                        "baseline": {"output": "All good", "latency_ms": 100.0, "cost_usd": 0.01},
                        "candidate": {"output": "All good", "latency_ms": 90.0, "cost_usd": 0.008},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["replay", "--config", str(config_file), "--input", str(replay_file)],
    )

    assert result.exit_code == 0
    assert "Replay complete" in result.stdout
    results_path = tmp_path / "driftcut-results" / "results.json"
    assert results_path.exists()
    assert '"mode": "replay"' in results_path.read_text(encoding="utf-8")

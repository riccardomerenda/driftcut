"""Tests for config loading and validation."""

from pathlib import Path

import pytest
import yaml

from driftcut.config import load_config

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_load_example_config() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.name == "GPT-4o to Claude Haiku migration gate"
    assert cfg.models.baseline.provider == "openai"
    assert cfg.models.baseline.model == "gpt-4o"
    assert cfg.models.candidate.provider == "anthropic"
    assert cfg.models.candidate.model == "claude-haiku"


def test_corpus_file_parsed() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.corpus is not None
    assert cfg.corpus.file == Path("prompts.csv")


def test_sampling_defaults() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.sampling.batch_size_per_category == 3
    assert cfg.sampling.max_batches == 5
    assert cfg.sampling.min_batches == 2


def test_risk_thresholds() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.risk.stop_on_high_criticality_failure_rate == 0.20
    assert cfg.risk.stop_on_schema_break_rate == 0.25
    assert cfg.risk.proceed_if_overall_risk_below == 0.08
    assert cfg.risk.high_criticality_weight == 2.0


def test_evaluation_config() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.evaluation.judge_strategy == "light"
    assert cfg.evaluation.detect_failure_archetypes is True


def test_latency_config() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.latency.track is True
    assert cfg.latency.regression_threshold_p50 == 1.5
    assert cfg.latency.regression_threshold_p95 == 2.0


def test_output_config() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.output.save_json is True
    assert cfg.output.save_html is True


def test_defaults_applied_when_sections_missing(tmp_path: Path) -> None:
    minimal = {
        "name": "test run",
        "models": {
            "baseline": {"provider": "openai", "model": "gpt-4o"},
            "candidate": {"provider": "anthropic", "model": "claude-haiku"},
        },
        "corpus": {"file": "prompts.csv"},
    }
    config_file = tmp_path / "minimal.yaml"
    config_file.write_text(yaml.dump(minimal))
    cfg = load_config(config_file)
    assert cfg.sampling.batch_size_per_category == 3
    assert cfg.risk.stop_on_high_criticality_failure_rate == 0.20
    assert cfg.evaluation.judge_strategy == "light"


def test_replay_config_can_omit_corpus(tmp_path: Path) -> None:
    replay_cfg = {
        "name": "replay run",
        "models": {
            "baseline": {"provider": "openai", "model": "gpt-4o"},
            "candidate": {"provider": "anthropic", "model": "claude-haiku"},
        },
    }
    config_file = tmp_path / "replay.yaml"
    config_file.write_text(yaml.dump(replay_cfg))
    cfg = load_config(config_file)
    assert cfg.corpus is None


def test_missing_required_field(tmp_path: Path) -> None:
    bad = {"description": "no name or models"}
    config_file = tmp_path / "bad.yaml"
    config_file.write_text(yaml.dump(bad))
    with pytest.raises((ValueError, TypeError)):
        load_config(config_file)


def test_tiered_escalation_threshold_default() -> None:
    cfg = load_config(EXAMPLES_DIR / "migration.yaml")
    assert cfg.evaluation.tiered_escalation_threshold == 0.6


def test_tiered_escalation_threshold_custom(tmp_path: Path) -> None:
    cfg_dict = {
        "name": "test",
        "models": {
            "baseline": {"provider": "openai", "model": "gpt-4o"},
            "candidate": {"provider": "anthropic", "model": "claude-haiku"},
        },
        "corpus": {"file": "prompts.csv"},
        "evaluation": {"judge_strategy": "tiered", "tiered_escalation_threshold": 0.8},
    }
    config_file = tmp_path / "tiered.yaml"
    config_file.write_text(yaml.dump(cfg_dict))
    cfg = load_config(config_file)
    assert cfg.evaluation.judge_strategy == "tiered"
    assert cfg.evaluation.tiered_escalation_threshold == 0.8


def test_invalid_judge_strategy(tmp_path: Path) -> None:
    cfg_dict = {
        "name": "test",
        "models": {
            "baseline": {"provider": "openai", "model": "gpt-4o"},
            "candidate": {"provider": "anthropic", "model": "claude-haiku"},
        },
        "corpus": {"file": "prompts.csv"},
        "evaluation": {"judge_strategy": "invalid"},
    }
    config_file = tmp_path / "bad_judge.yaml"
    config_file.write_text(yaml.dump(cfg_dict))
    with pytest.raises((ValueError, TypeError)):
        load_config(config_file)

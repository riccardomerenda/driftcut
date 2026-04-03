"""Tests for driftcut init command and scaffolding."""

from pathlib import Path

from typer.testing import CliRunner

from driftcut.cli import app
from driftcut.config import load_config
from driftcut.corpus import load_corpus
from driftcut.init import scaffold_project

runner = CliRunner()


def test_scaffold_creates_files(tmp_path: Path) -> None:
    written = scaffold_project(
        target=tmp_path,
        baseline="openai/gpt-4o",
        candidate="anthropic/claude-haiku",
    )
    assert len(written) == 2
    assert (tmp_path / "migration.yaml").exists()
    assert (tmp_path / "prompts.csv").exists()


def test_scaffold_config_is_valid(tmp_path: Path) -> None:
    scaffold_project(
        target=tmp_path,
        baseline="openai/gpt-4o",
        candidate="anthropic/claude-haiku",
    )
    cfg = load_config(tmp_path / "migration.yaml")
    assert cfg.models.baseline.provider == "openai"
    assert cfg.models.baseline.model == "gpt-4o"
    assert cfg.models.candidate.provider == "anthropic"
    assert cfg.models.candidate.model == "claude-haiku"


def test_scaffold_corpus_is_valid(tmp_path: Path) -> None:
    scaffold_project(
        target=tmp_path,
        baseline="openai/gpt-4o",
        candidate="anthropic/claude-haiku",
    )
    corpus = load_corpus(tmp_path / "prompts.csv")
    assert corpus.size == 6
    assert "support" in corpus.categories
    assert "extraction" in corpus.categories
    assert "classification" in corpus.categories


def test_scaffold_config_references_corpus(tmp_path: Path) -> None:
    scaffold_project(
        target=tmp_path,
        baseline="openai/gpt-4o",
        candidate="anthropic/claude-haiku",
    )
    cfg = load_config(tmp_path / "migration.yaml")
    assert cfg.corpus is not None
    assert cfg.corpus.file == Path("prompts.csv")


def test_scaffold_custom_models(tmp_path: Path) -> None:
    scaffold_project(
        target=tmp_path,
        baseline="azure/gpt-4-turbo",
        candidate="openrouter/mistral-large",
    )
    cfg = load_config(tmp_path / "migration.yaml")
    assert cfg.models.baseline.provider == "azure"
    assert cfg.models.baseline.model == "gpt-4-turbo"
    assert cfg.models.candidate.provider == "openrouter"
    assert cfg.models.candidate.model == "mistral-large"


def test_scaffold_model_without_slash(tmp_path: Path) -> None:
    scaffold_project(
        target=tmp_path,
        baseline="gpt-4o",
        candidate="claude-haiku",
    )
    cfg = load_config(tmp_path / "migration.yaml")
    assert cfg.models.baseline.provider == "gpt-4o"
    assert cfg.models.baseline.model == "gpt-4o"


def test_init_command_creates_files(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Project scaffolded" in result.stdout
    assert (tmp_path / "migration.yaml").exists()
    assert (tmp_path / "prompts.csv").exists()


def test_init_command_with_models(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "init",
            "--dir",
            str(tmp_path),
            "--baseline",
            "azure/gpt-4-turbo",
            "--candidate",
            "openrouter/mistral-large",
        ],
    )
    assert result.exit_code == 0
    cfg = load_config(tmp_path / "migration.yaml")
    assert cfg.models.baseline.model == "gpt-4-turbo"
    assert cfg.models.candidate.model == "mistral-large"


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    (tmp_path / "migration.yaml").write_text("existing", encoding="utf-8")
    result = runner.invoke(app, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "already exist" in result.stdout


def test_init_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / "migration.yaml").write_text("existing", encoding="utf-8")
    result = runner.invoke(app, ["init", "--dir", str(tmp_path), "--force"])
    assert result.exit_code == 0
    assert "Project scaffolded" in result.stdout
    cfg = load_config(tmp_path / "migration.yaml")
    assert cfg.name != ""


def test_init_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested" / "dir"
    result = runner.invoke(app, ["init", "--dir", str(nested)])
    assert result.exit_code == 0
    assert (nested / "migration.yaml").exists()


def test_init_validates_end_to_end(tmp_path: Path) -> None:
    """Scaffolded files pass driftcut validate."""
    runner.invoke(app, ["init", "--dir", str(tmp_path)])
    result = runner.invoke(
        app,
        ["validate", "--config", str(tmp_path / "migration.yaml")],
    )
    assert result.exit_code == 0
    assert "Config is valid" in result.stdout

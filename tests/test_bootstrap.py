"""Tests for driftcut bootstrap command and classification."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from driftcut.bootstrap import (
    _generate_ids,
    _parse_classifications,
    classify_prompts,
    load_raw_prompts,
    write_corpus_csv,
)
from driftcut.cli import app
from driftcut.corpus import load_corpus

runner = CliRunner()


# ── Input loading ──


def test_load_text_one_per_line(tmp_path: Path) -> None:
    path = tmp_path / "prompts.txt"
    path.write_text("Summarize this article.\nExtract entities.\nClassify sentiment.\n")
    prompts = load_raw_prompts(path)
    assert len(prompts) == 3
    assert prompts[0]["prompt"] == "Summarize this article."


def test_load_text_paragraph_mode(tmp_path: Path) -> None:
    path = tmp_path / "prompts.txt"
    path.write_text("First prompt\nwith two lines.\n\nSecond prompt.\n")
    prompts = load_raw_prompts(path)
    assert len(prompts) == 2
    assert "two lines" in prompts[0]["prompt"]


def test_load_csv_prompts(tmp_path: Path) -> None:
    path = tmp_path / "raw.csv"
    path.write_text("id,prompt\np1,Summarize this.\np2,Extract entities.\n")
    prompts = load_raw_prompts(path)
    assert len(prompts) == 2
    assert prompts[0]["id"] == "p1"
    assert prompts[1]["prompt"] == "Extract entities."


def test_load_csv_without_id(tmp_path: Path) -> None:
    path = tmp_path / "raw.csv"
    path.write_text("prompt\nSummarize this.\n")
    prompts = load_raw_prompts(path)
    assert len(prompts) == 1
    assert "id" not in prompts[0]


def test_load_csv_missing_prompt_column(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("text,label\nfoo,bar\n")
    with pytest.raises(ValueError, match="prompt"):
        load_raw_prompts(path)


def test_load_json_strings(tmp_path: Path) -> None:
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(["Summarize this.", "Extract entities."]))
    prompts = load_raw_prompts(path)
    assert len(prompts) == 2
    assert prompts[0]["prompt"] == "Summarize this."


def test_load_json_objects(tmp_path: Path) -> None:
    path = tmp_path / "prompts.json"
    data = [{"id": "p1", "prompt": "Summarize."}, {"prompt": "Extract."}]
    path.write_text(json.dumps(data))
    prompts = load_raw_prompts(path)
    assert len(prompts) == 2
    assert prompts[0]["id"] == "p1"
    assert "id" not in prompts[1]


def test_load_json_invalid_item(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([42]))
    with pytest.raises(ValueError, match="prompt"):
        load_raw_prompts(path)


# ── Classification parsing ──


def test_parse_classifications_direct_json() -> None:
    content = json.dumps(
        [
            {
                "index": 0,
                "category": "support",
                "criticality": "high",
                "expected_output_type": "free_text",
            },
            {
                "index": 1,
                "category": "extraction",
                "criticality": "medium",
                "expected_output_type": "json",
            },
        ]
    )
    result = _parse_classifications(content, 2)
    assert len(result) == 2
    assert result[0]["category"] == "support"
    assert result[1]["expected_output_type"] == "json"


def test_parse_classifications_wrapped_in_markdown() -> None:
    content = (
        "Here are the results:\n```json\n"
        + json.dumps(
            [
                {
                    "index": 0,
                    "category": "summarization",
                    "criticality": "low",
                    "expected_output_type": "markdown",
                }
            ]
        )
        + "\n```"
    )
    result = _parse_classifications(content, 1)
    assert len(result) == 1
    assert result[0]["category"] == "summarization"


def test_parse_classifications_normalizes_invalid_values() -> None:
    content = json.dumps(
        [
            {
                "index": 0,
                "category": "Support Tasks",
                "criticality": "CRITICAL",
                "expected_output_type": "text",
            }
        ]
    )
    result = _parse_classifications(content, 1)
    assert result[0]["category"] == "support_tasks"
    assert result[0]["criticality"] == "medium"  # normalized from invalid
    assert result[0]["expected_output_type"] == "free_text"  # normalized from invalid


def test_parse_classifications_no_json_raises() -> None:
    with pytest.raises((ValueError, json.JSONDecodeError)):
        _parse_classifications("No JSON here at all.", 1)


# ── ID generation ──


def test_generate_ids_from_category() -> None:
    prompts = [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}]
    classifications = [
        {"category": "support"},
        {"category": "support"},
        {"category": "extraction"},
    ]
    ids = _generate_ids(prompts, classifications)
    assert ids == ["sup-001", "sup-002", "ext-001"]


def test_generate_ids_preserves_existing() -> None:
    prompts = [{"id": "my-id", "prompt": "a"}, {"prompt": "b"}]
    classifications = [{"category": "support"}, {"category": "support"}]
    ids = _generate_ids(prompts, classifications)
    assert ids[0] == "my-id"
    assert ids[1] == "sup-001"


# ── CSV output ──


def test_write_corpus_csv_produces_valid_corpus(tmp_path: Path) -> None:
    prompts = [
        {"prompt": "Summarize this article."},
        {"prompt": "Extract entities from text."},
    ]
    classifications = [
        {"category": "summarization", "criticality": "low", "expected_output_type": "markdown"},
        {"category": "extraction", "criticality": "high", "expected_output_type": "json"},
    ]
    output = tmp_path / "corpus.csv"
    write_corpus_csv(output, prompts, classifications)

    # Must be loadable by driftcut's own corpus loader
    corpus = load_corpus(output)
    assert corpus.size == 2
    assert "summarization" in corpus.categories
    assert "extraction" in corpus.categories
    assert corpus.records[0].criticality == "low"
    assert corpus.records[1].expected_output_type == "json"


# ── End-to-end with mocked LLM ──


@pytest.fixture()
def _mock_litellm_classify() -> AsyncMock:
    """Patch litellm.acompletion to return canned classifications."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(
        [
            {
                "index": 0,
                "category": "support",
                "criticality": "high",
                "expected_output_type": "free_text",
            },
            {
                "index": 1,
                "category": "extraction",
                "criticality": "medium",
                "expected_output_type": "json",
            },
            {
                "index": 2,
                "category": "classification",
                "criticality": "low",
                "expected_output_type": "labels",
            },
        ]
    )

    async_mock = AsyncMock(return_value=mock_response)
    return async_mock


@pytest.mark.asyncio()
async def test_classify_prompts_calls_model(_mock_litellm_classify: AsyncMock) -> None:
    prompts = [
        {"prompt": "Help me reset my password."},
        {"prompt": "Extract names from: Alice at Acme Corp."},
        {"prompt": "Classify this as positive or negative."},
    ]
    with patch("driftcut.bootstrap.litellm.acompletion", _mock_litellm_classify):
        result = await classify_prompts(prompts, model="openai/gpt-4.1-mini")

    assert len(result) == 3
    assert result[0]["category"] == "support"
    assert result[1]["expected_output_type"] == "json"
    assert result[2]["criticality"] == "low"


def test_bootstrap_command_end_to_end(
    tmp_path: Path,
    _mock_litellm_classify: AsyncMock,
) -> None:
    input_file = tmp_path / "raw.txt"
    input_file.write_text(
        "Help me reset my password.\nExtract names from text.\nClassify this review.\n"
    )
    output_file = tmp_path / "prompts.csv"

    with patch("driftcut.bootstrap.litellm.acompletion", _mock_litellm_classify):
        result = runner.invoke(
            app,
            [
                "bootstrap",
                "--input",
                str(input_file),
                "--output",
                str(output_file),
                "--model",
                "openai/gpt-4.1-mini",
            ],
        )

    assert result.exit_code == 0
    assert "Corpus generated" in result.stdout
    assert output_file.exists()

    corpus = load_corpus(output_file)
    assert corpus.size == 3


def test_bootstrap_refuses_overwrite(tmp_path: Path) -> None:
    input_file = tmp_path / "raw.txt"
    input_file.write_text("Some prompt.\n")
    output_file = tmp_path / "prompts.csv"
    output_file.write_text("existing content")

    result = runner.invoke(
        app,
        ["bootstrap", "--input", str(input_file), "--output", str(output_file)],
    )
    assert result.exit_code == 1
    assert "already exists" in result.stdout


def test_bootstrap_force_overwrites(
    tmp_path: Path,
    _mock_litellm_classify: AsyncMock,
) -> None:
    input_file = tmp_path / "raw.txt"
    input_file.write_text("Help me.\nExtract names.\nClassify this.\n")
    output_file = tmp_path / "prompts.csv"
    output_file.write_text("existing content")

    with patch("driftcut.bootstrap.litellm.acompletion", _mock_litellm_classify):
        result = runner.invoke(
            app,
            [
                "bootstrap",
                "--input",
                str(input_file),
                "--output",
                str(output_file),
                "--force",
            ],
        )

    assert result.exit_code == 0
    assert "Corpus generated" in result.stdout


def test_bootstrap_empty_input(tmp_path: Path) -> None:
    input_file = tmp_path / "empty.txt"
    input_file.write_text("")

    result = runner.invoke(
        app,
        ["bootstrap", "--input", str(input_file), "--output", str(tmp_path / "out.csv")],
    )
    assert result.exit_code == 1
    assert "No prompts found" in result.stdout

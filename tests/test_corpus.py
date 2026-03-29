"""Tests for corpus loading and validation."""

import json
from pathlib import Path

import pytest

from driftcut.corpus import load_corpus

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_load_example_csv():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    assert corpus.size == 30


def test_categories():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    assert set(corpus.categories) == {
        "customer_support",
        "structured_extraction",
        "classification",
        "summarization",
    }


def test_category_counts():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    counts = corpus.category_counts()
    assert counts["customer_support"] == 8
    assert counts["structured_extraction"] == 8
    assert counts["classification"] == 8
    assert counts["summarization"] == 6


def test_criticality_counts():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    crit = corpus.criticality_counts()
    assert "high" in crit
    assert "medium" in crit
    assert "low" in crit
    assert sum(crit.values()) == 30


def test_by_category():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    support = corpus.by_category("customer_support")
    assert len(support) == 8
    assert all(r.category == "customer_support" for r in support)


def test_by_criticality():
    corpus = load_corpus(EXAMPLES_DIR / "prompts.csv")
    high = corpus.by_criticality("high")
    assert len(high) > 0
    assert all(r.criticality == "high" for r in high)


def test_load_json_corpus(tmp_path):
    records = [
        {
            "id": "t-001",
            "category": "test",
            "prompt": "Hello",
            "criticality": "low",
            "expected_output_type": "free_text",
        },
        {
            "id": "t-002",
            "category": "test",
            "prompt": "World",
            "criticality": "high",
            "expected_output_type": "json",
        },
    ]
    json_file = tmp_path / "corpus.json"
    json_file.write_text(json.dumps(records))
    corpus = load_corpus(json_file)
    assert corpus.size == 2


def test_empty_corpus_raises(tmp_path):
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text("id,category,prompt,criticality,expected_output_type\n")
    with pytest.raises(ValueError, match="empty"):
        load_corpus(csv_file)


def test_invalid_criticality(tmp_path):
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text(
        "id,category,prompt,criticality,expected_output_type\n"
        't-001,test,Hello,CRITICAL,free_text\n'
    )
    with pytest.raises(ValueError, match="Row 2"):
        load_corpus(csv_file)


def test_unsupported_format(tmp_path):
    xml_file = tmp_path / "corpus.xml"
    xml_file.write_text("<data/>")
    with pytest.raises(ValueError, match="Unsupported"):
        load_corpus(xml_file)

"""Corpus loader and data models for Driftcut."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class PromptRecord(BaseModel):
    id: str
    category: str
    prompt: str
    criticality: Literal["low", "medium", "high"]
    expected_output_type: Literal["free_text", "json", "labels", "markdown"]
    notes: str = ""


class Corpus:
    """A validated collection of prompt records."""

    def __init__(self, records: list[PromptRecord]) -> None:
        if not records:
            msg = "Corpus is empty — at least one prompt record is required"
            raise ValueError(msg)
        self._records = records

    @property
    def records(self) -> list[PromptRecord]:
        return self._records

    @property
    def categories(self) -> list[str]:
        return sorted({r.category for r in self._records})

    @property
    def size(self) -> int:
        return len(self._records)

    def by_category(self, category: str) -> list[PromptRecord]:
        return [r for r in self._records if r.category == category]

    def by_criticality(self, criticality: str) -> list[PromptRecord]:
        return [r for r in self._records if r.criticality == criticality]

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._records:
            counts[r.category] = counts.get(r.category, 0) + 1
        return dict(sorted(counts.items()))

    def criticality_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._records:
            counts[r.criticality] = counts.get(r.criticality, 0) + 1
        return counts


def _load_csv(path: Path) -> list[PromptRecord]:
    records: list[PromptRecord] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, restkey="_extra")
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            try:
                # If CSV has unquoted commas in notes, extra fields land in _extra.
                # Merge them back into notes.
                extra = row.pop("_extra", None)
                if extra and "notes" in row:
                    row["notes"] = ",".join([row["notes"], *extra])
                records.append(PromptRecord(**row))
            except Exception as e:
                msg = f"Row {i} in {path.name}: {e}"
                raise ValueError(msg) from e
    return records


def _load_json(path: Path) -> list[PromptRecord]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        msg = f"JSON corpus must be a list of objects, got {type(raw).__name__}"
        raise ValueError(msg)
    records: list[PromptRecord] = []
    for i, item in enumerate(raw):
        try:
            records.append(PromptRecord(**item))
        except Exception as e:
            msg = f"Item {i} in {path.name}: {e}"
            raise ValueError(msg) from e
    return records


def load_corpus(path: Path) -> Corpus:
    """Load a prompt corpus from a CSV or JSON file."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        records = _load_csv(path)
    elif suffix == ".json":
        records = _load_json(path)
    else:
        msg = f"Unsupported corpus format '{suffix}' — use .csv or .json"
        raise ValueError(msg)
    return Corpus(records)

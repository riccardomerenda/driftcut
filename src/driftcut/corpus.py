"""Corpus loader and data models for Driftcut."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class PromptRecord(BaseModel):
    id: str
    category: str
    prompt: str
    criticality: Literal["low", "medium", "high"]
    expected_output_type: Literal["free_text", "json", "labels", "markdown"]
    notes: str = ""
    required_substrings: list[str] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)
    json_required_keys: list[str] = Field(default_factory=list)
    max_output_chars: int | None = None

    @field_validator(
        "required_substrings",
        "forbidden_substrings",
        "json_required_keys",
        mode="before",
    )
    @classmethod
    def _parse_expectation_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                parsed = json.loads(text)
                if not isinstance(parsed, list):
                    msg = "expected a JSON list"
                    raise TypeError(msg)
                return [str(item).strip() for item in parsed if str(item).strip()]
            separator = "|" if "|" in text else ";" if ";" in text else None
            if separator is None:
                return [text]
            return [item.strip() for item in text.split(separator) if item.strip()]
        msg = f"unsupported list value: {type(value).__name__}"
        raise TypeError(msg)

    @field_validator("max_output_chars", mode="before")
    @classmethod
    def _parse_max_output_chars(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)


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
                records.append(PromptRecord.model_validate(row))
            except Exception as e:
                msg = f"Row {i} in {path.name}: {e}"
                raise ValueError(msg) from e
    return records


def _load_json(path: Path) -> list[PromptRecord]:
    with open(path, encoding="utf-8") as f:
        raw: Any = json.load(f)
    if not isinstance(raw, list):
        msg = f"JSON corpus must be a list of objects, got {type(raw).__name__}"
        raise ValueError(msg)
    records: list[PromptRecord] = []
    for i, item in enumerate(raw):
        try:
            records.append(PromptRecord.model_validate(item))
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

"""Corpus bootstrap: classify raw prompts into a structured Driftcut corpus."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import litellm

litellm.suppress_debug_info = True

_BATCH_SIZE = 20
_VALID_CRITICALITIES = {"low", "medium", "high"}
_VALID_OUTPUT_TYPES = {"free_text", "json", "labels", "markdown"}

_SYSTEM_PROMPT = """\
You are a prompt corpus classifier for an LLM migration testing tool.

For each prompt, assign:
- category: a short snake_case label grouping similar prompts (e.g. customer_support, \
extraction, classification, summarization, code_generation)
- criticality: low, medium, or high — based on how much a wrong answer would matter \
in production
- expected_output_type: free_text, json, labels, or markdown — based on what the prompt \
asks for

Return a JSON array. Each element must have: index (0-based), category, criticality, \
expected_output_type. Nothing else.\
"""


def _classify_prompt(prompts: list[str]) -> str:
    """Build the user message listing prompts to classify."""
    lines = [f"[{i}] {text}" for i, text in enumerate(prompts)]
    return "Classify these prompts:\n\n" + "\n\n".join(lines)


def _parse_classifications(
    content: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Extract the JSON array from the model response."""
    content = content.strip()

    # Try direct parse first
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return _validate_classifications(parsed, batch_size)
    except json.JSONDecodeError:
        pass

    # Fall back to extracting a JSON array from freeform text
    match = re.search(r"\[[\s\S]*\]", content)
    if match is None:
        msg = "Model response does not contain a JSON array"
        raise ValueError(msg)
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        msg = "Extracted JSON is not an array"
        raise ValueError(msg)
    return _validate_classifications(parsed, batch_size)


def _validate_classifications(
    items: list[Any],
    batch_size: int,
) -> list[dict[str, Any]]:
    """Validate and normalize each classification entry."""
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        idx = item.get("index", len(result))
        category = str(item.get("category", "uncategorized")).strip().lower().replace(" ", "_")
        criticality = str(item.get("criticality", "medium")).strip().lower()
        output_type = str(item.get("expected_output_type", "free_text")).strip().lower()

        if criticality not in _VALID_CRITICALITIES:
            criticality = "medium"
        if output_type not in _VALID_OUTPUT_TYPES:
            output_type = "free_text"

        result.append(
            {
                "index": int(idx),
                "category": category,
                "criticality": criticality,
                "expected_output_type": output_type,
            }
        )

    # Sort by index and ensure we don't have more than batch_size
    result.sort(key=lambda x: x["index"])
    return result[:batch_size]


def load_raw_prompts(path: Path) -> list[dict[str, str]]:
    """Load prompts from a text, CSV, or JSON file.

    Returns a list of dicts with at least a ``prompt`` key.
    An ``id`` key is included when the source provides one.
    """
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv_prompts(path)
    if suffix == ".json":
        return _load_json_prompts(path)
    return _load_text_prompts(path)


def _load_text_prompts(path: Path) -> list[dict[str, str]]:
    """Load one prompt per non-blank line (or paragraph separated by blank lines)."""
    text = path.read_text(encoding="utf-8")
    # If there are blank-line separators, treat as paragraph mode
    if "\n\n" in text:
        blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    else:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]
    return [{"prompt": block} for block in blocks]


def _load_csv_prompts(path: Path) -> list[dict[str, str]]:
    """Load prompts from a CSV that has at least a ``prompt`` column."""
    records: list[dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "prompt" not in reader.fieldnames:
            msg = f"CSV file {path.name} must have a 'prompt' column"
            raise ValueError(msg)
        for row in reader:
            entry: dict[str, str] = {"prompt": row["prompt"]}
            if "id" in row and row["id"]:
                entry["id"] = row["id"]
            records.append(entry)
    return records


def _load_json_prompts(path: Path) -> list[dict[str, str]]:
    """Load prompts from a JSON array of strings or objects."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        msg = f"JSON file {path.name} must contain an array"
        raise ValueError(msg)
    records: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            records.append({"prompt": item})
        elif isinstance(item, dict) and "prompt" in item:
            entry: dict[str, str] = {"prompt": item["prompt"]}
            if "id" in item and item["id"]:
                entry["id"] = str(item["id"])
            records.append(entry)
        else:
            msg = "JSON array items must be strings or objects with a 'prompt' key"
            raise ValueError(msg)
    return records


def _generate_ids(
    prompts: list[dict[str, str]],
    classifications: list[dict[str, Any]],
) -> list[str]:
    """Generate IDs for prompts that don't have one.

    Format: ``{category}-{seq:03d}`` where seq is per-category.
    """
    category_counters: dict[str, int] = {}
    ids: list[str] = []
    for i, prompt in enumerate(prompts):
        if "id" in prompt and prompt["id"]:
            ids.append(prompt["id"])
        else:
            cat = classifications[i]["category"] if i < len(classifications) else "prompt"
            # Short prefix from category
            prefix = cat[:3] if len(cat) >= 3 else cat
            category_counters[prefix] = category_counters.get(prefix, 0) + 1
            ids.append(f"{prefix}-{category_counters[prefix]:03d}")
    return ids


async def classify_prompts(
    prompts: list[dict[str, str]],
    *,
    model: str,
    batch_size: int = _BATCH_SIZE,
) -> list[dict[str, Any]]:
    """Classify a list of prompts using an LLM.

    Returns one classification dict per prompt with keys:
    category, criticality, expected_output_type.
    """
    texts = [p["prompt"] for p in prompts]
    all_classifications: list[dict[str, Any]] = []

    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start : batch_start + batch_size]
        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _classify_prompt(batch)},
            ],
        )
        content = response.choices[0].message.content or ""
        batch_results = _parse_classifications(content, len(batch))

        # Pad with defaults if model returned fewer items than expected
        while len(batch_results) < len(batch):
            batch_results.append(
                {
                    "index": len(batch_results),
                    "category": "uncategorized",
                    "criticality": "medium",
                    "expected_output_type": "free_text",
                }
            )

        all_classifications.extend(batch_results)

    return all_classifications


def write_corpus_csv(
    path: Path,
    prompts: list[dict[str, str]],
    classifications: list[dict[str, Any]],
) -> None:
    """Write the structured corpus CSV."""
    ids = _generate_ids(prompts, classifications)
    fieldnames = ["id", "category", "prompt", "criticality", "expected_output_type", "notes"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, prompt in enumerate(prompts):
            classification = classifications[i] if i < len(classifications) else {}
            writer.writerow(
                {
                    "id": ids[i],
                    "category": classification.get("category", "uncategorized"),
                    "prompt": prompt["prompt"],
                    "criticality": classification.get("criticality", "medium"),
                    "expected_output_type": classification.get("expected_output_type", "free_text"),
                    "notes": "",
                }
            )

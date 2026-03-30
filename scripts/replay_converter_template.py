"""Template for converting external paired outputs into Driftcut replay JSON.

This script is intentionally not wired into the CLI. Keep source-specific
adapters outside the Driftcut runtime and emit the canonical replay contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_source_rows() -> list[dict[str, Any]]:
    """Load rows from your internal export format."""
    msg = "Implement source-specific loading here"
    raise NotImplementedError(msg)


def convert_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map one external row into the canonical Driftcut replay schema."""
    return {
        "id": str(row["id"]),
        "category": row["category"],
        "prompt": row["prompt"],
        "criticality": row["criticality"],
        "expected_output_type": row["expected_output_type"],
        "notes": row.get("notes", ""),
        "required_substrings": row.get("required_substrings", []),
        "forbidden_substrings": row.get("forbidden_substrings", []),
        "json_required_keys": row.get("json_required_keys", []),
        "max_output_chars": row.get("max_output_chars"),
        "baseline": {
            "output": row.get("baseline_output"),
            "latency_ms": row.get("baseline_latency_ms"),
            "cost_usd": row.get("baseline_cost_usd"),
            "error": row.get("baseline_error"),
        },
        "candidate": {
            "output": row.get("candidate_output"),
            "latency_ms": row.get("candidate_latency_ms"),
            "cost_usd": row.get("candidate_cost_usd"),
            "error": row.get("candidate_error"),
        },
    }


def main() -> None:
    rows = load_source_rows()
    payload = {
        "format_version": 1,
        "records": [convert_row(row) for row in rows],
    }
    output_path = Path("replay.json")
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

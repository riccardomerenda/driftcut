"""Project scaffolding for driftcut init."""

from __future__ import annotations

from pathlib import Path

_CONFIG_TEMPLATE = """\
# ---------------------------------------------------------
# Driftcut - Migration config
# ---------------------------------------------------------
# Validate:  driftcut validate --config migration.yaml
# Run:       driftcut run --config migration.yaml
# ---------------------------------------------------------

name: "{baseline_model} to {candidate_model} migration gate"
description: "Early-stop migration test"

models:
  baseline:
    provider: {baseline_provider}
    model: {baseline_model}
  candidate:
    provider: {candidate_provider}
    model: {candidate_model}

corpus:
  file: prompts.csv

sampling:
  batch_size_per_category: 3
  max_batches: 5
  min_batches: 2

risk:
  high_criticality_weight: 2.0
  stop_on_schema_break_rate: 0.25
  stop_on_high_criticality_failure_rate: 0.20
  proceed_if_overall_risk_below: 0.08

evaluation:
  judge_strategy: light
  judge_model_light: openai/gpt-4.1-mini
  judge_model_heavy: openai/gpt-4.1
  detect_failure_archetypes: true

latency:
  track: true
  regression_threshold_p50: 1.5
  regression_threshold_p95: 2.0

output:
  save_json: true
  save_html: true
  save_examples: true
  show_thresholds: true
  show_confidence: true
"""

_CORPUS_HEADER = "id,category,prompt,criticality,expected_output_type,notes"

_CORPUS_ROWS = [
    (
        "sample-001,support,"
        '"Draft a support response for: I need help resetting my password."'
        ",medium,free_text,Should include clear steps"
    ),
    (
        "sample-002,support,"
        '"Draft a response for: I was charged twice for order #1234."'
        ",high,free_text,Must include specific next steps"
    ),
    (
        "sample-003,extraction,"
        '"Extract names and orgs from: Alice Smith from Acme Corp met Bob."'
        ",high,json,Must return valid JSON"
    ),
    (
        "sample-004,extraction,"
        '"Extract dates from: Project starts Jan 15 and deadline is March 30."'
        ",medium,json,Must return structured pairs"
    ),
    (
        "sample-005,classification,"
        '"Classify as billing/technical/general: My invoice shows wrong amount."'
        ",medium,labels,"
    ),
    (
        "sample-006,classification,"
        '"Classify as positive/negative/neutral: Product works but shipping slow."'
        ",low,labels,"
    ),
]

_CORPUS_TEMPLATE = _CORPUS_HEADER + "\n" + "\n".join(_CORPUS_ROWS) + "\n"


def _parse_model_spec(spec: str) -> tuple[str, str]:
    """Parse 'provider/model' into (provider, model)."""
    if "/" in spec:
        provider, _, model = spec.partition("/")
        return provider.strip(), model.strip()
    return spec.strip(), spec.strip()


def scaffold_project(
    *,
    target: Path,
    baseline: str,
    candidate: str,
) -> list[Path]:
    """Write starter migration.yaml and prompts.csv into *target*."""
    baseline_provider, baseline_model = _parse_model_spec(baseline)
    candidate_provider, candidate_model = _parse_model_spec(candidate)

    config_content = _CONFIG_TEMPLATE.format(
        baseline_provider=baseline_provider,
        baseline_model=baseline_model,
        candidate_provider=candidate_provider,
        candidate_model=candidate_model,
    )

    config_path = target / "migration.yaml"
    corpus_path = target / "prompts.csv"

    config_path.write_text(config_content, encoding="utf-8")
    corpus_path.write_text(_CORPUS_TEMPLATE, encoding="utf-8")

    return [config_path, corpus_path]

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this?

Driftcut is an early-stop canary testing tool for LLM model migrations. It samples strategically from a prompt corpus, compares baseline and candidate models, runs deterministic checks first, escalates only ambiguous prompts to a judge model, and outputs a STOP/CONTINUE/PROCEED decision — all before committing to a full evaluation run.

## Commands

```bash
pip install -e ".[dev]"              # Install in dev mode
pytest                                # Run all tests
pytest tests/test_runner.py           # Run a single test file
pytest tests/test_runner.py -k "test_name"  # Run a single test
ruff check src tests                  # Lint
ruff format src tests                 # Format
mypy src                              # Type check
driftcut validate --config migration.yaml   # Validate config + corpus
driftcut run --config migration.yaml        # Run a migration test
driftcut replay --config replay.yaml --input replay.json  # Replay historical outputs
```

## Architecture

### Data flow

```
CLI (cli.py) loads config + corpus
    → StratifiedSampler yields Batch objects (criticality-first)
    → runner.py orchestrates batch-by-batch execution
        → executor.py runs baseline + candidate concurrently per prompt (asyncio.gather)
        → quality.py runs deterministic checks on every response (free)
        → judge.py called only for ambiguous prompts (both pass deterministic but differ semantically)
        → decision.py evaluates STOP/CONTINUE/PROCEED after each batch
    → reporting.py writes JSON + HTML to driftcut-results/
```

Replay mode substitutes pre-recorded responses for live execution but uses the same evaluation pipeline.

### Module roles

| Module | Role |
|---|---|
| `cli.py` | Typer commands: `run`, `validate`, `replay` |
| `config.py` | Pydantic models for YAML config with constrained fields |
| `corpus.py` | CSV/JSON loader → `PromptRecord` list with flexible delimiter parsing (`\|` or `;`) |
| `sampler.py` | `StratifiedSampler` iterator — yields equal-sized batches, pre-sorted by criticality within category |
| `runner.py` | Async orchestrator — batch loop, wires executor → quality → judge → decision |
| `executor.py` | Async LiteLLM wrapper with retry (3 attempts, exponential backoff for rate limits/5xx/timeouts) |
| `quality.py` | Deterministic checks driven by `expected_output_type`: JSON validity, required keys, substrings, length |
| `judge.py` | Sends ambiguous prompt pairs to judge model, extracts JSON verdict from freeform responses |
| `decision.py` | Decision engine: hard stops on schema breaks/high-crit failures, proceed gate on overall risk + latency |
| `trackers.py` | Cost and latency accumulators (cost gracefully handles missing LiteLLM pricing) |
| `models.py` | Frozen dataclasses: `ModelResponse`, `PromptEvaluation`, `JudgeResult`, `RunDecision`, `RunResult` |
| `reporting.py` | JSON serialization + HTML report with failure archetypes |
| `replay.py` | Replay-specific data models for loading historical paired outputs |

### Decision engine (`decision.py`)

Evaluated after every batch:

1. **Hard stops** (checked first): `schema_break_rate >= 0.25` or `high_criticality_failure_rate >= 0.20`
2. **Proceed gate**: `overall_risk < 0.08` AND latency ratios within bounds AND `min_batches` reached
3. **Continue**: neither triggered and batches remain
4. **Final stop**: budget exhausted without proceeding

Overall risk is a weighted average of regression rate, failure rate, schema breaks, high-criticality failures (weighted 2x), and latency penalty.

### Concurrency model

- Prompts within a batch run concurrently via `asyncio.as_completed()`
- Baseline and candidate for each prompt run in parallel via `asyncio.gather()`
- Results are re-sorted by original index after completion (preserves deterministic order)
- Judge calls are sequential per prompt

## Key conventions

- **src layout**: imports are `from driftcut.xxx import yyy`
- **Config validation at load time**: Pydantic fields have `ge`/`le` constraints; invalid configs fail immediately
- **`expected_output_type` drives evaluation**: `"json"` checks validity + keys, `"labels"` parses as list, `"free_text"`/`"markdown"` check substrings + length only
- **Judge strategy enum**: `"none"` (deterministic only), `"light"` (cheap model), `"heavy"` (expensive model), `"tiered"` (light first, escalates to heavy when confidence < `tiered_escalation_threshold`)
- **Cost error tolerance**: if LiteLLM can't price a model, run continues with `cost_usd=0.0` and `cost_error` stores the message
- **Conservative defaults**: decision engine favors false negatives (saying STOP) over false positives (saying PROCEED)
- **B008 suppressed in cli.py**: `typer.Option()` in function defaults is idiomatic Typer
- **ruff line length**: 100 chars, target Python 3.12
- **mypy strict mode** enabled
- **pytest-asyncio auto mode**: async test functions are auto-detected

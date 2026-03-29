<p align="center">
  <img src="assets/logo.svg" alt="Driftcut" width="64" height="64">
</p>

<h1 align="center">Driftcut</h1>

<p align="center">
  <strong>Early-stop decision gating for LLM model migrations.</strong><br>
  v0.3.0 alpha CLI for sampling migration candidates before you commit to a full evaluation.
</p>

<p align="center">
  <a href="#current-status">Current status</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#corpus-format">Corpus format</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

## The problem

You want to migrate from one LLM to another: cheaper, faster, better, self-hosted, or more private.

So you run your full prompt corpus against the candidate model. Hundreds or thousands of API calls. Hours of waiting. And only at the end do you discover the candidate breaks the categories that matter most.

You just burned budget to learn something you could have known in the first 10-20%.

**Driftcut is the test you run before the full evaluation.** It samples strategically, compares baseline and candidate on a representative slice, runs deterministic checks on the outputs, and tells you whether to `STOP`, `CONTINUE`, or `PROCEED`.

## What it is (and what it is not)

Driftcut is **not** a generic eval framework. It does not replace Promptfoo, DeepEval, or your internal eval suite. It sits one step earlier in the workflow: the filter that decides whether a full evaluation is worth the money.

| Driftcut is | Driftcut is not |
|---|---|
| A pre-evaluation filter | A generic eval framework |
| A migration decision layer | An experiment tracker |
| A budget-aware canary | A prompt optimization tool |
| CLI-first and single-purpose | A dashboard-first platform |

## Current status

Today, Driftcut can:

- Validate a structured corpus and migration config
- Build stratified batches that prioritize high-criticality prompts
- Run baseline and candidate models concurrently via LiteLLM
- Track latency and cost across the sampled run
- Run deterministic checks for format, JSON validity, required content, and optional output limits
- Produce `STOP`, `CONTINUE`, or `PROCEED` decisions during the run
- Export both JSON results and an HTML report
- Summarize failure archetypes such as `api_error`, `json_invalid`, `missing_json_keys`, and `missing_required_content`

Still planned next:

- Judge-based quality comparison for ambiguous cases
- Richer failure archetypes beyond deterministic checks
- Better report polish and benchmark demos

## Quickstart

```bash
git clone https://github.com/riccardomerenda/driftcut.git
cd driftcut
pip install -e .
```

Create a config file:

```yaml
# migration.yaml
name: "GPT-4o to Claude Haiku migration gate"

models:
  baseline:
    provider: openai
    model: gpt-4o
  candidate:
    provider: anthropic
    model: claude-haiku

corpus:
  file: prompts.csv

sampling:
  batch_size_per_category: 3
  max_batches: 5
  min_batches: 2
```

Validate first, then run:

```bash
driftcut validate --config migration.yaml
driftcut run --config migration.yaml
```

`driftcut run` now:

- executes sampled batches,
- evaluates deterministic quality checks,
- decides whether to stop, continue, or proceed,
- writes `driftcut-results/results.json`,
- writes `driftcut-results/report.html`.

Works with any [LiteLLM-supported provider](https://docs.litellm.ai/): OpenAI, Anthropic, OpenRouter, Azure, self-hosted, and more.

## How it works

### Current runtime

```text
Your prompt corpus
        |
        v
Stratified sampling by category and criticality
        |
        v
Run baseline and candidate on sampled batches
        |
        v
Deterministic checks:
- expected format
- JSON validity / required keys
- required / forbidden content
- max output length
        |
        v
Track latency and cost
        |
        v
Decision engine
        |
        v
STOP / CONTINUE / PROCEED
        |
        v
JSON + HTML report
```

### Planned next

```text
Deterministic checks
        +
Tiered judge strategy
        +
Richer failure archetypes
        ->
Higher-confidence migration decisions
```

## The three dimensions

Driftcut is designed around three migration dimensions:

- **Quality** - deterministic checks are live; judge comparison is still planned.
- **Latency** - p50 and p95 are tracked and fed into the decision engine.
- **Cost** - spend is tracked per run and included in the final report.

## Failure archetypes

The current deterministic layer can classify failures such as:

| Archetype | What it means |
|---|---|
| `api_error` | Model call failed |
| `empty_output` | Response is empty |
| `json_invalid` | Output is not valid JSON |
| `missing_json_keys` | Required JSON keys are missing |
| `invalid_labels` | Label output could not be parsed |
| `missing_required_content` | Required substring was not found |
| `forbidden_content` | Forbidden substring was found |
| `overlong_output` | Output exceeded `max_output_chars` |

## Corpus format

Driftcut requires a structured corpus.

```csv
id,category,prompt,criticality,expected_output_type,notes,required_substrings,forbidden_substrings,json_required_keys,max_output_chars
cx-001,customer_support,"Given this ticket: {ticket}, draft a response.",high,free_text,,refund|replacement,,,
ex-001,structured_extraction,"Extract entities from: {text}. Return JSON.",high,json,,,,"persons|organizations|locations",
cl-001,classification,"Classify this review: {review}",medium,labels,,,,,
su-001,summarization,"Summarize this document: {doc}",low,markdown,,,,1200
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Unique identifier |
| `category` | string | yes | Example: `customer_support`, `structured_extraction` |
| `prompt` | string | yes | Prompt to execute |
| `criticality` | enum | yes | `low` / `medium` / `high` |
| `expected_output_type` | enum | yes | `free_text` / `json` / `labels` / `markdown` |
| `notes` | string | no | Optional human context |
| `required_substrings` | list-like string | no | `|` or `;` separated required phrases |
| `forbidden_substrings` | list-like string | no | `|` or `;` separated forbidden phrases |
| `json_required_keys` | list-like string | no | Keys that must exist in parsed JSON |
| `max_output_chars` | int | no | Hard upper bound for deterministic length checks |

## Configuration

The runtime actively uses `sampling`, `risk`, `latency`, and `output` settings. `evaluation.judge_strategy` is still future-facing and currently documents the intended next layer.

```yaml
name: "OpenAI to Anthropic migration gate"
description: "Early-stop migration decision support for support and extraction workloads"

models:
  baseline:
    provider: openai
    model: gpt-4o
  candidate:
    provider: anthropic
    model: claude-haiku

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
  judge_strategy: tiered
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
```

## Planned judge strategy

Driftcut aims to save budget, so the judge cannot consume all of it.

| Stage | Method | Cost | Catches |
|---|---|---|---|
| Early batches | Deterministic checks | $0 | Format, schema, content, and output-limit failures |
| Mid batches | Light judge | Low | General quality comparison |
| Later ambiguous cases | Heavy judge | Higher | Nuanced quality differences |

## Roadmap

- [x] Concept document
- [x] Demo config and corpus
- [x] Config loader + corpus loader (CSV, JSON)
- [x] Stratified batch sampler
- [x] `driftcut validate` command
- [x] Async model execution via LiteLLM
- [x] `driftcut run` command with concurrent execution
- [x] Latency tracker (p50, p95 per category)
- [x] Cost tracker (per-prompt and cumulative)
- [x] JSON export
- [x] Multi-provider support (OpenRouter, Azure, custom endpoints)
- [x] Deterministic checker
- [x] Failure archetype summary
- [x] Decision engine with configurable thresholds
- [x] HTML report
- [ ] Tiered judge integration
- [ ] Richer failure archetypes
- [ ] Public benchmark demo

Full roadmap: [docs.driftcut.dev/roadmap](https://docs.driftcut.dev/roadmap/)

## Tech stack

Python 3.12 · Typer · LiteLLM · Rich · Pydantic · YAML

## Positioning

Driftcut answers a narrower question than generic eval tooling:

> "Should we continue this migration, or are we already seeing enough risk to stop?"

That narrow scope is the product wedge.

## Links

- GitHub: [riccardomerenda/driftcut](https://github.com/riccardomerenda/driftcut)
- Docs: [docs.driftcut.dev](https://docs.driftcut.dev/getting-started/)
- Landing page: [driftcut.dev](https://driftcut.dev)

## License

MIT

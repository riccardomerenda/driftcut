<p align="center">
  <img src="assets/logo.svg" alt="Driftcut" width="64" height="64">
</p>

<h1 align="center">Driftcut</h1>

<p align="center">
  <strong>Early-stop decision gating for LLM model migrations.</strong><br>
  Alpha CLI for sampling migration candidates before you commit to a full evaluation.
</p>

<p align="center">
  <a href="#current-status">Current status</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

## The problem

You want to migrate from one LLM to another - cheaper, faster, better, self-hosted, or more private.

So you run your full prompt corpus against the candidate model. Hundreds or thousands of API calls. Hours of waiting. And only at the end do you discover the candidate breaks the categories that matter most.

You just burned budget to learn something you could have known in the first 10-20%.

**Driftcut is the test you run before the full evaluation.** The current alpha samples strategically, runs baseline and candidate models on a representative slice, and gives you latency/cost signals early. Deterministic quality checks, judge-based scoring, and early-stop decisions are the next milestone.

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
- Export JSON results for later analysis

Planned next:

- Deterministic quality checks
- Judge-based quality comparison
- Failure archetype classification
- Early-stop decision output
- HTML reporting

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

Validate first (no API calls), then run:

```bash
driftcut validate --config migration.yaml
driftcut run --config migration.yaml
```

Today, `driftcut run` executes the planned sample and exports JSON results. It does not yet stop early or produce judge-based quality decisions.

Works with any [LiteLLM-supported provider](https://docs.litellm.ai/): OpenAI, Anthropic, OpenRouter, Azure, self-hosted, and more. See the [docs](https://docs.driftcut.dev/getting-started/) for config examples.

## How it works

### Current alpha

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
Track latency and cost
        |
        v
Export JSON results for review
```

### Planned next

```text
Deterministic checks
        +
Tiered judge strategy
        +
Failure archetype detection
        +
Decision engine
        ->
STOP / CONTINUE / PROCEED
```

## The three dimensions

Driftcut is designed around three migration dimensions. In the current alpha, latency and cost are implemented; quality decisioning is on the roadmap.

- **Quality** - Planned next: deterministic checks, judge comparison, and failure archetypes.
- **Latency** - p50, p95, and variance per category.
- **Cost** - spend so far, per-category cost, and cumulative cost across the sampled run.

## Failure archetypes

This is a planned feature, not something the runtime classifies today. The target categories are:

| Archetype | What it means |
|---|---|
| `schema_break` | JSON invalid, missing fields, incompatible structure |
| `format_break` | Output does not match the expected format |
| `coverage_drop` | Response is incomplete vs baseline |
| `reasoning_degradation` | Candidate is less reliable on complex prompts |
| `refusal_increase` | Candidate refuses more often than baseline |
| `tone_mismatch` | Style is worse for the use case |
| `hallucination_increase` | Candidate fabricates more content |
| `latency_regression` | Candidate is significantly slower than baseline |

## Target output (planned)

This is the intended end-state report once the decision engine and quality layer land. The current alpha CLI output is simpler and focuses on batch execution, latency, cost, and JSON export.

```text
Run: GPT-4o -> Claude Haiku
Corpus: 120 prompts, 4 categories
Batches executed: 2/6
Prompts tested: 24/120 (20%)
Confidence: medium

Quality:
  Overall compatibility: 0.61
  High-criticality failure rate: 62.5% (5/8)

Latency:
  Baseline p50: 820ms | Candidate p50: 340ms (-58%)
  Baseline p95: 2100ms | Candidate p95: 890ms (-57%)

Cost:
  Spend so far: $11.80 (incl. $0.72 judge)
  Estimated spend avoided: $74.30

Decision: STOP NOW
```

## Corpus format

Driftcut requires a structured corpus.

```csv
id,category,prompt,criticality,expected_output_type,notes
cx-001,customer_support,"Given this ticket: {ticket}, draft a response.",high,free_text,
ex-001,structured_extraction,"Extract entities from: {text}. Return JSON.",high,json,Must match schema
cl-001,classification,"Classify this review: {review}",medium,labels,
su-001,summarization,"Summarize this document: {doc}",low,markdown,
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Unique identifier |
| `category` | string | yes | Example: `customer_support`, `structured_extraction` |
| `prompt` | string | yes | Prompt to execute |
| `criticality` | enum | yes | `low` / `medium` / `high` |
| `expected_output_type` | enum | yes | `free_text` / `json` / `labels` / `markdown` |
| `notes` | string | no | Optional context |

## Configuration

The config schema already includes `risk`, `evaluation`, and richer `output` settings. In the current alpha, some of these fields are parsed and displayed by `validate` before they become active runtime behavior.

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
| Early batches | Deterministic checks | $0 | Schema breaks, format errors, refusals |
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
- [ ] Deterministic checker (schema, format, refusal detection)
- [ ] Tiered judge integration
- [ ] Failure archetype classifier
- [ ] Decision engine with configurable thresholds
- [ ] Terminal report with Rich
- [ ] HTML report
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

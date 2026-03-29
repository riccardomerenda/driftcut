<p align="center">
  <img src="assets/logo.svg" alt="Driftcut" width="64" height="64">
</p>

<h1 align="center">Driftcut</h1>

<p align="center">
  <strong>Early-stop decision gating for LLM model migrations.</strong><br>
  Cut bad migration candidates before they burn budget on full-scale evaluations.
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#example-output">Example output</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

## The problem

You want to migrate from one LLM to another — cheaper, faster, better, self-hosted, or more private.

So you run your full prompt corpus against the candidate model. Hundreds or thousands of API calls. Hours of waiting. And only at the end do you discover the candidate breaks the categories that matter most.

You just burned budget to learn something you could have known in the first 10–20%.

**Driftcut is the test you run before the full evaluation.** It samples strategically, evaluates progressively, and tells you early: stop now, keep sampling, or proceed to full eval.

## What it is (and what it isn't)

Driftcut is **not** a generic eval framework. It does not replace Promptfoo, DeepEval, or your internal eval suite. It sits one step earlier in the workflow: the filter that decides whether a full evaluation is worth the money.

| Driftcut is | Driftcut is not |
|---|---|
| A pre-evaluation filter | A generic eval framework |
| A migration decision layer | An experiment tracker |
| A budget-saving gate | A prompt optimization tool |
| CLI-first and single-purpose | A dashboard-first platform |

## Why the name

A migration can fail not because the new model is unusable everywhere, but because it introduces unacceptable drift in the wrong places.

**Driftcut** is designed to catch and cut that drift early, before you commit to a full run.

## Quickstart

> Current status: concept + pre-MVP scaffold. The commands below describe the intended CLI workflow.

Create a config file:

```yaml
# driftcut-migration.yaml
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

Run it:

```bash
driftcut run --config driftcut-migration.yaml
```

The goal is to get a reliable decision in minutes, not a complete benchmark in hours.

## How it works

```text
                  Your prompt corpus
                          |
               +----------+----------+
               | Stratified sampling |
               | by category and     |
               | criticality         |
               +----------+----------+
                          |
                  Batch 1 (small slice)
                          |
              +-----------+-----------+
              |                       |
         Run baseline           Run candidate
              |                       |
              +-----------+-----------+
                          |
               +----------+----------+
               | Evaluate with:      |
               | 1. Deterministic    |
               | 2. Light judge      |
               | 3. Heavy judge      |
               +----------+----------+
                          |
               +----------+----------+
               | Decision engine     |
               |                     |
               | > STOP NOW          |
               | > CONTINUE          |
               | > PROCEED           |
               | > PARTIAL PROCEED   |
               +---------------------+
```

## The three dimensions

Driftcut compares baseline and candidate across three decision dimensions:

- **Quality** — Format adherence, completeness, correctness, hallucination risk, and failure archetypes.
- **Latency** — p50, p95, and variance per category. It flags regressions even when quality appears stable.
- **Cost** — Spend so far, projected full-run cost, and estimated spend avoided by stopping early.

## Failure archetypes

The report should not just say “quality dropped”. It should classify how the candidate is failing.

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

## Example output

```text
Run: GPT-4o → Claude Haiku
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

Reason:
- Category "structured_extraction" shows repeated schema breaks
- High-criticality prompts failed above threshold
- Latency improved significantly but quality regression is blocking
- Candidate not suitable for full eval without prompt adaptation
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
| `category` | string | yes | e.g. `customer_support`, `structured_extraction` |
| `prompt` | string | yes | Prompt to execute |
| `criticality` | enum | yes | `low` / `medium` / `high` |
| `expected_output_type` | enum | yes | `free_text` / `json` / `labels` / `markdown` |
| `notes` | string | no | Optional context |

## Configuration

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

### Threshold philosophy

Defaults are conservative. The engine should rather stop a questionable migration too early than approve a bad candidate that later fails in production.

## Tiered judge strategy

Driftcut aims to save budget, so the judge cannot consume all of it.

| Stage | Method | Cost | Catches |
|---|---|---|---|
| Early batches | Deterministic checks | $0 | Schema breaks, format errors, refusals |
| Mid batches | Light judge | Low | General quality comparison |
| Later ambiguous cases | Heavy judge | Higher | Nuanced quality differences |

## Roadmap

- [x] Concept document
- [x] Demo config and corpus
- [x] Shareable demo report
- [ ] Core CLI (`driftcut run`)
- [ ] Corpus loader (CSV, JSON)
- [ ] Stratified batch sampler
- [ ] Model adapters
- [ ] Deterministic checker
- [ ] Tiered judge integration
- [ ] Failure archetype classifier
- [ ] Latency and cost tracker
- [ ] Decision engine with configurable thresholds
- [ ] Terminal report
- [ ] JSON export
- [ ] Public benchmark demo

## Tech stack

Python 3.12 · Typer · LiteLLM · SQLite · httpx + asyncio · Rich · Pydantic · YAML

## Positioning

Driftcut answers a narrower question than generic eval tooling:

> “Should we continue this migration, or are we already seeing enough risk to stop?”

That narrow scope is the product wedge.

## License

MIT

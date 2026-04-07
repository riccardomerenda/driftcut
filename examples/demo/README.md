# Driftcut demo: a real cost-cut migration

This is the demo run we'd point a curious engineer at to answer "what does Driftcut actually tell you?".

It walks through one realistic question:

> We're on `gpt-4o`. We want to cut our LLM bill. **Should we move to `gpt-4o-mini` or to `claude-3.5-haiku`?**

Both are roughly an order of magnitude cheaper than `gpt-4o`. Both look fine on a vibes-check. Driftcut tells you neither one is safe to migrate to **without** category-specific guardrails — and the categories where each one fails are completely different. That's the kind of finding you want before you burn a full eval run.

## What's in here

| File | Role |
|---|---|
| `raw-prompts.txt` | 30 unstructured prompts across 5 categories (the input to `driftcut bootstrap`) |
| `prompts.csv` | Structured corpus produced by bootstrap, with criticality + checks |
| `migration-mini.yaml` | Live config: `gpt-4o` -> `gpt-4o-mini` |
| `migration-haiku.yaml` | Live config: `gpt-4o` -> `claude-3.5-haiku` |
| `results-mini.json` | Captured results from the live `gpt-4o-mini` run |
| `results-haiku.json` | Captured results from the live `claude-3.5-haiku` run |
| `report-mini.html` | HTML report from the live `gpt-4o-mini` run |
| `report-haiku.html` | HTML report from the live `claude-3.5-haiku` run |
| `replay-mini.json` + `replay-mini.yaml` | Reproduce the `gpt-4o-mini` decision offline, no API key needed |
| `replay-haiku.json` + `replay-haiku.yaml` | Reproduce the `claude-3.5-haiku` decision offline, no API key needed |

## Reproduce the demo with no API key (60 seconds)

This is the path most people will want first. It uses replay mode and `judge_strategy: none`, so the STOP decisions are driven entirely by deterministic checks against the captured outputs.

```bash
pip install driftcut

# From the repo root:
driftcut replay --config examples/demo/replay-mini.yaml  --input examples/demo/replay-mini.json
driftcut replay --config examples/demo/replay-haiku.yaml --input examples/demo/replay-haiku.json
driftcut diff   --before examples/demo/results-mini.json --after examples/demo/results-haiku.json
```

You'll see two `STOP` decisions and a side-by-side diff. The numbers below are the actual numbers from those runs.

## Reproduce live (costs ~$0.07 of OpenRouter credit)

```bash
export OPENROUTER_API_KEY=sk-or-...
cd examples/demo
driftcut run --config migration-mini.yaml
driftcut run --config migration-haiku.yaml
driftcut diff --before driftcut-results/results.json --after driftcut-results/results.json
```

Both live runs stop after the first batch of 15 prompts each, so you only pay for ~30 baseline calls plus a handful of judge calls.

## Building the corpus from raw text

The corpus in `prompts.csv` was generated from `raw-prompts.txt` with:

```bash
driftcut bootstrap --input raw-prompts.txt --output prompts.csv
```

`raw-prompts.txt` is just 30 paragraphs grouped loosely by category. `bootstrap` calls a small LLM to classify each one into a category, assign criticality, infer the expected output type, and propose deterministic checks (required substrings, forbidden substrings, JSON keys, max length). We then hand-tweaked a couple of rows. The point of including the raw file is to show what the bootstrap input actually looks like — you don't need a perfectly structured corpus to start.

## What the runs found

### Run 1: `gpt-4o` -> `gpt-4o-mini`

```text
Decision:       STOP (100% confidence)
Reason:         Candidate exceeded the high-criticality failure threshold
                (64% >= 20%). Most affected category: code_generation
                (high-crit 100%; json_invalid x3).
Risk summary:   overall=45.4%, high-crit=63.6%, schema=0.0%
```

`gpt-4o-mini` failed every single high-criticality `code_generation` and `extraction` prompt. The failure mode was almost entirely the same: when asked for raw JSON with no markdown fences, it returned a `json` markdown fence anyway, so the deterministic JSON parser rejected the response. That's a real production risk: anything downstream that does `json.loads()` on the candidate's output would crash.

### Run 2: `gpt-4o` -> `claude-3.5-haiku`

```text
Decision:       STOP (100% confidence)
Reason:         Candidate exceeded the high-criticality failure threshold
                (45% >= 20%). Most affected category: summarization
                (high-crit 100%; missing_required_content x1, overlong_output x1).
Risk summary:   overall=41.5%, high-crit=45.5%, schema=0.0%
```

`claude-3.5-haiku` actually did the strict-JSON tasks fine — `extraction` came in at **0% failure**. But it dropped key requirements in `summarization` and `customer_support` (e.g., legal phrasing it was told to preserve), and ran long on the cases with a `max_output_chars` budget.

### The diff

```text
+--------------------------------- Decision ----------------------------------+
| STOP -> STOP                                                                |
+-----------------------------------------------------------------------------+
+--------------------------------- Coverage ----------------------------------+
|               Before      After       Delta                                 |
|   Prompts         15         15                                             |
|   Batches          1          1                                             |
|   Cost       $0.0303    $0.0311    +$0.0008                                 |
+-----------------------------------------------------------------------------+
+---------------------------------- Metrics ----------------------------------+
|   Metric                       Before    After     Delta                    |
|   Overall risk                  45.4%    41.5%     -3.9%                    |
|   Candidate failure rate        66.7%    46.7%    -20.0%                    |
|   Candidate regression rate      6.7%    20.0%    +13.3%                    |
|   High-crit failure rate        63.6%    45.5%    -18.2%                    |
|   Latency p50 ratio             1.37x    1.77x    +0.39x                    |
|   Latency p95 ratio             2.07x    2.06x    -0.00x                    |
+-----------------------------------------------------------------------------+
+-------------------------------- Categories ---------------------------------+
|   Category            Before risk    After risk     Delta                   |
|   extraction                61.3%          6.7%    -54.6%                   |
|   summarization             12.6%         58.7%    +46.1%                   |
|   customer_support          18.0%         53.0%    +35.0%                   |
|   classification            11.1%         27.8%    +16.7%                   |
|   code_generation           66.7%         50.0%    -16.7%                   |
+-----------------------------------------------------------------------------+
```

## The point of the demo

Both candidates would ship a `STOP`. That alone is useful — you avoided a full evaluation run, which on a real corpus means real money.

But the more interesting thing is the **shape** of the diff. The two cheap models have **complementary failure profiles**:

- `gpt-4o-mini` is bad at structured output (`code_generation`, `extraction`) and fine at prose.
- `claude-3.5-haiku` is the inverse: bad at prose with strict requirements (`summarization`, `customer_support`) and fine at structured output.

That's the kind of insight you would only get from a per-category breakdown, and it directly suggests a real strategy: **don't pick one cheap model — route per category.** Use `claude-3.5-haiku` for the structured-output workloads and `gpt-4o-mini` for the prose workloads. Or, more conservatively, use the cheap model only on the categories where Driftcut says it's safe and keep `gpt-4o` for the rest.

That decision was made on 30 baseline API calls, ~$0.06 of total spend, and about 30 seconds of wall time per run. That's the entire pitch.

## Notes on reproducibility

- The replay configs use `judge_strategy: none`, so they reach the same `STOP` decisions deterministically without any LLM call. The live runs use `judge_strategy: tiered` and will judge the small number of prompts that pass deterministic checks but differ from baseline.
- The captured `results-mini.json` and `results-haiku.json` are the exact outputs from the live runs we used here. They're checked in so the diff in this README is reproducible without re-running anything.
- The `replay-*.json` files are model outputs only — no API keys, no PII, no proprietary text. The corpus is fully synthetic.

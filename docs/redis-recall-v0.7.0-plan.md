# Driftcut Recall Narrow Plan (v0.7.0)

## Purpose

Add an optional Redis-backed memory layer that makes repeated migration gates cheaper and more queryable without changing Driftcut's core product wedge.

This plan intentionally scopes "Recall" down to two capabilities:

1. baseline response cache
2. searchable run history

It explicitly defers live streaming, dashboards, and prompt-similarity search.

## Product Position

Driftcut remains a migration decision engine.

Recall is not a separate product and not a generic experiment tracker. It is an optional storage layer that helps teams:

- avoid re-calling unchanged baseline prompts
- keep a searchable record of prior gates
- ask operational questions about previous decisions and failures

## Why This Scope

### Build now

- Baseline cache saves real money on repeated gates
- Run history makes the tool more useful without changing its semantics
- Both map cleanly onto the current architecture

### Do not build yet

- Streams are useful, but they mainly enable dashboards and sidecar consumers
- Vector sets are interesting, but they are not central to Driftcut's current wedge
- Similarity features would push the project toward a broader eval platform too early

## Non-Goals

- No always-on requirement for Redis
- No dashboard or run-history UI
- No arbitrary vendor-ingestion layer
- No cross-run analytics beyond narrow run-history queries
- No prompt similarity or vector embeddings in the core runtime
- No caching of candidate outputs
- No hidden behavior changes for existing `run` or `replay`

## User Experience

Default behavior stays exactly the same:

```bash
driftcut run --config migration.yaml
driftcut replay --config replay.yaml --input replay.json
```

Recall is enabled only when configured:

```yaml
memory:
  backend: redis
  redis_url: redis://localhost:6379/0
  response_cache:
    enabled: true
    ttl_seconds: 604800
  run_history:
    enabled: true
    ttl_seconds: 2592000
```

Optional CLI override can come later, but config should be the primary interface.

## Architectural Direction

Create a narrow storage abstraction instead of binding Redis directly into executor or runner logic.

Recommended shape:

- `src/driftcut/store.py`
  Defines a small protocol or base class used by runtime code.
- `src/driftcut/store_redis.py`
  Redis implementation.
- `src/driftcut/store_null.py`
  No-op implementation used when memory is disabled.

This keeps the rest of the runtime mostly unaware of Redis details.

## Phase 1: Baseline Response Cache

### Goal

Skip repeated baseline API calls when the exact same baseline prompt and execution context have already been seen.

### Why baseline only

- baseline reuse is the most common repeated-work case
- candidate outputs are the thing teams are actively testing, so caching them is less trustworthy
- limiting scope reduces product ambiguity

### Cache key

The cache key should be derived from:

- provider
- model
- prompt text hash
- execution context hash

The execution context hash should include only fields that can materially change the output:

- provider
- model
- api_base
- relevant model-call options if Driftcut adds them later

It should not include unrelated migration thresholds or output-reporting settings.

### Stored value

Store a serialized `ModelResponse` plus cache metadata:

- `output`
- `input_tokens`
- `output_tokens`
- `cost_usd`
- `cost_error`
- `error`
- `created_at`
- `source = "live"`
- `cache_hit = false` on write, true on read

### Important latency rule

Do not treat cached baseline latency as live latency evidence.

Recommended behavior:

- cache and return the response content and token/cost data
- set `cache_hit = true`
- set `latency_ms = 0.0` or preserve stored latency in a separate field
- exclude cached baseline latency from live latency regression decisions

This matters because Driftcut's decision engine uses latency. Reusing old baseline latency would make the live candidate comparison misleading.

### Runtime integration

- `executor.py`
  Add an optional baseline-cache lookup path before LiteLLM execution
- `runner.py`
  Pass the optional store into live execution only
- `models.py`
  Extend `ModelResponse` with `cache_hit: bool = False`
- `reporting.py`
  Surface cache hits in JSON output and optionally in HTML summaries

### Failure behavior

- Redis failure must not fail the run
- if cache read/write fails, log a warning to the console and continue normally
- the migration verdict must never depend on Redis availability

## Phase 2: Run History

### Goal

Persist completed run summaries and full run artifacts in Redis so teams can query past gates.

### Primary use cases

- show all runs for baseline X and candidate Y
- show all runs with `STOP`
- show runs where `json_invalid` occurred
- compare cost and risk across recent runs

### What to store

Store one run document per completed run.

Suggested top-level fields:

- `run_id`
- `name`
- `mode`
- `started_at`
- `completed_at`
- `baseline_model`
- `candidate_model`
- `decision.outcome`
- `decision.confidence`
- `decision.metrics.overall_risk`
- `decision.metrics.schema_break_rate`
- `decision.metrics.high_criticality_failure_rate`
- `decision.metrics.archetypes`
- `cost`
- `historical_metrics_present`
- `config_fingerprint`
- `version`

Also store the full serialized results payload produced by `reporting.py`.

### Indexing approach

Use Redis JSON for the run document and Redis Query Engine / Search for indexing.

Index fields should prioritize operational questions, not analytics ambition:

- outcome
- baseline_model
- candidate_model
- mode
- created_at
- archetype names
- overall_risk

### Time series guidance

If time series are added in this phase, key them by metric family rather than by run.

Good shape:

- `driftcut:ts:risk`
- `driftcut:ts:cost`

with labels such as:

- `baseline_model`
- `candidate_model`
- `outcome`
- `mode`

Do not create one time-series key per run.

### Runtime integration

- `runner.py`
  Attach run timestamps and a generated `run_id`
- `reporting.py`
  Reuse the JSON payload as the canonical persisted run document
- new store layer
  Add `save_run(result_payload)` and narrow query helpers later

## Redis Data Model

### Response cache

- key: `driftcut:cache:baseline:<hash>`
- type: JSON document
- TTL: configurable, default 7 days

### Run history

- key: `driftcut:run:<run_id>`
- type: JSON document
- TTL: configurable, default 30 days or no expiry if omitted

### Search index

- index name: `idx:driftcut:runs`
- schema should cover outcome, models, mode, created_at, and selected numeric metrics

## Config Changes

Add a new optional config section:

```yaml
memory:
  backend: redis
  redis_url: redis://localhost:6379/0
  response_cache:
    enabled: true
    ttl_seconds: 604800
  run_history:
    enabled: true
    ttl_seconds: 2592000
```

Suggested model shape:

- `MemoryConfig`
- `RedisMemoryConfig`
- `ResponseCacheConfig`
- `RunHistoryConfig`

Rules:

- if `memory` is omitted, behavior is unchanged
- if `backend=redis`, `redis_url` is required
- replay mode should not use response cache
- replay mode may still write run history

## CLI Behavior

Keep CLI changes minimal for v0.7.0.

No required new flags.

If an override is added, keep it narrow:

```bash
driftcut run --config migration.yaml --redis-url redis://localhost:6379/0
```

But config-only is preferable for the first release.

## Testing Plan

### Unit tests

- cache-key stability tests
- cache-hit and cache-miss behavior
- store-failure fallback behavior
- run-history serialization tests
- config validation for memory settings

### Integration tests

- repeated live run reuses cached baseline output
- cache hit does not break quality, judge, or decision flow
- cached baseline latency does not distort latency decisions
- completed run is persisted to run history when enabled

### Verification strategy

Use a fake store or test double by default.

Do not require a live Redis instance for the main test suite.

If desired later:

- add an opt-in integration test job for real Redis in CI

## Reporting Changes

Add narrow transparency fields:

- per-response `cache_hit`
- run-level `memory_backend`
- run-level `baseline_cache_hits`
- run-level `baseline_cache_misses`

Keep them informational only.

They must not change existing decision semantics.

## Risks and Guardrails

### Risk: product drift

Guardrail:

- keep Recall framed as optional run memory for migration gates
- no dashboard or generic analytics language in README

### Risk: incorrect cache reuse

Guardrail:

- hash only output-relevant execution context
- baseline cache only in v0.7.0
- clear docs on what is and is not cached

### Risk: latency distortion

Guardrail:

- cached baseline responses must not be treated as live latency evidence

### Risk: runtime fragility

Guardrail:

- Redis failures degrade gracefully to no-memory behavior

## Rollout Recommendation

Ship this as alpha and say so clearly.

### v0.7.0

- optional Redis config
- baseline response cache
- run-history persistence and indexing
- JSON/report transparency for cache use

### Later, only if demand appears

- stream events for live observers
- CLI query commands for run history
- prompt similarity and embeddings

## Recommended File Changes

- `src/driftcut/config.py`
  Add memory config models
- `src/driftcut/models.py`
  Add `cache_hit` and run metadata where needed
- `src/driftcut/executor.py`
  Add optional baseline cache lookup/write path
- `src/driftcut/runner.py`
  Thread store through live runs and persist run history on completion
- `src/driftcut/reporting.py`
  Add cache metadata to JSON and HTML
- `src/driftcut/store.py`
  Store interface and shared helpers
- `src/driftcut/store_null.py`
  No-op implementation
- `src/driftcut/store_redis.py`
  Redis implementation
- `tests/`
  Add store, config, executor, runner, and reporting coverage

## Acceptance Criteria

- A live run with Redis enabled can reuse cached baseline responses on repeated execution
- A live run without Redis behaves exactly as today
- Replay mode behavior is unchanged except optional run-history persistence
- Driftcut can persist searchable run documents without changing decision semantics
- Redis outages do not fail or corrupt runs
- Reports clearly disclose cache usage

## Final Recommendation

Build Recall now, but only as a narrow memory layer:

- baseline cache
- run history

Do not ship streams or vector similarity in the first version.

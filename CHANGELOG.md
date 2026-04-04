# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.0] - 2026-04-04

### Added

- `driftcut diff --before results-v1.json --after results-v2.json` command to compare two run results
- Shows decision change, metric deltas (risk, failure rates, latency), cost difference, category-level risk changes, and archetype additions/removals
- Color-coded Rich output: green for improvements, red for regressions
- 13 new tests covering diff logic, file loading, and CLI command (155 total)

## [0.10.0] - 2026-04-04

### Added

- `driftcut bootstrap --input raw-prompts.txt` command that classifies raw prompts into a structured Driftcut corpus using an LLM
- Accepts plain text (one per line or paragraph-separated), CSV with a `prompt` column, or JSON arrays of strings/objects
- `--model` flag to choose the classification model (default: `openai/gpt-4.1-mini`)
- `--output` flag for target path and `--force` to overwrite
- Auto-generates IDs from inferred categories when the input has none
- Normalizes invalid LLM responses (unknown criticality/output types fall back to safe defaults)
- 20 new tests covering input loading, classification parsing, CSV output, and CLI (142 total)

## [0.9.0] - 2026-04-04

### Added

- `driftcut init` scaffolding command that generates a working `migration.yaml` and `prompts.csv`
- `--baseline` and `--candidate` flags to pre-fill model names (e.g. `driftcut init --baseline azure/gpt-4-turbo --candidate openrouter/mistral-large`)
- `--dir` flag to scaffold into a specific directory and `--force` flag to overwrite existing files
- Scaffolded files pass `driftcut validate` out of the box
- 12 new tests covering scaffolding logic and CLI command (122 total)

## [0.8.0] - 2026-04-02

### Added

- Richer prompt-level failure archetypes, including semantic regressions such as `refusal_regression`, `instruction_miss`, `incomplete_answer`, and `format_drift`
- Per-category scorecards in decision metrics, JSON output, and HTML reports
- Category-aware decision reasoning and console summaries that highlight the highest-risk category
- 4 new tests covering richer archetypes, category scorecards, and clearer run-level reasoning (110 total)

### Changed

- Prompt evaluations now retain multiple failure archetypes instead of collapsing to a single coarse label
- Judge-driven regressions can now classify into more actionable semantic buckets instead of only `judge_worse`
- HTML examples now surface archetype summaries alongside deterministic and judge rationale

## [0.7.0] - 2026-04-02

### Added

- Optional Redis memory layer for baseline response caching and searchable run-history persistence
- `cache_hit`, cache summary, and saved baseline cost metrics in JSON and HTML outputs
- `driftcut[redis]` extra plus a Redis-enabled sample config for local testing
- `Dockerfile`, `docker-compose.yml`, and `.dockerignore` for reproducible local Redis-backed runs
- 9 new tests covering Redis config, caching behavior, reporting, and store adapters (106 total)

### Changed

- Cached baseline responses are excluded from live latency comparisons so reuse does not distort candidate latency decisions
- Memory-backed runs now persist canonical run payloads through the same reporting shape used for file exports
- README and docs now document local Docker + Redis workflows alongside the normal Python path

## [0.6.0] - 2026-04-01

### Added

- Real tiered judging with light-to-heavy escalation when light judge confidence is below threshold
- Configurable `tiered_escalation_threshold` in evaluation config (default 0.6)
- `tier` and `escalated` fields on judge results for tracking which judge tier produced the verdict
- `escalated_prompts` metric in decision metrics and JSON/HTML reports
- Split judge cost tracking: `judge_light_usd` and `judge_heavy_usd` in cost summaries
- Escalation threshold shown in HTML thresholds table when strategy is tiered
- 8 new tests for tiered escalation, config validation, cost splitting, and reporting (97 total)

### Changed

- `judge_strategy: tiered` now performs actual light-then-heavy escalation instead of aliasing to light
- Judge cost breakdown (light vs heavy) shown in HTML report when both tiers are used
- Console run summary includes escalated count when escalation occurs

## [0.5.1] - 2026-03-30

### Added

- CLI reference documentation page for `validate`, `run`, `replay`, and global flags
- Visible quickstart output examples across the README and docs site, including terminal and `results.json` excerpts

### Changed

- README, landing page, and docs now show the produced artifacts more concretely instead of only describing the workflow
- Concept documentation now reflects the shipped three-way decision engine and no longer implies category-scoped proceed decisions

### Fixed

- Live model calls now retry transient rate-limit, timeout, connection, and 5xx failures before counting them as API errors
- JSON exports now include per-response `retry_count` so retry behavior is auditable in saved artifacts

## [0.5.0] - 2026-03-30

### Added

- `driftcut replay --config ... --input ...` for historical paired-output backtesting
- Canonical replay JSON loader with versioned schema validation
- Replay-aware JSON and HTML reports with explicit `mode: replay` labeling
- Replay example assets and an external converter template under `scripts/`
- 8 new tests covering replay loading, CLI behavior, reporting, and live/replay parity

### Changed

- Refactored the runner so live execution and replay share the same post-processing path
- Replay now reuses stratified sampling, deterministic checks, judge flow, decision logic, and early-stop behavior
- Replay configs can omit `corpus.file`; the canonical replay input provides prompt metadata directly

## [0.4.0] - 2026-03-29

### Added

- Judge layer for ambiguous prompts with semantic verdicts, confidence, and rationale
- Judge-aware decision metrics, confidence scoring, and cost tracking
- Judge details in JSON output and HTML reports
- 6 new tests for judge helpers and runtime integration

### Changed

- `judge_strategy: light` is now the active default for the alpha runtime
- Ambiguous prompts now lower confidence until they are judged or the strategy is disabled
- `tiered` remains a compatibility alias for light judging until heavy escalation lands

## [0.3.0] - 2026-03-29

### Added

- Deterministic quality checks for expected output formats, required content, JSON keys, and length limits
- Early-stop decision engine with `STOP`, `CONTINUE`, and `PROCEED` outcomes
- HTML report generation alongside richer JSON output
- Run-level risk metrics, confidence, and failure archetype summaries
- 6 new tests for quality checks, reporting, and decision behavior

### Changed

- `min_batches` now actively gates early `PROCEED` decisions
- `risk` and most `output` settings are now active runtime behavior instead of validation-only config
- Public repo messaging and examples now reflect the real runtime feature set

## [0.2.2] - 2026-03-29

### Changed

- Raised the repository quality bar with enforced `mypy` checks in CI and a clean strict-typing pass
- Stabilized sampled batch result ordering and refreshed the public alpha messaging across the app site

### Fixed

- Preserved successful model responses when pricing metadata is unavailable
- Aligned the shipped app version across package metadata, CLI output, changelog, and landing page badge

## [0.2.1] - 2026-03-29

### Added

- `api_base` field on model config for custom endpoints (Azure, proxies, self-hosted)
- OpenRouter support documented and tested
- Multi-provider config examples (same-provider, OpenRouter, custom endpoint)
- 5 new tests (66 total)

## [0.2.0] - 2026-03-29

### Added

- Async model execution via LiteLLM (`executor.py`)
- Latency tracker with p50/p95 per category (`trackers.py`)
- Cost tracker with per-prompt and cumulative spend (`trackers.py`)
- Migration runner with concurrent batch execution (`runner.py`)
- `driftcut run --config` command — fully wired end-to-end
- JSON results export to `driftcut-results/results.json`
- Result data models: `ModelResponse`, `PromptResult`, `BatchResult` (`models.py`)
- Rich progress bars during batch execution
- 26 new tests (61 total)

## [0.1.0] - 2026-03-28

### Added

- YAML config loading and validation with Pydantic models
- Corpus loading from CSV and JSON with full validation
- Stratified batch sampler (high-criticality prioritized in early batches)
- `driftcut validate --config` command with Rich terminal output
- CI pipeline (ruff lint + format + pytest on Python 3.12 & 3.13)
- Pre-launch landing page at driftcut.dev
- Documentation site at docs.driftcut.dev
- 35 tests covering config, corpus, sampler, and CLI

[0.11.0]: https://github.com/riccardomerenda/driftcut/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/riccardomerenda/driftcut/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/riccardomerenda/driftcut/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/riccardomerenda/driftcut/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/riccardomerenda/driftcut/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/riccardomerenda/driftcut/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/riccardomerenda/driftcut/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/riccardomerenda/driftcut/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/riccardomerenda/driftcut/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/riccardomerenda/driftcut/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/riccardomerenda/driftcut/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/riccardomerenda/driftcut/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/riccardomerenda/driftcut/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/riccardomerenda/driftcut/releases/tag/v0.1.0

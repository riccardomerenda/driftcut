# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.6.0]: https://github.com/riccardomerenda/driftcut/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/riccardomerenda/driftcut/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/riccardomerenda/driftcut/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/riccardomerenda/driftcut/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/riccardomerenda/driftcut/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/riccardomerenda/driftcut/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/riccardomerenda/driftcut/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/riccardomerenda/driftcut/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/riccardomerenda/driftcut/releases/tag/v0.1.0

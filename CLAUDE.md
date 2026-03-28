# Driftcut — Development Guide

## What is this?
Driftcut is an early-stop canary testing tool for LLM model migrations. It helps teams decide quickly whether a migration candidate is worth a full evaluation, before burning budget on complete test runs.

## Tech stack
- Python 3.12+ with src layout
- Typer (CLI), Rich (terminal UI), Pydantic (config/models), LiteLLM (multi-provider), httpx + asyncio (concurrency), SQLite (storage), PyYAML (config)
- Tests: pytest + pytest-asyncio
- Linting: ruff
- Type checking: mypy

## Project structure
```
src/driftcut/       # Main package
  cli.py            # CLI entry point (Typer app)
  __main__.py       # python -m driftcut support
tests/              # pytest tests
examples/           # Sample config + corpus
site/               # Pre-launch landing page (GitHub Pages)
docs/               # Documentation (concept doc lives here)
```

## Commands
- `pip install -e ".[dev]"` — install in dev mode
- `pytest` — run tests
- `ruff check src tests` — lint
- `ruff format src tests` — format
- `mypy src` — type check
- `driftcut --help` — CLI help
- `driftcut run --config examples/migration.yaml` — run a migration test

## Key conventions
- Use `src` layout (imports are `from driftcut.xxx import yyy`)
- All config uses Pydantic models validated from YAML
- CLI uses Typer with Rich console output
- Async execution for model calls via httpx
- Conservative defaults in decision engine (favor false negatives over false positives)

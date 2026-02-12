# AGENTS.md

## Overview

This repo is a Python library (`hyperdrive/`) for algorithmic trading — data sourcing, exchange integration, ML prediction, and file/storage utilities.

## CI Checks

All changes must pass these checks before merging (runs on ubuntu, macOS, and Windows):

```bash
make lint      # ruff check . && ruff format --check .
make type      # ty check hyperdrive tests
make cov       # pytest with coverage (threshold enforced)
```

## Running Checks Locally

```bash
make ci DEV=1          # install deps (frozen lockfile, requires uv)
make lint              # lint + format check
make type              # type check (ty)
make test              # unit tests only
make cov               # unit tests with coverage
make smoke             # smoke tests (tests/smoke.py)
make format            # auto-fix lint + format
```

## Project Structure

- `hyperdrive/` — core library modules (Exchange, DataSource, FileOps, Storage, Calculus, Precognition, TimeMachine, etc.)
- `tests/unit/` — pytest unit tests (mocked S3 via moto, mocked APIs via responses)
- `tests/integration/` — integration tests (require real API credentials, marked `@pytest.mark.integration`)
- `tests/smoke.py` — smoke tests for import validation
- `scripts/` — utility scripts (QR codes, etc.)
- `pyproject.toml` — project config, dependencies, and tool settings
- `Makefile` — build/test/lint commands

## Key Conventions

- **Package manager**: `uv` (all commands run via `uv run`)
- **Type checker**: `ty` (astral, not mypy) — `invalid-assignment` is set to `warn` for tests
- **Linter/Formatter**: `ruff`
- **Test runner**: `pytest` with `pytest-xdist` (`-n auto`) and `pytest-cov`
- **Python version**: 3.11
- **Path handling**: use `os.sep` / `os.path` for cross-platform compatibility (tests run on Windows)

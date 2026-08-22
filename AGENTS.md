# AGENTS.md

## Overview

This repo is a Python library (`hyperdrive/`) for algorithmic trading, including data sourcing, exchange integration, ML prediction, and file/storage utilities.

## Style

Preserve the strengths of the direct, low-ceremony style established on the master branch:

- Keep domain flow visible. A reader should be able to follow inputs, calculations, and side effects without crossing unnecessary wrapper layers.
- Prefer focused functions and concrete local variables over abstractions that only rename a basic operation.
- Use positive truthiness checks for present and non-empty values. Arrange the successful path first when it remains clear.
- Keep provider behavior with its provider class and script orchestration in the script entry point.
- Add helpers when they provide meaningful reuse, isolate an external boundary, or make a complex rule easier to verify.
- Preserve observable behavior during refactors and keep unrelated cleanup out of focused changes.

## Design Principles

Patterns the codebase has followed since before the tooling refactor. They are independent of which
linter runs, so formatting, import order, docstring shape, and annotations are left to ruff and `ty`
through `pyproject.toml` rather than restated here.

### Path Discipline

Every filesystem path comes from `PathFinder` in `hyperdrive/Constants.py`. No other module builds a
data path inline, and a new data type adds a `get_*_path` method there before it reads or writes
anything. Path tests assert the exact literal, as in
`finder.get_ohlc_path("aapl") == "data/ohlc/polygon/AAPL.csv"`, which is what stops a path change
from silently orphaning a bucket prefix.

### Column Vocabulary

Column names are constants in `Constants.py` (`SYMBOL`, `TIME`, `OPEN`, `CLOSE`, `EX`, `DIV`,
`RATIO`), grouped under domain comment headers. Reference the constant. A raw column string in logic
is a defect, since renaming a column should be one edit.

### Adapter Boundaries

Vendor vocabulary stops at the adapter. `MarketData.standardize` takes a field mapping and rewrites a
provider payload onto repo constants, with `standardize_dividends`, `standardize_splits`, and
`standardize_ohlc` supplying the mappings. `Kraken.standardize_order` does the same for trades.

Nothing downstream of an adapter should ever see `exDate` or `cash_amount`. When adding a provider,
write the mapping first and let the rest of the code stay unaware of who supplied the data.

### One Subclass Per Vendor

`MarketData` is subclassed by `Indices`, `AlpacaData`, `Polygon`, `LaborStats`, and `Glassnode`. `CEX`
is subclassed by `AlpacaEx`, `Kraken`, and `Binance`. A subclass sets `self.provider` and overrides
only what genuinely differs. Shared behavior belongs on the base class.

### Shared Reliability Primitives

Retry and throttling are written once and reused. Do not hand-roll either at a call site.

- `MarketData.try_again` for retries, reading `C.DEFAULT_RETRIES` and `C.DEFAULT_DELAY`
- `obey_free_limit` and `log_api_call_time` for free-tier spacing
- `Polygon.paginate` for page walking

The established idiom is a private inner closure returned through the wrapper:

```python
def get_dividends(self, **kwargs):
    def _get_dividends(symbol, timeframe="max"):
        self.obey_free_limit(C.POLY_FREE_DELAY)
        ...
    return self.try_again(func=_get_dividends, **kwargs)
```

Rate limits are named constants (`POLY_FREE_DELAY`, `POLY_MAX_LIMIT`), never inline numbers.

### Composition For Testability

Collaborators are assembled in `__init__` and held as attributes. `MarketData.__init__` builds
`writer`, `reader`, `finder`, `traveller`, and `calculator`.

This is what makes the test suite possible: `SwissArmyKnife.replace_attr` walks an object graph
recursively and `use_dev` swaps in the S3 dev bucket, with production code unaware it happened. A
collaborator constructed inside a method instead of `__init__` cannot be retargeted, so avoid it.

### Injectable Credentials

Secrets are constructor parameters with an environment fallback, resolved at construction:
`Polygon(token=os.environ.get("POLYGON"), free=True)`, and `Robinhood(usr=None, ...)` resolving
`usr or os.environ["RH_USERNAME"]`. Do not reach into `os.environ` from deep inside a method.

### Failure Budgets

Batch scripts tolerate per-item failure and still fail the run when too much breaks.
`scripts/update_ohlc.py` is the reference: each symbol is wrapped in `try/except/finally`, successes
are counted in a `multiprocessing.Value`, CI-local files are cleaned up in `finally`, and the script
ends with

```python
if counter.value / total < 0.95:
    exit(1)
```

One bad symbol never aborts the run. A bad day still turns the build red. Pick an explicit floor for
any new batch job rather than letting the first exception decide.

### Thin Scripts

`scripts/` holds procedural glue and all logic lives in `hyperdrive/`. Most scripts are under 60
lines. If a script grows a function worth testing, that function belongs in a module.

### Schedule Awareness

`Flow.get_workflow_start_time` parses the cron expression out of `.github/workflows/{name}.yml` and
`is_workflow_running` estimates a run's duration from symbol count times `POLY_FREE_DELAY`. The code
reads its own schedule so scheduled jobs do not contend for the same rate limit. Keep that link
intact when adding or retiming a workflow.

### Test Layout

One test file per module, an exact 1:1 mapping. A new module arrives with its test file in the same
change. Tests namespace their fixtures by `RUN_ID` so parallel CI runs cannot collide.

### Raising The Bar Incrementally

This codebase has always been mid-migration rather than uniform. `TimeMachine.py` and `Storage.py`
carried full type hints, Google docstrings, and a named alias `FlexibleDate` while older modules
carried none, and the standard moved forward module by module.

New and touched code meets the current bar. Untouched code is left alone. Do not open a sweeping
mechanical change across files unrelated to the task at hand.

## Multiprocessing

- Use the `spawn` multiprocessing context for work that touches network, storage, or provider clients.
- Construct external clients inside the process that uses them. Pass plain, serializable inputs into workers.
- Put process startup behind `main()` and an `if __name__ == "__main__"` guard so module imports remain safe.
- Keep worker orchestration local and explicit unless several callers share a substantial lifecycle policy.

## CI Checks

All changes must pass these checks before merging (runs on ubuntu, macOS, and Windows):

```bash
make lint      # ruff check . && ruff format --check .
make type      # ty check hyperdrive tests
make cov       # pytest with coverage (threshold enforced)
```

These thresholds are ratchets. They encode the current state and move up over time, and the 95%
coverage gate predates the refactor rather than arriving with it. Raise a threshold when the code
clears it. Never lower one to make a change pass.

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

## Workflow Conventions

One workflow per data domain, each with its own cron and a comment translating UTC to Eastern:

```yaml
- cron: "0 16 * * *"
  # 11am EST every day (for crypto)
```

Each job declares only the secrets its script actually needs, which keeps blast radius small. Follow
that when adding a workflow instead of copying a full secret block.

## Commit Format

`emoji type(scope): summary emoji (#PR)`, for example `🔒 chore(strategy): update encryption 🔒 (#264)`
and `🧼 chore(lint): improvements 🧼 (#263)`.

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

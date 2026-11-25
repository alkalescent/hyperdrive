NAME := $(shell basename $(CURDIR))

# DEV=1 includes dev dependencies
UV_SYNC := uv sync $(if $(DEV),--dev,--no-dev)
UV_SYNC_FROZEN := uv sync --frozen $(if $(DEV),--dev,--no-dev)
# --locked stops when uv.lock is out of date with pyproject.toml instead of
# re-locking it
UV_RUN := uv run --locked

.PHONY: install ci lint format type smoke test cov clean qr help all

help:
	@echo "Available targets:"
	@echo "  install - Install dependencies (DEV=1 for dev deps)"
	@echo "  ci      - Install with frozen lock file (DEV=1 for dev deps)"
	@echo "  lint    - Run ruff linter and formatter check"
	@echo "  format  - Run ruff formatter"
	@echo "  type    - Run type checking with ty"
	@echo "  smoke   - Run smoke tests"
	@echo "  test    - Run unit tests with pytest"
	@echo "  cov     - Run tests with pytest and coverage"
	@echo "  qr      - Generate QR codes for donation addresses"
	@echo "  clean   - Remove build artifacts"
	@echo "  all     - Run lint, type, test, and cov"

install:
	$(UV_SYNC)

ci:
	$(UV_SYNC_FROZEN)

lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .

format:
	$(UV_RUN) ruff check . --fix
	$(UV_RUN) ruff format .

type:
	$(UV_RUN) ty check hyperdrive tests

test:
	$(UV_RUN) python -m pytest

cov:
	$(UV_RUN) python -m pytest --cov

smoke:
	$(UV_RUN) python tests/smoke.py

qr:
	$(UV_RUN) --no-dev --group qr python scripts/qr.py

clean:
	rm -rf dist/ build/ *.egg-info/ .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true

all: lint type test cov

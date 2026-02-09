NAME := $(shell basename $(CURDIR))

# DEV=1 includes dev dependencies
UV_SYNC := uv sync $(if $(DEV),--dev,--no-dev)
UV_SYNC_FROZEN := uv sync --frozen $(if $(DEV),--dev,--no-dev)

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
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check . --fix
	uv run ruff format .

type:
	uv run ty check hyperdrive tests

test:
	uv run python -m pytest

cov:
	uv run python -m pytest --cov

smoke:
	uv run python tests/smoke.py

qr:
	uv run python scripts/qr.py

clean:
	rm -rf dist/ build/ *.egg-info/ .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true

all: lint type test cov

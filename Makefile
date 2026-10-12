.DEFAULT_GOAL := help
PYTHON ?= python
VERSION := $(shell $(PYTHON) -c "from dbx_premig.version import APP_VERSION; print(APP_VERSION)" 2>/dev/null)

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install the package with the dev extra
	$(PYTHON) -m pip install -e ".[dev]"

lint: ## ruff + format check + mypy
	ruff check .
	ruff format --check .
	mypy dbx_premig tests scripts

format: ## Apply ruff formatting and safe fixes
	ruff check --fix .
	ruff format .

test: ## pytest with the coverage gate
	$(PYTHON) -m pytest

test-all: ## pytest including slow tests (builds a wheel)
	$(PYTHON) -m pytest -m "" --run-slow

check: lint test ## The acceptance gate

build: ## One-file binary for this OS + smoke test (dist/dbx-discovery)
	PYTHON=$(PYTHON) bash packaging/build.sh

demo: ## Discovery of the bundled fixture -> output/
	$(PYTHON) discovery.py discover --input tests/fixtures/mini/snapshot.json --out output

assets: ## Regenerate brand images, sheet titles and the app icon
	$(PYTHON) scripts/extract_assets.py

clean: ## Remove build output and caches
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov output
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

.PHONY: help install lint format test test-all check build demo assets clean

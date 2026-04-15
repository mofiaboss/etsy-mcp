.PHONY: help sync test test-unit test-integration lint format manifest pre-commit core-test shared-test app-test clean

help:
	@echo "etsy-mcp Ecosystem — Top-Level Commands"
	@echo ""
	@echo "  make sync              Sync uv workspace (install/update all packages)"
	@echo "  make test              Run all tests (core + shared + app unit + app integration if gated)"
	@echo "  make test-unit         Run only unit tests (fast, no network)"
	@echo "  make test-integration  Run integration tests (requires ETSY_INTEGRATION_TESTS=1)"
	@echo "  make lint              Lint all packages"
	@echo "  make format            Format all packages with ruff"
	@echo "  make manifest          Regenerate tools_manifest.json"
	@echo "  make pre-commit        Format + lint + unit tests"
	@echo ""
	@echo "  make core-test         Run etsy-core tests only"
	@echo "  make shared-test       Run etsy-mcp-shared tests only"
	@echo "  make app-test          Run apps/etsy unit tests only"
	@echo ""
	@echo "  make clean             Remove build artifacts and caches"

sync:
	uv sync --all-packages

core-test:
	uv run --package etsy-core pytest packages/etsy-core/tests -v

shared-test:
	uv run --package etsy-mcp-shared pytest packages/etsy-mcp-shared/tests -v

app-test:
	uv run --package etsy-mcp pytest apps/etsy/tests/unit -v

test-unit: core-test shared-test app-test

test-integration:
	@if [ "$$ETSY_INTEGRATION_TESTS" != "1" ]; then \
		echo "Integration tests are gated. Set ETSY_INTEGRATION_TESTS=1 to run."; \
		exit 1; \
	fi
	uv run --package etsy-mcp pytest apps/etsy/tests/integration -v

test: test-unit
	@if [ "$$ETSY_INTEGRATION_TESTS" = "1" ]; then \
		$(MAKE) test-integration; \
	fi

lint:
	uv run ruff check packages/etsy-core packages/etsy-mcp-shared apps/etsy

format:
	uv run ruff format packages/etsy-core packages/etsy-mcp-shared apps/etsy
	uv run ruff check --fix packages/etsy-core packages/etsy-mcp-shared apps/etsy

manifest:
	$(MAKE) -C apps/etsy manifest

pre-commit: format lint test-unit

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .coverage -exec rm -rf {} +
	find . -type d -name htmlcov -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf dist/ build/

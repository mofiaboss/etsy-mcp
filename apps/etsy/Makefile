.PHONY: help test lint format manifest serve clean

help:
	@echo "apps/etsy — Commands"
	@echo ""
	@echo "  make test          Run unit tests"
	@echo "  make lint          Lint with ruff"
	@echo "  make format        Format with ruff"
	@echo "  make manifest      Regenerate tools_manifest.json"
	@echo "  make serve         Run the MCP server (stdio mode)"
	@echo "  make clean         Remove caches"

test:
	uv run --package etsy-mcp pytest tests/unit -v

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

manifest:
	uv run python -m etsy_mcp.cli.manifest --out src/etsy_mcp/tools_manifest.json

serve:
	uv run --package etsy-mcp python -m etsy_mcp

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +

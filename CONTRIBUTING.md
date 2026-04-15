# Contributing to etsy-mcp

Thanks for considering a contribution. Read [AGENTS.md](AGENTS.md) first — it's the canonical project rules and overrides anything below if there's a conflict.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (workspace package manager)

## Setup

```bash
git clone https://github.com/mofiaboss/etsy-mcp.git
cd etsy-mcp
uv sync --all-packages
```

This installs every workspace package in development mode.

## Repository Layout

| Path | Purpose |
|---|---|
| `apps/etsy/` | The MCP server (tools, managers, runtime, CLI) |
| `packages/etsy-core/` | Low-level Etsy connectivity (HTTP client, OAuth, retry, rate limiter, redaction) |
| `packages/etsy-mcp-shared/` | Shared MCP patterns (permissions, confirmation, lazy loading) |
| `docs/` | Architecture, OAuth, workflows, error handling |

## Development Workflow

```bash
make sync              # install/update workspace
make test-unit         # fast unit tests (no network)
make test-integration  # gated on ETSY_INTEGRATION_TESTS=1 — needs real tokens
make lint
make format
make pre-commit        # format + lint + unit tests
```

## Adding a tool — golden path

The full golden path lives in [AGENTS.md](AGENTS.md). The short version:

1. Add a manager method in `apps/etsy/src/etsy_mcp/managers/<domain>_manager.py`
2. Add the tool function in `apps/etsy/src/etsy_mcp/tools/<category>.py` — thin wrapper, delegate to the manager
3. Register the tool name in `TOOL_MODULE_MAP` in `apps/etsy/src/etsy_mcp/categories.py`
4. Run `make manifest` to regenerate `tools_manifest.json`
5. Add unit tests in `apps/etsy/tests/unit/test_<category>.py`
6. Add `ToolAnnotations` to the `@server.tool()` decorator (read-only or mutating, idempotent or not)
7. Mutating tools MUST implement preview-then-confirm
8. Commit the manager + tool + manifest + tests in a single PR

If you're tempted to add a "scoring" or "judgment" or "tag suggestion" tool — read the **Pure Primitive Rule** section at the top of [AGENTS.md](AGENTS.md). The MCP is a capability layer, not a reasoning layer. Reasoning lives in the model.

## PR Conventions

- Branch naming: `feat/short-description`, `fix/short-description`, `docs/short-description`, `chore/short-description`
- Conventional commits required:
  - `feat:` new tool or feature
  - `fix:` bug fix
  - `docs:` documentation only
  - `refactor:` code change without behavior change
  - `test:` test additions or fixes
  - `chore:` deps, CI, configuration
- Keep PRs small and focused — one tool per PR is ideal
- Never push directly to `main`. CI must pass before merge.
- Branch protection requires at least one approving review from `@mofiaboss`

## Review Expectations

- All public functions must have type hints
- All async I/O paths must be async (no blocking calls in tools or managers)
- All tools return `Dict[str, Any]` envelopes (`{"success": True, "data": ...}` or `{"success": False, "error": "..."}`)
- All exceptions must be caught at the tool boundary — no raw tracebacks to MCP clients
- All log lines must run user data through F3 redaction before emission
- Tests must cover happy path, error path, and at least one boundary case
- New tools must include `readOnlyHint` / `destructiveHint` / `idempotentHint` annotations

## Running Tests

```bash
# Unit only — fast, no network
make test-unit

# Specific package
uv run --package etsy-core pytest packages/etsy-core/tests -v

# Specific file
uv run --package etsy-core pytest packages/etsy-core/tests/test_auth.py -v

# Integration — gated, needs ETSY_INTEGRATION_TESTS=1 + real tokens
ETSY_INTEGRATION_TESTS=1 make test-integration
```

## Questions?

Open a discussion at https://github.com/mofiaboss/etsy-mcp/discussions or file an issue.

# Architecture

## Monorepo Structure

```
etsy-mcp/
  apps/
    etsy/                    # The Etsy MCP server
  packages/
    etsy-core/               # Etsy API connectivity (no MCP dependency)
    etsy-mcp-shared/         # Shared MCP server patterns
  docs/                      # Ecosystem-level documentation
```

The workspace is managed by [uv](https://docs.astral.sh/uv/) with `pyproject.toml` at the root defining workspace members. Each app and package is an independent Python package with its own `pyproject.toml`.

## Package Responsibilities

### etsy-core

Low-level Etsy API connectivity. **No MCP dependency.** Any Python application that needs to call Etsy's API can use it directly.

| Module | Purpose |
|---|---|
| `client.py` | `EtsyClient` — async httpx client with auth, retry, rate limit, redaction |
| `auth.py` | `EtsyAuth` — OAuth 2.0 + PKCE, refresh rotation, atomic token storage, file lock |
| `pkce.py` | RFC 7636 PKCE helpers (verifier, challenge, state) |
| `retry.py` | tenacity retry config — Retry-After honoring, exponential backoff, idempotent-only |
| `rate_limiter.py` | Token bucket + persistent daily counter with warn/refuse thresholds |
| `redaction.py` | F3 redaction layer — scrubs OAuth tokens and buyer PII from logs and envelopes |
| `exceptions.py` | Exception hierarchy — `EtsyError`, `EtsyAuthError`, `EtsyPossiblyCompletedError`, etc. |

Used by: `apps/etsy`.

### etsy-mcp-shared

Shared MCP server patterns. Depends on `mcp` SDK and `omegaconf`.

| Module | Purpose |
|---|---|
| `permissions.py` | Permission mode (`confirm` / `bypass`) |
| `confirmation.py` | Preview-then-confirm flow for mutations (`preview_response`, `update_preview`, etc.) |
| `policy_gate.py` | Env-var-based hard policy gates |
| `lazy_tools.py` | Lazy tool loading — only meta-tools register at startup |
| `config.py` | OmegaConf YAML loading with env var interpolation |
| `formatting.py` | Response envelope helpers |

Used by: `apps/etsy`.

### apps/etsy

The Etsy MCP server. 90 tools across 13 categories.

```
apps/etsy/src/etsy_mcp/
  __main__.py        # CLI entry point
  main.py            # FastMCP server bootstrap, transport dispatch
  runtime.py         # @lru_cache singleton factories
  bootstrap.py       # config/auth/client wiring
  categories.py      # ETSY_CATEGORY_MAP + TOOL_MODULE_MAP
  schemas.py         # JSON schemas for tool input validation
  cli/               # auth login/status/logout
  config/            # default config.yaml
  managers/          # one per domain — domain logic + Etsy API translation
  tools/             # thin tool wrappers (one file per category)
  models/            # shared pydantic models (single source of truth for field symmetry)
  tools_manifest.json
```

## Layering

```
MCP Client (Claude Desktop, Claude Code, automation)
    |
    v  MCP Protocol (stdio / Streamable HTTP)
    |
FastMCP Server (main.py)
    |
    v  Tool registration (permissioned_tool decorator)
    |
Tool Functions (tools/*.py)           <- thin wrappers, validate + delegate + envelope
    |
    v  Manager method calls
    |
Manager Layer (managers/*.py)         <- domain logic, fetch-merge-put, verification polling
    |
    v  EtsyClient API calls
    |
EtsyClient (etsy-core)                <- single HTTP authority
    |
    v  httpx + auth + retry + rate limit + redaction
    |
Etsy API
```

**Rules:**

- Tool functions MUST NOT contain business logic beyond argument validation and response formatting
- Managers MUST NOT import from `tools/` (no circular dependencies)
- All Etsy API communication MUST flow through `EtsyClient`
- Shared singletons via `@lru_cache` factories in `runtime.py`
- Config via env vars only — no hardcoded credentials
- Validation schemas in `schemas.py` — never inline JSON schema dicts in tool functions

## Shared Patterns

- **Permissions:** Two-level env var hierarchy (`ETSY_POLICY_*`)
- **Confirmation:** Preview-then-confirm for all mutations, auto-confirm for automation via `ETSY_TOOL_PERMISSION_MODE=bypass`
- **Lazy tool loading:** Meta-tools register at startup; others load on first call (~200 vs ~5000 tokens initial context)
- **Config:** OmegaConf YAML with `${oc.env:VAR,default}` interpolation
- **Tool response contract:** `{"success": bool, "data": ..., "rate_limit": {...}}` or `{"success": false, "error": "..."}`
- **F3 redaction:** Every log line, error envelope, and tool response runs through `redact_sensitive()` before emission

See also:

- [OAUTH.md](OAUTH.md) — full OAuth + PKCE flow
- [RATE_LIMITS.md](RATE_LIMITS.md) — token bucket and daily counter
- [ERROR_HANDLING.md](ERROR_HANDLING.md) — exception hierarchy and envelope shapes
- [WORKFLOWS.md](WORKFLOWS.md) — end-to-end LLM-driven workflows using only primitives
- [TESTING.md](TESTING.md) — unit and integration test strategy
- [permissions.md](permissions.md) — policy gates and confirmation modes

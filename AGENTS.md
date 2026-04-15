# Project Rules

## Pure Primitive Rule (READ THIS FIRST)

**The MCP is a capability layer, not a reasoning layer.**

No tool may implement:
- Scoring algorithms (no `seo_score_listing`, no `tag_quality_score`)
- Heuristic judgments ("this title is good", "these tags are best")
- Content generation (tag suggestions, description rewrites, alt_text templates)
- Ranking or prioritization
- AI-search or SEO "readiness" assessments
- Competitive analysis recommendations
- Any form of hidden intelligence

Every tool is a thin wrapper around an Etsy API endpoint that executes the LLM's decisions without second-guessing them.

The only acceptable cross-cutting tools are **bulk primitives** (`listings_bulk_create_from_template`, `listings_bulk_update_from_template`, `listing_images_bulk_update_alt_text`) — they exist purely to reduce rate-limit overhead. They execute decisions the LLM has already made, never their own.

**Why:** A baked-in heuristic goes stale the day it ships. AI ranking algorithms change constantly; Claude/GPT/Gemini/Llama all reason differently about SEO. Keeping reasoning in the model means the MCP works identically across every agent today and stays durable as both Etsy's algorithms and your model evolve. Pure primitives are trivially testable, cheaper to maintain, and honest about boundaries.

**Enforcement:** At every code review, ask: "Can this tool's behavior be described as 'call endpoint X with args, return response'?" If yes, ship it. If it makes judgments or generates content, reject it.

For full rationale see `etsy-mcp-context/research/08-pure-primitive-rationale.md`.

## Non-Goals

This project is **not**:

- a general-purpose Etsy admin dashboard
- a real-time monitoring or alerting service
- a CI/CD pipeline runner or deployment tool
- a web application with a frontend UI
- a database or persistent storage layer (all state lives on Etsy's API)
- an SEO scoring engine or tag generator (see Pure Primitive Rule)

## Architecture Rules

### Layering

- Tool functions MUST NOT contain business logic beyond argument validation and response formatting
- Tool functions MUST delegate to manager methods for all Etsy API interactions
- Manager methods MUST NOT import from `etsy_mcp.tools` (no circular dependencies)
- All Etsy API communication MUST flow through `EtsyClient` in `etsy-core`
- Tool modules MUST import singletons from `etsy_mcp.runtime`, never instantiate directly
- Shared packages MUST NOT import from app packages (dependency flows downward only)

### Singletons

- All shared objects (server, config, managers, client, auth) MUST be created via `@lru_cache` factories in `etsy_mcp/runtime.py`
- Tests MUST monkey-patch the factory or alias before importing tool modules
- There MUST be exactly one `EtsyClient` and one `EtsyAuth` instance per server process

### Tool Response Contract

All tools MUST return `Dict[str, Any]`:

```python
{"success": True, "data": <result>, "rate_limit": {...}}             # Success
{"success": False, "error": "<specific, actionable message>"}        # Error
{"success": True, "requires_confirmation": True, "preview": <pld>}   # Mutation preview
```

- Exceptions MUST NOT escape tool functions. Catch, log with `exc_info=True`, return error dict.
- Error messages MUST include the operation that failed (e.g., `"Failed to create listing: ..."` not just `str(e)`).
- Raw tracebacks MUST NOT be exposed to MCP clients.
- Every successful response includes a `rate_limit` envelope with `remaining_today`, `reset_at_utc`, and `warning`.

### Confirmation System

All state-changing tools MUST implement preview-then-confirm:
- `confirm=False` (default): validate input, return preview payload with current/proposed diff
- `confirm=True`: execute the mutation against the Etsy API
- Bypass mode (`ETSY_TOOL_PERMISSION_MODE=bypass`) injects `confirm=True` automatically
- **Anchor:** `packages/etsy-mcp-shared/src/etsy_mcp_shared/confirmation.py`

### MCP Tool Annotations

All tools MUST include `annotations=ToolAnnotations(...)` in `@server.tool()`:
- Read-only: `readOnlyHint=True, openWorldHint=True`
- Mutating: `readOnlyHint=False, destructiveHint=<bool>, idempotentHint=<bool>, openWorldHint=True`
- `destructiveHint=True` for delete, deactivate, bulk overwrite operations
- `idempotentHint=True` for update/rename (same args = same result)
- All tools: `openWorldHint=True` (Etsy API is a public uncontrolled domain)

### Async

- All I/O-bound operations MUST use `async`/`await`
- No synchronous blocking calls in tool implementations or managers
- `asyncio.run()` MUST NOT be called from within an async context

### Logging

- All log output MUST go to stderr (stdout is reserved for JSON-RPC in stdio mode)
- Use `%s` format strings in logger calls, not f-strings, for lazy evaluation
- All log emissions MUST run user data through F3 redaction (`etsy_core.redaction.redact_sensitive`)
- Configuration errors SHOULD fail fast at startup with clear guidance

### Hard Bans

- Hardcoding `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`, or any credential in Python source is **banned** — use env vars
- Permission category strings MUST be defined in `etsy_mcp/categories.py` (`ETSY_CATEGORY_MAP`)
- Tool-to-module mappings MUST be in `TOOL_MODULE_MAP` in `etsy_mcp/categories.py`
- Validation schemas MUST be in `etsy_mcp/schemas.py` — never inline JSON schema dicts in tool functions
- No monkey-patches in production code
- No retries on POST/PATCH/non-idempotent PUT/DELETE — see `EtsyPossiblyCompletedError`

## Permission System

Two concepts:

**Permission Mode** — controls mutation handling:
- `confirm` (default): mutations require preview-then-confirm
- `bypass`: mutations execute without confirmation
- Read-only tools are always allowed

Env var: `ETSY_TOOL_PERMISSION_MODE`

**Policy Gates** — hard boundaries that disable actions:

Two-level hierarchy (most specific wins): `ETSY_POLICY_<CATEGORY>_<ACTION>` > `ETSY_POLICY_<ACTION>`

Actions: `CREATE`, `UPDATE`, `DELETE`. Unset = allowed.

All tools MUST remain visible and discoverable regardless of policy gates. Authorization is checked at call time by the `permissioned_tool` decorator.

- **Anchor:** `packages/etsy-mcp-shared/src/etsy_mcp_shared/policy_gate.py`

## Golden Paths

All changes MUST follow a golden path. If no path applies, ask before inventing a new pattern.

### Add a new tool to an existing category

1. Add manager method in `apps/etsy/src/etsy_mcp/managers/<domain>_manager.py`
   - **Anchor (read-only):** `apps/etsy/src/etsy_mcp/managers/shop_manager.py`
   - **Anchor (mutating):** `apps/etsy/src/etsy_mcp/managers/listing_manager.py`
2. Add tool function in `apps/etsy/src/etsy_mcp/tools/<category>.py`
3. Add tool name to `TOOL_MODULE_MAP` in `etsy_mcp/categories.py`
4. Run `make manifest`
5. Add tests in `apps/etsy/tests/unit/test_<category>.py`
6. Add `ToolAnnotations` to the `@server.tool()` decorator
7. Verify the tool passes the **Pure Primitive Rule** test (see top of file)
8. Commit code + manifest + tests together

### Add a new tool category

1. Create manager: `apps/etsy/src/etsy_mcp/managers/<domain>_manager.py`
2. Add `@lru_cache` factory + alias in `etsy_mcp/runtime.py`
3. Create tool module: `apps/etsy/src/etsy_mcp/tools/<category>.py`
4. Add tool names to `TOOL_MODULE_MAP` in `etsy_mcp/categories.py`
5. Add category to `ETSY_CATEGORY_MAP` in `etsy_mcp/categories.py`
6. Run `make manifest`
7. Add tests, update docs and README as needed
8. Commit everything together

### Add a configuration value

1. Add default to `apps/etsy/src/etsy_mcp/config/config.yaml` with `${oc.env:VAR,default}` syntax
2. Add env var to `.env.example` with a comment
3. Document in README.md configuration section

### Add or modify an update tool

Update tools MUST use the fetch-merge-put pattern. The manager fetches current state, merges the caller's partial updates, and PUTs the full object. The tool layer accepts a partial dict, validates via schema, and shows a before/after preview.

1. Manager method: fetch existing → copy → merge updates → PUT full object
2. Add update schema in `etsy_mcp/schemas.py` — all properties optional, no `required` key
3. Tool function: validate via the registry, fetch for preview, use `update_preview`
4. Tool description MUST include: "Pass only the fields you want to change — current values are automatically preserved."
5. Run `make manifest`
6. Add tests covering: partial merge preserves unmentioned fields, not-found returns False, empty update is a no-op

### Add or migrate a domain to shared field models

When a tool domain has list/create/update tools, define a shared pydantic model as the single source of truth for field names, types, and mutability. This ensures list output field names are always accepted by create/update tools — preventing silent data loss.

1. Create model in `apps/etsy/src/etsy_mcp/models/<domain>.py`
   - One `BaseModel` class with all fields (mutable + read-only)
   - Read-only fields marked with `json_schema_extra={"mutable": False}`
   - Export `MUTABLE_FIELDS` and `READ_ONLY_FIELDS` frozensets
   - Co-locate translation helpers: `from_etsy(raw)`, `to_etsy_create(model)`, `to_etsy_update(fields)`
2. Refactor tool functions to derive I/O from the model
3. Retire the domain's JSON Schema from `schemas.py`
4. Manager layer is unchanged — continues to speak the Etsy API dialect
5. Add a field symmetry test asserting every mutable field is a create param
6. Run `make manifest`
7. Commit model + refactored tools + retired schema + tests together

### Add shared functionality

1. Choose package: `etsy-core` (Etsy connectivity, no MCP dependency) or `etsy-mcp-shared` (MCP utilities)
2. Add module to `packages/<pkg>/src/<pkg_name>/`
3. Add tests in `packages/<pkg>/tests/`
4. Run `make core-test` or `make shared-test`

## Quality Gates

A change is not done unless ALL pass:

```bash
make pre-commit   # format + lint + unit tests
```

### Tool Changes Checklist

- [ ] Passes the Pure Primitive Rule test
- [ ] Follows anchor pattern (thin wrapper, delegates to manager)
- [ ] Returns standardized `{"success": bool, ...}` response
- [ ] Added to `TOOL_MODULE_MAP` in `categories.py`
- [ ] `make manifest` run and manifest committed
- [ ] Mutating tools implement preview-then-confirm
- [ ] Permission category and action set via decorator kwargs
- [ ] `ToolAnnotations` added with correct hints
- [ ] Tests cover success, error, and permission denial paths
- [ ] F3 redaction applied to any new log lines

### Configuration Changes Checklist

- [ ] Default in `config.yaml` with `${oc.env:VAR,default}`
- [ ] `.env.example` updated
- [ ] README.md configuration table updated

### Version and Manifest Rules

- Version is derived from git tags via `hatch-vcs`. MUST NOT manually edit version in `pyproject.toml`.
- `tools_manifest.json` MUST be regenerated (`make manifest`) and committed before release.

## Patterns

### Extension Over Patching

- Prefer adding new tool modules and managers over modifying existing ones
- New tool categories get their own manager + tool module (vertical slice)
- Fix root causes, not symptoms

### Conflict Resolution

- Consult the anchor files in Golden Paths when unsure which pattern to follow
- If no anchor applies, ask before inventing a new pattern
- If adopting a genuinely new pattern, update this rules file first

### Plan First

Before non-trivial changes, produce a short plan covering: approach, impacted files, which anchors apply, new tests needed, verification steps.

**Skip the plan only when all are true:** single-file edit, no new behavior or tools, no config/permission/schema changes, no new tests.

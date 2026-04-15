## Summary

<!-- One or two sentences. What does this PR change and why? -->

## Type of change

- [ ] feat: new tool or feature
- [ ] fix: bug fix
- [ ] docs: documentation only
- [ ] refactor: code change without behavior change
- [ ] test: test additions or fixes
- [ ] chore: deps, CI, configuration

## Pre-flight checklist

- [ ] Ran `make pre-commit` (format + lint + unit tests pass)
- [ ] Added or updated tests covering the change
- [ ] No secrets, tokens, or `.env` files committed
- [ ] No raw tracebacks exposed to MCP clients
- [ ] All log lines run through F3 redaction

## Tool changes only (skip if N/A)

- [ ] **Passes the Pure Primitive Rule** — the tool wraps an Etsy API endpoint without scoring, ranking, or content generation
- [ ] Follows the anchor pattern (thin wrapper, delegates to manager)
- [ ] Added to `TOOL_MODULE_MAP` in `categories.py`
- [ ] Ran `make manifest` and committed `tools_manifest.json`
- [ ] `ToolAnnotations` added with correct `readOnlyHint` / `destructiveHint` / `idempotentHint`
- [ ] Mutating tools implement preview-then-confirm
- [ ] Updated `docs/` if the tool surface changed materially

## Test plan

<!-- How did you verify this works? Manual test? New unit tests? Integration test against your own shop? -->

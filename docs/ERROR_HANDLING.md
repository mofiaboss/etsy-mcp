# Error Handling

## Exception Hierarchy

All Etsy-specific errors inherit from `EtsyError`. Callers can catch broadly (`except EtsyError`) or narrowly (`except EtsyAuthError`).

```
EtsyError                              # Base — all etsy-core errors
├── EtsyAuthError                      # 401, invalid_grant, missing tokens, scope insufficient
├── EtsyNotFound                       # 404 base
│   ├── EtsyResourceNotFound           # /listings/12345 — endpoint OK, resource missing
│   └── EtsyEndpointRemoved            # /legacy/forwarding — whole endpoint gone
├── EtsyRateLimitError                 # 429 after retries exhausted (carries retry_after_seconds)
├── EtsyServerError                    # 5xx after retries exhausted
├── EtsyValidationError                # 400 / 422 — bad input
└── EtsyPossiblyCompletedError         # Timeout on non-idempotent write — DO NOT auto-retry
```

### `EtsyError` base

| Attribute | Type | Description |
|---|---|---|
| `message` | str | Human-readable, safe to log and display |
| `status` | int \| None | HTTP status code if applicable |
| `path` | str \| None | Request path that caused the error |
| `request_id` | str \| None | 8-char correlation ID (matches the log line) |
| `detail` | Any | Sanitized error detail payload (sensitive fields F3-redacted on construction) |

`__str__` formats as: `[request_id] HTTP {status} {path} {message}`. Raw dict detail is **never** emitted by `__str__`.

### `EtsyAuthError`

Raised for:

- 401 Unauthorized after refresh attempt
- 403 Forbidden — error message includes scope hint: "this often means insufficient OAuth scope. Verify your granted scopes via `etsy-mcp auth login` with --scope flag."
- `invalid_grant` on refresh — terminal, never auto-retried
- Missing `~/.config/etsy-mcp/tokens.json` and no `ETSY_REFRESH_TOKEN` env fallback
- Empty or whitespace `ETSY_KEYSTRING`
- Corrupt token store

### `EtsyResourceNotFound` vs `EtsyEndpointRemoved`

Both inherit from `EtsyNotFound`. The client distinguishes them heuristically: if the request path contains a numeric segment (e.g., `/listings/12345`), it's `EtsyResourceNotFound`; otherwise it's `EtsyEndpointRemoved`. The latter exists because GoDaddy removed their forwarding API entirely in 2024 — Etsy could do the same, and we want a clear signal when it happens.

### `EtsyRateLimitError`

Carries an extra `retry_after_seconds` attribute parsed from the response header. By the time this error reaches a tool, the client has already retried up to `max_attempts` times honoring `Retry-After`. The LLM should back off significantly or switch to batch mode rather than retry.

### `EtsyPossiblyCompletedError`

Raised when a non-idempotent write (POST, PATCH, etc.) times out. The request **may have completed server-side** — the client just didn't receive a response. The error message says explicitly:

> "DO NOT blindly retry. For money-spending operations, verify state via a read operation before any retry."

This is the hardest lesson from godaddy-mcp baked into etsy-mcp from day one.

## Tool response envelope shapes

All tool functions catch exceptions at the boundary and return a `Dict[str, Any]` envelope. Three shapes:

### Success

```json
{
  "success": true,
  "data": {
    "shop_id": 12345,
    "shop_name": "MyShop"
  },
  "rate_limit": {
    "remaining_today": 9847,
    "reset_at_utc": "2026-04-16T00:00:00Z",
    "warning": null
  }
}
```

### Error

```json
{
  "success": false,
  "error": "Failed to create listing: Validation error: missing required field 'title'",
  "rate_limit": {
    "remaining_today": 9846,
    "reset_at_utc": "2026-04-16T00:00:00Z",
    "warning": null
  }
}
```

The error message MUST include the operation that failed — never just `str(e)`.

### Mutation preview

```json
{
  "success": true,
  "requires_confirmation": true,
  "preview": {
    "operation": "update_listing",
    "listing_id": 12345,
    "current": { "title": "Old Title", "price": 9.99 },
    "proposed": { "title": "New Title", "price": 9.99 },
    "changes": ["title"]
  }
}
```

The agent calls the same tool again with `confirm=True` to execute.

## Translation rules

The `EtsyClient._map_exception` method is the single source of truth for status -> exception mapping:

| HTTP status | Exception class | Notes |
|---|---|---|
| 400, 422 | `EtsyValidationError` | Validation failure |
| 401 | `EtsyAuthError` | "Unauthorized: ..." |
| 403 | `EtsyAuthError` | Includes scope hint |
| 404 (numeric segment in path) | `EtsyResourceNotFound` | |
| 404 (no numeric segment) | `EtsyEndpointRemoved` | |
| 429 | `EtsyRateLimitError` | Includes `retry_after_seconds` |
| 5xx | `EtsyServerError` | After retries exhausted |
| Other | `EtsyError` | Generic fallback |
| `httpx.TimeoutException` (idempotent) | `EtsyServerError` | "timed out after retries exhausted" |
| `httpx.TimeoutException` (non-idempotent) | `EtsyPossiblyCompletedError` | Special — never auto-retried |

## Discipline

- Exceptions MUST NOT escape tool functions
- Tool functions catch broadly (`except Exception`), log with `exc_info=True`, return error envelope
- Manager methods may raise — the tool layer catches
- Raw tracebacks MUST NOT reach MCP clients
- Error messages MUST include the operation that failed
- F3 redaction is applied to `detail` payloads on `EtsyError` construction — sensitive fields are replaced before the exception is even raised

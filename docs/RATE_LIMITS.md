# Rate Limits

## Etsy's published limits

| Limit | Value |
|---|---|
| Per-second | ~10 requests per app |
| Per-day | ~10,000 requests per app |
| Per-shop | None — writes go through the per-app bucket |
| 429 response | Includes `Retry-After` header (integer seconds) |

There is no documented per-token limit. The constraint is per-app: every MCP process using the same `ETSY_KEYSTRING` shares the same daily budget, even across machines.

## Daily budget — what's actually achievable

| Workflow | Approx calls |
|---|---|
| Interactive seller use (a few tool calls/hour) | <100/day — unreachable |
| Bulk catalog refresh (50 listings × 10 lookups + 50 updates) | ~550 |
| Batch import 200 Printful products (5 calls each) | ~1,000 |
| Pathological retry loop from a buggy LLM | unbounded — must be guarded |

The pathological case is why the MCP has a hard refuse threshold at 95% of the daily budget. A misbehaving LLM cannot exhaust the budget below ~9,500 calls — that leaves 500 calls of headroom for recovery.

## Client-side strategy

### Token bucket (in-process)

`packages/etsy-core/src/etsy_core/rate_limiter.py` -> `_TokenBucket`:

- Capacity: 10 tokens
- Refill rate: 10 tokens/second
- Every request acquires 1 token before issuing
- If the bucket is empty, the call awaits until enough tokens have refilled
- Async-safe via `asyncio.Lock`
- No shared state across MCP processes — each process has its own bucket. Acceptable because the per-day cap (which IS shared) is the bigger concern.

### Daily counter

`DailyCounter` in the same module:

- Tracks `count` and `date` (UTC)
- Persists to `~/.config/etsy-mcp/daily_counter.json` every 10 increments
- Loads on startup; resets to 0 if the persisted date is from a prior UTC day
- On UTC rollover during runtime, resets in place
- **Warns at 80%** of budget (single warning per UTC day)
- **Refuses at 95%** of budget — raises `DailyBudgetExceeded`, mapped to `EtsyRateLimitError`

The persisted file is mode `0600` (parent dir `0700`).

### Rate limit envelope

Every successful tool response includes a `rate_limit` envelope:

```json
{
  "success": true,
  "data": { ... },
  "rate_limit": {
    "remaining_today": 9847,
    "reset_at_utc": "2026-04-16T00:00:00Z",
    "warning": null
  }
}
```

The LLM reads `remaining_today` and decides whether to continue, batch, or stop. When the warning threshold is hit, `warning` becomes e.g. `"daily_budget_80_percent_used"`.

## Retry policy

### Idempotent operations (`GET`, explicitly-marked `PUT`)

- Retry on 429: honor `Retry-After` header, else exponential backoff `[1s, 2s, 4s]`, max 16s
- Retry on 5xx: same backoff
- Max 3 attempts total
- Implemented via `tenacity.AsyncRetrying` with the custom `_wait_retry_after_or_exponential` strategy

### Non-idempotent operations (`POST`, `PATCH`, non-idempotent `PUT`, `DELETE`)

- **No automatic retry**
- On timeout: raise `EtsyPossiblyCompletedError`
- The error message says: "the request MAY have completed server-side. DO NOT blindly retry. For money-spending operations, verify state via a read operation before any retry."
- This is the godaddy-mcp lesson hard-coded in: retrying a money-spending POST can double-charge.

### Retry-After parsing

`_extract_retry_after` parses the header as a float, clamps to `[1, 300]` seconds, and returns `None` if the header is absent or malformed. The 300s clamp prevents a server bug or hostile response from making the client sleep for hours.

## Circuit breaker (deferred)

A circuit breaker that opens after 5 consecutive 429s within 30 seconds is planned for v0.2. Until then, the daily counter is the primary defense against runaway loops.

## Testing

- `test_rate_limiter.py::TestTokenBucket::test_acquire_beyond_capacity_waits` — bucket empties and the next acquire blocks
- `test_rate_limiter.py::TestDailyCounter::test_refuses_at_95_percent` — 95% threshold raises
- `test_rate_limiter.py::TestDailyCounter::test_load_resets_on_prior_day` — UTC rollover resets the counter
- `test_retry.py::TestExtractRetryAfter::test_clamps_high_to_300` — clamp upper bound
- `test_client.py::TestGetRetries::test_get_retries_on_429_then_succeeds` — full retry path on a mocked 429
- `test_client.py::TestPostNoRetry::test_post_does_not_retry_on_5xx` — POST never retries
- `test_client.py::TestPostNoRetry::test_post_timeout_raises_possibly_completed` — timeout raises the right exception

"""Token bucket rate limiter for Etsy API calls.

Etsy's rate limits (2026):
- ~10 requests/second per app
- ~10,000 requests/day per app

This module implements an in-process token bucket that enforces the
per-second rate and tracks daily usage. On startup, the daily counter is
loaded from disk and reset if it's from a prior UTC day.

The token bucket is shared across all tools in a single MCP process.
Concurrent MCP processes each have their own bucket (acceptable tradeoff
since the per-day cap is the bigger concern and that could be persisted to
a shared file in the future).

Design notes:
- Async-safe via asyncio.Lock
- Warns at 80% daily budget, refuses at 95%
- No circuit breaker (deferred to v0.2 per development/11-deferred-work.md#d-m02)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class DailyBudgetExceeded(Exception):
    """Raised when the daily request budget has been refused (≥95% threshold)."""


class _TokenBucket:
    """Simple async-safe token bucket.

    Parameters:
        capacity: Maximum tokens in the bucket (default 10)
        refill_rate: Tokens added per second (default 10.0)
    """

    def __init__(self, capacity: int = 10, refill_rate: float = 10.0) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire `tokens` from the bucket, waiting if necessary.

        Blocks until enough tokens are available. Never fails.
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait_time = deficit / self.refill_rate
            # Sleep outside the lock so other coroutines can acquire
            await asyncio.sleep(wait_time)


class DailyCounter:
    """Persistent daily request counter.

    Tracks total requests made today (UTC). Persists to disk for process
    restart continuity. Warns at 80% and refuses at 95% of the configured
    daily budget.
    """

    WARN_THRESHOLD = 0.80
    REFUSE_THRESHOLD = 0.95

    def __init__(
        self,
        budget: int = 10_000,
        persist_path: Path | None = None,
    ) -> None:
        self.budget = budget
        self.persist_path = persist_path
        self._count = 0
        self._date = self._utc_date()
        self._lock = asyncio.Lock()
        self._warned = False
        if persist_path is not None:
            self._load()

    @staticmethod
    def _utc_date() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if self.persist_path is None or not self.persist_path.exists():
            return
        try:
            data = json.loads(self.persist_path.read_text())
            if data.get("date") == self._date:
                self._count = int(data.get("count", 0))
            else:
                # New day — reset
                self._count = 0
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to load daily counter from %s: %s", self.persist_path, exc)
            self._count = 0

    def _persist(self) -> None:
        if self.persist_path is None:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = self.persist_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": self._date, "count": self._count}))
            tmp.chmod(0o600)
            tmp.rename(self.persist_path)
        except OSError as exc:
            logger.warning("Failed to persist daily counter to %s: %s", self.persist_path, exc)

    async def increment(self) -> None:
        """Increment the counter. Raises DailyBudgetExceeded at refuse threshold."""
        async with self._lock:
            # Check for UTC rollover
            today = self._utc_date()
            if today != self._date:
                logger.info("Daily counter UTC rollover: was %d on %s", self._count, self._date)
                self._date = today
                self._count = 0
                self._warned = False

            self._count += 1

            ratio = self._count / self.budget
            if ratio >= self.REFUSE_THRESHOLD:
                self._persist()
                raise DailyBudgetExceeded(
                    f"Daily request budget at {int(ratio * 100)}% ({self._count}/{self.budget}). "
                    f"Refusing new requests to preserve recovery headroom. "
                    f"Resets at UTC midnight."
                )
            if ratio >= self.WARN_THRESHOLD and not self._warned:
                logger.warning(
                    "Daily request budget at %d%% (%d/%d). Consider pausing bulk operations.",
                    int(ratio * 100),
                    self._count,
                    self.budget,
                )
                self._warned = True

            # Persist periodically (every 10 calls) to reduce disk writes
            if self._count % 10 == 0:
                self._persist()

    def remaining(self) -> int:
        """Return the number of requests remaining in the daily budget."""
        return max(0, self.budget - self._count)

    def reset_at_utc(self) -> str:
        """Return the UTC midnight when the counter resets, as ISO 8601."""
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return tomorrow.isoformat().replace("+00:00", "Z")

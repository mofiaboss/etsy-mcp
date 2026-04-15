"""Retry configuration for etsy-core client.

Uses tenacity with a custom wait strategy that honors Retry-After headers.

Policy:
- Idempotent operations (GET, idempotent PUT): retry on 429 and 5xx
- Non-idempotent operations (POST, PATCH, non-idempotent PUT, DELETE): NO retry
- Max 3 retries
- Wait: Retry-After header if present, else exponential backoff [1s, 2s, 4s]

Non-idempotent timeout handling is in client.py — this module only
handles the retry decision logic.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def is_retryable_http_error(exc: BaseException) -> bool:
    """Determine whether an httpx exception is retryable.

    This predicate is method-agnostic — it answers "is this exception class
    one we WOULD retry IF the caller marked the request as idempotent?". The
    actual idempotency check happens in `client._request`, which only runs
    this predicate on idempotent calls (GET + explicitly-marked PUT). Non-
    idempotent calls (POST, PATCH, DELETE) never reach this predicate.

    Returns True for:
    - httpx.TimeoutException (idempotent reads should retry once on timeout)
    - httpx.HTTPStatusError with status 429 (rate limited)
    - httpx.HTTPStatusError with status 5xx (server error)

    Returns False for:
    - All other exceptions
    - 4xx errors other than 429
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or 500 <= status < 600
    return False


def _extract_retry_after(exc: BaseException) -> float | None:
    """Extract the Retry-After header value from an httpx HTTPStatusError.

    Returns the number of seconds to wait, or None if the header is absent
    or malformed. Clamps to a sane range (1-300 seconds).
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    retry_after = exc.response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        seconds = float(retry_after)
    except (ValueError, TypeError):
        return None
    return max(1.0, min(300.0, seconds))


def _wait_retry_after_or_exponential(retry_state: Any) -> float:
    """Custom tenacity wait strategy: honor Retry-After or exponential backoff.

    If the last exception carries a Retry-After header (429 response), wait
    that many seconds. Otherwise fall back to exponential backoff.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None:
        retry_after = _extract_retry_after(exc)
        if retry_after is not None:
            logger.info(
                "Honoring Retry-After: %ss from response (attempt %d)",
                retry_after,
                retry_state.attempt_number,
            )
            return retry_after

    # Exponential backoff: 1s, 2s, 4s (max 16s)
    base_wait = wait_exponential(multiplier=1, min=1, max=16)
    return base_wait(retry_state)


def build_retry_config(max_attempts: int = 3) -> AsyncRetrying:
    """Build a tenacity AsyncRetrying configuration for idempotent requests.

    Args:
        max_attempts: Maximum retry attempts (default 3). The first attempt
            is not a retry, so total request count = max_attempts.

    Returns:
        An AsyncRetrying instance configured for Etsy's retry semantics.
    """
    return AsyncRetrying(
        retry=retry_if_exception(is_retryable_http_error),
        wait=_wait_retry_after_or_exponential,
        stop=stop_after_attempt(max_attempts),
        reraise=True,
    )

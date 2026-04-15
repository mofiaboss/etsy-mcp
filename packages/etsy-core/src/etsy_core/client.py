"""EtsyClient — the sole HTTP authority for all Etsy API communication.

Managers call this client. Tools never touch HTTP directly. Tests can swap
the client via runtime singleton monkey-patching.

Responsibilities:
- httpx.AsyncClient lifecycle (connection pool, timeouts)
- OAuth token injection via EtsyAuth (auto-refresh)
- Rate limiting via token bucket + daily counter
- Retry on idempotent calls (GET + explicitly marked PUT)
- No auto-retry on non-idempotent writes (POST/PATCH/non-idempotent PUT/DELETE)
- PossiblyCompleted guard on timeouts for writes
- Request ID propagation for log correlation
- F3 secret redaction in all log paths
- ACCESS_DENIED enrichment with scope hints
"""

from __future__ import annotations

import logging
import uuid
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import httpx
from tenacity import RetryError

from etsy_core.auth import EtsyAuth
from etsy_core.exceptions import (
    EtsyAuthError,
    EtsyEndpointRemoved,
    EtsyError,
    EtsyPossiblyCompletedError,
    EtsyRateLimitError,
    EtsyResourceNotFound,
    EtsyServerError,
    EtsyValidationError,
    _extract_message,
)
from etsy_core.rate_limiter import DailyBudgetExceeded, DailyCounter, _TokenBucket
from etsy_core.redaction import redact_sensitive
from etsy_core.retry import build_retry_config

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.etsy.com/v3/application"
DEFAULT_TIMEOUT = 15.0


class EtsyClient:
    """Async HTTP client for Etsy API v3.

    Instantiated once per process via `runtime.get_client()`. Managers
    receive it via dependency injection. Never instantiated directly from
    tool functions.
    """

    def __init__(
        self,
        auth: EtsyAuth,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        rate_limit_per_second: float = 10.0,
        daily_budget: int = 10_000,
        daily_counter_path: Path | None = None,
    ) -> None:
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Cycle 2 fix P1-B + Cycle 3 hardening: capacity must be at least 1
        # AND refill_rate must be positive. A rate_limit_per_second value
        # below 1.0 (e.g. 0.5 for very slow clients) used to yield int(0.5)=0
        # capacity and `acquire()` would loop forever. A negative refill_rate
        # from a misconfigured env var would cause undefined token-bucket math.
        # Both bounded here.
        safe_refill_rate = max(0.1, float(rate_limit_per_second))
        self._rate_limiter = _TokenBucket(
            capacity=max(1, int(safe_refill_rate)),
            refill_rate=safe_refill_rate,
        )
        self._daily_counter = DailyCounter(budget=daily_budget, persist_path=daily_counter_path)
        self._http: httpx.AsyncClient | None = None
        self._retry_config = build_retry_config(max_attempts=3)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def _ensure_open(self) -> httpx.AsyncClient:
        """Lazily instantiate the underlying httpx client."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=True,
            )
        return self._http

    async def close(self) -> None:
        """Close the underlying httpx client. Called on server shutdown."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -------------------------------------------------------------------------
    # Core request methods
    # -------------------------------------------------------------------------

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET request with automatic retry on 429, 5xx, and timeouts.

        Retries are delegated to `_retry_config` (tenacity) and honor the
        `Retry-After` header when present. Idempotent by definition, so
        retries are always safe.
        """
        return await self._request("GET", path, params=params, json=None, idempotent=True)

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
    ) -> dict[str, Any]:
        """POST request — NO auto-retry (non-idempotent)."""
        return await self._request("POST", path, params=None, json=json, data=data, files=files, idempotent=False)

    async def put(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """PUT request — auto-retry only if explicitly marked idempotent=True."""
        return await self._request("PUT", path, params=None, json=json, idempotent=idempotent)

    async def patch(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PATCH request — NO auto-retry (non-idempotent per Etsy semantics)."""
        return await self._request("PATCH", path, params=None, json=json, idempotent=False)

    async def delete(self, path: str) -> dict[str, Any]:
        """DELETE request — NO auto-retry (caller must reason about idempotence)."""
        return await self._request("DELETE", path, params=None, json=None, idempotent=False)

    # -------------------------------------------------------------------------
    # Internal request orchestration
    # -------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """Execute an HTTP request with auth, retry, rate limit, and error mapping."""
        request_id = uuid.uuid4().hex[:8]
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"

        # Rate limit + daily budget
        await self._rate_limiter.acquire()
        try:
            await self._daily_counter.increment()
        except DailyBudgetExceeded as exc:
            raise EtsyRateLimitError(str(exc), request_id=request_id) from exc

        # Get auth token (may trigger refresh)
        try:
            access_token = await self.auth.get_access_token()
        except EtsyAuthError:
            raise  # Re-raise as-is
        except Exception as exc:  # pragma: no cover — unexpected auth error
            raise EtsyAuthError(f"Unexpected auth failure: {exc.__class__.__name__}", request_id=request_id) from exc

        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-api-key": self.auth.get_keystring(),
        }
        if json is not None:
            headers["Content-Type"] = "application/json"

        logger.debug(
            "[%s] %s %s (idempotent=%s, remaining_today=%d)",
            request_id,
            method,
            path,
            idempotent,
            self._daily_counter.remaining(),
        )

        client = await self._ensure_open()

        if idempotent:
            # Retry wrapper for idempotent operations
            try:
                async for attempt in self._retry_config:
                    with attempt:
                        response = await client.request(
                            method,
                            url,
                            headers=headers,
                            params=params,
                            json=json,
                            data=data,
                            files=files,
                        )
                        response.raise_for_status()
            except RetryError as exc:
                inner = exc.last_attempt.exception() if exc.last_attempt else exc
                raise self._map_exception(inner, method, path, request_id) from exc
            except httpx.HTTPStatusError as exc:
                raise self._map_exception(exc, method, path, request_id) from exc
            except httpx.HTTPError as exc:
                raise self._map_exception(exc, method, path, request_id) from exc
        else:
            # Non-idempotent: single attempt, no retry
            try:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                )
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                raise EtsyPossiblyCompletedError(
                    f"{method} {path} timed out — the request MAY have completed server-side. "
                    f"DO NOT blindly retry. For money-spending operations, "
                    f"verify state via a read operation before any retry.",
                    path=path,
                    request_id=request_id,
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise self._map_exception(exc, method, path, request_id) from exc
            except httpx.HTTPError as exc:
                raise self._map_exception(exc, method, path, request_id) from exc

        # Parse JSON response (or return empty dict for 204 No Content)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except (JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            # Cycle 3 fix: narrow the bare `except Exception` to specific JSON
            # parse errors. The previous broad catch could mask MemoryError,
            # RecursionError, or future httpx-specific exceptions and silently
            # convert them to "Failed to parse JSON" — debugging hellish.
            # Note: imported as `from json import JSONDecodeError` not `import
            # json` because `_request()` has a `json=None` parameter that
            # would shadow the module reference inside this except clause.
            raise EtsyError(
                f"Failed to parse JSON response from {method} {path}",
                status=response.status_code,
                path=path,
                request_id=request_id,
            ) from exc

    # -------------------------------------------------------------------------
    # Exception mapping
    # -------------------------------------------------------------------------

    def _map_exception(
        self,
        exc: BaseException,
        method: str,
        path: str,
        request_id: str,
    ) -> EtsyError:
        """Map an httpx exception to the appropriate EtsyError subclass.

        Enriches with context: path, request_id, redacted detail. Never
        emits the raw response body into the message.
        """
        if isinstance(exc, httpx.TimeoutException):
            # For idempotent GETs that retried and still timed out, this is a server issue
            return EtsyServerError(
                f"{method} {path} timed out after retries exhausted",
                path=path,
                request_id=request_id,
            )

        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            try:
                detail = exc.response.json() if exc.response.content else None
            except Exception:
                detail = None

            message = _extract_message(detail) if detail else f"HTTP {status}"

            if status == 401:
                return EtsyAuthError(
                    f"Unauthorized: {message}",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                )
            if status == 403:
                return EtsyAuthError(
                    f"Forbidden: {message} — this often means insufficient OAuth scope. "
                    f"Verify your granted scopes via `etsy-mcp auth login` with --scope flag.",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                )
            if status == 405:
                # Method Not Allowed — the endpoint exists but doesn't accept this verb.
                # This is the strongest signal for "endpoint doesn't support this operation"
                # and should drive the fallback logic in managers that implement workarounds.
                return EtsyEndpointRemoved(
                    f"Method not allowed: {message} — this endpoint does not support the {method} verb",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                )
            if status == 404:
                # Distinguishing resource-missing from endpoint-missing on 404 is inherently
                # ambiguous without a second probe. Heuristic:
                # - Path ending in a numeric segment (resource ID): prefer ResourceNotFound.
                #   The caller (typically a manager implementing a destructive fallback like
                #   image_manager.update_alt_text) can verify via a follow-up GET to disambiguate.
                # - Path NOT ending in a numeric segment: probably endpoint-missing.
                #
                # Cycle 2 fix: removed the `if method.upper() == "GET"` branch because both
                # arms produced identical results. The actual "is the verb supported?" question
                # is answered by the manager's GET probe, not by this static heuristic.
                last_segment = path.rstrip("/").split("/")[-1]
                has_numeric_leaf = last_segment.isdigit()
                cls = EtsyResourceNotFound if has_numeric_leaf else EtsyEndpointRemoved
                return cls(
                    f"Not found: {message or path}",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                )
            if status == 400 or status == 422:
                return EtsyValidationError(
                    f"Validation error: {message}",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                )
            if status == 429:
                retry_after = exc.response.headers.get("Retry-After")
                try:
                    retry_after_s = int(retry_after) if retry_after else None
                except ValueError:
                    retry_after_s = None
                return EtsyRateLimitError(
                    f"Rate limit exceeded: {message}",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                    retry_after_seconds=retry_after_s,
                )
            if 500 <= status < 600:
                return EtsyServerError(
                    f"Server error: {message}",
                    status=status,
                    path=path,
                    request_id=request_id,
                    detail=detail,
                )
            return EtsyError(
                f"HTTP {status}: {message}",
                status=status,
                path=path,
                request_id=request_id,
                detail=detail,
            )

        # Any other httpx error (network, DNS, SSL, etc.)
        return EtsyError(
            f"{method} {path} failed: {exc.__class__.__name__}",
            path=path,
            request_id=request_id,
        )

    # -------------------------------------------------------------------------
    # Envelope helpers (used by managers to build consistent responses)
    # -------------------------------------------------------------------------

    def rate_limit_status(self) -> dict[str, Any]:
        """Return the current rate-limit snapshot for inclusion in tool envelopes."""
        remaining = self._daily_counter.remaining()
        ratio = 1.0 - (remaining / max(self._daily_counter.budget, 1))
        warning = None
        if ratio >= 0.80:
            warning = f"daily_budget_{int(ratio * 100)}_percent_used"
        return {
            "remaining_today": remaining,
            "reset_at_utc": self._daily_counter.reset_at_utc(),
            "warning": warning,
        }

    def redact(self, data: Any) -> Any:
        """Public helper: apply F3 redaction to arbitrary data."""
        return redact_sensitive(data)

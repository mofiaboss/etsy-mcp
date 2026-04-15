"""Exception hierarchy for etsy-core.

All Etsy-specific errors inherit from EtsyError. Subclasses carry HTTP status
and operational semantics. The hierarchy is designed so callers can catch
broadly (`except EtsyError`) or narrowly (`except EtsyAuthError`) as needed.

Critical rule: EtsyError.__str__ never emits raw dict detail payloads.
Use _extract_message + _redact_error_detail to format safely. This prevents
accidental secret leaks via exception strings.
"""

from __future__ import annotations

from typing import Any

from etsy_core.redaction import redact_sensitive


def _extract_message(detail: Any) -> str:
    """Extract a human-readable message from an Etsy error detail payload.

    Etsy error responses vary in shape. This helper handles the common cases
    and falls back to a safe string representation. It never emits raw dicts
    — every extracted message is a plain string.
    """
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        # Try common Etsy error keys in order of specificity
        for key in ("error_description", "error", "message", "detail"):
            if key in detail and isinstance(detail[key], str):
                return detail[key]
        # Fall back to the first string value in the dict
        for value in detail.values():
            if isinstance(value, str):
                return value
        return "(error detail could not be safely extracted)"
    if isinstance(detail, (list, tuple)) and detail:
        return _extract_message(detail[0])
    return str(detail)


def _redact_error_detail(detail: Any) -> Any:
    """Redact sensitive fields from an error detail payload.

    Dict payloads are passed through redact_sensitive. Strings, lists, and
    other types are returned as-is (string values cannot contain structured
    secret fields that we'd recognize).
    """
    if isinstance(detail, dict):
        return redact_sensitive(detail)
    if isinstance(detail, (list, tuple)):
        return type(detail)(_redact_error_detail(item) for item in detail)
    return detail


class EtsyError(Exception):
    """Base exception for all etsy-core errors.

    Attributes:
        message: Human-readable error message (safe to log and display)
        status: HTTP status code if applicable (else None)
        path: Request path that caused the error (else None)
        request_id: Correlation ID for tracing (else None)
        detail: Sanitized error detail payload (sensitive fields redacted)
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        path: str | None = None,
        request_id: str | None = None,
        detail: Any = None,
    ) -> None:
        self.message = message
        self.status = status
        self.path = path
        self.request_id = request_id
        self.detail = _redact_error_detail(detail)
        super().__init__(self._format_str())

    def _format_str(self) -> str:
        parts: list[str] = []
        if self.request_id:
            parts.append(f"[{self.request_id}]")
        if self.status is not None:
            parts.append(f"HTTP {self.status}")
        if self.path:
            parts.append(self.path)
        parts.append(self.message)
        return " ".join(parts)


class EtsyAuthError(EtsyError):
    """Authentication or authorization failure.

    Raised for:
    - 401 Unauthorized (invalid/expired access token after refresh attempt)
    - invalid_grant on refresh (token rotation lost)
    - Missing credentials / tokens.json
    - Insufficient scope for the requested endpoint
    """


class EtsyNotFound(EtsyError):
    """404 Not Found — base class for resource-absent errors.

    Callers should prefer catching the more specific subclasses
    (EtsyResourceNotFound or EtsyEndpointRemoved) when they can distinguish.
    """


class EtsyResourceNotFound(EtsyNotFound):
    """Specific resource (listing, shop, image, etc.) not found.

    Implies the endpoint exists but the resource doesn't.
    """


class EtsyEndpointRemoved(EtsyNotFound):
    """Etsy API endpoint no longer exists (or never did).

    Distinguishes from EtsyResourceNotFound when Etsy returns 404 for a whole
    endpoint. This happened to GoDaddy with their forwarding API in 2024 —
    this class exists to handle the same pattern if it ever happens to Etsy.
    """


class EtsyRateLimitError(EtsyError):
    """429 Too Many Requests — rate limit exceeded after retries exhausted.

    The client automatically retries on 429 with Retry-After honoring, so by
    the time this error surfaces we've already waited and retried. Callers
    should back off significantly or switch to batch mode.
    """

    def __init__(self, message: str, *, retry_after_seconds: int | None = None, **kwargs: Any) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, **kwargs)


class EtsyServerError(EtsyError):
    """5xx Server Error — Etsy-side failure.

    The client retries 5xx on idempotent operations. If this error surfaces,
    retries were exhausted or the operation was non-idempotent.
    """


class EtsyValidationError(EtsyError):
    """400 Bad Request — validation failure.

    Either client-side (our pydantic models rejected the input) or server-side
    (Etsy rejected the payload). The `detail` attribute contains the Etsy
    error response with sensitive fields redacted.
    """


class EtsyPossiblyCompletedError(EtsyError):
    """Timeout or transport error on a non-idempotent write.

    The request may have completed server-side even though the client didn't
    receive a response. DO NOT blindly retry. For money-spending operations
    (receipts_create_shipment, listings_activate, any POST), verify state via
    a read operation before any retry.

    This class is the etsy-core equivalent of godaddy-mcp's
    GoDaddyPossiblyCompletedError — same defensive posture against double-charges.
    """

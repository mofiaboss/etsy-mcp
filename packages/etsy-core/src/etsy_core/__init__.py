"""etsy-core — Low-level Etsy API connectivity.

This package contains the HTTP client, OAuth PKCE flow, rate limiter, retry logic,
exception hierarchy, and secret redaction helpers. It has NO MCP dependency —
any Python application that needs to call Etsy's API can use it directly.

Exports:
    EtsyClient      — async HTTP client with auth + retry + rate limit + redaction
    EtsyAuth        — OAuth 2.0 + PKCE + refresh rotation + atomic token storage
    EtsyError       — exception hierarchy base
    EtsyAuthError   — 401, invalid_grant, refresh failures
    EtsyNotFound    — 404 base
    EtsyResourceNotFound
    EtsyEndpointRemoved
    EtsyRateLimitError
    EtsyServerError
    EtsyValidationError
    EtsyPossiblyCompletedError  — timeout on non-idempotent writes
    SENSITIVE_FIELDS  — frozenset of field names that F3 redacts
    redact_sensitive  — redact sensitive fields from a dict
"""

from etsy_core.auth import EtsyAuth
from etsy_core.client import EtsyClient
from etsy_core.exceptions import (
    EtsyAuthError,
    EtsyEndpointRemoved,
    EtsyError,
    EtsyNotFound,
    EtsyPossiblyCompletedError,
    EtsyRateLimitError,
    EtsyResourceNotFound,
    EtsyServerError,
    EtsyValidationError,
)
from etsy_core.redaction import SENSITIVE_FIELDS, redact_sensitive

__all__ = [
    "EtsyAuth",
    "EtsyClient",
    "EtsyError",
    "EtsyAuthError",
    "EtsyNotFound",
    "EtsyResourceNotFound",
    "EtsyEndpointRemoved",
    "EtsyRateLimitError",
    "EtsyServerError",
    "EtsyValidationError",
    "EtsyPossiblyCompletedError",
    "SENSITIVE_FIELDS",
    "redact_sensitive",
]

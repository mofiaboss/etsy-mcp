"""Shared schemas, envelope helpers, and F3 redaction integration.

Single source of truth for validation models and response envelope shapes.
Tool modules and managers import from here — never inline pydantic schemas.
"""

from __future__ import annotations

from typing import Any

from etsy_core.redaction import SENSITIVE_FIELDS, redact_sensitive

__all__ = [
    "SENSITIVE_FIELDS",
    "redact_sensitive",
    "success_envelope",
    "error_envelope",
    "update_with_verification_envelope",
    "partial_success_envelope",
]


def success_envelope(
    data: Any,
    *,
    rate_limit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a success response envelope.

    Args:
        data: The payload (will be passed through redact_sensitive)
        rate_limit: Optional rate-limit snapshot from EtsyClient.rate_limit_status()

    Returns:
        {"success": True, "data": <redacted_data>, "rate_limit": <optional>}
    """
    envelope: dict[str, Any] = {
        "success": True,
        "data": redact_sensitive(data) if data is not None else None,
    }
    if rate_limit is not None:
        envelope["rate_limit"] = rate_limit
    return envelope


def error_envelope(
    error: str,
    *,
    error_code: str | None = None,
    rate_limit: dict[str, Any] | None = None,
    detail: Any = None,
) -> dict[str, Any]:
    """Build an error response envelope.

    Args:
        error: Human-readable error message (should be actionable)
        error_code: Optional machine-readable error code (e.g., "ETSY_AUTH_INSUFFICIENT_SCOPE")
        rate_limit: Optional rate-limit snapshot
        detail: Optional sanitized detail payload

    Returns:
        {"success": False, "error": "...", ...}
    """
    envelope: dict[str, Any] = {
        "success": False,
        "error": error,
    }
    if error_code is not None:
        envelope["error_code"] = error_code
    if rate_limit is not None:
        envelope["rate_limit"] = rate_limit
    if detail is not None:
        envelope["detail"] = redact_sensitive(detail)
    return envelope


def update_with_verification_envelope(
    *,
    requested: dict[str, Any],
    applied: dict[str, Any],
    diverged: dict[str, Any] | None = None,
    ignored: list[str] | None = None,
    warnings: list[str] | None = None,
    rate_limit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an envelope for update operations that poll-verify post-PUT.

    Structure:
    - requested: what the caller asked to change
    - applied: what the server actually shows after verification polling
    - diverged: fields where applied != requested (server normalized, ignored, or transformed)
    - ignored: field names the server silently dropped
    - warnings: human-readable notes about the update
    """
    data = {
        "requested": redact_sensitive(requested),
        "applied": redact_sensitive(applied),
        "diverged": redact_sensitive(diverged or {}),
        "ignored": list(ignored or []),
        "warnings": list(warnings or []),
    }
    return success_envelope(data, rate_limit=rate_limit)


def partial_success_envelope(
    *,
    created: list[dict[str, Any]] | None = None,
    updated: list[dict[str, Any]] | None = None,
    deleted: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    rate_limit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a partial-success envelope for bulk operations.

    Used by bulk primitive tools (bulk_create_from_template, bulk_update_*,
    bulk_update_alt_text) to surface per-item success/failure.

    Envelope `success` semantics (Cycle 1 review fix):
    - Empty input (total == 0) → success=True (nothing to do is not failure)
    - At least one item succeeded → success=True (partial success)
    - All items failed → success=False (total failure is not success)

    The previous version reported success=True unconditionally, which
    deceived callers on all-items-failed runs. Per-item details still live
    in the `data` payload (`created`, `updated`, `deleted`, `failed`), so
    callers can always inspect the fine-grained outcome.
    """
    total = 0
    successful = 0
    failed_count = 0

    data: dict[str, Any] = {}
    if created is not None:
        data["created"] = [redact_sensitive(item) for item in created]
        total += len(created)
        successful += len([i for i in created if i.get("status") == "success"])
    if updated is not None:
        data["updated"] = [redact_sensitive(item) for item in updated]
        total += len(updated)
        successful += len([i for i in updated if i.get("status") == "success"])
    if deleted is not None:
        data["deleted"] = [redact_sensitive(item) for item in deleted]
        total += len(deleted)
        successful += len([i for i in deleted if i.get("status") == "success"])
    if failed is not None:
        data["failed"] = [redact_sensitive(item) for item in failed]
        total += len(failed)
        failed_count = len(failed)

    data["total"] = total
    data["successful"] = successful
    data["failed_count"] = failed_count

    # success = True only if at least one item succeeded OR there was
    # nothing to do. All-failure must not masquerade as success.
    envelope_success = total == 0 or successful > 0

    envelope: dict[str, Any] = {
        "success": envelope_success,
        "data": redact_sensitive(data),
    }
    if rate_limit is not None:
        envelope["rate_limit"] = rate_limit
    if not envelope_success:
        envelope["error"] = (
            f"Bulk operation failed: 0 of {total} items succeeded. "
            f"See data.failed for per-item errors."
        )
    return envelope

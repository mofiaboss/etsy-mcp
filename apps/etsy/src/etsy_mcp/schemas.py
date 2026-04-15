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


#: Per-item statuses that count as "the server accepted this item".
#: Cycle 2 fix P0-B: `diverged` MUST count as success because Etsy
#: routinely normalizes input fields (price rounding, string trimming,
#: tag casing). A bulk PATCH where every item was accepted by the server
#: but one field per item got normalized used to report success=False
#: with "0 of N items succeeded" — a worse semantic inversion than the
#: original Cycle 1 SA-2 bug. The diverged status means "the PATCH
#: succeeded, the server returned a different value than requested" —
#: that's accepted-with-modification, not failure.
SUCCESS_STATUSES: frozenset[str] = frozenset({"success", "diverged"})


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

    Envelope `success` semantics:
    - Empty input (total == 0) → success=True (nothing to do is not failure)
    - At least one item succeeded → success=True (partial success)
    - All items failed → success=False (total failure is not success)

    "Succeeded" includes both `status="success"` AND `status="diverged"`,
    because diverged means "the server accepted the PATCH but returned a
    normalized value" — that's still acceptance, not failure. See
    SUCCESS_STATUSES for the canonical set.

    Per-item details (success, diverged, failed counts plus the raw item
    lists) live in the `data` payload so callers can always inspect the
    fine-grained outcome.
    """
    total = 0
    successful = 0
    diverged_count = 0
    failed_count = 0

    def _count_successes(items: list[dict[str, Any]]) -> tuple[int, int]:
        """Return (successful_count, diverged_count) for a per-item list."""
        ok = 0
        div = 0
        for item in items:
            status = item.get("status")
            if status in SUCCESS_STATUSES:
                ok += 1
                if status == "diverged":
                    div += 1
        return ok, div

    data: dict[str, Any] = {}
    if created is not None:
        data["created"] = [redact_sensitive(item) for item in created]
        total += len(created)
        ok, div = _count_successes(created)
        successful += ok
        diverged_count += div
    if updated is not None:
        data["updated"] = [redact_sensitive(item) for item in updated]
        total += len(updated)
        ok, div = _count_successes(updated)
        successful += ok
        diverged_count += div
    if deleted is not None:
        data["deleted"] = [redact_sensitive(item) for item in deleted]
        total += len(deleted)
        ok, div = _count_successes(deleted)
        successful += ok
        diverged_count += div
    if failed is not None:
        data["failed"] = [redact_sensitive(item) for item in failed]
        total += len(failed)
        failed_count = len(failed)

    data["total"] = total
    data["successful"] = successful
    data["diverged_count"] = diverged_count
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

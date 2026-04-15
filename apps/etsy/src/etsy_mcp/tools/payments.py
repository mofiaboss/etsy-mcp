"""MCP tool module: payments category (READ-ONLY).

8 read-only tools wrapping PaymentManager:
- etsy_payments_get_by_receipt
- etsy_payments_get_by_ledger_entry
- etsy_payments_list                      (batch by payment_ids)
- etsy_ledger_entries_list
- etsy_ledger_entry_get
- etsy_ledger_entry_payments_get
- etsy_ledger_list_by_payment_account
- etsy_payment_account_summary

The entire category is read-only — Etsy does not allow third-party apps to
move money. Every tool is guarded under the transactions_r scope.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations

from etsy_mcp.runtime import get_client, get_payment_manager, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


@server.tool(
    name="etsy_payments_get_by_receipt",
    description="Get all payment records for a single receipt. Each payment includes amount, "
    "currency, processing fees, payout status, and any refund details.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_payments_get_by_receipt(
    shop_id: int,
    receipt_id: int,
) -> dict[str, Any]:
    """Get payments for a receipt."""
    try:
        manager = get_payment_manager()
        data = await manager.get_by_receipt(shop_id, receipt_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_payments_get_by_receipt(%s,%s) failed: %s",
            shop_id,
            receipt_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get payments for receipt {receipt_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_payments_get_by_receipt unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_payments_get_by_ledger_entry",
    description="Get the payment(s) associated with a single payment-account ledger entry. "
    "Useful for tracing which order generated a particular ledger debit/credit.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_payments_get_by_ledger_entry(
    shop_id: int,
    ledger_entry_id: int,
) -> dict[str, Any]:
    """Get payments for a ledger entry."""
    try:
        manager = get_payment_manager()
        data = await manager.get_by_ledger_entry(shop_id, ledger_entry_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_payments_get_by_ledger_entry(%s,%s) failed: %s",
            shop_id,
            ledger_entry_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get payments for ledger entry {ledger_entry_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_payments_get_by_ledger_entry unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_payments_list",
    description="Batch-get multiple payment records by passing a list of payment_ids. Etsy "
    "returns them in a single response — much cheaper than calling get_by_receipt repeatedly.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_payments_list(
    shop_id: int,
    payment_ids: list[int],
) -> dict[str, Any]:
    """Batch-get payments by ID list."""
    try:
        if not payment_ids:
            return error_envelope("payment_ids must not be empty")
        if len(payment_ids) > 100:
            return error_envelope("payment_ids supports at most 100 IDs per call")

        manager = get_payment_manager()
        data = await manager.list_payments(shop_id, payment_ids)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_payments_list(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to batch-get payments: {exc.message}")
    except Exception as exc:
        logger.error("etsy_payments_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_ledger_entries_list",
    description="List entries from the shop's payment-account ledger. Each entry represents a "
    "credit or debit (sale, fee, refund, payout) against the shop's Etsy balance. Supports "
    "pagination and creation-date filters. Max limit is 100.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_ledger_entries_list(
    shop_id: int,
    limit: int = 25,
    offset: int = 0,
    min_created: int | None = None,
    max_created: int | None = None,
) -> dict[str, Any]:
    """List ledger entries with optional date filters."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_payment_manager()
        data = await manager.ledger_entries_list(
            shop_id,
            limit=limit,
            offset=offset,
            min_created=min_created,
            max_created=max_created,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_ledger_entries_list(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to list ledger entries: {exc.message}")
    except Exception as exc:
        logger.error("etsy_ledger_entries_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_ledger_entry_get",
    description="Get a single payment-account ledger entry by ID.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_ledger_entry_get(
    shop_id: int,
    ledger_entry_id: int,
) -> dict[str, Any]:
    """Get a single ledger entry."""
    try:
        manager = get_payment_manager()
        data = await manager.ledger_entry_get(shop_id, ledger_entry_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_ledger_entry_get(%s,%s) failed: %s",
            shop_id,
            ledger_entry_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get ledger entry {ledger_entry_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_ledger_entry_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_ledger_entry_payments_get",
    description="Get payments associated with a payment-account ledger entry. Mirrors "
    "etsy_payments_get_by_ledger_entry but kept distinct for explicit ledger-walk workflows.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_ledger_entry_payments_get(
    shop_id: int,
    ledger_entry_id: int,
) -> dict[str, Any]:
    """Get payments via the ledger-entry route."""
    try:
        manager = get_payment_manager()
        data = await manager.ledger_entry_payments_get(shop_id, ledger_entry_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_ledger_entry_payments_get(%s,%s) failed: %s",
            shop_id,
            ledger_entry_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get payments for ledger entry {ledger_entry_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_ledger_entry_payments_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_ledger_list_by_payment_account",
    description="List ledger entries via the payment_account route. NOTE: This is currently a "
    "duplicate of etsy_ledger_entries_list pending docs verification — Etsy v3 may not expose a "
    "distinct payment-account-scoped listing endpoint.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_ledger_list_by_payment_account(
    shop_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List ledger entries via payment-account scope."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_payment_manager()
        data = await manager.ledger_list_by_payment_account(
            shop_id, limit=limit, offset=offset
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_ledger_list_by_payment_account(%s) failed: %s",
            shop_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to list payment-account ledger: {exc.message}")
    except Exception as exc:
        logger.error("etsy_ledger_list_by_payment_account unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_payment_account_summary",
    description="Get a summary of the shop's Etsy payment account: available balance, pending "
    "balance, currency, and payout schedule. NOTE: Etsy v3 may not document this endpoint — "
    "if so, the call will return a 404/EtsyEndpointRemoved error envelope.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="payments",
    permission_action="READ",
)
async def etsy_payment_account_summary(shop_id: int) -> dict[str, Any]:
    """Get the payment account summary."""
    try:
        manager = get_payment_manager()
        data = await manager.payment_account_summary(shop_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_payment_account_summary(%s) failed: %s", shop_id, exc, exc_info=True
        )
        return error_envelope(f"Failed to get payment account summary: {exc.message}")
    except Exception as exc:
        logger.error("etsy_payment_account_summary unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

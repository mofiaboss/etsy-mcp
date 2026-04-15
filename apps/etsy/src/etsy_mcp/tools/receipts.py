"""MCP tool module: receipts category.

10 tools wrapping ReceiptManager:
- etsy_receipts_list_by_shop
- etsy_receipts_get
- etsy_receipts_update
- etsy_receipts_create_shipment   (MONEY/BUYER-NOTIFICATION)
- etsy_transactions_list_by_shop
- etsy_transactions_list_by_receipt
- etsy_transactions_list_by_listing
- etsy_transactions_get
- etsy_refunds_list_by_receipt
- etsy_receipts_list_by_buyer

All write tools use preview-then-confirm. The shipment tool is the only
non-idempotent write — on timeout the manager surfaces
EtsyPossiblyCompletedError and the tool returns an actionable error envelope
that explicitly tells the caller NOT to retry without verification.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import (
    EtsyError,
    EtsyPossiblyCompletedError,
)
from mcp.types import ToolAnnotations

from etsy_mcp.runtime import get_client, get_receipt_manager, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Receipts — read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_receipts_list_by_shop",
    description="List receipts (orders) for an Etsy shop. Supports pagination and filters by "
    "creation date range, paid status, and shipped status. Use this to find unfulfilled orders, "
    "recent sales, or orders pending shipment. Max limit is 100.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_receipts_list_by_shop(
    shop_id: int,
    limit: int = 25,
    offset: int = 0,
    min_created: int | None = None,
    max_created: int | None = None,
    was_paid: bool | None = None,
    was_shipped: bool | None = None,
) -> dict[str, Any]:
    """List receipts for a shop with optional filters."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_receipt_manager()
        data = await manager.list_by_shop(
            shop_id,
            limit=limit,
            offset=offset,
            min_created=min_created,
            max_created=max_created,
            was_paid=was_paid,
            was_shipped=was_shipped,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_receipts_list_by_shop(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to list receipts for shop {shop_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_receipts_list_by_shop unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_receipts_get",
    description="Get a single Etsy receipt by receipt_id, including buyer info, line items, "
    "shipping address, payment status, and shipment tracking.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_receipts_get(shop_id: int, receipt_id: int) -> dict[str, Any]:
    """Get a receipt."""
    try:
        manager = get_receipt_manager()
        data = await manager.get(shop_id, receipt_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_receipts_get(%s,%s) failed: %s", shop_id, receipt_id, exc, exc_info=True
        )
        return error_envelope(f"Failed to get receipt {receipt_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_receipts_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_receipts_list_by_buyer",
    description="List receipts in an Etsy shop filtered by buyer user_id. Useful for looking up "
    "all orders from a specific repeat customer. NOTE: Etsy's filter support for this query "
    "parameter is unverified; if the server ignores it, callers should fall back to "
    "etsy_receipts_list_by_shop and filter client-side.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_receipts_list_by_buyer(
    shop_id: int,
    buyer_user_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List receipts filtered by buyer."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_receipt_manager()
        data = await manager.list_by_buyer(
            shop_id, buyer_user_id, limit=limit, offset=offset
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_receipts_list_by_buyer(%s,%s) failed: %s",
            shop_id,
            buyer_user_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to list receipts for buyer {buyer_user_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_receipts_list_by_buyer unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Receipts — write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_receipts_update",
    description="Update mutable fields on a receipt (gift note, message_from_seller, etc). "
    "Uses fetch-merge-put: pass only the fields you want to change. "
    "With confirm=False (default), returns a preview. With confirm=True, executes the update.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="receipts",
    permission_action="UPDATE",
)
async def etsy_receipts_update(
    shop_id: int,
    receipt_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a receipt with fetch-merge-put + preview."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_receipt_manager()

        # Fetch current state for both preview and merge
        current = await manager.get(shop_id, receipt_id)
        current_relevant = {k: current.get(k) for k in updates.keys()}
        merged = {**current_relevant, **updates}

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "receipt",
                "resource_id": str(receipt_id),
                "preview": {
                    "current": current_relevant,
                    "proposed": updates,
                },
                "warnings": [
                    "Updates to message_from_seller may be visible to the buyer.",
                ],
                "message": f"Will update {', '.join(updates.keys())} on receipt {receipt_id}. "
                "Set confirm=true to execute.",
            }

        data = await manager.update(shop_id, receipt_id, merged)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_receipts_update(%s,%s) failed: %s", shop_id, receipt_id, exc, exc_info=True
        )
        return error_envelope(f"Failed to update receipt {receipt_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_receipts_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_receipts_create_shipment",
    description="Mark a receipt as shipped and submit tracking information to Etsy. "
    "*** MONEY/BUYER-NOTIFICATION OPERATION *** This triggers an automated shipment-confirmation "
    "email to the buyer and CANNOT be cleanly undone. The underlying API call is non-idempotent: "
    "on timeout, the tool returns an error and explicitly tells the caller NOT to retry without "
    "verifying state via etsy_receipts_get first. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="receipts",
    permission_action="CREATE",
)
async def etsy_receipts_create_shipment(
    shop_id: int,
    receipt_id: int,
    tracking_code: str,
    carrier_name: str,
    send_bcc: bool = False,
    note_to_buyer: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Submit tracking info / mark shipped — non-idempotent buyer notification."""
    try:
        if not tracking_code or not tracking_code.strip():
            return error_envelope("tracking_code must not be empty")
        if not carrier_name or not carrier_name.strip():
            return error_envelope("carrier_name must not be empty")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create_shipment",
                "resource_type": "receipt_shipment",
                "resource_id": str(receipt_id),
                "preview": {
                    "current": None,
                    "proposed": {
                        "shop_id": shop_id,
                        "receipt_id": receipt_id,
                        "tracking_code": tracking_code.strip(),
                        "carrier_name": carrier_name.strip(),
                        "send_bcc": send_bcc,
                        "note_to_buyer": note_to_buyer,
                    },
                },
                "warnings": [
                    "MONEY/BUYER-NOTIFICATION OPERATION: marks the order shipped on Etsy.",
                    "Etsy will automatically email the buyer with tracking details.",
                    "This call is non-idempotent — on timeout, DO NOT retry blindly. "
                    "Verify state with etsy_receipts_get before any retry.",
                ],
                "message": f"Will mark receipt {receipt_id} as shipped via {carrier_name.strip()} "
                f"with tracking {tracking_code.strip()}. Set confirm=true to execute.",
            }

        manager = get_receipt_manager()
        data = await manager.create_shipment(
            shop_id,
            receipt_id,
            tracking_code=tracking_code.strip(),
            carrier_name=carrier_name.strip(),
            send_bcc=send_bcc,
            note_to_buyer=note_to_buyer,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyPossiblyCompletedError as exc:
        # Critical: do NOT advise retry without state verification.
        logger.error(
            "etsy_receipts_create_shipment(%s,%s) POSSIBLY COMPLETED: %s",
            shop_id,
            receipt_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            "Shipment request timed out — the operation MAY have completed server-side. "
            "DO NOT retry. Verify the receipt's shipment state with etsy_receipts_get "
            f"for receipt {receipt_id} before taking further action.",
            error_code="ETSY_POSSIBLY_COMPLETED",
            rate_limit=get_client().rate_limit_status(),
        )
    except EtsyError as exc:
        logger.error(
            "etsy_receipts_create_shipment(%s,%s) failed: %s",
            shop_id,
            receipt_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to create shipment for receipt {receipt_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_receipts_create_shipment unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Transactions — read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_transactions_list_by_shop",
    description="List all transactions (line items across all receipts) for a shop. "
    "A transaction is a single line item on a receipt — one receipt may contain several.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_transactions_list_by_shop(
    shop_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List shop-wide transactions."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_receipt_manager()
        data = await manager.transactions_list_by_shop(shop_id, limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_transactions_list_by_shop(%s) failed: %s", shop_id, exc, exc_info=True
        )
        return error_envelope(f"Failed to list transactions for shop {shop_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_transactions_list_by_shop unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_transactions_list_by_receipt",
    description="List all transactions (line items) within a single receipt.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_transactions_list_by_receipt(
    shop_id: int,
    receipt_id: int,
) -> dict[str, Any]:
    """List transactions for a receipt."""
    try:
        manager = get_receipt_manager()
        data = await manager.transactions_list_by_receipt(shop_id, receipt_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_transactions_list_by_receipt(%s,%s) failed: %s",
            shop_id,
            receipt_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to list transactions for receipt {receipt_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_transactions_list_by_receipt unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_transactions_list_by_listing",
    description="List all transactions (sales) for a single listing. Useful for sales-history "
    "analytics on a specific product.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_transactions_list_by_listing(
    shop_id: int,
    listing_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List transactions for a listing."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_receipt_manager()
        data = await manager.transactions_list_by_listing(
            shop_id, listing_id, limit=limit, offset=offset
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_transactions_list_by_listing(%s,%s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to list transactions for listing {listing_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_transactions_list_by_listing unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_transactions_get",
    description="Get a single transaction (line item) by transaction_id.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_transactions_get(shop_id: int, transaction_id: int) -> dict[str, Any]:
    """Get a transaction."""
    try:
        manager = get_receipt_manager()
        data = await manager.transactions_get(shop_id, transaction_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_transactions_get(%s,%s) failed: %s",
            shop_id,
            transaction_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to get transaction {transaction_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_transactions_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Refunds — read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_refunds_list_by_receipt",
    description="List refund records associated with a receipt. NOTE: Etsy v3 surfaces refunds "
    "inside the Payment objects on the /receipts/{id}/payments endpoint — there is no dedicated "
    "/refunds endpoint. Each returned payment may contain a 'refunds' array with refund details.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="receipts",
    permission_action="READ",
)
async def etsy_refunds_list_by_receipt(
    shop_id: int,
    receipt_id: int,
) -> dict[str, Any]:
    """List refunds for a receipt (via the payments endpoint)."""
    try:
        manager = get_receipt_manager()
        data = await manager.refunds_list_by_receipt(shop_id, receipt_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_refunds_list_by_receipt(%s,%s) failed: %s",
            shop_id,
            receipt_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to list refunds for receipt {receipt_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_refunds_list_by_receipt unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

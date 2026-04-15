"""Receipt manager — wraps Etsy Receipt + Transaction + Refund endpoints.

10 operations:
- list_by_shop: GET /shops/{shop_id}/receipts
- get: GET /shops/{shop_id}/receipts/{receipt_id}
- update: PATCH /shops/{shop_id}/receipts/{receipt_id} (fetch-merge-patch)
- create_shipment: POST /shops/{shop_id}/receipts/{receipt_id}/tracking
    *** MONEY/BUYER-NOTIFICATION operation — uses non-idempotent POST ***
- transactions_list_by_shop
- transactions_list_by_receipt
- transactions_list_by_listing
- transactions_get
- refunds_list_by_receipt
- list_by_buyer

Receipts represent buyer orders. Modifications and shipment notifications are
buyer-visible and money-sensitive. The tool layer is responsible for preview-
then-confirm and for surfacing EtsyPossiblyCompletedError on shipment timeouts.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class ReceiptManager:
    """Manages Etsy Receipt, Transaction, and Refund operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Receipts — read
    # -------------------------------------------------------------------------

    async def list_by_shop(
        self,
        shop_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
        min_created: int | None = None,
        max_created: int | None = None,
        was_paid: bool | None = None,
        was_shipped: bool | None = None,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/receipts with optional filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created
        if was_paid is not None:
            params["was_paid"] = "true" if was_paid else "false"
        if was_shipped is not None:
            params["was_shipped"] = "true" if was_shipped else "false"
        return await self.client.get(f"/shops/{shop_id}/receipts", params=params)

    async def get(self, shop_id: int, receipt_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/receipts/{receipt_id}"""
        return await self.client.get(f"/shops/{shop_id}/receipts/{receipt_id}")

    async def list_by_buyer(
        self,
        shop_id: int,
        buyer_user_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List receipts filtered by buyer_user_id.

        [UNVERIFIED] Etsy's /shops/{shop_id}/receipts may not support a
        buyer_user_id query parameter directly. We attempt the query first;
        if Etsy ignores the filter, the tool layer should fall back to
        client-side filtering of list_by_shop results.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "buyer_user_id": buyer_user_id,
        }
        return await self.client.get(f"/shops/{shop_id}/receipts", params=params)

    # -------------------------------------------------------------------------
    # Receipts — write
    # -------------------------------------------------------------------------

    async def update(
        self,
        shop_id: int,
        receipt_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/receipts/{receipt_id} — fetch-merge-put.

        Etsy's receipt update endpoint accepts a small set of fields
        (gift note, message_from_seller, was_shipped, was_paid). The tool
        layer handles fetch-merge so the manager just sends the merged payload.
        """
        return await self.client.put(
            f"/shops/{shop_id}/receipts/{receipt_id}",
            json=updates,
            idempotent=True,
        )

    async def create_shipment(
        self,
        shop_id: int,
        receipt_id: int,
        *,
        tracking_code: str,
        carrier_name: str,
        send_bcc: bool = False,
        note_to_buyer: str | None = None,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/receipts/{receipt_id}/tracking.

        *** NON-IDEMPOTENT MONEY/BUYER-NOTIFICATION OPERATION ***

        This call:
        - Marks the receipt as shipped on Etsy
        - Triggers an automated email to the buyer with tracking info
        - Cannot be cleanly undone

        Uses client.post() (no auto-retry). On timeout/transport failure the
        client raises EtsyPossiblyCompletedError — the tool layer must NOT
        blindly retry. Verify state via receipts.get() before any retry.
        """
        payload: dict[str, Any] = {
            "tracking_code": tracking_code,
            "carrier_name": carrier_name,
            "send_bcc": send_bcc,
        }
        if note_to_buyer is not None:
            payload["note_to_buyer"] = note_to_buyer
        return await self.client.post(
            f"/shops/{shop_id}/receipts/{receipt_id}/tracking",
            json=payload,
        )

    # -------------------------------------------------------------------------
    # Transactions — read
    # -------------------------------------------------------------------------

    async def transactions_list_by_shop(
        self,
        shop_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/transactions"""
        return await self.client.get(
            f"/shops/{shop_id}/transactions",
            params={"limit": limit, "offset": offset},
        )

    async def transactions_list_by_receipt(
        self,
        shop_id: int,
        receipt_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/receipts/{receipt_id}/transactions"""
        return await self.client.get(
            f"/shops/{shop_id}/receipts/{receipt_id}/transactions"
        )

    async def transactions_list_by_listing(
        self,
        shop_id: int,
        listing_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/transactions"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/transactions",
            params={"limit": limit, "offset": offset},
        )

    async def transactions_get(
        self,
        shop_id: int,
        transaction_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/transactions/{transaction_id}"""
        return await self.client.get(
            f"/shops/{shop_id}/transactions/{transaction_id}"
        )

    # -------------------------------------------------------------------------
    # Refunds — read
    # -------------------------------------------------------------------------

    async def refunds_list_by_receipt(
        self,
        shop_id: int,
        receipt_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/receipts/{receipt_id}/payments.

        [UNVERIFIED] Refunds are surfaced inside the Payment objects on this
        endpoint (each payment carries a refunds array). There is no dedicated
        /refunds endpoint per Etsy v3 docs as of this writing.
        """
        return await self.client.get(
            f"/shops/{shop_id}/receipts/{receipt_id}/payments"
        )

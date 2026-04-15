"""Payment manager — wraps Etsy Payment + Ledger Entry endpoints (READ-ONLY).

8 read operations:
- get_by_receipt: GET /shops/{shop_id}/receipts/{receipt_id}/payments
- get_by_ledger_entry
- list (batch by payment_ids)
- ledger_entries_list
- ledger_entry_get
- ledger_entry_payments_get
- ledger_list_by_payment_account
- payment_account_summary

There are NO write operations on payments — Etsy does not let third-party apps
move money. This manager is intentionally read-only; the entire category is
guarded by the transactions_r scope.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class PaymentManager:
    """Manages Etsy Payment and Payment Ledger read operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Payments — read
    # -------------------------------------------------------------------------

    async def get_by_receipt(
        self,
        shop_id: int,
        receipt_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/receipts/{receipt_id}/payments"""
        return await self.client.get(
            f"/shops/{shop_id}/receipts/{receipt_id}/payments"
        )

    async def get_by_ledger_entry(
        self,
        shop_id: int,
        ledger_entry_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/payment-account/ledger-entries/{ledger_entry_id}/payments"""
        return await self.client.get(
            f"/shops/{shop_id}/payment-account/ledger-entries/{ledger_entry_id}/payments"
        )

    async def list_payments(
        self,
        shop_id: int,
        payment_ids: list[int],
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/payments?payment_ids=... (batch fetch)."""
        # Etsy expects a comma-separated list for the array param.
        joined = ",".join(str(pid) for pid in payment_ids)
        return await self.client.get(
            f"/shops/{shop_id}/payments",
            params={"payment_ids": joined},
        )

    # -------------------------------------------------------------------------
    # Ledger entries — read
    # -------------------------------------------------------------------------

    async def ledger_entries_list(
        self,
        shop_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
        min_created: int | None = None,
        max_created: int | None = None,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/payment-account/ledger-entries"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created
        return await self.client.get(
            f"/shops/{shop_id}/payment-account/ledger-entries",
            params=params,
        )

    async def ledger_entry_get(
        self,
        shop_id: int,
        ledger_entry_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/payment-account/ledger-entries/{ledger_entry_id}"""
        return await self.client.get(
            f"/shops/{shop_id}/payment-account/ledger-entries/{ledger_entry_id}"
        )

    async def ledger_entry_payments_get(
        self,
        shop_id: int,
        ledger_entry_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/payment-account/ledger-entries/{ledger_entry_id}/payments"""
        return await self.client.get(
            f"/shops/{shop_id}/payment-account/ledger-entries/{ledger_entry_id}/payments"
        )

    async def ledger_list_by_payment_account(
        self,
        shop_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List ledger entries for a payment account.

        [UNVERIFIED] This may be a duplicate of ledger_entries_list above; the
        Etsy docs are inconsistent about whether /payment-account/ledger-entries
        is the only entry point. This wrapper exists for API parity and forwards
        to the same endpoint with no extra filtering.
        """
        return await self.client.get(
            f"/shops/{shop_id}/payment-account/ledger-entries",
            params={"limit": limit, "offset": offset},
        )

    async def payment_account_summary(self, shop_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/payment-account.

        [UNVERIFIED] Etsy does not currently document a /payment-account
        summary endpoint in v3 — this may 404. If so, the tool layer surfaces
        EtsyResourceNotFound / EtsyEndpointRemoved cleanly.
        """
        return await self.client.get(f"/shops/{shop_id}/payment-account")

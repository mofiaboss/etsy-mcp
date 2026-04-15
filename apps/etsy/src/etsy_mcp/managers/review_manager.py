"""Review manager — wraps Etsy Review endpoints (read-only).

2 operations:
- list_by_shop: list reviews for a shop
- list_by_listing: list reviews for a listing

All operations return raw Etsy response dicts. Tool layer handles envelope
formatting. Reviews require the feedback_r OAuth scope.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class ReviewManager:
    """Manages Etsy Review (feedback) read operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    async def list_by_shop(
        self,
        shop_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/reviews"""
        return await self.client.get(
            f"/shops/{shop_id}/reviews",
            params={"limit": limit, "offset": offset},
        )

    async def list_by_listing(
        self,
        listing_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /listings/{listing_id}/reviews"""
        return await self.client.get(
            f"/listings/{listing_id}/reviews",
            params={"limit": limit, "offset": offset},
        )

"""Buyer manager — wraps Etsy buyer-side endpoints (favorites, cart, feedback).

6 operations:
- favorites_listings_list:   GET /users/{user_id}/favorites/listings
- favorites_listings_add:    POST /users/{user_id}/favorites/listings/{listing_id}
- favorites_listings_delete: DELETE /users/{user_id}/favorites/listings/{listing_id}
- cart_list:                 GET /users/{user_id}/carts  [UNVERIFIED — see tool docstring]
- feedback_received_list:    GET /users/{user_id}/feedback (received)
- feedback_given_list:       GET /users/{user_id}/feedback (given)

Scopes:
- favorites_r / favorites_w
- cart_r (if Etsy still exposes cart endpoints)
- feedback_r
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class BuyerManager:
    """Manages Etsy buyer-side operations: favorites, cart, feedback."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Favorites
    # -------------------------------------------------------------------------

    async def favorites_listings_list(
        self,
        user_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /users/{user_id}/favorites/listings"""
        return await self.client.get(
            f"/users/{user_id}/favorites/listings",
            params={"limit": limit, "offset": offset},
        )

    async def favorites_listings_add(
        self,
        user_id: int,
        listing_id: int,
    ) -> dict[str, Any]:
        """POST /users/{user_id}/favorites/listings/{listing_id}"""
        return await self.client.post(
            f"/users/{user_id}/favorites/listings/{listing_id}",
            json={},
        )

    async def favorites_listings_delete(
        self,
        user_id: int,
        listing_id: int,
    ) -> dict[str, Any]:
        """DELETE /users/{user_id}/favorites/listings/{listing_id}"""
        return await self.client.delete(
            f"/users/{user_id}/favorites/listings/{listing_id}"
        )

    # -------------------------------------------------------------------------
    # Cart [UNVERIFIED]
    # -------------------------------------------------------------------------

    async def cart_list(self, user_id: int) -> dict[str, Any]:
        """GET /users/{user_id}/carts.

        [UNVERIFIED] As of the v3 API rewrite, Etsy may have removed or
        restricted cart endpoints. If this 404s or returns insufficient_scope,
        document it in api-quirks.md and remove the tool.
        """
        return await self.client.get(f"/users/{user_id}/carts")

    # -------------------------------------------------------------------------
    # Feedback (received / given)
    # -------------------------------------------------------------------------

    async def feedback_received_list(
        self,
        user_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /users/{user_id}/feedback?type=received

        [UNVERIFIED] The exact query parameter name (`type` vs separate
        endpoints) varies across Etsy API generations. Confirm against
        live response and adjust if needed.
        """
        return await self.client.get(
            f"/users/{user_id}/feedback",
            params={"type": "received", "limit": limit, "offset": offset},
        )

    async def feedback_given_list(
        self,
        user_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /users/{user_id}/feedback?type=given

        [UNVERIFIED] See feedback_received_list note on parameter shape.
        """
        return await self.client.get(
            f"/users/{user_id}/feedback",
            params={"type": "given", "limit": limit, "offset": offset},
        )

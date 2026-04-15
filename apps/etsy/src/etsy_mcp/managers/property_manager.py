"""Property manager — wraps Etsy ListingProperty endpoints.

3 operations:
- list: list all properties on a listing
- update: fetch-merge-put a single property
- delete: delete a property from a listing

Managers return raw Etsy response dicts. Tool layer handles envelopes.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class PropertyManager:
    """Manages Etsy ListingProperty operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    async def list(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/properties"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/properties"
        )

    async def get_one(
        self,
        shop_id: int,
        listing_id: int,
        property_id: int,
    ) -> dict[str, Any] | None:
        """Helper: fetch a single property out of the list (Etsy has no GET-one endpoint)."""
        listing_props = await self.list(shop_id, listing_id)
        results = listing_props.get("results") or []
        for prop in results:
            if prop.get("property_id") == property_id:
                return prop
        return None

    async def update(
        self,
        shop_id: int,
        listing_id: int,
        property_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/listings/{listing_id}/properties/{property_id}.

        Fetch-merge-put: read the current property, layer caller updates on
        top, send the merged object back.
        """
        current = await self.get_one(shop_id, listing_id, property_id) or {}
        merged: dict[str, Any] = {**current, **updates}
        return await self.client.put(
            f"/shops/{shop_id}/listings/{listing_id}/properties/{property_id}",
            json=merged,
            idempotent=True,
        )

    async def delete(
        self,
        shop_id: int,
        listing_id: int,
        property_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/listings/{listing_id}/properties/{property_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/listings/{listing_id}/properties/{property_id}"
        )

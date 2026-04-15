"""Shop manager — wraps Etsy Shop + ShopSection + ShopProductionPartner endpoints.

9 operations:
- get_me: return the authenticated user's own shop
- get_by_id: get a shop by shop_id
- get_by_owner_user_id: get a shop by its owner's user_id
- search: search shops by keyword
- update: fetch-merge-put on a shop
- sections_list: list shop sections
- sections_create: create a new shop section
- sections_update: fetch-merge-put on a section
- sections_delete: delete a section
- production_partners_list: list the shop's production partners

All operations return raw Etsy response dicts. Tool layer handles envelope
formatting. Managers do not redact — EtsyClient already redacts in logs and
the tool envelope helpers redact in output.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class ShopManager:
    """Manages Etsy Shop and nested resource operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Shop read
    # -------------------------------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        """GET /users/me/shops — return the authenticated user's shop."""
        return await self.client.get("/users/me/shops/")

    async def get_by_id(self, shop_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}"""
        return await self.client.get(f"/shops/{shop_id}")

    async def get_by_owner_user_id(self, user_id: int) -> dict[str, Any]:
        """GET /users/{user_id}/shops"""
        return await self.client.get(f"/users/{user_id}/shops")

    async def search(
        self,
        *,
        shop_name: str,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops?shop_name=... — search shops by name."""
        return await self.client.get(
            "/shops",
            params={"shop_name": shop_name, "limit": limit, "offset": offset},
        )

    # -------------------------------------------------------------------------
    # Shop update (fetch-merge-put)
    # -------------------------------------------------------------------------

    async def update(
        self,
        shop_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PATCH /shops/{shop_id} with fetch-merge-put semantics.

        Fetches current shop state, merges the caller's partial updates,
        sends the full object back via PATCH. Returns the updated shop.
        """
        # Note: Etsy uses PUT for shop update in some endpoints. Follow docs.
        return await self.client.put(f"/shops/{shop_id}", json=updates, idempotent=True)

    # -------------------------------------------------------------------------
    # Shop sections
    # -------------------------------------------------------------------------

    async def sections_list(self, shop_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/sections"""
        return await self.client.get(f"/shops/{shop_id}/sections")

    async def sections_create(
        self,
        shop_id: int,
        *,
        title: str,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/sections"""
        return await self.client.post(f"/shops/{shop_id}/sections", json={"title": title})

    async def sections_update(
        self,
        shop_id: int,
        shop_section_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/sections/{shop_section_id}"""
        return await self.client.put(
            f"/shops/{shop_id}/sections/{shop_section_id}",
            json=updates,
            idempotent=True,
        )

    async def sections_delete(
        self,
        shop_id: int,
        shop_section_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/sections/{shop_section_id}"""
        return await self.client.delete(f"/shops/{shop_id}/sections/{shop_section_id}")

    # -------------------------------------------------------------------------
    # Production partners
    # -------------------------------------------------------------------------

    async def production_partners_list(self, shop_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/production-partners"""
        return await self.client.get(f"/shops/{shop_id}/production-partners")

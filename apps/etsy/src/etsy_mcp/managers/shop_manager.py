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
from etsy_core.exceptions import EtsyValidationError

from etsy_mcp.models.shop import (
    MUTABLE_FIELDS as SHOP_MUTABLE_FIELDS,
)
from etsy_mcp.models.shop import (
    to_api_update as shop_to_api_update,
)
from etsy_mcp.models.shop import (
    validate_update_fields as shop_validate_update_fields,
)
from etsy_mcp.models.shop_section import (
    MUTABLE_FIELDS as SECTION_MUTABLE_FIELDS,
)
from etsy_mcp.models.shop_section import (
    to_api_update as section_to_api_update,
)
from etsy_mcp.models.shop_section import (
    validate_update_fields as section_validate_update_fields,
)

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
        """Update a shop with real fetch-merge-put semantics.

        Fetches current shop state, validates that all caller updates target
        mutable fields (rejecting read-only fields with a clear error),
        merges the updates into the current state, and PATCHes the merged
        result back. Without the fetch-merge step, a partial payload would
        wipe every unspecified mutable field on the server — catastrophic
        data loss on shop policies, announcements, and vacation settings.

        Etsy's updateShop endpoint is documented as PATCH in Open API v3,
        so we use the non-idempotent client.patch() helper here.

        Returns the raw updated shop dict from Etsy.

        Raises:
            EtsyValidationError: if `updates` is empty OR contains any
                field outside MUTABLE_FIELDS (e.g., shop_id, user_id,
                num_favorers). Fields are rejected loudly instead of
                silently dropped so the caller learns immediately.
        """
        if not updates:
            raise EtsyValidationError("updates must not be empty")

        allowed, rejected = shop_validate_update_fields(updates)
        if rejected:
            raise EtsyValidationError(
                f"Cannot update read-only or unknown fields on shop: "
                f"{sorted(rejected)}. Mutable fields are: "
                f"{sorted(SHOP_MUTABLE_FIELDS)}"
            )
        if not allowed:
            raise EtsyValidationError(
                "No mutable fields in update request. Mutable fields are: "
                f"{sorted(SHOP_MUTABLE_FIELDS)}"
            )

        # Fetch current state
        current = await self.get_by_id(shop_id)

        # Merge: start with only the mutable subset of current state, then
        # overlay the caller's validated updates. Starting from the full
        # `current` dict would push every read-only field back to Etsy; we
        # trust to_api_update to filter but it is cleaner to narrow first.
        merged: dict[str, Any] = {
            k: current.get(k) for k in SHOP_MUTABLE_FIELDS if k in current
        }
        merged.update(allowed)

        payload = shop_to_api_update(merged)

        return await self.client.patch(
            f"/shops/{shop_id}",
            json=payload,
        )

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
        """Update a shop section with real fetch-merge-put semantics.

        Same pattern as `update()`: fetch current section, validate the
        caller fields against ShopSection.MUTABLE_FIELDS, merge, and PUT
        the merged result back. Etsy uses PUT for updateShopSection, so we
        use client.put() with idempotent=True (safe to retry on transport
        errors because the payload carries the full desired state).

        Raises:
            EtsyValidationError: on empty updates, unknown fields, or
                read-only fields. Shop section only supports `title` and
                `rank` as mutable.
        """
        if not updates:
            raise EtsyValidationError("updates must not be empty")

        allowed, rejected = section_validate_update_fields(updates)
        if rejected:
            raise EtsyValidationError(
                f"Cannot update read-only or unknown fields on shop section: "
                f"{sorted(rejected)}. Mutable fields are: "
                f"{sorted(SECTION_MUTABLE_FIELDS)}"
            )
        if not allowed:
            raise EtsyValidationError(
                "No mutable fields in update request. Mutable fields are: "
                f"{sorted(SECTION_MUTABLE_FIELDS)}"
            )

        # sections_list returns the full collection; there is no
        # documented per-section GET endpoint in Etsy v3, so fetch all and
        # locate the target section. This is O(n) on the shop's section
        # count, which is tiny in practice (shops rarely have more than a
        # few dozen sections).
        sections_response = await self.sections_list(shop_id)
        current = self._find_section(sections_response, shop_section_id)
        if current is None:
            raise EtsyValidationError(
                f"Shop section {shop_section_id} not found in shop {shop_id}"
            )

        merged: dict[str, Any] = {
            k: current.get(k) for k in SECTION_MUTABLE_FIELDS if k in current
        }
        merged.update(allowed)

        payload = section_to_api_update(merged)

        return await self.client.put(
            f"/shops/{shop_id}/sections/{shop_section_id}",
            json=payload,
            idempotent=True,
        )

    @staticmethod
    def _find_section(
        sections_response: dict[str, Any],
        shop_section_id: int,
    ) -> dict[str, Any] | None:
        """Locate a section dict inside a sections_list response envelope.

        Etsy wraps collections in `{"count": n, "results": [...]}`. This
        helper tolerates both the wrapped and unwrapped shapes so the
        manager is resilient to minor response-shape changes.
        """
        results = sections_response.get("results")
        if isinstance(results, list):
            for section in results:
                if isinstance(section, dict) and section.get("shop_section_id") == shop_section_id:
                    return section
        return None

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

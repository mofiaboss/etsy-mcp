"""Shipping manager — wraps Etsy ShippingProfile + nested resources.

13 operations:
- shipping_profiles_list / get / create / update / delete
- destinations_create / update / delete
- upgrades_create / update / delete
- carriers_list (public)
- origin_countries_list (public)

Shipping profiles have HIGH BLAST RADIUS: a single profile is referenced by
many listings. Updating cost or destinations changes the buyer-visible price
on EVERY listing using the profile, immediately. The tool layer is responsible
for surfacing the warning in the preview envelope.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class ShippingManager:
    """Manages Etsy ShippingProfile, ShippingDestination, ShippingUpgrade,
    plus public ShippingCarrier and Country lookups."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Shipping profiles
    # -------------------------------------------------------------------------

    async def profiles_list(self, shop_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/shipping-profiles"""
        return await self.client.get(f"/shops/{shop_id}/shipping-profiles")

    async def profiles_get(
        self,
        shop_id: int,
        shipping_profile_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/shipping-profiles/{shipping_profile_id}"""
        return await self.client.get(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}"
        )

    async def profiles_create(
        self,
        shop_id: int,
        *,
        title: str,
        origin_country_iso: str,
        primary_cost: float,
        secondary_cost: float,
        min_processing_time: int,
        max_processing_time: int,
        processing_time_unit: str = "business_days",
        destination_country_iso: str | None = None,
        destination_region: str = "none",
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/shipping-profiles"""
        payload: dict[str, Any] = {
            "title": title,
            "origin_country_iso": origin_country_iso,
            "primary_cost": primary_cost,
            "secondary_cost": secondary_cost,
            "min_processing_time": min_processing_time,
            "max_processing_time": max_processing_time,
            "processing_time_unit": processing_time_unit,
            "destination_region": destination_region,
        }
        if destination_country_iso is not None:
            payload["destination_country_iso"] = destination_country_iso
        return await self.client.post(
            f"/shops/{shop_id}/shipping-profiles",
            json=payload,
        )

    async def profiles_update(
        self,
        shop_id: int,
        shipping_profile_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/shipping-profiles/{shipping_profile_id}.

        High blast radius — every listing using this profile is affected.
        Tool layer must include the warning in the preview envelope.
        """
        return await self.client.put(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}",
            json=updates,
            idempotent=True,
        )

    async def profiles_delete(
        self,
        shop_id: int,
        shipping_profile_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/shipping-profiles/{shipping_profile_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}"
        )

    # -------------------------------------------------------------------------
    # Shipping profile destinations
    # -------------------------------------------------------------------------

    async def destinations_create(
        self,
        shop_id: int,
        shipping_profile_id: int,
        *,
        destination_country_iso: str | None = None,
        destination_region: str = "none",
        primary_cost: float | None = None,
        secondary_cost: float | None = None,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/shipping-profiles/{shipping_profile_id}/destinations"""
        payload: dict[str, Any] = {"destination_region": destination_region}
        if destination_country_iso is not None:
            payload["destination_country_iso"] = destination_country_iso
        if primary_cost is not None:
            payload["primary_cost"] = primary_cost
        if secondary_cost is not None:
            payload["secondary_cost"] = secondary_cost
        return await self.client.post(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}/destinations",
            json=payload,
        )

    async def destinations_update(
        self,
        shop_id: int,
        shipping_profile_id: int,
        destination_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/shipping-profiles/{shipping_profile_id}/destinations/{destination_id}"""
        return await self.client.put(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}/destinations/{destination_id}",
            json=updates,
            idempotent=True,
        )

    async def destinations_delete(
        self,
        shop_id: int,
        shipping_profile_id: int,
        destination_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/shipping-profiles/{shipping_profile_id}/destinations/{destination_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}/destinations/{destination_id}"
        )

    # -------------------------------------------------------------------------
    # Shipping profile upgrades
    # -------------------------------------------------------------------------

    async def upgrades_create(
        self,
        shop_id: int,
        shipping_profile_id: int,
        *,
        type: str,
        upgrade_name: str,
        price: float,
        secondary_price: float,
        shipping_carrier_id: int | None = None,
        mail_class: str | None = None,
        min_delivery_days: int | None = None,
        max_delivery_days: int | None = None,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/shipping-profiles/{shipping_profile_id}/upgrades"""
        payload: dict[str, Any] = {
            "type": type,
            "upgrade_name": upgrade_name,
            "price": price,
            "secondary_price": secondary_price,
        }
        if shipping_carrier_id is not None:
            payload["shipping_carrier_id"] = shipping_carrier_id
        if mail_class is not None:
            payload["mail_class"] = mail_class
        if min_delivery_days is not None:
            payload["min_delivery_days"] = min_delivery_days
        if max_delivery_days is not None:
            payload["max_delivery_days"] = max_delivery_days
        return await self.client.post(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}/upgrades",
            json=payload,
        )

    async def upgrades_update(
        self,
        shop_id: int,
        shipping_profile_id: int,
        upgrade_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/shipping-profiles/{shipping_profile_id}/upgrades/{upgrade_id}"""
        return await self.client.put(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}/upgrades/{upgrade_id}",
            json=updates,
            idempotent=True,
        )

    async def upgrades_delete(
        self,
        shop_id: int,
        shipping_profile_id: int,
        upgrade_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/shipping-profiles/{shipping_profile_id}/upgrades/{upgrade_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/shipping-profiles/{shipping_profile_id}/upgrades/{upgrade_id}"
        )

    # -------------------------------------------------------------------------
    # Public lookups (no auth scope needed)
    # -------------------------------------------------------------------------

    async def carriers_list(self, origin_country_iso: str) -> dict[str, Any]:
        """GET /shipping-carriers?origin_country_iso=...

        [UNVERIFIED] Public endpoint per Etsy v3; may not require shops_w but
        still consumes a daily-budget unit. Tool layer guards under shops_r.
        """
        return await self.client.get(
            "/shipping-carriers",
            params={"origin_country_iso": origin_country_iso},
        )

    async def origin_countries_list(self) -> dict[str, Any]:
        """GET /countries — list of supported shipping origin countries.

        [UNVERIFIED] Etsy may publish this under a different path
        (e.g., /shipping-carriers does not return countries directly).
        If 404, the tool will surface EtsyEndpointRemoved cleanly.
        """
        return await self.client.get("/countries")

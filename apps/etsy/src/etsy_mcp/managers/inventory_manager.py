"""Inventory manager — wraps Etsy ListingInventory + Product + Offering endpoints.

5 operations:
- get: fetch full inventory tree for a listing
- update: fetch-merge-PUT on inventory with 6-tuple identity key for offering merging
- get_product: fetch a specific product
- get_offering: fetch a specific product offering
- update_offering_quantity: convenience wrapper that does get -> modify -> put

The 6-tuple identity key (sku, property_values_sorted, quantity, price, is_enabled,
offering_id) prevents collapsing distinct offerings that happen to share some
fields. Critical for variation-heavy listings (e.g. MX/SRV-style multi-axis).

Managers return raw Etsy response dicts. Tool layer handles envelopes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


def _offering_identity_key(offering: dict[str, Any]) -> tuple:
    """Build a 6-tuple identity for an offering used to detect duplicates during merge.

    Components (in order):
    - sku (str | None)
    - property_values_sorted (tuple of (property_id, value_id) sorted)
    - quantity (int | None)
    - price (str — Etsy returns Money object; we serialize to str for hashing)
    - is_enabled (bool | None)
    - offering_id (int | None) — last to allow None to collapse with future writes
    """
    sku = offering.get("sku")
    pv_raw = offering.get("property_values") or []
    pv_pairs = []
    for pv in pv_raw:
        pid = pv.get("property_id")
        vids = pv.get("value_ids") or []
        for vid in vids:
            pv_pairs.append((pid, vid))
    pv_sorted = tuple(sorted(pv_pairs))

    qty = offering.get("quantity")
    price = offering.get("price")
    if isinstance(price, dict):
        price_key = json.dumps(price, sort_keys=True)
    else:
        price_key = str(price) if price is not None else None
    is_enabled = offering.get("is_enabled")
    offering_id = offering.get("offering_id") or offering.get("product_offering_id")
    return (sku, pv_sorted, qty, price_key, is_enabled, offering_id)


def _product_identity_key(product: dict[str, Any]) -> tuple:
    """Build a stable identity for a product based on sku + property_values."""
    sku = product.get("sku")
    pv_raw = product.get("property_values") or []
    pv_pairs = []
    for pv in pv_raw:
        pid = pv.get("property_id")
        vids = pv.get("value_ids") or []
        for vid in vids:
            pv_pairs.append((pid, vid))
    pv_sorted = tuple(sorted(pv_pairs))
    return (sku, pv_sorted, product.get("product_id"))


class InventoryManager:
    """Manages Etsy ListingInventory + Product + Offering operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    async def get(self, listing_id: int) -> dict[str, Any]:
        """GET /listings/{listing_id}/inventory"""
        return await self.client.get(f"/listings/{listing_id}/inventory")

    async def get_product(self, listing_id: int, product_id: int) -> dict[str, Any]:
        """GET /listings/{listing_id}/inventory/products/{product_id}"""
        return await self.client.get(
            f"/listings/{listing_id}/inventory/products/{product_id}"
        )

    async def get_offering(
        self,
        listing_id: int,
        product_id: int,
        product_offering_id: int,
    ) -> dict[str, Any]:
        """GET /listings/{listing_id}/inventory/products/{product_id}/offerings/{product_offering_id}"""
        return await self.client.get(
            f"/listings/{listing_id}/inventory/products/{product_id}/offerings/{product_offering_id}"
        )

    async def update(
        self,
        listing_id: int,
        inventory: dict[str, Any],
    ) -> dict[str, Any]:
        """PUT /listings/{listing_id}/inventory with fetch-merge-put semantics.

        Fetches current inventory, merges caller's partial product/offering
        updates using a 6-tuple identity key on offerings to avoid collapsing
        distinct variation rows. Sends the full inventory document back.
        """
        current = await self.get(listing_id)
        current_products: list[dict[str, Any]] = list(current.get("products") or [])
        incoming_products: list[dict[str, Any]] = list(inventory.get("products") or [])

        # Index current products by identity key
        current_by_key: dict[tuple, dict[str, Any]] = {}
        for prod in current_products:
            current_by_key[_product_identity_key(prod)] = prod

        merged_products: list[dict[str, Any]] = []
        seen_keys: set[tuple] = set()

        for inc_prod in incoming_products:
            key = _product_identity_key(inc_prod)
            base = current_by_key.get(key)
            if base is None:
                # New product, take incoming as-is
                merged_products.append(inc_prod)
                seen_keys.add(key)
                continue

            seen_keys.add(key)
            merged: dict[str, Any] = {**base, **inc_prod}

            # Merge offerings using 6-tuple identity
            base_offerings = base.get("offerings") or []
            inc_offerings = inc_prod.get("offerings") or []
            base_off_by_key: dict[tuple, dict[str, Any]] = {
                _offering_identity_key(o): o for o in base_offerings
            }
            merged_offerings: list[dict[str, Any]] = []
            seen_off_keys: set[tuple] = set()

            for inc_off in inc_offerings:
                ok = _offering_identity_key(inc_off)
                base_off = base_off_by_key.get(ok)
                if base_off is None:
                    merged_offerings.append(inc_off)
                else:
                    merged_offerings.append({**base_off, **inc_off})
                seen_off_keys.add(ok)

            # Carry over base offerings the caller did not touch
            for ok, base_off in base_off_by_key.items():
                if ok not in seen_off_keys:
                    merged_offerings.append(base_off)

            merged["offerings"] = merged_offerings
            merged_products.append(merged)

        # Carry over current products the caller did not touch
        for key, prod in current_by_key.items():
            if key not in seen_keys:
                merged_products.append(prod)

        payload: dict[str, Any] = {"products": merged_products}
        # Pass through top-level inventory hints if caller supplied them
        for k in ("price_on_property", "quantity_on_property", "sku_on_property"):
            if k in inventory:
                payload[k] = inventory[k]
            elif k in current:
                payload[k] = current[k]

        return await self.client.put(
            f"/listings/{listing_id}/inventory",
            json=payload,
            idempotent=True,
        )

    async def update_offering_quantity(
        self,
        listing_id: int,
        product_id: int,
        offering_id: int,
        quantity: int,
    ) -> dict[str, Any]:
        """Convenience: get -> modify single offering quantity -> put.

        Uses the full-inventory fetch-merge-put path so the 6-tuple identity
        merge protects every other offering.
        """
        current = await self.get(listing_id)
        partial: dict[str, Any] = {"products": []}

        for prod in current.get("products") or []:
            if prod.get("product_id") != product_id:
                continue
            patched_offerings: list[dict[str, Any]] = []
            for off in prod.get("offerings") or []:
                off_id = off.get("offering_id") or off.get("product_offering_id")
                if off_id == offering_id:
                    patched_offerings.append({**off, "quantity": int(quantity)})
                else:
                    patched_offerings.append(off)
            partial["products"].append({**prod, "offerings": patched_offerings})
            break

        if not partial["products"]:
            raise ValueError(
                f"product_id={product_id} not found on listing {listing_id}"
            )

        return await self.update(listing_id, partial)

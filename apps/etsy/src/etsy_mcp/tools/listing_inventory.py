"""MCP tool module: listing_inventory category.

5 tools:
- etsy_listing_inventory_get
- etsy_listing_inventory_update                        (fetch-merge-put with 6-tuple identity)
- etsy_listing_inventory_get_product
- etsy_listing_inventory_get_offering
- etsy_listing_inventory_update_offering_quantity      (convenience get -> modify -> put)

The update path uses InventoryManager's 6-tuple offering identity
(sku, property_values_sorted, quantity, price, is_enabled, offering_id) so
distinct variation rows are never collapsed during merge — critical for
multi-axis variation listings.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_inventory_manager, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_inventory_get",
    description="Get the full inventory tree for a listing — products, offerings, prices, quantities, "
    "SKUs, and property values. Use this before any update to see the current state.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_inventory",
    permission_action="READ",
)
async def etsy_listing_inventory_get(listing_id: int) -> dict[str, Any]:
    """Get the inventory document for a listing."""
    try:
        manager = get_inventory_manager()
        data = await manager.get(listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_inventory_get(%s) failed: %s", listing_id, exc, exc_info=True)
        return error_envelope(f"Failed to get inventory for listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid listing_id: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_inventory_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_inventory_get_product",
    description="Get a single inventory product by product_id within a listing.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_inventory",
    permission_action="READ",
)
async def etsy_listing_inventory_get_product(
    listing_id: int,
    product_id: int,
) -> dict[str, Any]:
    """Get a specific product from a listing's inventory."""
    try:
        manager = get_inventory_manager()
        data = await manager.get_product(listing_id, product_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_inventory_get_product failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to get product {product_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_inventory_get_product unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_inventory_get_offering",
    description="Get a single product offering by offering_id within a listing's product.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_inventory",
    permission_action="READ",
)
async def etsy_listing_inventory_get_offering(
    listing_id: int,
    product_id: int,
    product_offering_id: int,
) -> dict[str, Any]:
    """Get a specific offering."""
    try:
        manager = get_inventory_manager()
        data = await manager.get_offering(listing_id, product_id, product_offering_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_inventory_get_offering failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to get offering {product_offering_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_inventory_get_offering unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_inventory_update",
    description="Update a listing's inventory using fetch-merge-put. Pass a partial inventory dict "
    "with the products/offerings you want to change — current state is preserved for everything else. "
    "Offering merging uses a 6-tuple identity (sku, property_values, quantity, price, is_enabled, "
    "offering_id) so distinct variations are never collapsed. With confirm=False (default), returns a "
    "preview. With confirm=True, executes the PUT.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_inventory",
    permission_action="UPDATE",
)
async def etsy_listing_inventory_update(
    listing_id: int,
    inventory: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update inventory with fetch-merge-put + preview."""
    try:
        if not inventory:
            return error_envelope("inventory must not be empty")
        if "products" not in inventory:
            return error_envelope("inventory must contain a 'products' key")

        manager = get_inventory_manager()

        if not confirm:
            current = await manager.get(listing_id)
            current_product_ids = [
                p.get("product_id") for p in (current.get("products") or [])
            ]
            proposed_product_count = len(inventory.get("products") or [])
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "listing_inventory",
                "resource_id": str(listing_id),
                "preview": {
                    "current": {
                        "product_count": len(current_product_ids),
                        "product_ids": current_product_ids,
                    },
                    "proposed": {
                        "products_to_modify_or_add": proposed_product_count,
                        "raw": inventory,
                    },
                },
                "warnings": [
                    "Merging uses 6-tuple offering identity — variations with distinct "
                    "(sku, property_values, quantity, price, is_enabled, offering_id) will NOT collapse."
                ],
                "message": (
                    f"Will update inventory for listing {listing_id} "
                    f"({proposed_product_count} product entries). Set confirm=true to execute."
                ),
            }

        data = await manager.update(listing_id, inventory)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_inventory_update failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to update inventory: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid inventory payload: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_inventory_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_inventory_update_offering_quantity",
    description="Convenience: update the quantity of a single product offering. Performs "
    "get -> modify -> put on the full inventory document so the 6-tuple identity merge protects "
    "every other offering. With confirm=False (default), returns a preview. With confirm=True, executes.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_inventory",
    permission_action="UPDATE",
)
async def etsy_listing_inventory_update_offering_quantity(
    listing_id: int,
    product_id: int,
    offering_id: int,
    quantity: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a single offering's quantity."""
    try:
        if quantity < 0:
            return error_envelope("quantity must be >= 0")

        manager = get_inventory_manager()

        if not confirm:
            try:
                current_offering = await manager.get_offering(
                    listing_id, product_id, offering_id
                )
                current_qty = current_offering.get("quantity")
            except EtsyError:
                current_offering = None
                current_qty = None
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "listing_offering",
                "resource_id": str(offering_id),
                "preview": {
                    "current": {"quantity": current_qty},
                    "proposed": {"quantity": quantity},
                },
                "message": (
                    f"Will update offering {offering_id} (product {product_id}, listing "
                    f"{listing_id}) quantity from {current_qty} to {quantity}. "
                    f"Set confirm=true to execute."
                ),
            }

        data = await manager.update_offering_quantity(
            listing_id, product_id, offering_id, quantity
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_inventory_update_offering_quantity failed: %s",
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to update offering quantity: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error(
            "etsy_listing_inventory_update_offering_quantity unexpected error",
            exc_info=True,
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

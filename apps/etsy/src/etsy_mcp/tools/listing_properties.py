"""MCP tool module: listing_properties category.

3 tools:
- etsy_listing_properties_list
- etsy_listing_properties_update   (fetch-merge-put + preview + confirm)
- etsy_listing_properties_delete   (destructive + confirm)
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_property_manager, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Read tool
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_properties_list",
    description="List all attribute properties on an Etsy listing (color, material, size, etc.). "
    "Returns property_id, property_name, scale_id, scale_name, value_ids, and values.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_properties",
    permission_action="READ",
)
async def etsy_listing_properties_list(
    shop_id: int,
    listing_id: int,
) -> dict[str, Any]:
    """List properties on a listing."""
    try:
        manager = get_property_manager()
        data = await manager.list(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_properties_list(%s, %s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to list properties: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_properties_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_properties_update",
    description="Update a single attribute property on a listing. Uses fetch-merge-put — pass only the "
    "fields you want to change, current values are preserved. With confirm=False (default), returns a "
    "preview showing current vs proposed. With confirm=True, executes the PUT.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_properties",
    permission_action="UPDATE",
)
async def etsy_listing_properties_update(
    shop_id: int,
    listing_id: int,
    property_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a property with fetch-merge-put + preview."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_property_manager()

        if not confirm:
            current = await manager.get_one(shop_id, listing_id, property_id)
            current_relevant = (
                {k: current.get(k) for k in updates.keys()} if current else None
            )
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "listing_property",
                "resource_id": str(property_id),
                "preview": {
                    "current": current_relevant,
                    "proposed": updates,
                },
                "message": (
                    f"Will update property {property_id} on listing {listing_id} "
                    f"({', '.join(updates.keys())}). Set confirm=true to execute."
                ),
            }

        data = await manager.update(shop_id, listing_id, property_id, updates)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_properties_update failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to update property: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid update payload: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_properties_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_properties_delete",
    description="Delete an attribute property from a listing. DESTRUCTIVE — the property is removed. "
    "Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_properties",
    permission_action="DELETE",
)
async def etsy_listing_properties_delete(
    shop_id: int,
    listing_id: int,
    property_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a listing property."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "listing_property",
                "resource_id": str(property_id),
                "warnings": [
                    "Removing a required property may cause the listing to fail validation."
                ],
                "message": (
                    f"Will DELETE property {property_id} from listing {listing_id}. "
                    f"This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_property_manager()
        data = await manager.delete(shop_id, listing_id, property_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_properties_delete failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to delete property: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_properties_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

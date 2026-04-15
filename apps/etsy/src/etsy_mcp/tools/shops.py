"""MCP tool module: shops category.

10 tools:
- etsy_shops_get_me
- etsy_shops_get_by_id
- etsy_shops_get_by_owner_user_id
- etsy_shops_search
- etsy_shops_update
- etsy_shop_sections_list
- etsy_shop_sections_create
- etsy_shop_sections_update
- etsy_shop_sections_delete
- etsy_shop_production_partners_list

All tools are thin wrappers: validate args → delegate to ShopManager →
format envelope → return. Exceptions are caught and returned as error envelopes.

Pattern reference: unifi-mcp/apps/network/src/unifi_network_mcp/tools/clients.py
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_server, get_shop_manager
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()

# -----------------------------------------------------------------------------
# Read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shops_get_me",
    description="Get the authenticated user's own Etsy shop. Returns shop_id, shop_name, "
    "url, listing counts, and other shop metadata. Use this first to verify auth is working "
    "and to discover the shop_id for subsequent calls.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True,
    ),
    permission_category="shops",
    permission_action="READ",
)
async def etsy_shops_get_me() -> dict[str, Any]:
    """Get the authenticated user's shop."""
    try:
        manager = get_shop_manager()
        data = await manager.get_me()
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shops_get_me failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to get current shop: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shops_get_me unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error getting current shop: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shops_get_by_id",
    description="Get an Etsy shop by its shop_id. Returns full shop metadata.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shops",
    permission_action="READ",
)
async def etsy_shops_get_by_id(shop_id: int) -> dict[str, Any]:
    """Get a shop by shop_id."""
    try:
        manager = get_shop_manager()
        data = await manager.get_by_id(shop_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shops_get_by_id(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to get shop {shop_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid shop_id: {exc}")
    except Exception as exc:
        logger.error("etsy_shops_get_by_id unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shops_get_by_owner_user_id",
    description="Get an Etsy shop by its owner's user_id. Useful when you know the user but not the shop.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shops",
    permission_action="READ",
)
async def etsy_shops_get_by_owner_user_id(user_id: int) -> dict[str, Any]:
    """Get a shop by owner user_id."""
    try:
        manager = get_shop_manager()
        data = await manager.get_by_owner_user_id(user_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shops_get_by_owner_user_id(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(f"Failed to get shop for user {user_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shops_get_by_owner_user_id unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shops_search",
    description="Search Etsy shops by name keyword. Returns a paginated list of matching shops. "
    "Use limit + offset for pagination. Max limit is 100.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shops",
    permission_action="READ",
)
async def etsy_shops_search(
    shop_name: str,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Search shops by name."""
    try:
        if not shop_name or not shop_name.strip():
            return error_envelope("shop_name must not be empty")
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_shop_manager()
        data = await manager.search(shop_name=shop_name.strip(), limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shops_search failed: %s", exc, exc_info=True)
        return error_envelope(f"Shop search failed: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shops_search unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shop_sections_list",
    description="List all sections within an Etsy shop. Sections organize listings into groups.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shops",
    permission_action="READ",
)
async def etsy_shop_sections_list(shop_id: int) -> dict[str, Any]:
    """List shop sections."""
    try:
        manager = get_shop_manager()
        data = await manager.sections_list(shop_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shop_sections_list(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to list sections for shop {shop_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shop_sections_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shop_production_partners_list",
    description="List all production partners for an Etsy shop. Production partners are third-party "
    "manufacturers a shop uses (relevant for shops that don't produce items themselves).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shops",
    permission_action="READ",
)
async def etsy_shop_production_partners_list(shop_id: int) -> dict[str, Any]:
    """List production partners."""
    try:
        manager = get_shop_manager()
        data = await manager.production_partners_list(shop_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shop_production_partners_list(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to list production partners for shop {shop_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shop_production_partners_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools (with preview-then-confirm)
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shops_update",
    description="Update an Etsy shop's mutable fields. Pass only the fields you want to change — "
    "current values are automatically preserved (fetch-merge-put pattern). "
    "With confirm=False (default), returns a preview showing current vs proposed state. "
    "With confirm=True, executes the update.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shops",
    permission_action="UPDATE",
)
async def etsy_shops_update(
    shop_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a shop with fetch-merge-put + preview."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_shop_manager()

        if not confirm:
            # Preview: fetch current state, show diff
            current = await manager.get_by_id(shop_id)
            current_relevant = {k: current.get(k) for k in updates.keys()}
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "shop",
                "resource_id": str(shop_id),
                "preview": {
                    "current": current_relevant,
                    "proposed": updates,
                },
                "message": f"Will update {', '.join(updates.keys())} on shop {shop_id}. Set confirm=true to execute.",
            }

        data = await manager.update(shop_id, updates)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shops_update(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to update shop {shop_id}: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shops_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shop_sections_create",
    description="Create a new section in an Etsy shop. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="shops",
    permission_action="CREATE",
)
async def etsy_shop_sections_create(
    shop_id: int,
    title: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a shop section."""
    try:
        if not title or not title.strip():
            return error_envelope("title must not be empty")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "shop_section",
                "resource_id": "(new)",
                "preview": {
                    "current": None,
                    "proposed": {"shop_id": shop_id, "title": title.strip()},
                },
                "message": (
                    f"Will create shop section '{title.strip()}' in shop {shop_id}. "
                    "Set confirm=true to execute."
                ),
            }

        manager = get_shop_manager()
        data = await manager.sections_create(shop_id, title=title.strip())
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shop_sections_create failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to create shop section: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shop_sections_create unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shop_sections_update",
    description="Update a shop section. Uses fetch-merge-put. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shops",
    permission_action="UPDATE",
)
async def etsy_shop_sections_update(
    shop_id: int,
    shop_section_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a shop section."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_shop_manager()

        if not confirm:
            # Preview: fetch current sections, locate this one, show diff.
            sections = await manager.sections_list(shop_id)
            current_section: dict[str, Any] | None = None
            results = sections.get("results") if isinstance(sections, dict) else None
            if isinstance(results, list):
                for section in results:
                    if (
                        isinstance(section, dict)
                        and section.get("shop_section_id") == shop_section_id
                    ):
                        current_section = section
                        break
            current_relevant = (
                {k: current_section.get(k) for k in updates.keys()}
                if current_section is not None
                else None
            )
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "shop_section",
                "resource_id": str(shop_section_id),
                "preview": {
                    "current": current_relevant,
                    "proposed": updates,
                },
                "message": f"Will update section {shop_section_id}. Set confirm=true to execute.",
            }

        data = await manager.sections_update(shop_id, shop_section_id, updates)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shop_sections_update failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to update shop section: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shop_sections_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shop_sections_delete",
    description="Delete a shop section. DESTRUCTIVE — existing listings in this section will be "
    "unlinked (but not deleted). Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shops",
    permission_action="DELETE",
)
async def etsy_shop_sections_delete(
    shop_id: int,
    shop_section_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a shop section."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "shop_section",
                "resource_id": str(shop_section_id),
                "warnings": ["Listings currently in this section will be unlinked but not deleted."],
                "message": (
                    f"Will DELETE shop section {shop_section_id}. "
                    "This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_shop_manager()
        data = await manager.sections_delete(shop_id, shop_section_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shop_sections_delete failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to delete shop section: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shop_sections_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

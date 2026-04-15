"""MCP tool module: buyer category (favorites, cart, feedback).

6 tools:
- etsy_favorites_listings_list   (favorites_r)
- etsy_favorites_listings_add    (favorites_w, confirm required)
- etsy_favorites_listings_delete (favorites_w, destructive, confirm required)
- etsy_cart_list                 (cart_r) [UNVERIFIED]
- etsy_feedback_received_list    (feedback_r) [UNVERIFIED]
- etsy_feedback_given_list       (feedback_r) [UNVERIFIED]
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_buyer_manager, get_client, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Favorites — read
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_favorites_listings_list",
    description="List a user's favorited listings. Requires the favorites_r OAuth scope. Use limit + "
    "offset for pagination (max limit 100).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="buyer",
    permission_action="READ",
)
async def etsy_favorites_listings_list(
    user_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List favorited listings."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_buyer_manager()
        data = await manager.favorites_listings_list(user_id, limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_favorites_listings_list(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(f"Failed to list favorites for user {user_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_favorites_listings_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Favorites — write
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_favorites_listings_add",
    description="Add a listing to a user's favorites. Requires the favorites_w OAuth scope. "
    "With confirm=False (default), returns a preview. With confirm=True, executes the favorite.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="buyer",
    permission_action="CREATE",
)
async def etsy_favorites_listings_add(
    user_id: int,
    listing_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Favorite a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "favorite_listing",
                "resource_id": str(listing_id),
                "preview": {
                    "current": None,
                    "proposed": {"user_id": user_id, "listing_id": listing_id},
                },
                "message": (
                    f"Will favorite listing {listing_id} for user {user_id}. "
                    "Set confirm=true to execute."
                ),
            }

        manager = get_buyer_manager()
        data = await manager.favorites_listings_add(user_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_favorites_listings_add(%s, %s) failed: %s",
            user_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to favorite listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_favorites_listings_add unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_favorites_listings_delete",
    description="Remove a listing from a user's favorites. DESTRUCTIVE — the favorite entry is removed "
    "and cannot be undone (only re-added). Requires the favorites_w OAuth scope. With confirm=False "
    "(default), returns a preview. With confirm=True, executes the deletion.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="buyer",
    permission_action="DELETE",
)
async def etsy_favorites_listings_delete(
    user_id: int,
    listing_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Unfavorite a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "favorite_listing",
                "resource_id": str(listing_id),
                "warnings": [
                    "The favorite entry will be removed. Re-add via etsy_favorites_listings_add.",
                ],
                "preview": {"user_id": user_id, "listing_id": listing_id},
                "message": (
                    f"Will REMOVE favorite for listing {listing_id} (user {user_id}). "
                    "Set confirm=true to execute."
                ),
            }

        manager = get_buyer_manager()
        data = await manager.favorites_listings_delete(user_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_favorites_listings_delete(%s, %s) failed: %s",
            user_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to remove favorite listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_favorites_listings_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Cart [UNVERIFIED]
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_cart_list",
    description="List the contents of a user's cart. [UNVERIFIED] Etsy may have removed or restricted "
    "cart endpoints in the v3 API rewrite — this tool may 404 or require a scope that is no longer "
    "issued. If it fails, document the quirk in api-quirks.md and remove this tool. Requires the "
    "cart_r OAuth scope (if still supported).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="buyer",
    permission_action="READ",
)
async def etsy_cart_list(user_id: int) -> dict[str, Any]:
    """List a user's cart contents."""
    try:
        manager = get_buyer_manager()
        data = await manager.cart_list(user_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_cart_list(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(
            f"Failed to list cart for user {user_id}: {exc.message} "
            "(cart endpoints may not exist in the current Etsy v3 API)"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid user_id: {exc}")
    except Exception as exc:
        logger.error("etsy_cart_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Feedback (received / given)
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_feedback_received_list",
    description="List feedback entries RECEIVED by a user (as a seller or buyer counterpart). "
    "[UNVERIFIED] Etsy's feedback endpoint shape (single endpoint with type filter vs separate "
    "endpoints) may differ from this implementation — confirm against live response. Requires the "
    "feedback_r OAuth scope. Use limit + offset for pagination.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="buyer",
    permission_action="READ",
)
async def etsy_feedback_received_list(
    user_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List feedback received by a user."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_buyer_manager()
        data = await manager.feedback_received_list(user_id, limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_feedback_received_list(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(
            f"Failed to list received feedback for user {user_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_feedback_received_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_feedback_given_list",
    description="List feedback entries GIVEN by a user. [UNVERIFIED] See etsy_feedback_received_list "
    "for caveats on the feedback endpoint shape. Requires the feedback_r OAuth scope. Use limit + "
    "offset for pagination.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="buyer",
    permission_action="READ",
)
async def etsy_feedback_given_list(
    user_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List feedback given by a user."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_buyer_manager()
        data = await manager.feedback_given_list(user_id, limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_feedback_given_list(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(
            f"Failed to list given feedback for user {user_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_feedback_given_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

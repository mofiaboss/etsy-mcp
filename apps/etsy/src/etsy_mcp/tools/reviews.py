"""MCP tool module: reviews category.

2 tools (read-only, requires feedback_r scope):
- etsy_reviews_list_by_shop
- etsy_reviews_list_by_listing
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_review_manager, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


@server.tool(
    name="etsy_reviews_list_by_shop",
    description="List reviews (feedback) left for an Etsy shop. Returns paginated review entries with "
    "rating, message, language, and creation timestamps. Requires the feedback_r OAuth scope. "
    "Use limit + offset for pagination (max limit 100).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="reviews",
    permission_action="READ",
)
async def etsy_reviews_list_by_shop(
    shop_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List reviews for a shop."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_review_manager()
        data = await manager.list_by_shop(shop_id, limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_reviews_list_by_shop(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to list reviews for shop {shop_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_reviews_list_by_shop unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_reviews_list_by_listing",
    description="List reviews (feedback) left for a specific Etsy listing. Returns paginated review "
    "entries with rating, message, language, and creation timestamps. Requires the feedback_r OAuth "
    "scope. Use limit + offset for pagination (max limit 100).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="reviews",
    permission_action="READ",
)
async def etsy_reviews_list_by_listing(
    listing_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List reviews for a listing."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_review_manager()
        data = await manager.list_by_listing(listing_id, limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_reviews_list_by_listing(%s) failed: %s", listing_id, exc, exc_info=True)
        return error_envelope(f"Failed to list reviews for listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_reviews_list_by_listing unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")

"""MCP tool module: taxonomy category.

5 tools (PUBLIC, no auth scope required):
- etsy_buyer_taxonomy_nodes_list
- etsy_buyer_taxonomy_node_properties_get
- etsy_seller_taxonomy_nodes_list
- etsy_seller_taxonomy_node_properties_get
- etsy_taxonomy_node_search (client-side helper)
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_server, get_taxonomy_manager
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


@server.tool(
    name="etsy_buyer_taxonomy_nodes_list",
    description="List the entire Etsy buyer taxonomy tree. Returns hierarchical category nodes used "
    "for buyer-side browsing. Public endpoint — no OAuth scope required. Result can be large; "
    "consider etsy_taxonomy_node_search for targeted lookups.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="taxonomy",
    permission_action="READ",
)
async def etsy_buyer_taxonomy_nodes_list() -> dict[str, Any]:
    """List buyer taxonomy nodes."""
    try:
        manager = get_taxonomy_manager()
        data = await manager.buyer_nodes_list()
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_buyer_taxonomy_nodes_list failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to list buyer taxonomy: {exc.message}")
    except Exception as exc:
        logger.error("etsy_buyer_taxonomy_nodes_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_buyer_taxonomy_node_properties_get",
    description="Get the property definitions for a specific buyer taxonomy node. Returns the list of "
    "properties (e.g., color, size) that apply to listings under this category. Public endpoint.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="taxonomy",
    permission_action="READ",
)
async def etsy_buyer_taxonomy_node_properties_get(taxonomy_id: int) -> dict[str, Any]:
    """Get buyer taxonomy node properties."""
    try:
        manager = get_taxonomy_manager()
        data = await manager.buyer_node_properties_get(taxonomy_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_buyer_taxonomy_node_properties_get(%s) failed: %s", taxonomy_id, exc, exc_info=True
        )
        return error_envelope(
            f"Failed to get buyer taxonomy properties for {taxonomy_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid taxonomy_id: {exc}")
    except Exception as exc:
        logger.error("etsy_buyer_taxonomy_node_properties_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_seller_taxonomy_nodes_list",
    description="List the entire Etsy seller taxonomy tree. Returns hierarchical category nodes used "
    "when creating/categorizing listings. Public endpoint — no OAuth scope required. The result can be "
    "very large; prefer etsy_taxonomy_node_search to find a specific category.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="taxonomy",
    permission_action="READ",
)
async def etsy_seller_taxonomy_nodes_list() -> dict[str, Any]:
    """List seller taxonomy nodes."""
    try:
        manager = get_taxonomy_manager()
        data = await manager.seller_nodes_list()
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_seller_taxonomy_nodes_list failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to list seller taxonomy: {exc.message}")
    except Exception as exc:
        logger.error("etsy_seller_taxonomy_nodes_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_seller_taxonomy_node_properties_get",
    description="Get the property definitions for a specific seller taxonomy node. Returns the list of "
    "properties (e.g., color, size, material) that apply to listings under this category. Use this "
    "before creating a listing to discover required/optional property IDs. Public endpoint.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="taxonomy",
    permission_action="READ",
)
async def etsy_seller_taxonomy_node_properties_get(taxonomy_id: int) -> dict[str, Any]:
    """Get seller taxonomy node properties."""
    try:
        manager = get_taxonomy_manager()
        data = await manager.seller_node_properties_get(taxonomy_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_seller_taxonomy_node_properties_get(%s) failed: %s",
            taxonomy_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get seller taxonomy properties for {taxonomy_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid taxonomy_id: {exc}")
    except Exception as exc:
        logger.error("etsy_seller_taxonomy_node_properties_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_taxonomy_node_search",
    description="Search the Etsy taxonomy tree for nodes whose name matches a query (case-insensitive "
    "substring match). This is a client-side helper — Etsy does NOT expose a taxonomy search endpoint. "
    "The full tree is fetched once and walked locally. Set variant='seller' (default) or 'buyer'. "
    "Returns matching nodes with taxonomy_id, name, full path, and level.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="taxonomy",
    permission_action="READ",
)
async def etsy_taxonomy_node_search(
    query: str,
    variant: str = "seller",
) -> dict[str, Any]:
    """Search taxonomy nodes by name."""
    try:
        if not query or not query.strip():
            return error_envelope("query must not be empty")
        if variant not in ("seller", "buyer"):
            return error_envelope("variant must be 'seller' or 'buyer'")

        manager = get_taxonomy_manager()
        data = await manager.node_search(query.strip(), variant=variant)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_taxonomy_node_search failed: %s", exc, exc_info=True)
        return error_envelope(f"Taxonomy search failed: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_taxonomy_node_search unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
